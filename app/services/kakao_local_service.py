"""Kakao Local — 상호명 → 업종·주소·좌표.

bizno 무료 플랜이 상호명만 주므로(`biz_lookup_service` 참고) 업종·주소·좌표는
여기서 확보한다. 이 값들이 downstream의 canonical 소스다.

    업종  ← category_name       예: "음식점 > 카페 > 커피전문점"
    주소  ← road_address_name    → 상권 매칭에 사용
    좌표  ← (x=경도, y=위도)      → 기상청 격자 변환에 사용

## 주의 — x가 경도, y가 위도다

Kakao 응답은 `x`=longitude, `y`=latitude다. 뒤바꾸면 상권 매칭과 날씨가 전부
틀리는데 예외 없이 조용히 실패한다. `_to_location()`에 한 군데로 모아 두고
테스트로 고정한다.

## 후보 선택이 이 모듈의 핵심 문제다

bizno에 주소가 없어 검색 쿼리에 지역 힌트를 넣을 수 없다. 실측(2026-08-05):

    "스타벅스 강남"  → 233건
    "블루보틀"       → 27건
    "카페리즈 군산"  → 1건

즉 상호명만으로는 동명 타지역 매장이 1순위로 올 수 있다. `documents[0]`을
그대로 믿으면 안 된다(김천 사례: 통칭으로 검색해 엉뚱한 매장이 잡혔다).
그래서 후보 전체를 상호명 유사도로 스코어링하고, **1등이 충분히 높고 2등과
격차가 뚜렷할 때만 자동 확정**한다. 그 외에는 호출자가 사용자에게 고르게 한다.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx
from rapidfuzz import fuzz

from ..config import get_settings
from ..schemas import PlaceCandidate
from ..utils import http as shared_http
from ..utils.cache import get_cache
from ..utils.logging import get_logger
from .entity_validation_service import normalize_company_name, strip_legal_prefix
from .trade_area_service import (
    SURROUND_GROUPS as TA_GROUPS,
    SURROUND_RADIUS_M as TA_RADIUS,
    UNIV_RADIUS_M as TA_UNIV_RADIUS,
)

logger = get_logger(__name__)

KAKAO_MAX_SIZE = 15          # API 상한
CANDIDATE_LIMIT = 8          # 사용자에게 보여줄 최대 후보 수

# 자동 확정 기준 (실측 근거: 일치 사례는 유사도 100 근처, 불일치는 0~47로 갈린다)
AUTO_ACCEPT_SCORE = 0.80     # 1등 점수가 이 이상이고
AUTO_ACCEPT_MARGIN = 0.15    # 2등과 이만큼 벌어지면 자동 확정
SINGLE_HIT_MIN_SCORE = 0.55  # 후보가 1건일 때는 기준을 낮춘다

# 좌표 기반 확정 기준 (APICK 이 위·경도를 줄 때만 쓰인다).
#
# 2026-10-01 광진구 49곳 실측: 상호명만으로 보류됐던 20곳에 좌표를 붙이자
# 17곳이 자동 확정됐다. 정답은 **3~8m**, 2등은 153m~238km 였다 — 경계가 애매한
# 분포가 아니라 두 덩어리로 완전히 갈린다. 그래서 임계값은 넉넉하게 잡아도
# 안전하고, 오히려 '가까운 두 곳' 을 잘못 고르지 않는 쪽이 중요하다.
LOCATION_MAX_M = 150.0        # 1등이 이보다 멀면 같은 매장이라고 보지 않는다
LOCATION_RUNNERUP_RATIO = 3.0  # 2등이 1등의 3배 이상 멀거나
LOCATION_RUNNERUP_GAP_M = 200.0  # 절대 거리로 이만큼 벌어지면 자동 확정

# category_group_code → 사람이 읽는 업종군 (참고용)
CATEGORY_GROUPS = {
    "MT1": "대형마트", "CS2": "편의점", "PS3": "어린이집·유치원", "SC4": "학교",
    "AC5": "학원", "PK6": "주차장", "OL7": "주유소·충전소", "SW8": "지하철역",
    "BK9": "은행", "CT1": "문화시설", "AG2": "중개업소", "PO3": "공공기관",
    "AT4": "관광명소", "AD5": "숙박", "FD6": "음식점", "CE7": "카페",
    "HP8": "병원", "PM9": "약국",
}


# ---------------------------------------------------------------- 매핑

def _to_location(doc: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Kakao x/y → {"lat","lng"}. **x=경도, y=위도** — 순서를 바꾸면 안 된다."""
    try:
        lng = float(doc.get("x"))
        lat = float(doc.get("y"))
    except (TypeError, ValueError):
        return None
    return {"lat": lat, "lng": lng}


def business_type_from_category(category_name: str, place_name: str = "") -> str:
    """'음식점 > 카페 > 커피전문점' → '커피전문점' (말단 토큰).

    Kakao는 프랜차이즈면 말단에 브랜드를 덧붙인다:
        '음식점 > 카페 > 커피전문점 > 스타벅스'
    이때 말단(스타벅스)은 업종이 아니므로 그 앞 토큰을 써야 한다.

    브랜드 판별은 **매장명에 그 토큰이 들어 있는지**로 한다. 예전에는 업종어
    포함 여부('점/카페/관/실/장/소')로 판단했는데, `스포츠,레저 > 스포츠시설 >
    헬스클럽` 의 '헬스클럽'을 브랜드로 오판해 '스포츠시설'을 뽑았고, 그 값이
    음원 업종군 매칭에 걸리지 않아 **헬스장에 카페 곡이 추천됐다** (2026-08-05 실측).

    깊이 3 이상에서만 적용한다 — '음식점 > 카페' 같은 2단에서 '카페민'이라는
    매장명 때문에 '음식점'으로 올라가 버리는 것을 막는다.
    """
    parts = [p.strip() for p in (category_name or "").split(">") if p.strip()]
    if not parts:
        return ""
    tail = parts[-1]
    if len(parts) >= 3 and place_name:
        squash = lambda s: s.replace(" ", "").lower()
        if squash(tail) in squash(place_name):
            return parts[-2]
    return tail


def category_tokens(category_name: str, group_code: str = "") -> List[str]:
    """entity_validation의 업종 family 매핑에 넣을 토큰들.

    `category_name`이 한글이라 기존 `_MP_FAMILY_RULES`(한글 키워드)가 그대로 먹는다.
    group_code도 함께 넣어 `_GP_TYPE_FAMILY` 매핑을 태운다.
    """
    toks = [p.strip() for p in (category_name or "").split(">") if p.strip()]
    if group_code:
        toks.append(group_code)
    return toks


def _doc_to_candidate(doc: Dict[str, Any]) -> PlaceCandidate:
    cat = doc.get("category_name") or ""
    name = doc.get("place_name") or ""
    return PlaceCandidate(
        place_id=str(doc.get("id") or ""),
        place_name=name,
        category_name=cat,
        category_group_code=doc.get("category_group_code") or "",
        business_type=business_type_from_category(cat, name),
        address=doc.get("road_address_name") or doc.get("address_name") or "",
        # 지번 주소를 따로 보관한다. 상권 매칭 엑셀이 행정동 기준이라
        # 도로명 주소('… 성미산로 128')로는 동을 못 뽑아 sido-fallback 으로 떨어진다.
        region_address=doc.get("address_name") or doc.get("road_address_name") or "",
        phone=doc.get("phone") or "",
        place_url=doc.get("place_url") or "",
        location=_to_location(doc),
    )


# ---------------------------------------------------------------- 점수

# 업종 접두어·접미어 차이로 유사도가 깎이는 것을 막는다.
# 실측: bizno '더노라（The Nora）' vs Kakao '카페더노라' → 47점으로 떨어졌다.
_TYPE_AFFIXES = ("카페", "커피", "coffee", "cafe", "레스토랑", "베이커리", "헬스", "짐", "gym")


def _strip_type_affix(name: str) -> str:
    n = normalize_company_name(name)
    for a in _TYPE_AFFIXES:
        if len(n) > len(a) + 1:
            if n.startswith(a):
                n = n[len(a):].strip()
            if n.endswith(a):
                n = n[: -len(a)].strip()
    return n or normalize_company_name(name)


def name_score(query_name: str, place_name: str) -> float:
    """0~1. 전체 문자열 유사도 기반.

    **`partial_ratio`/`token_set_ratio`를 쓰면 안 된다.** 부분 문자열·부분 집합에
    100점을 줘서 짧은 한글 상호에서 오탐이 쏟아진다 (2026-08-05 실측):

        카페민   vs 마을카페민        partial_ratio 100  ← '카페민'이 부분 문자열
        달달한카페 vs 달달한 오늘       partial_ratio 100  ← 접두 3자 일치
        제이카페  vs 메리제이플라워카페   token_set 100     ← 토큰이 부분집합

    실제로 맞는 매장이 동점에 묻혀 3위로 밀렸다. `ratio`는 길이 차이를 벌점으로
    반영해 위 세 쌍이 각각 75 / 60 / 61로 갈린다.

    `token_sort_ratio`는 어순만 다른 경우('별빛카페 달빛차' ↔ '달빛차 별빛카페')를
    잡되 부분집합에는 관대하지 않으므로 함께 쓴다.
    """
    a, b = normalize_company_name(query_name), normalize_company_name(place_name)
    if not a or not b:
        return 0.0

    def _pair_score(x: str, y: str) -> float:
        if not x or not y:
            return 0.0
        # 한글 상호는 띄어쓰기가 임의적이다('헬카페스피리터스' ↔ '헬카페 스피리터스').
        # 공백을 제거한 비교를 함께 보되, ratio 는 길이에 민감하므로
        # 부분 일치가 만점을 받는 문제는 생기지 않는다.
        nx, ny = x.replace(" ", ""), y.replace(" ", "")
        return max(
            fuzz.ratio(x, y), fuzz.token_sort_ratio(x, y),
            fuzz.ratio(nx, ny),
        )

    raw = _pair_score(a, b)
    stripped = _pair_score(_strip_type_affix(query_name), _strip_type_affix(place_name))
    return max(raw, stripped) / 100.0


def score_candidates(
    company_name: str,
    candidates: List[PlaceCandidate],
    *,
    address_hint: Optional[str] = None,
    branch_hint: Optional[str] = None,
) -> List[PlaceCandidate]:
    """상호명 유사도(+주소/지점 힌트가 있으면 가산)로 점수를 매겨 내림차순 정렬.

    `branch_hint`는 상호명에서 뽑은 지역 토큰('홍대', '건대입구역')이다.
    후보의 주소나 매장명에 그 토큰이 있으면 가산한다 — 동명 타지역 매장이
    1순위로 올라오는 것을 막는 가장 값싼 신호다.
    """
    hint = (address_hint or "").strip()
    branch = (branch_hint or "").strip()
    for c in candidates:
        s = name_score(company_name, c.place_name)
        if hint and c.address:
            # 힌트가 있을 때만 주소를 가산 요소로 쓴다. 없으면 이름만으로 판단.
            addr_sim = fuzz.token_set_ratio(hint, c.address) / 100.0
            s = 0.75 * s + 0.25 * addr_sim
        if branch:
            # 지점명('홍대','건대입구역')은 통칭 지명이라 도로명 주소에는 거의 나타나지
            # 않는다. 따라서 변별력은 후보 **매장명**에서 나온다 — 같은 브랜드의
            # 다른 지점('아크로짐 강남점')을 가리는 것이 이 신호의 본래 용도다.
            # 주소도 함께 보되(구/동 이름이 지점명인 경우가 있다) 매장명이 주 신호다.
            haystack = f"{c.place_name} {c.address}"
            if branch in haystack:
                s = min(1.0, s + 0.12)
            else:
                s = max(0.0, s - 0.08)
        c.score = round(s, 4)
    candidates.sort(key=lambda c: (-c.score, c.place_name))
    return candidates


def haversine_m(a: Dict[str, float], b: Dict[str, float]) -> float:
    """두 좌표 사이의 대원 거리(m)."""
    r = 6371000.0
    lat1, lng1 = math.radians(a["lat"]), math.radians(a["lng"])
    lat2, lng2 = math.radians(b["lat"]), math.radians(b["lng"])
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def pick_by_location(
    candidates: List[PlaceCandidate],
    origin: Optional[Dict[str, float]],
) -> Tuple[Optional[PlaceCandidate], str]:
    """등록 주소 좌표에서 가장 가까운 후보를 고른다. 못 고르면 (None, "ambiguous").

    상호명 점수로는 동명 매장을 가를 수 없다(둘 다 1.000, 격차 0.000). 좌표가
    있으면 이 함수가 먼저 판단하고, 실패하면 호출자가 기존 이름/주소 점수
    경로로 degrade 한다 — 즉 이 함수는 절대 상황을 나쁘게 만들지 않는다.

    좌표가 없는 후보는 **건너뛴다**. 거리 0으로 취급하면 좌표 없는 후보가
    항상 1등이 되어 엉뚱한 매장을 확정하게 된다.
    """
    if not origin or not candidates:
        return None, "ambiguous"

    ranked = sorted(
        ((haversine_m(origin, c.location), c) for c in candidates if c.location),
        key=lambda pair: pair[0],
    )
    if not ranked:
        return None, "ambiguous"

    best_m, best = ranked[0]
    if best_m > LOCATION_MAX_M:
        logger.info("좌표 확정 실패: 가장 가까운 후보가 %.0fm — 같은 매장으로 보지 않는다", best_m)
        return None, "ambiguous"

    if len(ranked) > 1:
        second_m = ranked[1][0]
        separated = (second_m >= best_m * LOCATION_RUNNERUP_RATIO
                     or second_m - best_m >= LOCATION_RUNNERUP_GAP_M)
        if not separated:
            logger.info("좌표 확정 실패: 1등 %.0fm · 2등 %.0fm — 좌표로는 못 가른다",
                        best_m, second_m)
            return None, "ambiguous"

    logger.info("좌표로 매장 확정: '%s' (%.0fm)", best.place_name, best_m)
    return best, "location"


def pick_best(candidates: List[PlaceCandidate]) -> Tuple[Optional[PlaceCandidate], str]:
    """자동 확정 가능하면 (후보, "auto"), 아니면 (None, 사유).

    사유: "ambiguous"(여러 건이 비슷) | "low_score"(1등도 낮음) | "empty"
    """
    if not candidates:
        return None, "empty"
    top = candidates[0]
    if len(candidates) == 1:
        return (top, "auto") if top.score >= SINGLE_HIT_MIN_SCORE else (None, "low_score")
    second = candidates[1]
    if top.score >= AUTO_ACCEPT_SCORE and (top.score - second.score) >= AUTO_ACCEPT_MARGIN:
        return top, "auto"
    if top.score < SINGLE_HIT_MIN_SCORE:
        return None, "low_score"
    return None, "ambiguous"


# ---------------------------------------------------------------- 호출

async def _keyword_search(client: httpx.AsyncClient, query: str, size: int) -> List[Dict[str, Any]]:
    settings = get_settings()
    try:
        resp = await client.get(
            settings.kakao_keyword_url,
            params={"query": query, "size": min(size, KAKAO_MAX_SIZE)},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=20,
        )
    except Exception as exc:
        logger.warning("Kakao 키워드 검색 실패 (%s): %s", query, exc)
        return []
    if resp.status_code == 401:
        logger.error("Kakao 401 — REST API 키를 확인하세요 (JavaScript 키가 아닌지).")
        return []
    if resp.status_code == 403:
        logger.error("Kakao 403 — 앱의 [제품 설정 > 카카오맵] 사용 설정이 꺼져 있습니다.")
        return []
    if resp.status_code != 200:
        logger.warning("Kakao %s: %s", resp.status_code, resp.text[:160])
        return []
    return (resp.json() or {}).get("documents") or []


def _cache_key(company: str, hint: str) -> str:
    raw = f"{company}|{hint}".strip().lower()
    return "kakao:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def search_candidates(
    company_name: str,
    *,
    address_hint: Optional[str] = None,
    size: int = KAKAO_MAX_SIZE,
) -> List[PlaceCandidate]:
    """상호명(+주소 힌트)으로 후보를 찾아 점수순으로 돌려준다.

    쿼리 전략: 힌트가 있으면 "상호명 시군구"를 먼저 시도하고, 0건이면 상호명 단독으로
    한 번 더 시도한다. 힌트를 붙이면 결과가 0건이 되는 경우가 잦은데(등재 안 된 매장),
    그때 상호명 단독 결과라도 보여주고 사용자가 고르게 하는 편이 낫다.
    """
    settings = get_settings()
    name = (company_name or "").strip()
    if not name:
        return []
    if settings.effective_mock_mode() or not settings.kakao_rest_api_key:
        return _mock_candidates(name)

    hint = (address_hint or "").strip()
    cache = get_cache("places")
    ck = _cache_key(name, hint)
    if ck in cache:
        logger.info("Kakao cache hit for '%s'", name)
        return list(cache[ck])

    # 지역 힌트 우선순위: 사용자 입력 > 상호명의 지점명.
    # bizno가 주소를 주지 않으므로 지점명이 유일한 자동 힌트다.
    branch = extract_branch_hint(name)
    if branch:
        logger.info("상호명에서 지점 힌트 추출: '%s' → '%s'", name, branch)

    # 법인격 표기를 뗀 형태. Kakao 에는 법인명이 아니라 **간판명**이 등재되므로
    # '（재）서울예술실용전문학교' 로는 0건이지만 '서울예술실용전문학교' 로는 8건이
    # 나온다. 실측(2026-09-15): 검색 0건이던 7건 중 5건이 이것만으로 살아났다.
    bare = strip_legal_prefix(name)

    queries: List[str] = []
    if hint:
        queries.append(f"{name} {_sigungu(hint)}".strip())
        if bare != name:
            queries.append(f"{bare} {_sigungu(hint)}".strip())
    if branch:
        queries.append(f"{name} {branch}".strip())
    queries.append(name)
    if bare != name:
        queries.append(bare)

    docs: List[Dict[str, Any]] = []
    client = shared_http.get_client()
    for q in queries:
        docs = await _keyword_search(client, q, size)
        if docs:
            logger.info("Kakao '%s' → %d건", q, len(docs))
            break

    # 법인 등기상호(예: '주식회사 몸가짐 휘트니스필라테스구의')가 매장 간판명('몸가짐휘트니스 구의점')과
    # 달라 검색 결과가 0건일 때, 핵심 상호명과 업종 키워드로 점진적 폴백을 시도한다.
    if not docs:
        fallback_queries = _expand_storefront_fallbacks(bare, hint)
        for fq in fallback_queries:
            docs = await _keyword_search(client, fq, size)
            if docs:
                logger.info("Kakao 법인상호 폴백 '%s' → %d건", fq, len(docs))
                break

    cands = score_candidates(name, [_doc_to_candidate(d) for d in docs],
                             address_hint=hint, branch_hint=branch)
    cands = cands[:CANDIDATE_LIMIT]
    cache[ck] = list(cands)
    return cands


def _expand_storefront_fallbacks(bare_name: str, hint: Optional[str]) -> List[str]:
    """법인 등기상호에서 핵심 간판명과 업종 키워드를 추출해 폴백 쿼리를 만든다."""
    sgg = _sigungu(hint) if hint else ""
    alts: List[str] = []
    tokens = bare_name.split()
    if len(tokens) >= 2:
        first = tokens[0]
        # 2번째 토큰에 업종 단어가 포함되어 있으면 접합 및 분리 검색어 생성
        for ind in ("휘트니스", "피트니스", "헬스", "필라테스", "베이커리", "카페", "포차", "식당", "주점", "헤어", "미용실"):
            if ind in tokens[1]:
                if sgg:
                    alts.append(f"{first}{ind} {sgg}".strip())
                    alts.append(f"{first} {ind} {sgg}".strip())
                alts.append(f"{first}{ind}")
                alts.append(f"{first} {ind}")
                break
        if sgg:
            alts.append(f"{first} {sgg}".strip())
        alts.append(first)
    return alts


def _sigungu(addr: str) -> str:
    """'서울특별시 마포구 ...' / '서울 마포구 ...' 에서 시군구 토큰."""
    parts = addr.split()
    for p in parts[1:3]:
        if p.endswith(("구", "시", "군")):
            return p
    return parts[1] if len(parts) > 1 else ""


# 지점명에서 지역을 유추한다. bizno는 주소를 주지 않지만 **상호명에 지점명이 들어 있는
# 경우가 많다** (실측: '아크로짐 홍대점 24시 휘트니스', '어게인짐 건대입구역점').
# 이걸 검색 쿼리의 지역 힌트로 쓰면 동명 타지역 매장을 크게 줄일 수 있다.
_BRANCH_TOKEN = re.compile(r"^(.{2,12}?)(?:지점|점)$")
# 지역이 아닌 '점' 토큰들 — 힌트로 쓰면 오히려 검색을 망친다.
_BRANCH_STOPWORDS = {"본점", "직영점", "가맹점", "신규점", "임시점"}
_BRANCH_NUMERIC = re.compile(r"^\d+(호|호점)?$")


def extract_branch_hint(company_name: str) -> str:
    """'아크로짐 홍대점 24시 휘트니스' → '홍대', '어게인짐 건대입구역점' → '건대입구역'.

    지역을 뜻하지 않는 '본점/1호점' 류는 제외한다. 못 찾으면 빈 문자열.
    """
    name = (company_name or "").strip()
    if not name:
        return ""
    tokens = name.split()
    # 공백이 없으면 문자열 전체에서 말미의 '○○점'을 찾는다 (예: '카페베네강남점').
    if len(tokens) == 1:
        tokens = [name]
    for tok in reversed(tokens):
        if tok in _BRANCH_STOPWORDS:
            continue
        m = _BRANCH_TOKEN.match(tok)
        if not m:
            continue
        base = m.group(1).strip()
        if not base or _BRANCH_NUMERIC.match(base) or base in _BRANCH_STOPWORDS:
            continue
        # 브랜드명이 통째로 잡히는 것을 막는다 — 첫 토큰과 같으면 지역이 아니다.
        if len(tokens) > 1 and base == tokens[0]:
            continue
        return base
    return ""


def _grid_key(location: Dict[str, float], meters: int = 500) -> str:
    """좌표를 약 `meters` 격자로 스냅한 캐시 키.

    같은 동네 매장이 여러 곳이면 주변 집계를 재사용한다(연남동 카페 여러 곳 → 1회).
    위도 1도 ≈ 111km 기준으로 대략 계산한다 — 정밀도가 필요한 용도가 아니다.
    """
    step = meters / 111_000.0
    return f"{round(location['lat'] / step)}:{round(location['lng'] / step)}"


async def warm_connection_pool(size: int = 9) -> None:
    """Kakao 로 가는 keep-alive 연결을 미리 `size` 개 열어 둔다.

    실측(2026-09-15): 새 연결 위로 9건을 동시에 쏘면 응답이 1.08 / 2.07 / 3.08 /
    … 6.10초로 **정확히 1초 계단**을 밟으며 직렬화됐다. IPv6 폴백은 아니었고
    (IPv4 강제로도 동일), 원인을 끝까지 좁히진 못했지만 **예열된 풀에서는 9건이
    0.07초**다. `surroundings()` 가 딱 9건을 동시에 부르므로 9개를 연다.
    앱 시작 시 백그라운드로 한 번 돌리고, 연결은 `utils/http.py` 의 keepalive
    (300초) 동안 살아 있다.
    """
    settings = get_settings()
    if settings.effective_mock_mode() or not settings.kakao_rest_api_key:
        return
    client = shared_http.get_client()
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}

    async def one() -> None:
        try:
            await client.get(settings.kakao_keyword_url,
                             params={"query": "카페", "size": 1},
                             headers=headers, timeout=10)
        except Exception:
            pass  # 예열 실패는 조용히 — 본 요청이 느려질 뿐 틀리지는 않는다

    t0 = asyncio.get_running_loop().time()
    await asyncio.gather(*[one() for _ in range(size)])
    logger.info("Kakao 연결 풀 예열: %d개, %.2fs", size,
                asyncio.get_running_loop().time() - t0)


async def surroundings(
    location: Optional[Dict[str, float]], own_code: str = ""
) -> Optional[Dict[str, Any]]:
    """반경 내 업종 개수 + 대학 근접도를 집계한다. 상권 판정의 입력.

    카테고리별로 `size=1` 로 호출해 **개수(`meta.total_count`)만** 읽는다 —
    문서 목록은 받지 않으므로 응답이 작다. 카테고리 8종 + 대학 키워드 1회 = 9호출.
    Kakao 무료 쿼터가 일 10만이라 부담이 없고, 500m 격자 캐시로 더 줄인다.

    `own_code`(매장의 category_group_code)가 주어지면 같은 업종 개수를
    `own_count`로 함께 돌려준다. 집계 8종에 포함된 코드면 추가 호출 없이
    counts에서 읽고, 아니면 1회만 더 부른다(별도 캐시).
    """
    settings = get_settings()
    if not location or location.get("lat") is None or location.get("lng") is None:
        return None
    if settings.effective_mock_mode() or not settings.kakao_rest_api_key:
        return None

    cache = get_cache("places")
    gk = _grid_key(location)
    ck = "surround:" + gk

    lat, lng = location["lat"], location["lng"]
    headers = {"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"}

    # 9건을 동시에 부르되 클라이언트는 공유한다. 호출마다 새 클라이언트를 만들면
    # SSL 컨텍스트 생성(CPU 38ms)이 GIL에 묶여 직렬화되어 이 구간만 3.3초가 걸렸다.
    client = shared_http.get_client()

    async def one_category(code: str) -> Tuple[str, int]:
        try:
            r = await client.get(
                settings.kakao_category_url,
                params={"category_group_code": code, "x": lng, "y": lat,
                        "radius": TA_RADIUS, "size": 1},
                headers=headers, timeout=20,
            )
            if r.status_code != 200:
                return code, 0
            return code, int(((r.json() or {}).get("meta") or {}).get("total_count") or 0)
        except Exception:
            return code, 0

    async def univ_count() -> int:
        try:
            r = await client.get(
                settings.kakao_keyword_url,
                params={"query": "대학교", "x": lng, "y": lat,
                        "radius": TA_UNIV_RADIUS, "size": 1},
                headers=headers, timeout=20,
            )
            if r.status_code != 200:
                return 0
            return int(((r.json() or {}).get("meta") or {}).get("total_count") or 0)
        except Exception:
            return 0

    if ck in cache:
        logger.info("주변 상권 집계 캐시 히트 (%s)", ck)
        base = cache[ck]
    else:
        results = await asyncio.gather(
            *[one_category(c) for c in TA_GROUPS], univ_count(),
        )
        counts = dict(results[:-1])
        base = {"counts": counts, "univ": results[-1], "radius": TA_RADIUS}
        total = sum(counts.values())
        logger.info("주변 상권 집계: 총 %d곳, 대학 %d (반경 %dm)",
                    total, base["univ"], TA_RADIUS)
        if total > 0:
            cache[ck] = base

    if not own_code:
        return base
    if own_code in TA_GROUPS:
        own_count = int(base["counts"].get(own_code, 0) or 0)
    else:
        ock = f"surround-own:{gk}:{own_code}"
        if ock in cache:
            own_count = cache[ock]
        else:
            _, own_count = await one_category(own_code)
            # 매장 자신이 반경 안에 있으므로 정상 응답은 항상 1 이상이다.
            # 0 은 호출 실패(one_category 가 예외를 삼키고 0 을 준다)이므로 캐시하지
            # 않는다 — 집계 쪽 `if total > 0` 가드와 같은 이유다.
            if own_count > 0:
                cache[ock] = own_count
    # base(캐시 공유 객체)는 건드리지 않고 사본에 own 정보를 붙인다.
    return {**base, "own_code": own_code, "own_count": own_count}


async def region_from_coord(location: Optional[Dict[str, float]]) -> str:
    """좌표 → **행정동** 주소 문자열. 상권 매칭용.

    상권 엑셀은 행정동 기준인데 Kakao 키워드 검색의 지번 주소(`address_name`)는
    **법정동**을 준다. 둘이 다르면 매칭이 sido-fallback 으로 떨어진다
    (2026-08-05 실측: 중구 `만리동1가`(법정동) → 매칭 실패, 행정동은 `중림동`).
    연남동처럼 법정동=행정동인 경우만 우연히 맞았다.

    `coord2regioncode` 는 법정동(B)과 행정동(H)을 함께 주므로 H를 골라 쓴다.
    실패하면 빈 문자열 — 호출자가 지번 주소로 폴백한다.
    """
    settings = get_settings()
    if not location or location.get("lat") is None or location.get("lng") is None:
        return ""
    if settings.effective_mock_mode() or not settings.kakao_rest_api_key:
        return ""
    try:
        resp = await shared_http.get_client().get(
            settings.kakao_coord2region_url,
            params={"x": location["lng"], "y": location["lat"]},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=20,
        )
    except Exception as exc:
        logger.warning("Kakao 좌표→행정동 변환 실패: %s", exc)
        return ""
    if resp.status_code != 200:
        logger.warning("Kakao coord2regioncode %s: %s", resp.status_code, resp.text[:160])
        return ""
    docs = (resp.json() or {}).get("documents") or []
    for d in docs:
        if d.get("region_type") == "H":          # 행정동
            addr = d.get("address_name") or ""
            if addr:
                logger.info("행정동 확인: %s", addr)
                return addr
    return ""


async def geocode(address: str) -> Optional[Dict[str, float]]:
    """주소 → 좌표. Kakao 주소 검색 사용 (Google Geocoding 대체)."""
    settings = get_settings()
    if not address or not address.strip():
        return None
    if settings.effective_mock_mode() or not settings.kakao_rest_api_key:
        return {"lat": 37.5665, "lng": 126.9780}
    try:
        resp = await shared_http.get_client().get(
            settings.kakao_address_url,
            params={"query": address.strip(), "size": 1},
            headers={"Authorization": f"KakaoAK {settings.kakao_rest_api_key}"},
            timeout=20,
        )
    except Exception as exc:
        logger.warning("Kakao 지오코딩 실패: %s", exc)
        return None
    if resp.status_code != 200:
        logger.warning("Kakao 지오코딩 %s: %s", resp.status_code, resp.text[:160])
        return None
    docs = (resp.json() or {}).get("documents") or []
    return _to_location(docs[0]) if docs else None


# ---------------------------------------------------------------- mock

def _mock_candidates(name: str) -> List[PlaceCandidate]:
    return [PlaceCandidate(
        place_id="mock-kakao-1",
        place_name=name or "별빛카페 달빛차",
        category_name="음식점 > 카페 > 커피전문점",
        category_group_code="CE7",
        business_type="커피전문점",
        address="서울 마포구 포은로 109",
        phone="02-000-0000",
        place_url="https://place.map.kakao.com/0",
        location={"lat": 37.5547, "lng": 126.9068},
        score=1.0,
    )]
