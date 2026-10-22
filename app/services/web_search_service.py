"""Web-search fallback for ambience text evidence.

Used when Google Places either:
    a) refers to a different entity (validation failed), or
    b) refers to the right entity but has no usable review texts.

In both cases we re-query the web using the moneypin-derived keywords
(상호명, 업종, 주소) and return short text snippets that the LLM scoring
pipeline can consume the same way it consumes Google reviews.

Provider order:
    1. Mock mode / no internet -> deterministic canned snippets seeded by query.
    2. SerpAPI (if `SERPAPI_KEY` is set).
    3. Google Custom Search JSON API (if `GOOGLE_CSE_KEY` and `GOOGLE_CSE_CX`).
    4. DuckDuckGo HTML endpoint (no key, best-effort).

Each provider yields {title, url, snippet, source}. We normalise into
`WebEvidenceItem` objects and (separately) into `PlaceReview` objects so the
existing `llm_service.score_reviews` can be reused unchanged.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote_plus, urlsplit

import httpx

from ..config import get_settings
from ..schemas import PlaceReview, WebEvidenceItem
from ..utils import http as shared_http
from ..utils.cache import get_cache
from ..utils.logging import get_logger
from . import blog_search_policy as policy
from .search_budget import BudgetedClient, SearchBudget, SearchBudgetExceeded

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Hard cap on how many evidence items we keep / show / score downstream. Product
# decision (2026-10-22): a few accurate blog posts beat many; keep the best 4.
DEFAULT_MAX_RESULTS = 4
# Candidates requested per search, so the best few survive strict acceptance.
_CANDIDATES_PER_REQUEST = 20

# Strip noisy HTML / boilerplate from snippets before they reach the LLM.
_HTML_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def build_query(company_name: str, business_type: str, address: str) -> str:
    """The three moneypin-derived keywords, joined for a search engine."""
    parts = [p.strip() for p in (company_name, business_type, address) if p and p.strip()]
    return " ".join(parts)


def _sanitize_snippet(text: str) -> str:
    if not text:
        return ""
    cleaned = html.unescape(_HTML_TAGS.sub(" ", text))
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned


# ----------------------------------------------------------------- mock provider

_MOCK_TEMPLATES = [
    "{company} 다녀왔어요. {address} 근처라 점심에 들렀는데 자리가 빠르게 빠져서 회전이 좋아 보였습니다.",
    "{address}에 위치한 {company}, {biz_type} 치고는 분위기가 차분해서 미팅하기 좋아요.",
    "동네 단골들이 많아 보이는 {company}. 저녁 시간엔 조명이 살짝 어두워져 무드가 잡힙니다.",
    "{biz_type} 후기 - {company}. 직원이 친절하고 좌석 간격이 넉넉해서 업무 보기 편했어요.",
    "{address} 산책 겸 {company} 들렀는데 주말엔 사람이 꽤 많지만 평일은 한산한 편.",
    "{company} 블로그 리뷰: 인테리어가 깔끔하고 {biz_type} 메뉴 구성이 다양했습니다.",
    "오피스 근처라 점심시간엔 줄을 서기도 합니다. 테이크아웃이 빠른 편이에요. ({company})",
    "{company}는 가족 단위 손님도 많고 아이 의자도 준비되어 있습니다.",
]


def _mock_results(company: str, business_type: str, address: str, max_results: int) -> List[WebEvidenceItem]:
    out: List[WebEvidenceItem] = []
    for i, tmpl in enumerate(_MOCK_TEMPLATES[:max_results]):
        text = tmpl.format(company=company or "샘플 업체", biz_type=business_type or "매장", address=address or "")
        out.append(WebEvidenceItem(
            title=f"{company or '샘플'} 후기 #{i + 1}",
            url=f"https://example.com/mock/{i + 1}",
            text=text,
            source="mock",
        ))
    return out


# ----------------------------------------------------------------- HTTP helpers

async def _retrying_get(client: httpx.AsyncClient, url: str, **kwargs) -> Optional[httpx.Response]:
    # The search-only client counts redirect hops; there are no hidden retries.
    kwargs.setdefault("follow_redirects", True)
    try:
        return await client.get(url, timeout=15, **kwargs)
    except SearchBudgetExceeded:
        raise
    except Exception as exc:
        # Exception messages may embed API credentials in request query strings.
        logger.warning("web search request failed: %s", type(exc).__name__)
        return None


# ----------------------------------------------------------------- providers

async def _serpapi_search(client: httpx.AsyncClient, query: str, key: str, max_results: int) -> List[WebEvidenceItem]:
    params = {"engine": "google", "q": query, "hl": "ko", "gl": "kr", "num": max_results, "api_key": key}
    resp = await _retrying_get(client, "https://serpapi.com/search.json", params=params)
    if not resp or resp.status_code != 200:
        return []
    try:
        data = resp.json() or {}
    except json.JSONDecodeError:
        return []
    out: List[WebEvidenceItem] = []
    for hit in (data.get("organic_results") or [])[:max_results]:
        out.append(WebEvidenceItem(
            title=hit.get("title"),
            url=hit.get("link"),
            text=_sanitize_snippet(hit.get("snippet") or ""),
            source="serpapi",
        ))
    return out


async def _google_cse_search(
    client: httpx.AsyncClient, query: str, key: str, cx: str, max_results: int
) -> List[WebEvidenceItem]:
    params = {"q": query, "key": key, "cx": cx, "num": min(10, max_results), "lr": "lang_ko", "gl": "kr"}
    resp = await _retrying_get(client, "https://www.googleapis.com/customsearch/v1", params=params)
    if not resp or resp.status_code != 200:
        return []
    try:
        data = resp.json() or {}
    except json.JSONDecodeError:
        return []
    out: List[WebEvidenceItem] = []
    for item in (data.get("items") or [])[:max_results]:
        out.append(WebEvidenceItem(
            title=item.get("title"),
            url=item.get("link"),
            text=_sanitize_snippet(item.get("snippet") or ""),
            source="google_cse",
        ))
    return out


_DDG_RESULT_RE = re.compile(
    # The gap may not cross into the next result, or a snippet-less result would
    # borrow the following result's snippet under its own URL.
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>((?:(?!</a>).)*)</a>'
    r'(?:(?!class="result__a").)*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def _normalize_result_url(link: Optional[str]) -> Optional[str]:
    """Decode HTML hrefs and bypass DuckDuckGo's redirect endpoint."""
    # Only the outer href is HTML. The decoded destination is already URL data.
    link = html.unescape(link).strip() if link else None
    for _ in range(4):
        if not link:
            return None
        if link.startswith("//"):
            link = "https:" + link
        try:
            parsed = urlsplit(link)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                return None
            if (
                parsed.hostname in {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com"}
                and parsed.path.rstrip("/") == "/l"
            ):
                # parse_qs decodes the wrapper once, preserving the destination's
                # own escaped query values (do not unquote the entire URL).
                link = parse_qs(parsed.query).get("uddg", [None])[0]
                continue
            return link
        except ValueError:
            return None
    return None


async def _duckduckgo_search(client: httpx.AsyncClient, query: str, max_results: int) -> List[WebEvidenceItem]:
    # duckduckgo.com/html/ only 302s here; calling it directly saves one budgeted request.
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}&kl=kr-kr"
    resp = await _retrying_get(
        client, url,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
    )
    if not resp or resp.status_code != 200:
        return []
    out: List[WebEvidenceItem] = []
    for match in _DDG_RESULT_RE.finditer(resp.text):
        link, title_html, snippet_html = match.groups()
        title = _sanitize_snippet(title_html)
        snippet = _sanitize_snippet(snippet_html)
        if not snippet:
            continue
        out.append(WebEvidenceItem(
            title=title or None,
            url=_normalize_result_url(link),
            text=snippet,
            source="duckduckgo",
        ))
        if len(out) >= max_results:
            break
    return out


# ----------------------------------------------------------------- public API

async def search_business_evidence(
    company_name: str,
    business_type: str,
    address: str,
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    store_name: str = "",
    region_address: str = "",
    context: Optional[policy.SearchContext] = None,
    budget: Optional[SearchBudget] = None,
    diagnostics: Optional[dict] = None,
) -> List[WebEvidenceItem]:
    """Run a fallback web search using moneypin-derived keywords.

    Always returns a list (possibly empty). Caller decides whether the result
    is enough to feed the LLM scoring pipeline.
    """
    settings = get_settings()
    query = build_query(company_name, business_type, address)
    if not query:
        return []

    # Mock mode -> deterministic stub
    if settings.effective_mock_mode():
        logger.info("web_search MOCK for query='%s'", query)
        return _mock_results(company_name, business_type, address, max_results)

    target_store = store_name or company_name
    context = context or policy.build_search_context(
        target_store, address, region_address, registered_name=company_name,
    )
    return await _run_providers(
        query,
        max_results,
        store_name=target_store,
        address=address,
        region_address=region_address,
        context=context,
        budget=budget,
        diagnostics=diagnostics,
    )


async def _kakao_blog_search(
    client: httpx.AsyncClient, query: str, kakao_key: str, max_results: int,
    **_context,
) -> List[WebEvidenceItem]:
    """Fetch exactly one query; shared policy handles all providers uniformly."""
    if not kakao_key:
        return []
    response = await _retrying_get(
        client, "https://dapi.kakao.com/v2/search/blog",
        params={"query": query, "size": min(max_results, 20), "sort": "accuracy"},
        headers={"Authorization": f"KakaoAK {kakao_key}"},
    )
    if response is None or response.status_code != 200:
        return []
    try:
        documents = response.json().get("documents") or []
    except (ValueError, AttributeError):
        return []
    return [WebEvidenceItem(
        title=_sanitize_snippet(item.get("title") or ""),
        text=_sanitize_snippet(item.get("contents") or ""),
        url=item.get("url"), source="kakao_blog",
    ) for item in documents if isinstance(item, dict)]


def _search_cache_key(context: policy.SearchContext, purpose: str, provider: str, query: str, limit: int) -> str:
    payload = (policy.POLICY_VERSION, context.cache_identity, purpose, provider,
               context.review_queries, query, limit)
    return "blogsearch:" + hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def _accept_candidates(items, context, purpose, limit):
    candidates = items
    if purpose == "hours":
        candidates = [item for item in items if extract_business_hours([item])]
    accepted, stats = policy.filter_evidence(candidates, context, purpose=purpose, limit=limit)
    if len(candidates) != len(items):
        stats["candidates"] = len(items)
        stats["rejected"]["no_hours"] = len(items) - len(candidates)
    return accepted, stats


async def _run_providers(
    query: str, max_results: int, *, store_name: str = "", address: str = "",
    region_address: str = "", context: Optional[policy.SearchContext] = None,
    purpose: str = "reviews", budget: Optional[SearchBudget] = None,
    diagnostics: Optional[dict] = None,
) -> List[WebEvidenceItem]:
    """Ordered passes over providers, accepting only verified unique evidence."""
    settings = get_settings()
    context = context or policy.build_search_context(store_name, address, region_address)
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.setdefault("policy_version", policy.POLICY_VERSION)
    diagnostics["identity_reason"] = context.reason
    if context.reason:
        return []
    budget = budget or SearchBudget(settings.web_fallback_budget_sec)
    cache = get_cache("places")
    providers: List[Tuple[str, Any]] = []
    if settings.kakao_rest_api_key:
        providers.append(("kakao_blog", settings.kakao_rest_api_key))
    if os.getenv("SERPAPI_KEY", "").strip():
        providers.append(("serpapi", os.environ["SERPAPI_KEY"].strip()))
    if os.getenv("GOOGLE_CSE_KEY", "").strip() and os.getenv("GOOGLE_CSE_CX", "").strip():
        providers.append(("google_cse", (os.environ["GOOGLE_CSE_KEY"].strip(), os.environ["GOOGLE_CSE_CX"].strip())))
    providers.append(("duckduckgo", None))
    client = BudgetedClient(shared_http.get_client(), budget, purpose)
    queries = context.review_queries if purpose == "reviews" else (context.hours_query,)
    rejected = Counter(diagnostics.get("rejected", {}))
    for base_query in queries:
        sites = ("blog.naver.com", "tistory.com") if purpose == "reviews" else (None,)
        for site in sites:
            for name, conf in providers:
                if name == "kakao_blog" and site == "tistory.com":
                    continue  # Kakao already searches all supported blog hosts.
                provider_query = base_query if name == "kakao_blog" or not site else f"{base_query} site:{site}"
                ck = _search_cache_key(context, purpose, name, provider_query, max_results)
                if ck in cache:
                    accepted, stats = _accept_candidates(cache[ck], context, purpose, max_results)
                    if accepted:
                        diagnostics[f"{purpose}_provider"] = name
                        diagnostics["cache_hit"] = True
                        return accepted
                if budget.remaining <= 0 or budget.used >= 8 or (purpose == "reviews" and budget.review_used >= budget.review_limit):
                    diagnostics["stop_reason"] = "timeout" if budget.remaining <= 0 else "request_cap"
                    return []
                diagnostics.setdefault("attempted_providers", []).append(name)
                try:
                    if name == "kakao_blog":
                        raw = await _kakao_blog_search(client, provider_query, conf, _CANDIDATES_PER_REQUEST)
                    elif name == "serpapi":
                        raw = await _serpapi_search(client, provider_query, conf, _CANDIDATES_PER_REQUEST)
                    elif name == "google_cse":
                        raw = await _google_cse_search(client, provider_query, *conf, _CANDIDATES_PER_REQUEST)
                    else:
                        raw = await _duckduckgo_search(client, provider_query, _CANDIDATES_PER_REQUEST)
                except SearchBudgetExceeded:
                    diagnostics["stop_reason"] = budget.stop_reason
                    return []
                except Exception as exc:
                    logger.warning("web search provider=%s failed: %s", name, type(exc).__name__)
                    raw = []
                accepted, stats = _accept_candidates(raw, context, purpose, max_results)
                diagnostics["candidates"] = diagnostics.get("candidates", 0) + stats["candidates"]
                diagnostics["duplicates"] = diagnostics.get("duplicates", 0) + stats["duplicates"]
                rejected.update(stats["rejected"])
                diagnostics["rejected"] = dict(rejected)
                if accepted:
                    cache[ck] = accepted
                    diagnostics[f"{purpose}_provider"] = name
                    diagnostics[f"{purpose}_accepted"] = len(accepted)
                    return accepted
    return []


# --- opening-hours recovery from web-search snippets -----------------------
#
# Google's Place Details response often omits `currentOpeningHours` /
# `regularOpeningHours` for small local businesses. When that happens we
# scan web-search snippets for hour-range patterns and feed them back into
# `GooglePlaces.business_hours` so the TPO time label, daypart weights, and
# the UI's 영업시간 box all have something to render.

# HH:MM - HH:MM, HH:MM – HH:MM, HH:MM ~ HH:MM (and variants, plus wide tilde).
_WEB_HOURS_COLON = re.compile(r"(\d{1,2}):(\d{2})\s*[-–—~～]\s*(\d{1,2}):(\d{2})")

# Bare Korean form: "9시 ~ 22시", "10시부터 21시". Optional minute with 30분 etc.
_WEB_HOURS_HANGUL = re.compile(
    r"(\d{1,2})\s*시(?:\s*(\d{2})\s*분)?\s*(?:~|～|-|–|—|부터)\s*(\d{1,2})\s*시"
)

# Words that, when they appear just before a range, let us keep useful context
# so the UI's 평일/주말 split still has something to latch onto.
_HOURS_CONTEXT = re.compile(
    r"(영업시간|오픈\s*시간|오픈|평일|주말|매일|매주|연중무휴"
    r"|월\s*[~\-–]\s*금|월\s*[~\-–]\s*일"
    r"|[월화수목금토일]요일|[월화수목금토일]\s*[:：])",
    re.IGNORECASE,
)

_HOURS_MAX_LINES = 4


def _normalise_range(line: str) -> str:
    """Canonical form used purely for dedupe — digits + hyphen only."""
    return re.sub(r"\D", "", line)


def extract_business_hours(items: List[WebEvidenceItem]) -> List[str]:
    """Scan web-search snippets for opening-hour ranges.

    Returns a list of free-form strings that are compatible with both
    `ambience_service.parse_business_hours` (HH:MM-HH:MM regex) and the UI's
    `formatBusinessHours` weekday-prefix stripper. When nothing can be
    extracted, returns an empty list (caller keeps the existing empty state).
    """
    out: List[str] = []
    seen: set[str] = set()

    for item in items or []:
        haystack = " ".join(
            part for part in (item.title or "", item.text or "") if part
        )
        if not haystack:
            continue

        # Prefer HH:MM-HH:MM because it plugs straight into the existing regex.
        for match in _WEB_HOURS_COLON.finditer(haystack):
            s_h, s_m, e_h, e_m = match.groups()
            range_str = f"{int(s_h):02d}:{s_m}-{int(e_h):02d}:{e_m}"
            dedupe = _normalise_range(range_str)
            if dedupe in seen:
                continue
            seen.add(dedupe)

            prefix = _context_prefix(haystack, match.start())
            out.append(f"{prefix}{range_str}" if prefix else range_str)
            if len(out) >= _HOURS_MAX_LINES:
                return out

        # Fall back to "HH시 ~ HH시" — normalise into HH:MM-HH:MM so downstream
        # parsers don't need a second grammar.
        for match in _WEB_HOURS_HANGUL.finditer(haystack):
            s_h, s_m, e_h = match.groups()
            s_m_val = s_m or "00"
            range_str = f"{int(s_h):02d}:{s_m_val}-{int(e_h):02d}:00"
            dedupe = _normalise_range(range_str)
            if dedupe in seen:
                continue
            seen.add(dedupe)

            prefix = _context_prefix(haystack, match.start())
            out.append(f"{prefix}{range_str}" if prefix else range_str)
            if len(out) >= _HOURS_MAX_LINES:
                return out

    return out


def _context_prefix(haystack: str, range_start: int) -> str:
    """Peek ~20 chars before a range match for a weekday / 영업시간 marker.

    Keeps the rendered UI closer to what the source actually said (e.g.
    "매일 10:00-22:00" rather than a bare "10:00-22:00") while still being
    harmless to the downstream regex.
    """
    window_start = max(0, range_start - 20)
    window = haystack[window_start:range_start]
    match = None
    for candidate in _HOURS_CONTEXT.finditer(window):
        match = candidate  # keep the last (closest to the range)
    if not match:
        return ""
    label = match.group(1).strip()
    # Normalise the separator so the UI strip regex behaves predictably.
    return f"{label} " if not label.endswith((":", "：")) else f"{label} "


async def search_hours_evidence(
    company_name: str,
    address: str,
    *,
    max_results: int = 8,
    store_name: str = "",
    region_address: str = "",
    context: Optional[policy.SearchContext] = None,
    budget: Optional[SearchBudget] = None,
    diagnostics: Optional[dict] = None,
) -> List[WebEvidenceItem]:
    """Last-resort targeted search used only when the general review fallback
    didn't surface any opening-hour strings. Asks the same providers for a
    hours-biased query like "카페리즈 군산시 영업시간".
    """
    settings = get_settings()

    parts = [p.strip() for p in (company_name, address) if p and p.strip()]
    if not parts:
        return []
    query = " ".join(parts) + " 영업시간"

    if settings.effective_mock_mode():
        logger.info("search_hours_evidence MOCK for query='%s'", query)
        return _mock_results(company_name, "", address, max_results)

    context = context or policy.build_search_context(
        store_name or company_name, address, region_address, registered_name=company_name,
    )
    return await _run_providers(
        query, max_results, context=context, purpose="hours", budget=budget, diagnostics=diagnostics,
    )


def to_place_reviews(items: List[WebEvidenceItem]) -> List[PlaceReview]:
    """Adapt web-search items to the `PlaceReview` shape the LLM scorer expects.

    Note: `rating` and `relative_time` are intentionally None — the scorer
    treats missing recency as a neutral 1.0 weight, and missing ratings have
    no effect on the per-text axis scores.
    """
    out: List[PlaceReview] = []
    for it in items or []:
        text = (it.text or "").strip()
        if not text:
            continue
        out.append(PlaceReview(
            author=it.source or "web",
            rating=None,
            text=text,
            language="ko",
            relative_time=None,
            publish_time=None,
        ))
    return out


# ---------------------------------------------------------------------------
# 폴백 체인에 벽시계 예산을 건다
# ---------------------------------------------------------------------------

async def collect_fallback_evidence(
    company_name: str,
    business_type: str,
    address: str,
    *,
    need_hours: bool,
    budget_sec: float,
    store_name: str = "",
    region_address: str = "",
    place_id: str = "",
    registered_name: Optional[str] = None,
    diagnostics: Optional[dict] = None,
) -> Tuple[List[WebEvidenceItem], List[str]]:
    """웹검색 폴백 체인(근거 검색 → 필요 시 영업시간 재검색)을 **전체 예산** 안에서 돈다.

    왜 예산인가 (2026-09-15 실측): DuckDuckGo 가 Render 의 데이터센터 IP 를 막으면
    `_retrying_get` 이 2회 × 15초 타임아웃을 다 채우고, 라우터가 근거 검색과
    영업시간 검색을 **연쇄**로 부르니 최악 64초였다. 실제로 63.4초짜리 분석이 나왔고
    결과는 근거 0건이었다 — 60초를 기다려서 얻은 게 '없음' 이었다.

    이 폴백의 가치는 낮고(있으면 좋고 없으면 prior 로 간다) 비용은 무한이었다.
    예산을 넘기면 **그 시점까지 얻은 것만** 돌려준다 — 근거 검색이 끝난 뒤 영업시간
    검색이 늦으면 근거는 살린다. 파이프라인은 어떤 경우에도 계속 간다.
    """
    evidence: List[WebEvidenceItem] = []
    hours: List[str] = []
    # registered_name=None checks the selected store against company_name; the router
    # passes "" when the user picked the store, because that choice is authoritative.
    context = policy.build_search_context(
        store_name or company_name, address, region_address, place_id,
        company_name if registered_name is None else registered_name,
    )
    budget = SearchBudget(budget_sec, need_hours=need_hours)
    diagnostics = diagnostics if diagnostics is not None else {}
    diagnostics.update(policy_version=policy.POLICY_VERSION, identity_reason=context.reason)

    async def _chain() -> None:
        nonlocal evidence, hours
        evidence = await search_business_evidence(
            company_name,
            business_type,
            address,
            store_name=store_name,
            region_address=region_address,
            context=context,
            budget=budget,
            diagnostics=diagnostics,
        )
        if not need_hours:
            return
        hours = extract_business_hours(evidence)
        if hours:
            diagnostics["hours_origin"] = "accepted_reviews"
            return
        more = await search_hours_evidence(
            company_name, address, store_name=store_name, region_address=region_address,
            context=context, budget=budget, diagnostics=diagnostics,
        )
        hours = extract_business_hours(more)
        if hours:
            # Store-verified web pages (often directories): hours only, never reviews.
            diagnostics["hours_origin"] = "verified_web"

    try:
        await asyncio.wait_for(_chain(), timeout=budget_sec)
    except asyncio.TimeoutError:
        diagnostics["stop_reason"] = "timeout"
        logger.warning(
            "web search fallback exceeded %.1fs budget — continuing with %d evidence, %d hour lines",
            budget_sec, len(evidence), len(hours),
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("web search fallback raised: %s", type(exc).__name__)
    diagnostics["requests"] = budget.used
    diagnostics["reviews_accepted"] = len(evidence)
    diagnostics["hours_recovered"] = len(hours)
    diagnostics["elapsed_ms"] = round(max(0, budget_sec - budget.remaining) * 1000)
    return evidence, hours
