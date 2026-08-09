"""Pure-function unit tests — no network, no Playwright.

Covers:
- address normalisation
- business-type mapping
- trade-area matching (exact / prefix / dong-level / sigungu fallback)
- ambience fusion math
"""
from __future__ import annotations

import pytest

from app.schemas import TradeAreaMatch, Weather
from app.services import ambience_service, llm_service
from app.services.trade_area_service import get_trade_area_service
from app.utils.address import parse_address, address_prefix_key, normalize_address


# -------------------------------------------------------------- address utils

def test_normalize_address_full_form():
    parsed = parse_address("서울시 광진구 자양동 123-4 5층")
    assert parsed.sido == "서울특별시"
    assert parsed.sigungu == "광진구"
    assert parsed.dong == "자양동"
    assert parsed.canonical == "서울특별시 광진구 자양동"


def test_normalize_handles_compound_sigungu():
    parsed = parse_address("경기도 성남시 분당구 정자동")
    assert parsed.sido == "경기도"
    assert parsed.sigungu == "성남시 분당구"
    assert parsed.dong == "정자동"


def test_prefix_key_drops_details():
    assert address_prefix_key("서울특별시 광진구 자양동 123") == "서울특별시 광진구 자양동"
    assert address_prefix_key("부산시 수영구") == "부산광역시 수영구"


def test_normalize_address_removes_prefix():
    assert normalize_address("대한민국 서울특별시 강남구 역삼동").startswith("서울특별시")


# -------------------------------------------------------------- business-type mapping

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("커피전문점", "카페"),
        ("테이크아웃 커피숍", "테이크아웃 카페"),
        ("베이커리 & 카페", "베이커리 카페"),
        ("호프 주점", "주점/바"),
        # Non-F&B business types must be preserved verbatim — collapsing them to
        # "일반 음식점" would mislabel publishers, salons, real-estate firms, etc.
        ("음악 및 기타 오디오물 출판업", "음악 및 기타 오디오물 출판업"),
        ("부동산 중개업", "부동산 중개업"),
        ("미용실", "미용실"),
        ("", "일반 음식점"),
    ],
)
def test_classify_business_type(raw, expected):
    assert ambience_service.classify_business_type(raw) == expected


def test_derive_occasion_non_fb_uses_family_label():
    # No reviews / no review_scores → fall back on family-based mapping.
    occ = ambience_service.derive_occasion("음악 및 기타 오디오물 출판업", [], [])
    assert occ == "업무·미팅 방문"
    assert ambience_service.derive_occasion("부동산 중개업", [], []) == "방문 상담"
    assert ambience_service.derive_occasion("미용실", [], []) == "예약 방문"


# -------------------------------------------------------------- trade-area service

def test_trade_area_match_exact_or_graceful():
    svc = get_trade_area_service()
    # Try a likely-real address — either exact or prefix match, but always a known label
    result = svc.match("서울특별시 광진구 자양1동")
    assert result.label in ambience_service.TRADE_AREA_PRIORS
    assert 0.0 <= result.confidence <= 1.0

    # Fallback path: obviously missing address returns default label
    fallback = svc.match("")
    assert fallback.match_method == "fallback"


def test_trade_area_graceful_degradation():
    svc = get_trade_area_service()
    # 시군구-only addresses should degrade to SOMETHING non-default (sigungu / sido / fuzzy).
    result = svc.match("서울특별시 강남구")
    assert result.match_method in {"sigungu-fallback", "sido-fallback", "exact", "prefix", "fuzzy", "dong-level"}
    assert result.label in ambience_service.TRADE_AREA_PRIORS
    assert result.confidence > 0.15

    # Bare dong name still matches via the dong-level index.
    gangnam_dong = svc.match("서울특별시 강남구 역삼동")
    assert gangnam_dong.match_method in {"exact", "prefix", "fuzzy", "dong-level"}
    assert gangnam_dong.label in ambience_service.TRADE_AREA_PRIORS


# ------------------------------------------------------------- business hours parsing

def test_parse_business_hours_and_dayparts():
    lines = [
        "월요일: 07:00 – 22:00",
        "토요일: 10:00 – 23:00",
    ]
    windows = ambience_service.parse_business_hours(lines)
    assert (7, 22) in windows
    weights = ambience_service.compute_daypart_weights(windows)
    assert pytest.approx(sum(weights.values()), abs=1e-6) == 1.0
    assert weights["lunch"] > 0


def test_compute_daypart_weights_empty_returns_zero():
    # No business-hours signal → all-zero (NOT a fabricated lunch peak).
    weights = ambience_service.compute_daypart_weights([])
    assert sum(weights.values()) == 0.0
    # peak_slots must therefore return [] so the UI doesn't invent a peak.
    assert ambience_service.peak_slots(weights) == []


def test_daypart_fusion_handles_zero_weights():
    weights = {name: 0.0 for name, _, _ in ambience_service.DAYPART_WINDOWS}
    out = ambience_service.daypart_fusion(weights)
    # Neutral fallback prior — not driven by any specific daypart.
    assert 0.4 <= out["E"] <= 0.7
    assert 0.4 <= out["T"] <= 0.7
    assert 0.4 <= out["M"] <= 0.7


# -------------------------------------------------------------------- fusion

def _fake_text_scores(c_text: float = 0.6):
    return {"E_text": 0.6, "T_text": 0.7, "M_text": 0.55, "c_text": c_text, "n": 10, "q": 0.7, "d": 0.6}


def test_fuse_within_bounds():
    match = TradeAreaMatch(label="오피스 밀집 상권", match_method="exact", confidence=0.99)
    weather = Weather(condition="cloudy", summary="흐림")
    weights = {"lunch": 1.0, "early_morning": 0.0, "afternoon": 0.0, "dinner": 0.0, "late_night": 0.0}
    ambience, debug = ambience_service.fuse(
        text_scores=_fake_text_scores(0.7),
        trade_area=match,
        business_type="카페",
        daypart_weights=weights,
        weather=weather,
    )
    assert 0 <= ambience.energy <= 100
    assert 0 <= ambience.tempo <= 100
    assert 0 <= ambience.mood <= 100
    assert "text" in ambience.component_scores


def test_fuse_low_confidence_uses_priors():
    match = TradeAreaMatch(label="주거 밀집 상권", match_method="fallback", confidence=0.1)
    weather = Weather(condition="rainy", summary="비")
    weights = {"afternoon": 1.0, "lunch": 0.0, "early_morning": 0.0, "dinner": 0.0, "late_night": 0.0}
    low, _ = ambience_service.fuse(
        text_scores=_fake_text_scores(0.0),
        trade_area=match,
        business_type="카페",
        daypart_weights=weights,
        weather=weather,
    )
    # With c_text = 0, the final score collapses to the prior-only vector.
    priors = low.component_scores["prior_only"]
    assert abs(low.energy - round(100 * priors["E"])) <= 1
    assert abs(low.tempo - round(100 * priors["T"])) <= 1
    assert abs(low.mood - round(100 * priors["M"])) <= 1


# ------------------------------------------------------------ 업종 priors 3단계 폴백

def test_business_type_prior_exact_match_wins():
    assert ambience_service.business_type_prior("카페") is \
        ambience_service.BUSINESS_TYPE_PRIORS["카페"]


@pytest.mark.parametrize("business_type,group", [
    ("미용실", "beauty"),
    ("서점", "culture"),
    ("네일샵", "beauty"),
    ("호텔", "lodging"),
    ("여성의류 판매", "retail"),
])
def test_business_type_prior_falls_back_to_group(business_type, group):
    """비F&B 업종은 canonical이 원문 그대로라 exact 항목이 없다 → 업종군 priors."""
    prior = ambience_service.business_type_prior(business_type)
    assert prior is ambience_service.INDUSTRY_GROUP_PRIORS[group]
    assert prior is not ambience_service.DEFAULT_TYPE


def test_business_type_prior_uses_raw_category_when_canonical_is_vague():
    """Kakao가 '서비스,산업' 같은 대분류만 줄 때 원문 카테고리로 보정한다."""
    prior = ambience_service.business_type_prior(
        "서비스,산업", "서비스,산업 생활,서비스 > 미용 > 미용실",
    )
    assert prior is ambience_service.INDUSTRY_GROUP_PRIORS["beauty"]


def test_business_type_prior_unknown_industry_stays_neutral():
    assert ambience_service.business_type_prior("부동산 중개업") is \
        ambience_service.DEFAULT_TYPE
    assert ambience_service.business_type_prior("") is ambience_service.DEFAULT_TYPE


def test_fuse_separates_bookstore_from_bar():
    """확대 전에는 두 업종 모두 DEFAULT_TYPE으로 떨어져 E/T/M이 같았다."""
    match = TradeAreaMatch(label="복합 상권", match_method="surroundings", confidence=0.7)
    weather = Weather(condition="cloudy", summary="흐림")
    weights = {"afternoon": 0.6, "dinner": 0.4, "lunch": 0.0,
               "early_morning": 0.0, "late_night": 0.0}
    kwargs = dict(text_scores=_fake_text_scores(0.0), trade_area=match,
                  daypart_weights=weights, weather=weather)
    books, _ = ambience_service.fuse(business_type="서점", **kwargs)
    bar, _ = ambience_service.fuse(business_type="주점/바", **kwargs)
    assert bar.energy > books.energy + 10


# ----------------------------------------------------------- LLM aggregate (no network)

def test_llm_aggregate_weights_empty():
    out = llm_service.aggregate_text_scores([])
    assert out["n"] == 0
    assert out["c_text"] == 0.0
