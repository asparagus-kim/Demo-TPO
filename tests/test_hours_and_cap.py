"""영업시간 파싱 · Places 일별 상한 · 주소 부재 검증 — 회귀 테스트.

전부 2026-08-05 실데이터 연결 중에 발견한 버그를 고정한다.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.schemas import BusinessInfo, GooglePlaces
from app.services import ambience_service as A
from app.services import entity_validation_service as V
from app.services import places_service as P


# ---------------------------------------------------------------- 영업시간 (한국어 12시간제)
#
# Google Places를 languageCode=ko 로 부르면 "오전 8:00 ~ 오후 9:00" 로 온다.
# 24시간제만 보던 정규식이 매칭에 실패해 daypart 가중치가 전부 0이 되고
# TPO 시간 라벨에 원문이 그대로 노출됐다.

@pytest.mark.parametrize("line,expected", [
    ("월요일: 오전 8:00 ~ 오후 9:00", [(8, 21)]),
    ("토요일: 오전 10:00 ~ 오후 10:30", [(10, 22)]),
    ("매일 오전 7:00 ~ 오후 11:00", [(7, 23)]),
    # 정오·자정 경계
    ("오전 12:00 ~ 오후 12:00", [(0, 12)]),
    # 자정을 넘기면 end 에 24를 더한다
    ("월요일: 오후 12:00 ~ 오전 2:00", [(12, 26)]),
    # 24시간제는 그대로 동작해야 한다 (기존 동작 유지)
    ("월요일: 07:00 – 22:00", [(7, 22)]),
    ("일요일: 휴무일", []),
    ("", []),
])
def test_parse_business_hours_korean_and_24h(line, expected):
    assert A.parse_business_hours([line]) == expected


def test_normalize_hour_line_converts_only_ampm():
    assert A.normalize_hour_line("월요일: 오전 8:00 ~ 오후 9:00") == "월요일: 08:00 ~ 21:00"
    # AM/PM 표기가 없으면 건드리지 않는다
    assert A.normalize_hour_line("월요일: 07:00 – 22:00") == "월요일: 07:00 – 22:00"


def test_korean_hours_produce_daypart_weights():
    """정규화가 없으면 가중치가 전부 0이 되어 시간대 분석이 죽는다."""
    hours = [f"{d}: 오전 8:00 ~ 오후 9:00" for d in ("월요일", "화요일", "수요일")]
    weights = A.compute_daypart_weights(A.parse_business_hours(hours))
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["dinner"] > 0 and weights["lunch"] > 0
    assert A.peak_slots(weights), "피크 시간대가 산출되어야 한다"


def test_time_label_is_compact_not_raw_lines():
    hours = ["월요일: 오전 8:00 ~ 오후 9:00", "화요일: 오전 8:00 ~ 오후 9:00"]
    label = A._format_time_label(hours)
    assert "오전" not in label and "월요일" not in label
    assert "8" in label and "21" in label


# ---------------------------------------------------------------- 영업시간 (24시간 영업)
#
# 24시간 매장에는 Google이 시각 범위가 아니라 "월요일: 24시간 영업"을 준다.
# AM/PM 정규화만으로는 잡히지 않아 daypart 가중치가 전부 0이 되고 TPO 시간 라벨에
# "월요일: 24시간 영업, 화요일: 24시간 영업"이 그대로 노출됐다
# (2026-08-06 실측: 어게인짐 건대입구역점).

@pytest.mark.parametrize("line", [
    "월요일: 24시간 영업",
    "월요일: 24시간",
    "Monday: Open 24 hours",
    "매일 24 시간 영업",
])
def test_all_day_lines_become_full_window(line):
    assert A.parse_business_hours([line]) == [(0, 24)]


def test_all_day_normalization_does_not_touch_real_ranges():
    """'~ 24시간' 같은 표기가 섞여도 이미 있는 시각 범위를 덮어쓰지 않는다."""
    assert A.normalize_hour_line("월요일: 07:00 – 22:00") == "월요일: 07:00 – 22:00"
    assert A.parse_business_hours(["월요일: 오전 6:00 ~ 오후 11:00"]) == [(6, 23)]


def test_all_day_produces_daypart_weights():
    """정규화가 없으면 24시간 매장의 시간 축이 추천에서 통째로 빠진다."""
    hours = [f"{d}요일: 24시간 영업" for d in "월화수목금토일"]
    weights = A.compute_daypart_weights(A.parse_business_hours(hours))
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(w > 0 for w in weights.values()), "모든 시간대에 가중치가 실려야 한다"
    assert A.peak_slots(weights)


def test_all_day_time_label_reads_naturally():
    hours = [f"{d}요일: 24시간 영업" for d in "월화수목금토일"]
    label = A._format_time_label(hours)
    assert label == "24시간 영업"
    # 원문이 새어 나오면 안 된다 (이게 실제로 화면에 노출된 버그다)
    assert "월요일" not in label and "화요일" not in label


def test_all_day_weekday_only_still_splits_weekend():
    """평일 24시간 · 주말 단축 영업처럼 섞인 경우도 구분해서 보여준다."""
    hours = ([f"{d}요일: 24시간 영업" for d in "월화수목금"]
             + [f"{d}요일: 오전 9:00 ~ 오후 6:00" for d in "토일"])
    label = A._format_time_label(hours)
    assert "평일" in label and "주말" in label
    assert A.ALL_DAY_LABEL in label and "9시–18시" in label


# ---------------------------------------------------------------- Places 일별 상한

@pytest.fixture(autouse=True)
def _reset_places():
    P.reset_call_log()
    yield
    P.reset_call_log()


def test_calls_today_counts_and_caps(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mock_mode", False)
    monkeypatch.setattr(s, "google_maps_api_key", "test-key")
    monkeypatch.setattr(s, "kakao_rest_api_key", "kakao")
    monkeypatch.setattr(s, "openai_api_key", "llm")
    monkeypatch.setattr(s, "places_daily_cap", 3)

    assert P.availability() == (True, "ok")
    P._record_calls(2)
    assert P.calls_today() == 2
    assert P.availability()[0] is True
    P._record_calls(1)
    assert P.calls_today() == 3
    ok, reason = P.availability()
    assert ok is False and reason == "daily_cap"
    # 상한 초과는 실패가 아니라 degrade — 사용자에게 보여줄 문구가 있어야 한다
    assert P.SKIP_REASON_TEXT["daily_cap"]


def test_availability_reports_missing_key(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mock_mode", False)
    monkeypatch.setattr(s, "kakao_rest_api_key", "kakao")
    monkeypatch.setattr(s, "openai_api_key", "llm")
    monkeypatch.setattr(s, "google_maps_api_key", "")
    assert P.availability() == (False, "no_key")


def test_cap_zero_means_unlimited(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mock_mode", False)
    monkeypatch.setattr(s, "google_maps_api_key", "test-key")
    monkeypatch.setattr(s, "kakao_rest_api_key", "kakao")
    monkeypatch.setattr(s, "openai_api_key", "llm")
    monkeypatch.setattr(s, "places_daily_cap", 0)
    P._record_calls(999)
    assert P.availability()[0] is True


# ---------------------------------------------------------------- 주소 부재 검증
#
# bizno 무료 플랜은 주소를 주지 않는다. 주소를 0점으로 계산하면 임계값(주소 60) 때문에
# 정상 매장도 전부 불일치로 떨어진다.

def _google(name, addr, types=("cafe",)):
    return GooglePlaces(place_name=name, formatted_address=addr, place_types=list(types))


def test_missing_address_does_not_fail_matching_names():
    info = BusinessInfo(company_name="별빛카페 달빛차", business_type="카페", address="")
    res = V.validate_google_place_identity(info, _google("별빛카페 달빛차", "서울 마포구 성미산로 128"))
    assert res["is_consistent"] is True
    assert res["address_similarity"] == 0.0            # 신호 없음
    assert res["score"] > 0.55
    assert any("주소 정보가 없어" in r for r in res["reasons"])


def test_missing_address_still_rejects_different_names():
    info = BusinessInfo(company_name="별빛카페 달빛차", business_type="카페", address="")
    res = V.validate_google_place_identity(info, _google("전혀다른가게", "서울 강남구 테헤란로 1"))
    assert res["is_consistent"] is False


def test_present_addresses_still_use_address_signal():
    """주소가 양쪽에 있으면 기존 동작(시/도 불일치 거부)을 유지한다."""
    info = BusinessInfo(company_name="카페베네", business_type="카페",
                        address="경기도 파주시 월롱면 홀작로 129")
    res = V.validate_google_place_identity(info, _google("카페베네", "경기 양주시 백석읍 권율로 8"))
    assert res["address_similarity"] > 0.0
