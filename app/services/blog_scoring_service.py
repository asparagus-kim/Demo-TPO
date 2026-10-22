"""Pure-Python keyword and negation scorer for blog and web review snippets.

Complies with Kakao Developers Operations Policy and Naver Open API Terms of Service:
- 0 calls to external AI / LLMs on 3rd-party blog text.
- Operates purely in-memory (no persistent storage or reselling of blog snippets).
- Provides instant (<1ms) energy, tempo, mood, occasion, and keyword extraction.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from ..schemas import PlaceReview, WebEvidenceItem
from .llm_service import ReviewScore, compute_weight


# ---------------------------------------------------------------------------
# Calibrated Korean Keyword Dictionaries & Weights
# ---------------------------------------------------------------------------

POS_ENERGY: List[Tuple[str, float]] = [
    ("신나", 0.18), ("핫플", 0.16), ("활기", 0.16), ("시끌", 0.16),
    ("웨이팅", 0.15), ("줄서", 0.14), ("만석", 0.14), ("북적", 0.14),
    ("붐비", 0.14), ("힙한", 0.14), ("트렌디", 0.12), ("인기", 0.10),
    ("유명", 0.10), ("사람 많", 0.12), ("흥겨", 0.15), ("활발", 0.12),
]

NEG_ENERGY: List[Tuple[str, float]] = [
    ("조용", 0.18), ("한적", 0.18), ("차분", 0.18), ("여유", 0.15),
    ("아담", 0.12), ("편안", 0.12), ("한산", 0.15), ("고즈넉", 0.16),
    ("쉼", 0.10), ("힐링", 0.12), ("잔잔", 0.15), ("독서", 0.14),
]

POS_TEMPO: List[Tuple[str, float]] = [
    ("빠르", 0.14), ("신나", 0.14), ("경쾌", 0.14), ("회전율", 0.12),
    ("테이크아웃", 0.10), ("포장", 0.08), ("운동", 0.15), ("득근", 0.16),
]

NEG_TEMPO: List[Tuple[str, float]] = [
    ("느긋", 0.16), ("여유", 0.15), ("천천히", 0.15), ("오래 머물", 0.14),
    ("대화하기 좋", 0.12), ("작업하기 좋", 0.12), ("공부", 0.12), ("카공", 0.14),
]

POS_MOOD: List[Tuple[str, float]] = [
    ("감성", 0.15), ("분위기", 0.15), ("인테리어", 0.14), ("친절", 0.12),
    ("따뜻", 0.12), ("아늑", 0.14), ("예쁜", 0.12), ("깔끔", 0.10),
    ("고급", 0.14), ("정갈", 0.12), ("데이트", 0.15), ("추천", 0.08),
    ("맛집", 0.08), ("최고", 0.08), ("만족", 0.08), ("힐링", 0.12),
]

NEG_MOOD: List[Tuple[str, float]] = [
    ("불친절", 0.25), ("지저분", 0.25), ("어수선", 0.20), ("실망", 0.20),
    ("별로", 0.18), ("그저 그", 0.15), ("비위생", 0.25), ("냄새", 0.15),
]

OCCASION_RULES: List[Tuple[str, List[str]]] = [
    ("데이트", ["데이트", "연인", "기념일", "소개팅", "커플", "분위기 좋"]),
    ("친구모임", ["친구", "모임", "수다", "동기", "회식", "단체", "술자리"]),
    ("야간 모임", ["2차", "심야", "포차", "이자카야", "새벽", "안주", "술집"]),
    ("간식/테이크아웃", ["포장", "선물", "디저트", "쿠키", "베이커리", "빵집", "구움과자"]),
    ("혼밥/혼카페", ["혼자", "혼밥", "혼술", "카공", "작업", "노트북", "1인"]),
    ("운동/트레이닝", ["헬스", "PT", "운동", "기구", "트레이너", "필라테스", "스트레칭", "오운완"]),
    ("가족외식", ["가족", "부모님", "아이", "아기의자", "주말외식"]),
    ("비즈니스미팅", ["미팅", "접대", "조용한", "룸", "비즈니스"]),
]

_NEGATION_SUFFIX = re.compile(
    r"(?:지\s*않|지\s*못|지않|지못|안\s+|없|아닌|아니|전혀\s*안|별로\s*안)"
)


def _score_axis_with_negation(
    text: str,
    pos_rules: List[Tuple[str, float]],
    neg_rules: List[Tuple[str, float]],
    base: float = 0.50,
) -> Tuple[float, List[str]]:
    score = base
    matched: List[str] = []

    for tok, delta in pos_rules:
        idx = text.find(tok)
        if idx != -1:
            after = text[idx + len(tok): idx + len(tok) + 8]
            if _NEGATION_SUFFIX.search(after):
                # Negated positive -> acts as mild negative (e.g. "시끄럽지 않고" -> quiet)
                score -= delta * 0.8
                matched.append(f"!{tok}")
            else:
                score += delta
                matched.append(tok)

    for tok, delta in neg_rules:
        idx = text.find(tok)
        if idx != -1:
            after = text[idx + len(tok): idx + len(tok) + 8]
            if _NEGATION_SUFFIX.search(after):
                score += delta * 0.6
                matched.append(f"!{tok}")
            else:
                score -= delta
                matched.append(tok)

    return max(0.05, min(0.95, score)), matched


def score_blog_item(item: WebEvidenceItem) -> ReviewScore:
    """Score a single blog or web review snippet using pure Python."""
    text = (item.text or "").strip()
    energy, e_kw = _score_axis_with_negation(text, POS_ENERGY, NEG_ENERGY, base=0.50)
    tempo, t_kw = _score_axis_with_negation(text, POS_TEMPO, NEG_TEMPO, base=0.50)
    mood, m_kw = _score_axis_with_negation(text, POS_MOOD, NEG_MOOD, base=0.55)

    occasions: List[str] = []
    for label, kws in OCCASION_RULES:
        if any(k in text for k in kws):
            occasions.append(label)

    all_kw: List[str] = []
    for k in e_kw + t_kw + m_kw:
        clean_k = k.lstrip("!")
        if clean_k not in all_kw:
            all_kw.append(clean_k)

    # Informativeness scales with snippet length and atmosphere signal density
    signal_count = len(all_kw) + len(occasions)
    info = min(1.0, 0.45 + min(len(text), 220) / 400.0 + min(signal_count, 5) * 0.07)

    review_obj = PlaceReview(text=text, author=item.source or "blog")
    weight = compute_weight(review_obj)

    return ReviewScore(
        energy=round(energy, 3),
        tempo=round(tempo, 3),
        mood=round(mood, 3),
        informativeness=round(info, 3),
        occasion_labels=occasions[:2],
        keywords=all_kw[:5],
        evidence="pure_python_blog_keyword",
        weight=weight,
    )


def score_blog_items(items: List[WebEvidenceItem]) -> List[ReviewScore]:
    """Score a list of blog evidence items in memory."""
    return [score_blog_item(it) for it in items if (it.text or "").strip()]


# ---------------------------------------------------------------------------
# Storefront & Geographic Verification (Discards spam, brand mismatches, other cities)
# ---------------------------------------------------------------------------

_SPAM_KEYWORDS = (
    "분양", "임대", "매물", "원룸", "투룸", "오피스텔", "전세", "월세",
    "구인", "채용", "알바", "아르바이트", "창업비용", "권리금",
)

_SIDO_LIST = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]


def clean_store_brand(name: str) -> str:
    """Strip corporate prefixes/suffixes and branch labels to isolate the core brand."""
    cleaned = re.sub(
        r"^(?:주식회사|\(주\)|㈜|유한회사)\s*|\s*(?:주식회사|\(주\)|㈜|유한회사)$", "", (name or "").strip()
    ).strip()
    # Strip branch suffixes like 구의점, 본점, 직영점, 강남점
    cleaned = re.sub(r"\s+(?:[가-힣]+본점|[가-힣]+직영점|[가-힣]+점)$", "", cleaned).strip()
    return cleaned


def extract_geo_anchors(address: str, region_address: str = "") -> dict:
    """Extract Sido, Gu/Si/Gun, Dong/Town, and Road names from store addresses."""
    combined = f"{address or ''} {region_address or ''}".strip()
    sido = ""
    for s in _SIDO_LIST:
        if s in combined:
            sido = s
            break

    dongs = set(re.findall(r"([가-힣0-9]+(?:동|읍|면|가))\b", combined))
    dong_stems = {d[:-1] for d in dongs if len(d) >= 2 and d.endswith(("동", "읍", "면", "가"))}
    base_roads = set(re.findall(r"([가-힣]+[로])", combined))
    full_roads = set(re.findall(r"([가-힣0-9]+(?:로|길))\b", combined))
    gus = set(re.findall(r"([가-힣]+(?:구|시|군))\b", combined))

    return {
        "sido": sido,
        "dongs": dongs,
        "dong_stems": dong_stems,
        "roads": base_roads | full_roads,
        "gus": gus,
    }


def is_store_blog_match(
    title: str,
    snippet: str,
    store_name: str,
    address: str = "",
    region_address: str = "",
) -> Tuple[bool, str]:
    """Verify whether a blog post belongs to the target storefront.

    Enforces 3 checks:
    1. Anti-spam: Discards real-estate listings, job posts, and franchise sales.
    2. Brand presence: Requires the store brand name or its primary token.
    3. Geographic consistency:
       - Rejects posts mentioning a conflicting city/province (Sido).
       - If store specifies a branch (e.g. '구의점'), requires matching that branch or local dong/road.
       - Matches local dong, road name, or district.
    """
    full_text = f"{title or ''} {snippet or ''}"
    clean_text = re.sub(r"</?b>", "", full_text, flags=re.IGNORECASE)

    # 1. Anti-spam filter
    for sp in _SPAM_KEYWORDS:
        if sp in clean_text:
            return False, f"spam:{sp}"

    # If no store_name is provided, cannot verify brand/geo -> accept by default
    if not store_name:
        return True, "no_store_filter"

    # 2. Store brand match
    brand = clean_store_brand(store_name)
    bare_brand = brand.replace(" ", "").lower()
    text_bare = clean_text.replace(" ", "").lower()

    brand_matched = False
    if len(bare_brand) >= 2 and bare_brand in text_bare:
        brand_matched = True
    else:
        # Check significant tokens of compound brand names (e.g. '심야식당 후타리' -> '후타리')
        tokens = brand.split()
        for tok in tokens:
            t_bare = tok.lower()
            if len(t_bare) >= 2 and t_bare in text_bare:
                brand_matched = True
                break

    if not brand_matched:
        return False, f"brand_not_found:{brand}"

    # 3. Geographic consistency check
    if not (address or region_address):
        return True, "brand_only_no_address"

    geo = extract_geo_anchors(address, region_address)
    store_sido = geo["sido"]

    # Conflicting SIDO rejection
    if store_sido:
        for other_sido in _SIDO_LIST:
            if other_sido != store_sido and other_sido in clean_text:
                # If store's own local anchors (dong/road) aren't present, conflicting sido is fatal
                if not any(d in clean_text for d in (geo["dongs"] | geo["roads"])):
                    return False, f"conflicting_sido:{other_sido}"

    # Branch specification check (e.g., '몸가짐휘트니스 구의점' -> branch is '구의')
    branch_m = re.search(r"([가-힣]+)점\b", store_name)
    branch = branch_m.group(1) if branch_m else ""

    if branch:
        # If store explicitly has a branch name, we strictly require local/branch match
        # (must contain branch name or target dong, not merely a long avenue name)
        has_branch_or_dong = (branch in clean_text) or any(
            d in clean_text for d in (geo["dongs"] | geo["dong_stems"])
        )
        if not has_branch_or_dong:
            return False, f"branch_mismatch:expected_{branch}"
        return True, "branch_matched"

    local_anchors = geo["dongs"] | geo["dong_stems"] | geo["roads"]
    has_local = any(a in clean_text for a in local_anchors if a)
    has_gu = any(g in clean_text for g in geo["gus"] if g)

    if has_local:
        return True, "local_geo_matched"

    if has_gu:
        return True, "gu_geo_matched"

    # Distinctive brand fallback (e.g. unique 4+ char name like '딜란스쿠키' without conflicting SIDO)
    if len(bare_brand) >= 4 and not any(other in clean_text for other in _SIDO_LIST if other != store_sido):
        return True, "distinct_brand_no_conflict"

    return False, "no_geo_anchor"


def filter_relevant_blogs(
    items: List[WebEvidenceItem],
    store_name: str,
    address: str = "",
    region_address: str = "",
) -> List[WebEvidenceItem]:
    """Filter and rank blog posts to ensure they belong to the target storefront.

    - Verifies spam, brand presence, and geographic anchor consistency.
    - Prioritizes posts that feature the store brand directly in their title.
    - If dedicated title-matched reviews exist (>= 2), drops generic multi-spot roundups.
    """
    if not store_name and not address:
        return items

    clean_brand = clean_store_brand(store_name).replace(" ", "").lower() if store_name else ""

    kept: List[Tuple[bool, WebEvidenceItem]] = []
    for it in items:
        ok, _ = is_store_blog_match(
            it.title or "", it.text or "", store_name, address=address, region_address=region_address
        )
        if ok:
            title_clean = re.sub(r"</?b>", "", it.title or "").replace(" ", "").lower()
            in_title = bool(clean_brand and len(clean_brand) >= 2 and clean_brand in title_clean)
            kept.append((in_title, it))

    title_matched = [it for in_title, it in kept if in_title]
    body_only = [it for in_title, it in kept if not in_title]

    # If we have at least 2 dedicated store reviews with brand in title, prefer them
    if len(title_matched) >= 2:
        return title_matched + [it for it in body_only if not any(sp in (it.title or "") for sp in ("호텔", "투어", "축제", "페스티벌"))]

    return [it for _, it in kept]

