"""Conservative, provider-independent snippet acceptance; never resolves stores.

Search snippets are heuristic evidence of store experience, not proof of a visit.
No network calls, external models, or persisted snippets belong in this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from html import unescape
import re
from typing import Any, Optional
from urllib.parse import parse_qs, parse_qsl, unquote, urlsplit

from ..schemas import WebEvidenceItem

POLICY_VERSION = "storefront-blog-v4"
_CORPORATE = re.compile(r"주식회사|유한회사|\(\s*주\s*\)|㈜", re.I)
_GENERIC = {"커피", "카페", "식당", "음식점", "레스토랑", "coffee", "cafe", "restaurant", "매장", "가게"}
_CITIES = {
    "서울": "서울", "서울시": "서울", "서울특별시": "서울",
    "부산": "부산", "부산시": "부산", "부산광역시": "부산",
    "대구": "대구", "대구시": "대구", "대구광역시": "대구",
    "인천": "인천", "인천시": "인천", "인천광역시": "인천",
    "광주": "광주", "광주광역시": "광주",
    "대전": "대전", "대전시": "대전", "대전광역시": "대전",
    "울산": "울산", "울산시": "울산", "울산광역시": "울산",
    "세종": "세종", "세종시": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남",
    "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북", "전남": "전남", "전라남도": "전남",
    "경북": "경북", "경상북도": "경북", "경남": "경남", "경상남도": "경남",
    "제주": "제주", "제주도": "제주", "제주특별자치도": "제주",
}
# At least one Hangul syllable before the suffix: apartment labels like 101동 are not places.
_ADMIN = re.compile(r"[가-힣0-9·]*[가-힣][가-힣0-9·]*(?:동|읍|면|가|구|시|군)")
_PARTICLES = ("에서", "으로", "에", "의", "은", "는", "이", "가", "을", "를", "로", "쪽")
_ROAD = re.compile(r"[가-힣0-9·]+(?:로|길)(?:\d+번길)?")
_SPAM = re.compile(r"분양|임대|매물|원룸|투룸|오피스텔|전세|월세|구인|채용|알바|아르바이트|창업\s*비용|권리금|가맹\s*모집")
# Naver "related posts" widgets leak other posts' titles plus their domain into the
# snippet; a brand found there describes a different post, not this one.
_LINK_LIST = re.compile(r"blog\.naver\.com|[a-z0-9-]+\.tistory\.com", re.I)
_DIRECTORY = re.compile(r"사업자\s*(?:등록|정보|조회)|기업\s*정보|사업체\s*정보|통신판매업|사업자등록번호")
_EXPERIENCE = re.compile(
    r"다녀|들렀|들른|먹었|먹고|마셨|마시고|주문(?:했|한|하고|해서)|방문(?:했|한|해|기)|"
    r"앉아|앉았|머물|맛있|맛없|친절(?:했|하|해)|불친절|"
    r"(?:좌석|의자|자리).{0,15}(?:편|불편|넓|좁)|"
    r"(?:커피|음료|음식|디저트).{0,15}(?:고소|달콤|맛|향)|"
    r"분위기.{0,12}(?:좋|조용|아늑|시끄)|(?:조용|아늑).{0,12}(?:매장|카페|공간)|"
    r"\b(?:visited|ordered|tasted|delicious|seating|cozy|cosy)\b", re.I,
)


def _canonical_name(value: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", _CORPORATE.sub("", value or "").lower())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[가-힣a-zA-Z0-9·]+", value or ""))


def _has_token(tokens: tuple[str, ...], word: str) -> bool:
    """Whole-token match that tolerates a trailing particle (암사동에서, 암사점에)."""
    return bool(word) and any(t == word or t.startswith(word) and t[len(word):] in _PARTICLES for t in tokens)


def _names_compatible(registered: str, brand: str) -> bool:
    # One complete name must contain the other (주식회사 몸가짐 휘트니스필라테스구의 ⊇
    # 몸가짐휘트니스). A merely shared word (언니커피 vs 뽕쓰언니) is a conflict.
    registered, brand = _canonical_name(registered), _canonical_name(brand)
    if not registered or registered == brand:
        return True
    shorter = min(registered, brand, key=len)
    # A generic word (커피 inside 스타벅스커피) proves nothing about identity.
    return shorter not in _GENERIC and (registered in brand or brand in registered)


def _administrative_level(token: str) -> str:
    """Classify complete address tokens, distinguishing province from municipality.

    광주시 is a municipality in 경기도; 광주광역시 is the metropolitan
    province. The ambiguous shortened 광주 keeps its top-level interpretation.
    """
    if token in _CITIES:
        return "province"
    if not _ADMIN.fullmatch(token):
        return ""
    if token.endswith(("시", "군")):
        return "municipality"
    if token.endswith("구"):
        return "district"
    return "neighborhood"


def _conflicting_address_levels(tokens: tuple[str, ...]) -> bool:
    values: dict[str, set[str]] = {}
    for token in tokens:
        level = _administrative_level(token)
        if level:
            values.setdefault(level, set()).add(_CITIES.get(token, token))
    return any(len(names) > 1 for names in values.values())


def _split_name(value: str) -> tuple[str, str]:
    clean = _CORPORATE.sub("", value or "").strip()
    # Explicit separated labels are supported; guessing attached brand boundaries is unsafe.
    match = re.search(r"(?:\s+|\()([가-힣a-zA-Z0-9]+(?:점)|본점|직영점)\)?$", clean)
    if match:
        return clean[:match.start()].strip(), match.group(1)
    return clean, ""


@dataclass(frozen=True)
class SearchContext:
    store_name: str
    brand: str
    branch: str
    address: str
    region_address: str
    place_id: str
    registered_name: str
    locality_tokens: tuple[str, ...]
    city: str
    reason: str
    review_queries: tuple[str, ...]
    hours_query: str
    cache_identity: tuple[str, ...]


def build_search_context(store_name: str, address: str, region_address: str = "", place_id: str = "", registered_name: str = "") -> SearchContext:
    store_name, address, region_address, place_id, registered_name = (
        str(value or "").strip() for value in (store_name, address, region_address, place_id, registered_name)
    )
    brand, branch = _split_name(store_name)
    registered_brand, registered_branch = _split_name(registered_name)
    tokens = _tokens(f"{address} {region_address}")
    cities = tuple(dict.fromkeys(_CITIES[token] for token in tokens if token in _CITIES))
    # Full structured tokens only: 구천면로 must never create 구천면.
    admins = tuple(dict.fromkeys(token for token in tokens if token not in _CITIES and _ADMIN.fullmatch(token)))
    roads = tuple(dict.fromkeys(token for token in tokens if _ROAD.fullmatch(token)))
    dongs = tuple(token for token in admins if token.endswith(("동", "읍", "면", "가")))
    districts = tuple(token for token in admins if token.endswith(("구", "시", "군")))
    localities = dongs + roads + districts
    reason = ""
    if not _canonical_name(brand) or _canonical_name(brand) in _GENERIC or len(_canonical_name(brand)) < 2:
        reason = "missing_or_generic_store_name"
    elif re.search(r"(?<!\d)\d{3}[- ]?\d{2}[- ]?\d{5}(?!\d)", store_name):
        reason = "business_number_in_store_name"
    elif registered_name and (not _names_compatible(registered_brand, brand)
                              or registered_branch and registered_branch != branch):
        reason = "registered_name_conflict"
    elif _conflicting_address_levels(tokens):
        reason = "conflicting_address_identity"
    elif not branch and not localities:
        reason = "missing_reliable_locality"
    strongest = localities[0] if localities else ""
    # Third template broadens to the district first (언니커피 강동구 후기), then a road.
    broader = next((x for x in districts + roads if x != strongest), "")
    queries: list[str] = []
    if not reason:
        for query in (f"{store_name} {strongest}".strip(), f"{brand} {strongest} 후기".strip(),
                      f"{brand} {broader} 후기" if broader else ""):
            if query and query not in queries:
                queries.append(query)
    identity = (POLICY_VERSION, place_id, _canonical_name(store_name), _canonical_name(registered_name),
                " ".join(_tokens(address)), " ".join(_tokens(region_address)), branch, *cities, *localities)
    return SearchContext(store_name, brand, branch, address, region_address, place_id, registered_name,
                         localities, cities[0] if len(cities) == 1 else "", reason, tuple(queries[:3]),
                         f"{store_name} {strongest} 영업시간".strip() if not reason else "", identity)


def normalize_url(link: object, *, html_origin: bool = False) -> Optional[str]:
    """Decode an HTML href once; URL query bytes themselves are opaque.

    Only DDG's encoded destination is percent-decoded. Repeated normalization
    of API/JSON URLs preserves literal HTML-looking query parameters.
    """
    if not isinstance(link, str) or not link.strip():
        return None
    value = unescape(link.strip()) if html_origin else link.strip()
    if value.startswith("//"):
        value = "https:" + value
    for _ in range(5):
        if re.search(r"[\x00-\x20\x7f\\]", value):
            return None
        try:
            parsed = urlsplit(value)
            host = (parsed.hostname or "").lower()
            port = parsed.port
        except ValueError:
            return None
        if (parsed.scheme.lower() not in {"http", "https"} or not host or not parsed.netloc
                or parsed.username is not None or parsed.password is not None
                or not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host
                or port is not None and not 1 <= port <= 65535):
            return None
        if host in {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com", "links.duckduckgo.com"} and parsed.path.rstrip("/") == "/l":
            # A wrapper already percent-encoded by another wrapper may contain
            # '&amp;rut'; splitting at '&' still leaves uddg intact.
            destination = parse_qs(parsed.query, keep_blank_values=True).get("uddg", [])
            if len(destination) != 1 or not destination[0]:
                return None
            value = destination[0]
            continue
        return value
    return None


def _post_identity(url: str) -> tuple[Optional[tuple[str, ...]], Optional[str]]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.port not in (None, 80 if parsed.scheme == "http" else 443):
        return None, None
    path = unquote(parsed.path).rstrip("/")
    if host in {"blog.naver.com", "m.blog.naver.com"}:
        match = re.fullmatch(r"/([A-Za-z0-9_-]+)/([0-9]+)", path)
        if match:
            return ("naver", match.group(1).lower(), match.group(2)), "naver_blog"
        if path.lower() in {"/postview.nhn", "/postview.naver"}:
            query = parse_qs(parsed.query)
            ids, nums = query.get("blogId", []), query.get("logNo", [])
            if len(ids) == len(nums) == 1 and re.fullmatch(r"[A-Za-z0-9_-]+", ids[0]) and re.fullmatch(r"[0-9]+", nums[0]):
                return ("naver", ids[0].lower(), nums[0]), "naver_blog"
    elif (re.fullmatch(r"[a-z0-9-]+\.tistory\.com", host)
          and host.split(".")[0] not in {"www", "m", "notice", "blog", "api", "cs"}):
        if re.fullmatch(r"/[0-9]+", path) or re.fullmatch(r"/entry/[^/]+", path):
            tracking = {"fbclid", "gclid", "ref", "referrer"}
            meaningful = tuple(sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                                      if not key.lower().startswith("utm_") and key.lower() not in tracking))
            return ("tistory", host, path, repr(meaningful)), "kakao_blog"
    return None, None


def _same_branch(mentioned: str, target: str) -> bool:
    """Bloggers space or shorten labels: '어린이대공원 본점' yields 본점 for
    어린이대공원본점, and 구의점 names 구의역점. A different place name conflicts."""
    m, t = mentioned[:-1], target[:-1]  # drop the trailing 점
    return bool(m) and (m == t or t.endswith(m) and m == "본" or t.startswith(m) or m.startswith(t))


def _brand_pattern(brand: str) -> str:
    # Match the complete normalized brand, allowing spaces inside its spelling.
    return r"\s*".join(re.escape(c) for c in _canonical_name(brand))


def _brand_match(text: str, brand: str) -> bool:
    return bool(re.search(r"(?<![가-힣a-z0-9])" + _brand_pattern(brand)
                          + r"(?=$|[^가-힣a-z0-9]|에서|에\s|을\s|를\s|은\s|는\s|의\s|이\s|가\s)", text, re.I))


def _store_reason(title: str, text: str, context: SearchContext) -> str:
    combined = f"{title} {text}"
    if not _brand_match(combined, context.brand):
        return "brand_mismatch"
    brand = _brand_pattern(context.brand)
    # "스타벅스 근처 네일샵": the store is only a landmark for another business.
    if re.search(brand + r"\s*(?:옆|앞|건너편|맞은편|근처|있는\s*건물|건물)", title, re.I):
        return "landmark_mention"
    # The post must be about this store, so its title must name it. A body-only
    # mention is a landmark ("빽다방 있는 건물 3층") or a diary stop ("지니의 결혼을
    # 축하해" with the cafe's place card) — the right cafe, but not a review of it.
    if not _brand_match(title, context.brand):
        return "brand_not_in_title"
    # An explicit other branch attached to the full brand outweighs an incidental
    # mention of the target neighborhood elsewhere in the snippet.
    branch_matches = re.findall(_brand_pattern(context.brand) + r"\s+([가-힣a-z0-9]+점)\b", combined, re.I)
    branch_matches += [branch for branch in re.findall(r"(?<![가-힣a-z0-9])([가-힣a-z0-9]+점)\b", title, re.I)
                       if branch not in {"장점", "단점", "관점", "시점", "요점", "중점", "초점", "만점", "맛점", "체인점"}]
    locality_stems = {re.sub(r"(?:동|읍|면|가|구|시|군)$", "", loc) for loc in context.locality_tokens}
    for branch in branch_matches:
        if context.branch and not _same_branch(branch, context.branch):
            return "branch_conflict"
        if not context.branch and branch not in {"본점", "직영점"} and branch[:-1] not in locality_stems:
            return "branch_conflict"
    text_tokens = _tokens(combined)
    # An administrative chain (e.g. 성남시 분당구 정자동) is reliable
    # competing-address evidence; a bare substring in narrative text is not.
    for position, token in enumerate(text_tokens[:-1]):
        following = text_tokens[position + 1]
        # A clear parent+neighborhood address must agree at the finest known
        # administrative level. A shared district cannot override this conflict.
        expected_neighborhoods = {loc for loc in context.locality_tokens
                                  if _administrative_level(loc) == "neighborhood"}
        # Either order: 강동구 천호동 and 천호동 강동구 both name 천호동.
        for parent, child in ((token, following), (following, token)):
            if (_administrative_level(parent) in {"province", "municipality", "district"}
                    and _administrative_level(child) == "neighborhood"
                    and expected_neighborhoods and child not in expected_neighborhoods):
                return "locality_conflict"
        if (token not in _CITIES and _ADMIN.fullmatch(token)
                and token.endswith(("시", "군", "구"))
                and (_ADMIN.fullmatch(following) or _ROAD.fullmatch(following))
                and token not in context.locality_tokens):
            return "locality_conflict"
    mentioned_cities = {_CITIES[token] for token in text_tokens if token in _CITIES}
    if context.city and any(city != context.city for city in mentioned_cities):
        return "city_conflict"
    branch_found = _has_token(text_tokens, context.branch)
    # When the store's 동/road is known, a shared 구 alone does not place the post
    # there (the same brand can sit in another 동 of the district).
    local = tuple(loc for loc in context.locality_tokens if _administrative_level(loc) != "district")
    locality_found = any(_has_token(text_tokens, loc) for loc in (local or context.locality_tokens))
    if not branch_found and not locality_found:
        return "locality_mismatch"
    return ""


def filter_evidence(items: list[WebEvidenceItem], context: SearchContext, *, purpose: str = "reviews", limit: int = 12) -> tuple[list[WebEvidenceItem], dict]:
    """Accept only verified store snippets, deduplicate before ranking/truncation."""
    if purpose not in {"reviews", "hours"}:
        raise ValueError("Unsupported search purpose")
    rejected: Counter[str] = Counter()
    diagnostics: dict[str, Any] = {"candidates": len(items), "accepted": 0, "duplicates": 0, "rejected": rejected}
    if context.reason:
        rejected[context.reason] = len(items)
        return [], {**diagnostics, "rejected": dict(rejected)}
    accepted = []
    seen = set()
    for index, item in enumerate(items):
        url = normalize_url(item.url)
        identity, publisher = _post_identity(url) if url else (None, None)
        title = re.sub(r"<[^>]*>", " ", unescape(item.title or ""))
        text = re.sub(r"<[^>]*>", " ", unescape(item.text or ""))
        combined = f"{title} {text}"
        reason = "unsafe_url" if not url else ""
        if not reason and purpose == "reviews" and not identity:
            reason = "unsupported_post_url"
        if not reason and _SPAM.search(combined):
            reason = "spam"
        if not reason:
            reason = _store_reason(title, text, context)
        if not reason and purpose == "reviews" and _DIRECTORY.search(combined):
            reason = "metadata_only"
        if not reason and purpose == "reviews" and _LINK_LIST.search(text):
            reason = "related_post_list"
        if not reason and purpose == "reviews" and (len(text.strip()) < 15 or not _EXPERIENCE.search(text)):
            reason = "no_experience"
        if reason:
            rejected[reason] += 1
            continue
        key = identity or ("web", url)
        if key in seen:
            diagnostics["duplicates"] += 1
            continue
        seen.add(key)
        rank = (int(bool(context.branch and context.branch in _tokens(title))),
                sum(loc in _tokens(combined) for loc in context.locality_tokens),
                int(_canonical_name(context.store_name) in _canonical_name(title)))
        accepted.append((rank, index, item.model_copy(update={"url": url, "source": publisher or item.source})))
    accepted.sort(key=lambda row: (tuple(-part for part in row[0]), row[1]))
    result = [row[2] for row in accepted[:max(0, limit)]]
    diagnostics["accepted"] = len(result)
    diagnostics["rejected"] = dict(rejected)
    return result, diagnostics
