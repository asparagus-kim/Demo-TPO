"""Entity-consistency validation between moneypin (canonical) and Google Places.

Decision rule:
    - moneypin is the canonical identity source for 상호명 / 업종 / 주소.
    - Google Places is a candidate enrichment source. We accept it only when
      its name + address + business-type-family are compatible with moneypin.
    - When validation fails, downstream code must NOT use Google business type,
      hours, reviews, place_types, or rating as ambience evidence.

Pure functions (no network) so they are unit-testable.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz

from ..schemas import BusinessInfo, EntityValidation, GooglePlaces
from ..utils.address import (
    address_prefix_key,
    clean_whitespace,
    normalize_address as _normalize_address_canonical,
    parse_address,
)
from ..utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------- thresholds

NAME_SIMILARITY_THRESHOLD = 60.0     # 0-100 (rapidfuzz)
ADDRESS_SIMILARITY_THRESHOLD = 60.0  # 0-100
COMBINED_SCORE_THRESHOLD = 0.55      # 0-1
NAME_HARD_OVERRIDE = 88.0            # near-identical name overrides weak address
ADDRESS_HARD_OVERRIDE = 92.0         # exact-canonical address overrides weak name


# ---------------------------------------------------------------------- name helpers

_NAME_NOISE_PATTERNS = [
    re.compile(r"\([^)]*\)"),                         # any parenthesised text
    re.compile(r"\[[^\]]*\]"),
    re.compile(r"[　\s]+"),                       # whitespace
]

_LEGAL_PREFIXES = (
    "주식회사", "(주)", "㈜", "유한회사", "(유)", "합자회사",
    "합명회사", "사단법인", "재단법인", "협동조합", "유한책임회사",
)

_LOCATION_TOKEN = re.compile(
    r"(강남점|역삼점|신촌점|홍대점|명동점|판교점|분당점|구로점|선릉점|성수점|"
    r"본점|지점|\d+호점|점)$"
)


def normalize_company_name(name: Optional[str]) -> str:
    """Lowercase, strip legal-form prefixes, parens, store-suffixes, punctuation, whitespace."""
    if not name:
        return ""
    n = clean_whitespace(name)
    # Remove leading legal-form prefixes (with or without surrounding spaces)
    for pref in _LEGAL_PREFIXES:
        if n.startswith(pref):
            n = n[len(pref):].strip()
            break
        # Also strip when used as a suffix
        if n.endswith(pref):
            n = n[: -len(pref)].strip()
            break
    # Remove parenthetical and bracketed content
    for pat in _NAME_NOISE_PATTERNS:
        n = pat.sub(" ", n)
    n = re.sub(r"[·•/,\\.\-_'\"`!@#$%^&*?:;]+", " ", n)
    n = clean_whitespace(n).strip().lower()
    # Drop trailing 점/지점 token (e.g. "샘플카페 강남점" -> "샘플카페")
    base = _LOCATION_TOKEN.sub("", n).strip()
    return base or n


def name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """0-100. Token-set ratio is robust to ordering and 'XX점' suffixes."""
    na, nb = normalize_company_name(a), normalize_company_name(b)
    if not na or not nb:
        return 0.0
    score = max(
        fuzz.token_set_ratio(na, nb),
        fuzz.partial_ratio(na, nb),
    )
    return float(score)


# ---------------------------------------------------------------------- address helpers

def normalize_address(address: Optional[str]) -> str:
    """Canonical '시/도 시군구 행정동' form (or cleaned raw). Re-uses utils.address."""
    if not address:
        return ""
    return _normalize_address_canonical(address)


def address_similarity(a: Optional[str], b: Optional[str]) -> float:
    """0-100. Compares canonical sigungu/dong tokens; falls back to fuzz on raw strings."""
    if not a or not b:
        return 0.0
    pa, pb = parse_address(a), parse_address(b)

    # Hard requirement: same 시/도 (when both are detectable). Different 시/도
    # almost always means a different establishment.
    if pa.sido and pb.sido and pa.sido != pb.sido:
        return float(fuzz.token_set_ratio(pa.canonical or a, pb.canonical or b)) * 0.4

    # If both have sigungu, give credit for matching sigungu and dong.
    score = 0.0
    if pa.sigungu and pb.sigungu:
        if pa.sigungu == pb.sigungu:
            score += 60.0
        else:
            score += float(fuzz.ratio(pa.sigungu, pb.sigungu)) * 0.4
    if pa.dong and pb.dong:
        if pa.dong == pb.dong:
            score += 35.0
        else:
            score += float(fuzz.ratio(pa.dong, pb.dong)) * 0.25

    # Fallback / supplement: token-set ratio on the canonical-or-raw strings.
    canon_a = pa.canonical or clean_whitespace(a)
    canon_b = pb.canonical or clean_whitespace(b)
    fuzzy = float(fuzz.token_set_ratio(canon_a, canon_b))
    score = max(score, fuzzy)
    return min(100.0, score)


# ---------------------------------------------------------------------- business-type families

# Each family is one canonical "what kind of business is this?" bucket.
# Korean moneypin 업종 strings and Google Places `types[]` both map into this.
BUSINESS_TYPE_FAMILIES = (
    "food_and_beverage",
    "retail",
    "beauty",
    "health",
    "education",
    "lodging",
    "professional_services",
    "automotive",
    "real_estate",
    "manufacturing",
    "entertainment",
    "other",
)

# Korean (moneypin) keyword -> family
_MP_FAMILY_RULES: List[Tuple[str, List[str]]] = [
    ("food_and_beverage", [
        "카페", "커피", "음식", "식당", "분식", "한식", "일식", "양식", "중식",
        "베이커리", "빵", "제과", "디저트", "주점", "바", "호프", "이자카야",
        "치킨", "피자", "햄버거", "패스트", "포차", "와인", "레스토랑", "F&B",
        "주류", "포장", "테이크아웃",
    ]),
    ("retail", [
        "소매", "유통", "도소매", "편의점", "마트", "슈퍼", "쇼핑", "의류",
        "잡화", "생활용품", "전자상거래", "통신판매", "판매업",
    ]),
    ("beauty", ["미용", "뷰티", "헤어", "네일", "에스테틱", "피부", "왁싱", "메이크업"]),
    ("health", ["병원", "의원", "약국", "한의", "치과", "헬스", "필라테스", "요가", "스포츠 센터", "운동"]),
    ("education", ["학원", "교육", "교습소", "스쿨", "어학", "유치", "코딩"]),
    ("lodging", ["숙박", "호텔", "모텔", "게스트", "펜션", "민박", "리조트"]),
    ("professional_services", [
        "세무", "회계", "법무", "변호사", "컨설팅", "광고", "마케팅", "디자인",
        "소프트웨어", "IT", "정보서비스", "출판", "미디어", "콘텐츠", "교육서비스",
        "음악", "오디오", "영상", "방송", "기타 오디오물",
    ]),
    ("automotive", ["차량", "자동차", "주유", "정비", "운송", "택배", "물류"]),
    ("real_estate", ["부동산", "중개", "임대"]),
    ("manufacturing", ["제조", "공장", "가공", "수리", "설치", "건설", "인테리어"]),
    ("entertainment", ["오락", "게임", "PC방", "노래", "코인노래", "영화", "공연"]),
]

# Google Places `types[]` -> family
_GP_TYPE_FAMILY: Dict[str, str] = {
    # food
    "restaurant": "food_and_beverage",
    "food": "food_and_beverage",
    "cafe": "food_and_beverage",
    "coffee_shop": "food_and_beverage",
    "bakery": "food_and_beverage",
    "bar": "food_and_beverage",
    "meal_delivery": "food_and_beverage",
    "meal_takeaway": "food_and_beverage",
    "ice_cream_shop": "food_and_beverage",
    "fast_food_restaurant": "food_and_beverage",
    "pub": "food_and_beverage",
    "wine_bar": "food_and_beverage",
    # retail
    "store": "retail",
    "convenience_store": "retail",
    "supermarket": "retail",
    "shopping_mall": "retail",
    "clothing_store": "retail",
    "department_store": "retail",
    "grocery_or_supermarket": "retail",
    # beauty
    "beauty_salon": "beauty",
    "hair_care": "beauty",
    "nail_salon": "beauty",
    "spa": "beauty",
    # health
    "hospital": "health",
    "doctor": "health",
    "dentist": "health",
    "pharmacy": "health",
    "gym": "health",
    "physiotherapist": "health",
    # education
    "school": "education",
    "university": "education",
    "primary_school": "education",
    "secondary_school": "education",
    # lodging
    "lodging": "lodging",
    "hotel": "lodging",
    "motel": "lodging",
    # professional services
    "lawyer": "professional_services",
    "accounting": "professional_services",
    "real_estate_agency": "real_estate",
    "insurance_agency": "professional_services",
    "advertising_agency": "professional_services",
    # automotive
    "car_repair": "automotive",
    "car_dealer": "automotive",
    "car_wash": "automotive",
    "gas_station": "automotive",
    # entertainment
    "night_club": "entertainment",
    "movie_theater": "entertainment",
    "amusement_park": "entertainment",
    # generic
    "point_of_interest": "other",
    "establishment": "other",
}


def map_business_type_family(biz_type: Optional[str]) -> str:
    """Map a free-text 업종 string OR a single Google Places type to a family bucket.

    Heuristic:
        1. If the input matches a known Google Places type id, use that mapping.
        2. Otherwise scan Korean keywords from `_MP_FAMILY_RULES` (first match wins).
        3. Default to "other".
    """
    if not biz_type:
        return "other"
    raw = biz_type.strip().lower()
    if raw in _GP_TYPE_FAMILY:
        return _GP_TYPE_FAMILY[raw]
    for family, keywords in _MP_FAMILY_RULES:
        for kw in keywords:
            if kw in biz_type or kw.lower() in raw:
                return family
    return "other"


def _google_types_to_families(types: List[str]) -> List[str]:
    fams: List[str] = []
    for t in types or []:
        fam = _GP_TYPE_FAMILY.get((t or "").lower())
        if fam and fam != "other" and fam not in fams:
            fams.append(fam)
    return fams


def is_business_type_compatible(moneypin_type: Optional[str], google_type: Optional[Any]) -> bool:
    """`google_type` may be a single string OR a list[str] (Places `types[]`)."""
    mp_fam = map_business_type_family(moneypin_type)
    if isinstance(google_type, (list, tuple)):
        gp_fams = _google_types_to_families(list(google_type))
        if not gp_fams:
            # Only generic "establishment"/"point_of_interest" etc. — treat as
            # "no signal" rather than incompatible.
            return True
        return mp_fam in gp_fams or mp_fam == "other"
    gp_fam = map_business_type_family(google_type) if google_type else "other"
    if gp_fam == "other" or mp_fam == "other":
        return True
    return mp_fam == gp_fam


# ---------------------------------------------------------------------- main API

def _coerce_business_info(moneypin_info: Any) -> Dict[str, Any]:
    if isinstance(moneypin_info, BusinessInfo):
        return {
            "company_name": moneypin_info.company_name or "",
            "business_type": moneypin_info.business_type or "",
            "address": moneypin_info.address or "",
        }
    if isinstance(moneypin_info, dict):
        return {
            "company_name": moneypin_info.get("company_name") or "",
            "business_type": moneypin_info.get("business_type") or "",
            "address": (
                moneypin_info.get("address")
                or moneypin_info.get("location")
                or ""
            ),
        }
    return {"company_name": "", "business_type": "", "address": ""}


def _coerce_google_info(google_info: Any) -> Dict[str, Any]:
    if isinstance(google_info, GooglePlaces):
        return {
            "place_name": google_info.place_name or "",
            "formatted_address": google_info.formatted_address or "",
            "place_types": list(google_info.place_types or []),
        }
    if isinstance(google_info, dict):
        return {
            "place_name": google_info.get("place_name") or "",
            "formatted_address": google_info.get("formatted_address") or "",
            "place_types": list(google_info.get("place_types") or []),
        }
    return {"place_name": "", "formatted_address": "", "place_types": []}


def validate_google_place_identity(moneypin_info: Any, google_info: Any) -> Dict[str, Any]:
    """Decide whether Google Places refers to the same entity as moneypin.

    Returns a JSON-friendly dict mirroring the `EntityValidation` schema, plus
    a `score` in [0,1] that downstream code can use as a soft confidence.
    """
    mp = _coerce_business_info(moneypin_info)
    gp = _coerce_google_info(google_info)

    has_google = bool(gp["place_name"] or gp["formatted_address"] or gp["place_types"])
    if not has_google:
        return EntityValidation(
            is_consistent=False,
            name_similarity=0.0,
            address_similarity=0.0,
            business_type_compatible=False,
            score=0.0,
            reasons=["Google Places 결과가 비어 있어 검증할 수 없습니다."],
            moneypin_summary=mp,
            google_summary=gp,
        ).model_dump()

    name_sim = name_similarity(mp["company_name"], gp["place_name"])
    type_ok = is_business_type_compatible(mp["business_type"], gp["place_types"])

    # 한쪽에 주소가 없으면 "신호 없음"이지 "불일치"가 아니다.
    #
    # bizno 무료 플랜은 주소를 주지 않으므로(2026-08-05 실측) canonical 주소가 빈
    # 경우가 생긴다. 그때 addr_sim=0 으로 계산하면 아래 임계값(주소 60) 때문에
    # **정상 매장도 전부 불일치로 떨어진다.** 주소를 점수에서 빼고 이름·업종만으로
    # 판정하도록 가중치를 재분배한다.
    has_addresses = bool(mp["address"]) and bool(gp["formatted_address"])
    addr_sim = address_similarity(mp["address"], gp["formatted_address"]) if has_addresses else 0.0

    # Hard veto: if BOTH addresses have a detectable 시/도 and they differ,
    # the candidate cannot be the same establishment, regardless of how
    # closely the names match (chains share names across cities).
    pa = parse_address(mp["address"]) if mp["address"] else None
    pb = parse_address(gp["formatted_address"]) if gp["formatted_address"] else None
    sido_mismatch = bool(pa and pb and pa.sido and pb.sido and pa.sido != pb.sido)

    # Combined score: weighted sum on [0,1]. Type compatibility is a soft boost.
    # 주소가 없으면 주소 몫(0.40)을 이름으로 넘긴다 — 감점하지 않는다.
    if has_addresses:
        score = 0.45 * (name_sim / 100.0) + 0.40 * (addr_sim / 100.0) + 0.15 * (1.0 if type_ok else 0.0)
    else:
        score = 0.85 * (name_sim / 100.0) + 0.15 * (1.0 if type_ok else 0.0)

    reasons: List[str] = []
    is_consistent = True

    if sido_mismatch:
        is_consistent = False
        reasons.append(
            f"시/도 불일치 (moneypin='{pa.sido}', google='{pb.sido}') — 동일 업체로 판단할 수 없음"
        )
    if name_sim < NAME_SIMILARITY_THRESHOLD and addr_sim < ADDRESS_HARD_OVERRIDE:
        is_consistent = False
        reasons.append(
            f"상호명 유사도 낮음 ({name_sim:.0f} < {NAME_SIMILARITY_THRESHOLD:.0f})"
        )
    if has_addresses and addr_sim < ADDRESS_SIMILARITY_THRESHOLD and name_sim < NAME_HARD_OVERRIDE:
        is_consistent = False
        reasons.append(
            f"주소 유사도 낮음 ({addr_sim:.0f} < {ADDRESS_SIMILARITY_THRESHOLD:.0f})"
        )
    elif not has_addresses:
        reasons.append("주소 정보가 없어 상호명·업종만으로 판정했습니다.")
    if not type_ok:
        is_consistent = False
        reasons.append(
            f"업종 family 불일치 (moneypin='{map_business_type_family(mp['business_type'])}', "
            f"google={_google_types_to_families(gp['place_types']) or ['other']})"
        )
    if score < COMBINED_SCORE_THRESHOLD:
        is_consistent = False
        reasons.append(f"종합 점수 낮음 ({score:.2f} < {COMBINED_SCORE_THRESHOLD:.2f})")

    if is_consistent and not reasons:
        reasons.append("이름·주소·업종이 일관됩니다.")

    result = EntityValidation(
        is_consistent=is_consistent,
        name_similarity=round(float(name_sim), 1),
        address_similarity=round(float(addr_sim), 1),
        business_type_compatible=type_ok,
        score=round(float(score), 3),
        reasons=reasons,
        moneypin_summary=mp,
        google_summary=gp,
    )
    logger.info(
        "entity_validation: consistent=%s name=%.1f addr=%.1f type_ok=%s score=%.2f",
        is_consistent, name_sim, addr_sim, type_ok, score,
    )
    return result.model_dump()


def has_usable_review_text(reviews: List[Any], *, min_chars: int = 12, min_count: int = 2) -> bool:
    """Return True iff there are >= `min_count` reviews each with text >= `min_chars`."""
    usable = 0
    for rv in reviews or []:
        text = ""
        if hasattr(rv, "text"):
            text = (getattr(rv, "text") or "").strip()
        elif isinstance(rv, dict):
            text = (rv.get("text") or "").strip()
        elif isinstance(rv, str):
            text = rv.strip()
        if len(text) >= min_chars:
            usable += 1
            if usable >= min_count:
                return True
    return False
