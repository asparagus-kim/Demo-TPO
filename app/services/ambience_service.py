"""Priors + fusion for the ambience scoring pipeline.

Pure functions that can be unit-tested without network access.
Inputs come from other services; the fusion formula is the one defined in
the product spec. Scores are normalised to [0,1] internally and returned
on [0,100] for UI.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..schemas import Ambience, GooglePlaces, PlaceReview, TpoProfile, TradeAreaMatch, Weather
from ..utils.logging import get_logger
from .entity_validation_service import map_business_type_family
from .llm_service import ReviewScore, aggregate_text_scores
# 업종군 매핑은 music_service가 정본이다 (곡 메타데이터와 같은 어휘를 써야 한다).
from .music_service import detect_industry_group

logger = get_logger(__name__)

# --------------------------------------------------------------------- priors

TRADE_AREA_PRIORS: Dict[str, Dict[str, float]] = {
    "오피스 밀집 상권":   {"E": 0.72, "T": 0.82, "M": 0.52},
    "주거 밀집 상권":     {"E": 0.42, "T": 0.38, "M": 0.72},
    "대학가/유흥 상권":   {"E": 0.84, "T": 0.74, "M": 0.66},
    "복합 오피스 상권":   {"E": 0.68, "T": 0.72, "M": 0.60},
    "관광특구 상권":      {"E": 0.80, "T": 0.68, "M": 0.78},
    "트렌드/패션 상권":   {"E": 0.76, "T": 0.70, "M": 0.84},
    "학원가 특화 상권":   {"E": 0.58, "T": 0.66, "M": 0.56},
    "지식산업센터 상권":  {"E": 0.60, "T": 0.76, "M": 0.50},
    # 주변 분포 판정에서 신설된 레이블 (trade_area_service).
    # 카페·트렌드: 카페 밀집 상권 — 체류형이라 템포는 낮고 무드가 높다.
    "카페·트렌드 상권":   {"E": 0.58, "T": 0.44, "M": 0.84},
    # 복합: 어느 성격도 강하지 않을 때. 중립값이어야 하며 결과를 한쪽으로 끌지 않는다.
    "복합 상권":         {"E": 0.55, "T": 0.55, "M": 0.62},
}

BUSINESS_TYPE_PRIORS: Dict[str, Dict[str, float]] = {
    "카페":            {"E": 0.52, "T": 0.42, "M": 0.80},
    "테이크아웃 카페":  {"E": 0.66, "T": 0.82, "M": 0.62},
    "베이커리 카페":    {"E": 0.58, "T": 0.48, "M": 0.78},
    "일반 음식점":      {"E": 0.62, "T": 0.56, "M": 0.70},
    "패스트푸드":       {"E": 0.82, "T": 0.92, "M": 0.42},
    "주점/바":          {"E": 0.88, "T": 0.72, "M": 0.72},
    "디저트숍":         {"E": 0.56, "T": 0.40, "M": 0.82},
    "편의점형 F&B":     {"E": 0.64, "T": 0.86, "M": 0.38},
    # 파일럿 2업종 중 하나. 없으면 DEFAULT_TYPE(중립)으로 떨어져 카페와 구분이 안 됐다.
    "피트니스":         {"E": 0.86, "T": 0.82, "M": 0.62},
}

# 업종군 단위 priors — `BUSINESS_TYPE_PRIORS`에 정확히 일치하는 항목이 없을 때의
# 2차 후보다. 키는 `music_service.INDUSTRY_TOKENS`의 업종군 코드다.
#
# 왜 필요한가: `classify_business_type()`은 비F&B 업종을 **원문 그대로** 돌려준다
# (미용실이 "일반 음식점"으로 뭉개지는 것을 막는 의도적 설계). 그 결과 미용실·
# 서점·편의점 같은 업종은 전부 DEFAULT_TYPE(중립)으로 떨어져 E/T/M이 서로
# 구분되지 않았다 (2026-08-05 실측: 헤어케어 매장 E/T/M 48/51/64 — 중립값).
# 원문 라벨은 표시용으로 그대로 두고, priors만 업종군으로 보정한다.
INDUSTRY_GROUP_PRIORS: Dict[str, Dict[str, float]] = {
    "cafe":        {"E": 0.52, "T": 0.42, "M": 0.80},
    "fitness":     {"E": 0.86, "T": 0.82, "M": 0.62},
    # 미용실은 밝고 적당한 템포, 네일·스파는 훨씬 조용하다. 두 성격의 중간값.
    "beauty":      {"E": 0.48, "T": 0.42, "M": 0.78},
    # 리테일·편집샵: 둘러보는 동안 지루하지 않을 정도의 활기.
    "retail":      {"E": 0.66, "T": 0.62, "M": 0.80},
    "dining":      {"E": 0.62, "T": 0.56, "M": 0.70},
    "bar":         {"E": 0.84, "T": 0.70, "M": 0.72},
    # 호텔·라운지: 체류형이라 조용하고 무드 위주.
    "lodging":     {"E": 0.44, "T": 0.38, "M": 0.72},
    # 서점·갤러리: 정숙이 기본. 전 업종군 중 가장 낮은 에너지.
    "culture":     {"E": 0.32, "T": 0.30, "M": 0.62},
    "kids":        {"E": 0.70, "T": 0.68, "M": 0.88},
    # 편의점: 회전이 빨라 템포는 높지만 무드는 중립(배경음 성격).
    "convenience": {"E": 0.62, "T": 0.80, "M": 0.42},
    "office":      {"E": 0.46, "T": 0.52, "M": 0.52},
}

DAYPART_PRIORS: Dict[str, Dict[str, float]] = {
    "early_morning":  {"E": 0.45, "T": 0.52, "M": 0.58},
    "lunch":          {"E": 0.72, "T": 0.88, "M": 0.50},
    "afternoon":      {"E": 0.50, "T": 0.42, "M": 0.70},
    "dinner":         {"E": 0.70, "T": 0.62, "M": 0.72},
    "late_night":     {"E": 0.82, "T": 0.55, "M": 0.68},
}

DAYPART_WINDOWS: List[Tuple[str, int, int]] = [
    ("early_morning", 6, 10),
    ("lunch", 11, 14),
    ("afternoon", 14, 17),
    ("dinner", 17, 21),
    ("late_night", 21, 26),  # wraps past midnight
]

WEATHER_PRIORS: Dict[str, Dict[str, float]] = {
    "sunny":      {"E": 0.60, "T": 0.56, "M": 0.68},
    "cloudy":     {"E": 0.52, "T": 0.50, "M": 0.56},
    "rainy":      {"E": 0.46, "T": 0.44, "M": 0.66},
    "snowy":      {"E": 0.40, "T": 0.36, "M": 0.70},
    "hot_humid":  {"E": 0.50, "T": 0.46, "M": 0.48},
    "cold_clear": {"E": 0.48, "T": 0.42, "M": 0.64},
}

DEFAULT_TRADE = {"E": 0.55, "T": 0.55, "M": 0.60}
DEFAULT_TYPE = {"E": 0.55, "T": 0.55, "M": 0.65}
DEFAULT_WEATHER = WEATHER_PRIORS["cloudy"]


# -------------------------------------------------------------- business type mapping

_TYPE_RULES: List[Tuple[str, List[str]]] = [
    # 피트니스를 F&B보다 먼저 본다 — '헬스카페' 같은 이름이 카페로 잡히는 것을 막는다.
    ("피트니스", ["헬스클럽", "헬스장", "스포츠시설", "피트니스", "체력단련",
                  "필라테스", "요가", "스피닝", "크로스핏"]),
    ("테이크아웃 카페", ["테이크아웃", "take out", "takeaway", "투고"]),
    ("베이커리 카페",   ["베이커리", "빵집", "제과", "bakery"]),
    ("카페",            ["카페", "커피", "coffee", "cafe"]),
    ("패스트푸드",      ["패스트", "햄버거", "피자", "치킨", "프랜차이즈 분식", "분식"]),
    ("주점/바",         ["주점", "바(", " bar", "호프", "펍", "포차", "와인", "이자카야"]),
    ("디저트숍",        ["디저트", "아이스크림", "케이크", "베이글", "도넛", "쿠키"]),
    ("편의점형 F&B",    ["편의점", "convenience", "즉석"]),
    ("일반 음식점",     ["음식점", "식당", "한식", "일식", "양식", "중식", "분식", "레스토랑"]),
]


def classify_business_type(raw: str) -> str:
    """Map a moneypin 업종 string to a canonical bucket.

    For F&B businesses, return one of the F&B subtypes (`카페`, `주점/바`, ...)
    so that `BUSINESS_TYPE_PRIORS` can apply F&B-tuned priors. For non-F&B
    businesses, return the original moneypin string verbatim — collapsing
    them to `"일반 음식점"` previously caused publishers, real-estate firms,
    salons, etc. to be misrepresented in the TPO `place_label`.
    """
    if not raw:
        return "일반 음식점"
    lowered = raw.lower()
    for label, keywords in _TYPE_RULES:
        for kw in keywords:
            if kw in raw or kw.lower() in lowered:
                return label
    # Non-F&B → keep the canonical moneypin label so the UI honestly
    # shows the real 업종 (e.g. "음악 및 기타 오디오물 출판업").
    return raw.strip() or "일반 음식점"


# ------------------------------------------------------------------ opening hours

_HR_RANGE = re.compile(r"(\d{1,2}):?(\d{2})\s*[-–~]\s*(\d{1,2}):?(\d{2})")

# Google Places는 `languageCode=ko` 로 요청하면 영업시간을 한국어 12시간제로 준다:
#   "월요일: 오전 8:00 ~ 오후 9:00"
# `_HR_RANGE`는 24시간제만 보므로 그대로는 매칭에 실패해 daypart 가중치가 전부 0이 되고
# TPO 시간 라벨도 원문이 그대로 노출됐다 (2026-08-05 실측). 먼저 24시간제로 정규화한다.
_KO_AMPM = re.compile(r"(오전|오후)\s*(\d{1,2})(?::(\d{2}))?")

# 24시간 영업 매장에는 Google이 시각 범위가 아니라 "월요일: 24시간 영업"을 준다
# (영어 로케일은 "Open 24 hours"). `_HR_RANGE`·`_KO_AMPM` 어느 쪽도 매칭되지 않아
# ① daypart 가중치가 전부 0이 되고(시간 축이 추천에서 빠짐)
# ② TPO 시간 라벨에 원문이 그대로 노출됐다
#    (2026-08-06 실측: 어게인짐 건대입구역점 → "월요일: 24시간 영업, 화요일: 24시간 영업").
# 명시적인 0~24시 구간으로 정규화해 두 경로를 한 번에 살린다.
_ALL_DAY = re.compile(r"(?:24\s*시간(?:\s*영업)?|open\s*24\s*hours|24\s*hours)", re.I)
_ALL_DAY_RANGE = "00:00 ~ 24:00"
ALL_DAY_LABEL = "24시간"


def _ko_ampm_to_24h(match: "re.Match[str]") -> str:
    ampm, hour, minute = match.group(1), int(match.group(2)), match.group(3) or "00"
    if ampm == "오후" and hour != 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute}"


def normalize_hour_line(line: str) -> str:
    """영업시간 한 줄을 24시간제 시각 범위로 정규화한다.

        '월요일: 오전 8:00 ~ 오후 9:00' → '월요일: 08:00 ~ 21:00'
        '월요일: 24시간 영업'            → '월요일: 00:00 ~ 24:00'
    """
    if not line:
        return ""
    out = _KO_AMPM.sub(_ko_ampm_to_24h, line)
    # 이미 시각 범위가 있으면 손대지 않는다 — '~ 24시간' 같은 표기를 잘못 덮어쓰지 않기 위함.
    if not _HR_RANGE.search(out):
        out = _ALL_DAY.sub(_ALL_DAY_RANGE, out)
    return out


def parse_business_hours(lines: List[str]) -> List[Tuple[int, int]]:
    """Return list of (start_hour, end_hour) windows (end can be >24 if wraps)."""
    out: List[Tuple[int, int]] = []
    for line in lines or []:
        for m in _HR_RANGE.finditer(normalize_hour_line(line)):
            start = int(m.group(1))
            end = int(m.group(3))
            if end <= start:
                end += 24
            out.append((start, end))
    return out


def compute_daypart_weights(hour_windows: List[Tuple[int, int]]) -> Dict[str, float]:
    """Return normalised activity weight per daypart based on business-hour overlap.

    When `hour_windows` is empty we now return all-zero weights (rather than
    a fabricated lunch-heavy default). Callers must treat all-zero as
    "영업시간 미확인" — `daypart_fusion` substitutes a neutral prior and
    `peak_slots` returns an empty list so the UI doesn't invent a peak.
    """
    weights: Dict[str, float] = {name: 0.0 for name, _, _ in DAYPART_WINDOWS}
    if not hour_windows:
        return weights

    for start, end in hour_windows:
        for name, d_start, d_end in DAYPART_WINDOWS:
            overlap = max(0, min(end, d_end) - max(start, d_start))
            if overlap > 0:
                weights[name] += overlap

    total = sum(weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def daypart_fusion(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total < 1e-9:
        # No business-hours signal — return a neutral prior so the fusion
        # math stays well-defined without injecting a fake lunch peak.
        return {"E": 0.55, "T": 0.55, "M": 0.60}
    E = sum(weights[name] * DAYPART_PRIORS[name]["E"] for name in weights) / total
    T = sum(weights[name] * DAYPART_PRIORS[name]["T"] for name in weights) / total
    M = sum(weights[name] * DAYPART_PRIORS[name]["M"] for name in weights) / total
    return {"E": E, "T": T, "M": M}


def peak_slots(weights: Dict[str, float]) -> List[str]:
    order = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    out = []
    label_map = {
        "early_morning": "이른 아침 (06–10시)",
        "lunch": "점심 피크 (11–14시)",
        "afternoon": "오후 (14–17시)",
        "dinner": "저녁 (17–21시)",
        "late_night": "야간 (21시 이후)",
    }
    for name, w in order[:3]:
        if w <= 0.01:
            continue
        out.append(label_map.get(name, name))
    # Empty when there is no real business-hours signal — the UI omits the
    # "피크 ..." suffix so we don't fabricate a lunch peak out of nothing.
    return out


# --------------------------------------------------------------- occasion derivation

_FAMILY_OCCASION_DEFAULTS: Dict[str, str] = {
    "professional_services": "업무·미팅 방문",
    "real_estate":           "방문 상담",
    "beauty":                "예약 방문",
    "health":                "진료/예약 방문",
    "education":             "수업/상담 방문",
    "lodging":               "체크인",
    "retail":                "쇼핑/방문",
    "automotive":            "정비/상담 방문",
    "manufacturing":         "방문 상담",
    "entertainment":         "여가 방문",
}


def derive_occasion(
    business_type: str,
    reviews: List[PlaceReview],
    review_scores: List[ReviewScore],
) -> str:
    counter: Counter = Counter()
    for s in review_scores:
        for lab in s.occasion_labels:
            counter[lab] += 1

    if counter:
        top = counter.most_common(1)[0][0]
        return top

    # fallback from business-type keywords (F&B subtypes)
    if "카페" in business_type:
        return "점심 커피"
    if "베이커리" in business_type:
        return "간식/테이크아웃"
    if "패스트" in business_type:
        return "테이크아웃"
    if "주점" in business_type or "바" in business_type:
        return "야간 모임"
    if "디저트" in business_type:
        return "데이트"

    # Non-F&B → use the validated business-type family for a sensible label
    # instead of pretending every shop is a lunch café.
    family = map_business_type_family(business_type)
    if family in _FAMILY_OCCASION_DEFAULTS:
        return _FAMILY_OCCASION_DEFAULTS[family]
    if family == "food_and_beverage":
        return "점심 커피"
    return "방문 상담"


# --------------------------------------------------------------------- TPO profile

def build_tpo_profile(
    business_type: str,
    trade_area: TradeAreaMatch,
    places: GooglePlaces,
    reviews: List[PlaceReview],
    review_scores: List[ReviewScore],
) -> TpoProfile:
    hour_windows = parse_business_hours(places.business_hours)
    dp = compute_daypart_weights(hour_windows)
    peaks = peak_slots(dp)

    time_label = _format_time_label(places.business_hours) or "영업시간 정보 없음"
    place_label = f"{business_type} · {trade_area.label}"
    occasion_label = derive_occasion(business_type, reviews, review_scores)

    return TpoProfile(
        time_label=time_label,
        place_label=place_label,
        occasion_label=occasion_label,
        peak_slots=peaks,
    )


# 요일 판별은 '요일' 토큰째로 잡아야 한다. 예전에는 `"일" in line` 으로 주말을
# 골라냈는데 **"월요일"에도 "일"이 들어 있어** 모든 줄이 주말로 분류됐다.
# 그 결과 평일/주말 분기(`wd_range != we_range`)가 한 번도 성립하지 않았고,
# 평일 24시간 · 주말 단축 영업 같은 매장이 "24시간 영업"으로만 표시됐다.
_DAY_TOKEN = re.compile(r"([월화수목금토일])\s*요일")
_WEEKDAYS = frozenset("월화수목금")
_WEEKEND = frozenset("토일")


def _day_of(line: str) -> str:
    m = _DAY_TOKEN.search(line or "")
    return m.group(1) if m else ""


def _format_time_label(lines: List[str]) -> str:
    if not lines:
        return ""
    lines = [normalize_hour_line(l) for l in lines]
    weekday, weekend = [], []
    for line in lines:
        day = _day_of(line)
        if day in _WEEKDAYS:
            weekday.append(line)
        elif day in _WEEKEND:
            weekend.append(line)
    wd_range = _first_range(weekday) or _first_range(lines)
    we_range = _first_range(weekend)
    if wd_range and we_range and wd_range != we_range:
        return f"평일 {wd_range} · 주말 {we_range}"
    # '영업시간 24시간'은 어색하므로 24시간 영업은 문장을 따로 만든다.
    if wd_range == ALL_DAY_LABEL:
        return "24시간 영업"
    return f"영업시간 {wd_range}" if wd_range else ", ".join(lines[:2])


def _first_range(lines: List[str]) -> str:
    for line in lines:
        m = _HR_RANGE.search(line)
        if m:
            start, end = int(m.group(1)), int(m.group(3))
            if (start, m.group(2), end, m.group(4)) == (0, "00", 24, "00"):
                return ALL_DAY_LABEL
            s = f"{start}:{m.group(2)}" if m.group(2) != "00" else f"{start}시"
            e = f"{end}:{m.group(4)}" if m.group(4) != "00" else f"{end}시"
            return f"{s}–{e}"
    return ""


# ------------------------------------------------------------------- fusion core

def _prior(dct: Dict[str, Dict[str, float]], key: str, default: Dict[str, float]) -> Dict[str, float]:
    return dct.get(key, default)


def business_type_prior(*business_types: Optional[str]) -> Dict[str, float]:
    """업종 priors를 3단계로 찾는다: 정확 일치 → 업종군 → 중립(DEFAULT_TYPE).

    첫 인자가 canonical 업종(표시용 라벨)이고, 뒤에 원문/Kakao 카테고리를
    더 넘기면 업종군 추정에 함께 쓴다.
    """
    labels = [t for t in business_types if t]
    for label in labels:
        exact = BUSINESS_TYPE_PRIORS.get(label)
        if exact:
            return exact
    group = detect_industry_group(*labels)
    if group:
        prior = INDUSTRY_GROUP_PRIORS.get(group)
        if prior:
            return prior
    return DEFAULT_TYPE


def fuse(
    text_scores: Dict[str, float],
    trade_area: TradeAreaMatch,
    business_type: str,
    daypart_weights: Dict[str, float],
    weather: Weather,
    raw_business_type: Optional[str] = None,
) -> Tuple[Ambience, Dict[str, Any]]:
    E_text = text_scores.get("E_text", 0.5)
    T_text = text_scores.get("T_text", 0.5)
    M_text = text_scores.get("M_text", 0.5)
    c_text = text_scores.get("c_text", 0.0)

    area_prior = _prior(TRADE_AREA_PRIORS, trade_area.label, DEFAULT_TRADE)
    type_prior = business_type_prior(business_type, raw_business_type)
    time_prior = daypart_fusion(daypart_weights)
    weather_prior = _prior(WEATHER_PRIORS, weather.condition or "cloudy", DEFAULT_WEATHER)

    E_raw = (0.50 * E_text + 0.20 * area_prior["E"] + 0.15 * type_prior["E"]
             + 0.10 * time_prior["E"] + 0.05 * weather_prior["E"])
    T_raw = (0.50 * T_text + 0.20 * area_prior["T"] + 0.15 * type_prior["T"]
             + 0.10 * time_prior["T"] + 0.05 * weather_prior["T"])
    M_raw = (0.50 * M_text + 0.15 * area_prior["M"] + 0.20 * type_prior["M"]
             + 0.05 * time_prior["M"] + 0.10 * weather_prior["M"])

    E_prior_only = 0.55 * area_prior["E"] + 0.45 * type_prior["E"]
    T_prior_only = 0.55 * area_prior["T"] + 0.45 * type_prior["T"]
    M_prior_only = 0.45 * area_prior["M"] + 0.55 * type_prior["M"]

    E = c_text * E_raw + (1 - c_text) * E_prior_only
    T = c_text * T_raw + (1 - c_text) * T_prior_only
    M = c_text * M_raw + (1 - c_text) * M_prior_only

    clamp = lambda v: max(0.0, min(1.0, v))
    E, T, M = clamp(E), clamp(T), clamp(M)

    explanations = build_explanations(
        text_scores=text_scores,
        area_prior=(trade_area.label, area_prior),
        type_prior=(business_type, type_prior),
        time_prior=time_prior,
        daypart_weights=daypart_weights,
        weather=weather,
        final=(E, T, M),
    )

    component_scores = {
        "text": {"E": E_text, "T": T_text, "M": M_text, "c_text": c_text},
        "area": {"E": area_prior["E"], "T": area_prior["T"], "M": area_prior["M"]},
        "type": {"E": type_prior["E"], "T": type_prior["T"], "M": type_prior["M"]},
        "time": {"E": time_prior["E"], "T": time_prior["T"], "M": time_prior["M"]},
        "weather": {"E": weather_prior["E"], "T": weather_prior["T"], "M": weather_prior["M"]},
        "prior_only": {"E": E_prior_only, "T": T_prior_only, "M": M_prior_only},
    }

    amb = Ambience(
        energy=round(100 * E),
        tempo=round(100 * T),
        mood=round(100 * M),
        component_scores=component_scores,
        confidence=round(float(c_text), 3),
        explanations=explanations,
    )
    debug = {
        "E_raw": E_raw, "T_raw": T_raw, "M_raw": M_raw,
        "E_prior": E_prior_only, "T_prior": T_prior_only, "M_prior": M_prior_only,
        "daypart_weights": daypart_weights,
    }
    return amb, debug


def build_explanations(
    *,
    text_scores: Dict[str, float],
    area_prior: Tuple[str, Dict[str, float]],
    type_prior: Tuple[str, Dict[str, float]],
    time_prior: Dict[str, float],
    daypart_weights: Dict[str, float],
    weather: Weather,
    final: Tuple[float, float, float],
) -> List[str]:
    out: List[str] = []
    area_label, area = area_prior
    type_label, type_v = type_prior

    E, T, M = final
    peaks = peak_slots(daypart_weights)

    if text_scores.get("n", 0) >= 3:
        if text_scores["T_text"] >= 0.6:
            out.append("리뷰에 점심·업무 관련 방문 언급이 많아 템포가 높게 산정되었습니다.")
        if text_scores["E_text"] >= 0.65:
            out.append("리뷰에서 붐비는 시간대 언급이 많아 에너지가 활기 있게 평가되었습니다.")
        if text_scores["M_text"] >= 0.65:
            out.append("리뷰의 좌석/분위기 언급을 반영해 무드가 안정적으로 평가되었습니다.")

    out.append(f"{area_label} 특성이 반영되어 에너지·템포가 {_descriptor(area)} 수준입니다.")
    out.append(f"업종 '{type_label}' 프로파일이 {_descriptor(type_v)}의 무드를 제공합니다.")
    if peaks:
        out.append(f"영업시간 기준 활동 피크: {', '.join(peaks[:2])}.")
    out.append(f"현재 날씨({weather.condition or '정보없음'}) 보정이 적정하게 적용되었습니다.")

    # dedupe while preserving order
    seen = set()
    deduped = []
    for line in out:
        if line in seen:
            continue
        seen.add(line)
        deduped.append(line)
    return deduped[:6]


def _descriptor(v: Dict[str, float]) -> str:
    e = v.get("E", 0.5)
    if e >= 0.75:
        return "높은"
    if e >= 0.6:
        return "중상"
    if e >= 0.45:
        return "중간"
    return "낮은"
