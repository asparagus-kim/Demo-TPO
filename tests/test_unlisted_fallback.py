"""Tests for unlisted businesses and corporate offices fallback."""
from __future__ import annotations

import asyncio
import pytest

from app.schemas import AnalyseRequest, BizIdentity, PlaceCandidate
from app.routers import analyse as router_analyse
from app.services import (
    biz_lookup_service,
    kakao_local_service,
    nts_service,
    places_service,
    weather_service,
    sheets_logger,
)
from app.utils.cache import get_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    get_cache("analysis").clear()
    get_cache("places").clear()
    yield
    get_cache("analysis").clear()
    get_cache("places").clear()


def test_unlisted_business_with_address_auto_synthesizes_office_fallback(monkeypatch):
    """카카오맵 키워드 검색 결과가 없는 신규 사업장/오피스가 등록 주소로 자동 합성되어 분석 성공해야 한다."""
    # 1. Mock NTS: active business
    async def mock_nts(digits):
        return {"status_code": "01", "status_label": "계속사업자"}
    monkeypatch.setattr(nts_service, "lookup_status", mock_nts)

    # 2. Mock Biz lookup: returns company name, registered address, coordinates, and IT/software type
    async def mock_resolve(digits, *, user_company_name=None, user_address=None):
        return BizIdentity(
            company_name="(주)일더스테크",
            address="서울 강남구 테헤란로 123",
            business_type="소프트웨어 개발 및 정보서비스업",
            location={"lat": 37.4980, "lng": 127.0276},
            source="apick",
            confidence=1.0,
            registered_status="계속사업자",
        )
    monkeypatch.setattr(biz_lookup_service, "resolve_identity", mock_resolve)

    # 3. Mock Kakao search candidates: returns empty (unlisted on Kakao map)
    async def mock_search(name, *, address_hint=None, size=15):
        return []
    monkeypatch.setattr(kakao_local_service, "search_candidates", mock_search)

    # 4. Mock surroundings & weather & places & sheets_logger to avoid external calls
    async def mock_surroundings(location, own_code=""):
        return {
            "counts": {"CE7": 50, "FD6": 120, "BK9": 30, "AC5": 10, "HP8": 15, "CS2": 25, "AD5": 2, "AT4": 0},
            "univ": 0,
            "radius": 500,
        }
    monkeypatch.setattr(kakao_local_service, "surroundings", mock_surroundings)

    # Disable sheets logging in test
    monkeypatch.setattr(sheets_logger, "log_analysis", lambda *args, **kwargs: None)

    # Execute
    req = AnalyseRequest(business_number="1234567890")
    resp = asyncio.run(router_analyse.analyse(req))

    assert resp.success is True
    assert resp.needs_input is None
    assert resp.resolved_place is not None
    assert resp.resolved_place.place_id.startswith("unlisted-")
    assert resp.debug["kakao_pick"] == "unlisted_address_fallback"
    assert resp.business_info.company_name == "(주)일더스테크"
    assert resp.business_info.address == "서울 강남구 테헤란로 123"
    assert resp.music is not None
    assert len(resp.music.tracks) > 0


def test_unlisted_business_with_user_address_hint_succeeds(monkeypatch):
    """카카오맵에 없고 상호명만 확보된 상태에서, 사용자가 지역/주소를 입력하면 지오코딩되어 성공해야 한다."""
    async def mock_nts(digits):
        return {"status_code": "01", "status_label": "계속사업자"}
    monkeypatch.setattr(nts_service, "lookup_status", mock_nts)

    async def mock_resolve(digits, *, user_company_name=None, user_address=None):
        return BizIdentity(
            company_name="파트너스투자자문",
            address="",
            business_type="금융 및 보험업",
            location=None,
            source="bizno",
            confidence=1.0,
            registered_status="계속사업자",
        )
    monkeypatch.setattr(biz_lookup_service, "resolve_identity", mock_resolve)

    async def mock_search(name, *, address_hint=None, size=15):
        return []
    monkeypatch.setattr(kakao_local_service, "search_candidates", mock_search)

    # Geocoding returns coordinates for the address hint
    async def mock_geocode(addr):
        return {"lat": 37.5500, "lng": 126.9200}
    monkeypatch.setattr(kakao_local_service, "geocode", mock_geocode)

    async def mock_surroundings(location, own_code=""):
        return {
            "counts": {"CE7": 20, "FD6": 50, "BK9": 10, "AC5": 5, "HP8": 5, "CS2": 10, "AD5": 1, "AT4": 0},
            "univ": 1,
            "radius": 500,
        }
    monkeypatch.setattr(kakao_local_service, "surroundings", mock_surroundings)
    monkeypatch.setattr(sheets_logger, "log_analysis", lambda *args, **kwargs: None)

    # 1st attempt: no address hint -> returns needs_input
    req1 = AnalyseRequest(business_number="1234567890")
    resp1 = asyncio.run(router_analyse.analyse(req1))
    assert resp1.success is False
    assert resp1.needs_input is not None
    assert resp1.needs_input.reason == "not_found"

    # 2nd attempt: user passes address_hint -> succeeds with unlisted_address_fallback
    req2 = AnalyseRequest(business_number="1234567890", address_hint="서울 마포구 양화로 45")
    resp2 = asyncio.run(router_analyse.analyse(req2))
    assert resp2.success is True
    assert resp2.debug["kakao_pick"] == "unlisted_address_fallback"
    assert resp2.resolved_place.address == "서울 마포구 양화로 45"
    assert len(resp2.music.tracks) > 0
