"""'분석 근거' 10줄 템플릿용 신규 순수 함수 테스트.

- density_word: 밀도 구간 → 사람이 읽는 말
- criteria_trace: classify_by_surroundings 와 항상 일치하는 판정 기준 트레이스
- surroundings_payload: SurroundingProfile → API dict 매핑
"""
from __future__ import annotations

from app.schemas import TradeAreaMatch
from app.services.trade_area_service import (
    LABEL_CAFE_TREND,
    build_profile,
    classify_by_surroundings,
    criteria_trace,
    density_word,
    surroundings_payload,
)


def _counts(**kw) -> dict:
    base = {"CE7": 0, "FD6": 0, "AC5": 0, "BK9": 0,
            "AD5": 0, "AT4": 0, "HP8": 0, "CS2": 0}
    base.update(kw)
    return base


# ---------------------------------------------------------------- density_word

def test_density_word_bands():
    assert density_word(100) == "낮음"
    assert density_word(250) == "보통"
    assert density_word(699) == "보통"
    assert density_word(700) == "높음"


# --------------------------------------------------------------- criteria_trace

def test_trace_office_decided_by_bank_share():
    p = build_profile(_counts(CE7=150, FD6=500, AC5=100, BK9=60,
                              AD5=10, AT4=10, HP8=100, CS2=70), univ_count=10)
    label, _, _ = classify_by_surroundings(p)
    assert label == "오피스 밀집 상권"

    trace = criteria_trace(p)
    decided = [e for e in trace if e["decided"]]
    assert len(decided) == 1
    assert decided[0]["indicator"] == "은행 비중"
    assert decided[0]["met"] is True
    assert decided[0]["label"] == label


def test_trace_cafe_secondary_threshold_shown_when_decided_by_relaxed_rule():
    # cafe 17% / 은행 대비 5.7배 → 1차 기준(20%·8배) 미달, 2차 기준(16%·5배)로 판정.
    p = build_profile(_counts(CE7=170, FD6=500, AC5=50, BK9=30,
                              AD5=5, AT4=5, HP8=140, CS2=100), univ_count=10)
    label, _, _ = classify_by_surroundings(p)
    assert label == LABEL_CAFE_TREND

    trace = criteria_trace(p)
    cafe = next(e for e in trace if e["label"] == LABEL_CAFE_TREND)
    assert cafe["met"] is True
    assert cafe["decided"] is True
    assert "16%" in cafe["threshold"]  # 화면 문구가 실제 판정 기준과 일치해야 한다


def test_trace_university_decides():
    p = build_profile(_counts(CE7=100, FD6=300, AC5=50, BK9=20,
                              AD5=10, AT4=10, HP8=50, CS2=60), univ_count=120)
    trace = criteria_trace(p)
    univ = next(e for e in trace if e["label"] == "대학가/유흥 상권")
    assert univ["met"] is True and univ["decided"] is True


def test_trace_low_density_decides_residential():
    p = build_profile(_counts(CE7=10, FD6=30, AC5=5, BK9=2,
                              AD5=1, AT4=1, HP8=10, CS2=10), univ_count=0)
    label, _, _ = classify_by_surroundings(p)
    assert label == "주거 밀집 상권"
    trace = criteria_trace(p)
    density = next(e for e in trace if e["indicator"] == "상업 밀도")
    assert density["met"] is True and density["decided"] is True


def test_trace_mixed_label_has_no_decided_entry():
    # 고밀도인데 어떤 신호도 강하지 않음 → 복합 상권, decided 없음.
    p = build_profile(_counts(CE7=100, FD6=400, AC5=80, BK9=30,
                              AD5=10, AT4=10, HP8=90, CS2=80), univ_count=10)
    label, _, _ = classify_by_surroundings(p)
    assert label == "복합 상권"
    assert not [e for e in criteria_trace(p) if e["decided"]]


def test_trace_always_six_entries_with_required_fields():
    p = build_profile(_counts(CE7=50, FD6=200, AC5=30, BK9=10,
                              AD5=5, AT4=5, HP8=30, CS2=40), univ_count=0)
    trace = criteria_trace(p)
    assert len(trace) == 6
    for e in trace:
        assert e["indicator"] and e["value"] and e["threshold"] and e["label"]
        assert isinstance(e["met"], bool) and isinstance(e["decided"], bool)


# ---------------------------------------------------------- surroundings_payload

def test_payload_fields_and_own_pct():
    counts = _counts(CE7=100, FD6=400, AC5=80, BK9=30,
                     AD5=10, AT4=10, HP8=90, CS2=80)
    p = build_profile(counts, univ_count=10)
    payload = surroundings_payload(p, own_code="FD6", own_count=40)
    assert payload["total"] == 800
    assert payload["density"] == "높음"
    assert payload["counts"]["FD6"] == 400
    assert payload["own_code"] == "FD6"
    assert payload["own_count"] == 40
    assert payload["own_pct"] == 5.0
    assert payload["food_pct"] == 50.0
    # 스키마에 그대로 들어가야 한다 (pydantic 강제 변환 확인)
    ta = TradeAreaMatch(label="복합 상권", surroundings=payload,
                        criteria=criteria_trace(p))
    assert ta.surroundings is not None and ta.surroundings.total == 800
    assert len(ta.criteria) == 6


def test_payload_no_own_count():
    p = build_profile(_counts(FD6=100), univ_count=0)
    payload = surroundings_payload(p)
    assert payload["own_count"] is None and payload["own_pct"] is None
