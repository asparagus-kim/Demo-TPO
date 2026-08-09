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
import hashlib
import html
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..schemas import PlaceReview, WebEvidenceItem
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Hard cap on how many evidence items we keep / score downstream.
DEFAULT_MAX_RESULTS = 12

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


def _cache_key(query: str, provider: str) -> str:
    digest = hashlib.sha1((provider + "|" + query).encode("utf-8")).hexdigest()
    return f"websearch:{digest}"


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
    # follow_redirects=True 필수. httpx 기본값은 False 인데
    # `duckduckgo.com/html/` 은 `html.duckduckgo.com` 으로 302 한다.
    # 이게 없으면 len=138 짜리 리다이렉트 응답을 받고 status != 200 이라 항상 0건이 되어
    # **웹검색 폴백 전체가 조용히 죽어 있었다** (2026-08-05 발견).
    kwargs.setdefault("follow_redirects", True)
    try:
        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(2),
            wait=wait_exponential(min=1, max=4),
            retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
        ):
            with attempt:
                return await client.get(url, timeout=15, **kwargs)
    except Exception as exc:
        logger.warning("web search GET %s failed: %s", url, exc)
        return None
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
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)


async def _duckduckgo_search(client: httpx.AsyncClient, query: str, max_results: int) -> List[WebEvidenceItem]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}&kl=kr-kr"
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
            url=link,
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

    cache = get_cache("places")  # reuse the 6h TTL cache bucket

    # Provider selection by env (no extra config dataclass change required).
    serpapi_key = os.getenv("SERPAPI_KEY", "").strip()
    google_cse_key = os.getenv("GOOGLE_CSE_KEY", "").strip()
    google_cse_cx = os.getenv("GOOGLE_CSE_CX", "").strip()

    providers: List[Tuple[str, Any]] = []
    if serpapi_key:
        providers.append(("serpapi", serpapi_key))
    if google_cse_key and google_cse_cx:
        providers.append(("google_cse", (google_cse_key, google_cse_cx)))
    providers.append(("duckduckgo", None))

    return await _run_providers(query, max_results)


async def _run_providers(query: str, max_results: int) -> List[WebEvidenceItem]:
    """Shared provider-chain runner used by both general and hours-targeted
    search entry points. Picks the first provider that actually returns hits.
    Caches per (query, provider) to keep repeated calls cheap.
    """
    cache = get_cache("places")

    serpapi_key = os.getenv("SERPAPI_KEY", "").strip()
    google_cse_key = os.getenv("GOOGLE_CSE_KEY", "").strip()
    google_cse_cx = os.getenv("GOOGLE_CSE_CX", "").strip()

    providers: List[Tuple[str, Any]] = []
    if serpapi_key:
        providers.append(("serpapi", serpapi_key))
    if google_cse_key and google_cse_cx:
        providers.append(("google_cse", (google_cse_key, google_cse_cx)))
    providers.append(("duckduckgo", None))

    async with httpx.AsyncClient() as client:
        for name, conf in providers:
            ck = _cache_key(query, name)
            if ck in cache:
                logger.info("web_search cache hit (%s) for '%s'", name, query)
                return cache[ck]
            try:
                if name == "serpapi":
                    results = await _serpapi_search(client, query, conf, max_results)
                elif name == "google_cse":
                    key, cx = conf
                    results = await _google_cse_search(client, query, key, cx, max_results)
                else:
                    results = await _duckduckgo_search(client, query, max_results)
            except Exception as exc:
                logger.warning("web_search provider=%s raised: %s", name, exc)
                results = []
            if results:
                cache[ck] = results
                logger.info("web_search provider=%s returned %d hits", name, len(results))
                return results

    logger.info("web_search: no provider returned hits for '%s'", query)
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

    return await _run_providers(query, max_results)


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
