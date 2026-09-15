"""분석 수집(sheets_logger) — 행 평탄화·정책·안전성 테스트. 네트워크 없음."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.schemas import (
    AnalyseRequest,
    AnalyseResponse,
    BusinessInfo,
    NeedsInput,
    PlaceCandidate,
)
from app.services import sheets_logger

SAMPLE = Path(__file__).parent / "sample_response.json"


@pytest.fixture
def settings_with_webhook():
    """웹훅이 설정된 상태를 흉내낸다. 캐시된 Settings 를 쓰므로 원복까지 책임진다."""
    settings = get_settings()
    before = (
        settings.sheets_webhook_url,
        settings.sheets_logging_enabled,
        settings.sheets_log_cache_hits,
        settings.sheets_log_needs_input,
    )
    settings.sheets_webhook_url = "https://script.google.com/macros/s/TEST/exec"
    settings.sheets_logging_enabled = True
    settings.sheets_log_cache_hits = True
    settings.sheets_log_needs_input = False
    yield settings
    (
        settings.sheets_webhook_url,
        settings.sheets_logging_enabled,
        settings.sheets_log_cache_hits,
        settings.sheets_log_needs_input,
    ) = before


def _sample_response() -> AnalyseResponse:
    return AnalyseResponse(**json.loads(SAMPLE.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------
# 행 평탄화
# --------------------------------------------------------------------------
def test_row_has_exactly_the_declared_columns():
    """행의 키 집합이 COLUMNS 와 정확히 일치해야 시트 헤더와 어긋나지 않는다."""
    row = sheets_logger.build_row(_sample_response())
    assert set(row) == set(sheets_logger.COLUMNS)
    assert len(sheets_logger.COLUMNS) == len(set(sheets_logger.COLUMNS)), "중복 열 이름"


def test_every_cell_is_a_scalar():
    """시트 셀에 dict/list 를 넣을 수 없다 — 전부 평평해야 한다."""
    row = sheets_logger.build_row(_sample_response())
    for key, value in row.items():
        assert isinstance(value, (str, int, float, bool)), f"{key} is {type(value)}"


def test_core_fields_come_from_the_response():
    response = _sample_response()
    row = sheets_logger.build_row(response)

    assert row["biz_no"] == response.business_number
    assert row["store_name"] == response.business_info.company_name
    assert row["district_type"] == response.trade_area.label
    assert row["energy"] == response.ambience.energy
    assert row["tempo"] == response.ambience.tempo
    assert row["mood"] == response.ambience.mood
    assert row["playlist_track_count"] == len(response.music.tracks)
    assert row["outcome"] == "success"


def test_request_inputs_are_recorded():
    """기획이 검증하려는 것은 '입력값 → 결과' 쌍이다. 입력이 빠지면 안 된다."""
    row = sheets_logger.build_row(
        _sample_response(),
        request=AnalyseRequest(
            business_number="117-12-23963",
            company_name="사용자입력상호",
            address_hint="서울 마포구",
            place_id="12345",
        ),
        client="web",
        duration_ms=4210,
        cache_hit=True,
    )
    assert row["input_company_name"] == "사용자입력상호"
    assert row["input_address_hint"] == "서울 마포구"
    assert row["input_place_id"] == "12345"
    assert row["client"] == "web"
    assert row["duration_ms"] == 4210
    assert row["cache_hit"] is True


def test_lists_are_folded_into_one_cell():
    response = _sample_response()
    response.google_places.business_hours = ["월: 09:00~18:00", "화: 09:00~18:00"]
    row = sheets_logger.build_row(response)
    assert row["hours"] == "월: 09:00~18:00 · 화: 09:00~18:00"


def test_empty_response_does_not_raise():
    """`needs_input` 응답은 하위 객체가 전부 기본값이다 — 빈 셀이 될 뿐이어야 한다."""
    response = AnalyseResponse(
        success=False,
        business_number="123-45-67890",
        business_info=BusinessInfo(company_name="테스트"),
        error="매장을 선택해 주세요.",
        needs_input=NeedsInput(reason="place_choice", place_candidates=[PlaceCandidate()]),
    )
    row = sheets_logger.build_row(response, outcome="needs_input")

    assert set(row) == set(sheets_logger.COLUMNS)
    assert row["outcome"] == "needs_input"
    assert row["error"] == "매장을 선택해 주세요."
    assert row["rating"] == ""          # None → 빈 셀 (0 이 아니다)
    assert row["review_count"] == ""


def test_timestamp_is_kst():
    row = sheets_logger.build_row(_sample_response())
    assert row["timestamp"].endswith("+09:00")


# --------------------------------------------------------------------------
# 기록 정책
# --------------------------------------------------------------------------
def test_disabled_without_webhook_url():
    settings = get_settings()
    before = settings.sheets_webhook_url
    settings.sheets_webhook_url = ""
    try:
        assert sheets_logger.enabled() is False
        assert sheets_logger.should_log("success") is False
    finally:
        settings.sheets_webhook_url = before


def test_needs_input_is_off_by_default(settings_with_webhook):
    assert sheets_logger.should_log("success") is True
    assert sheets_logger.should_log("closed") is True
    assert sheets_logger.should_log("needs_input") is False

    settings_with_webhook.sheets_log_needs_input = True
    assert sheets_logger.should_log("needs_input") is True


def test_cache_hits_can_be_excluded(settings_with_webhook):
    assert sheets_logger.should_log("success", cache_hit=True) is True
    settings_with_webhook.sheets_log_cache_hits = False
    assert sheets_logger.should_log("success", cache_hit=True) is False
    assert sheets_logger.should_log("success", cache_hit=False) is True


# --------------------------------------------------------------------------
# 안전성 — 수집이 파이프라인을 깨면 안 된다
# --------------------------------------------------------------------------
def test_log_analysis_never_raises_outside_event_loop(settings_with_webhook):
    """동기 컨텍스트(루프 없음)에서 불려도 조용히 넘어가야 한다."""
    sheets_logger.log_analysis(_sample_response(), outcome="success")


def test_log_analysis_swallows_row_build_errors(settings_with_webhook, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("row build exploded")

    monkeypatch.setattr(sheets_logger, "build_row", boom)
    sheets_logger.log_analysis(_sample_response(), outcome="success")  # 예외가 새면 실패


def test_send_row_swallows_network_errors(settings_with_webhook, monkeypatch):
    class _Client:
        async def post(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(sheets_logger, "get_client", lambda: _Client())
    assert asyncio.run(sheets_logger.send_row({"biz_no": "1"})) is False


def test_fetch_rows_degrades_when_sheet_unreachable(settings_with_webhook, monkeypatch):
    class _Client:
        async def get(self, *args, **kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr(sheets_logger, "get_client", lambda: _Client())
    result = asyncio.run(sheets_logger.fetch_rows())
    assert result["available"] is False
    assert result["rows"] == []
    assert result["columns"] == list(sheets_logger.COLUMNS)


def test_send_row_posts_token_and_columns(settings_with_webhook, monkeypatch):
    settings_with_webhook.sheets_webhook_token = "secret-token"
    captured = {}

    class _Resp:
        status_code = 200

    class _Client:
        async def post(self, url, **kwargs):
            captured["url"] = url
            captured["json"] = kwargs["json"]
            captured["follow_redirects"] = kwargs.get("follow_redirects")
            return _Resp()

    monkeypatch.setattr(sheets_logger, "get_client", lambda: _Client())
    assert asyncio.run(sheets_logger.send_row({"biz_no": "117-12-23963"})) is True

    assert captured["json"]["token"] == "secret-token"
    assert captured["json"]["columns"] == list(sheets_logger.COLUMNS)
    assert captured["json"]["row"]["biz_no"] == "117-12-23963"
    # Apps Script 웹앱은 POST 에 302 로 응답한다 — 따라가지 않으면 행이 안 쌓인다.
    assert captured["follow_redirects"] is True
