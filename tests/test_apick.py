"""APICK biz_detail — 주소·좌표까지 주는 상호명 조회 경로.

왜 필요한가 (2026-10-01 광진구 49곳 실측):
bizno 무료 플랜은 **상호명만** 준다. 그래서 동명 매장 두 곳이 Kakao 에서
똑같이 1.000 점을 받아 격차가 0.000 이 되고, 49곳 중 20곳(41%)이
'매장 선택' 화면으로 떨어졌다. APICK 은 도로명주소와 위·경도를 함께 주고,
그 좌표로 고르면 20곳 중 17곳이 자동 확정됐다(정답 3~8m, 2등 153m~238km).
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.schemas import PlaceCandidate
from app.services import apick_service as apick
from app.services import biz_lookup_service as biz
from app.services import kakao_local_service as kakao
from app.utils import http as shared_http
from app.utils.cache import get_cache


# 실제 응답에서 쓰는 필드만 추린 것 (2026-10-01 테라다식당 군자점 실측).
APICK_OK = {
    "data": {
        "회사명": "테라다식당 군자점",
        "사업자상태": "계속사업자",
        "과세유형": "부가가치세 일반과세자",
        "대표명": "허혜빈",
        "업종": "음식점업",
        "업태": "한식 일반 음식점업",
        "도로명주소": "서울특별시 광진구 능동로36길 15, 1층(능동)",
        "지번주소": "서울특별시 광진구 능동 220-13, 1층(능동)",
        "위도": "37.55617306102622",
        "경도": "127.0800150120533",
        "전화번호": "031-227-3577",
    }
}


class _Settings:
    apick_api_key = "test-apick"
    apick_biz_detail_url = "https://apick.app/rest/biz_detail"
    bizno_api_key = "test-bizno"
    bizno_api_url = "https://bizno.net/api/fapi"

    def effective_mock_mode(self) -> bool:
        return False


def _responder(payload, status_code=200):
    """POST 만 받는 가짜 httpx 클라이언트."""
    def _client():
        async def _post(url, headers=None, files=None, timeout=None):
            return types.SimpleNamespace(
                status_code=status_code, json=lambda: payload, text=str(payload))
        async def _get(url, params=None, timeout=None):
            raise AssertionError("APICK 경로가 GET 을 쓰면 안 된다")
        return types.SimpleNamespace(post=_post, get=_get)
    return _client


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(apick, "get_settings", lambda: _Settings())
    monkeypatch.setattr(biz, "get_settings", lambda: _Settings())
    monkeypatch.setattr(biz, "_BIZNO_GAP_SEC", 0)
    get_cache("apick").clear()
    get_cache("bizno").clear()


# ------------------------------------------------------------------ apick_service

def test_lookup_normalises_address_and_location(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _responder(APICK_OK))

    rec = asyncio.run(apick.lookup("3020870922"))

    assert rec["company_name"] == "테라다식당 군자점"
    assert rec["address"].startswith("서울특별시 광진구 능동로36길 15")
    assert rec["location"] == pytest.approx(
        {"lat": 37.55617306102622, "lng": 127.0800150120533})
    assert rec["business_type"] == "한식 일반 음식점업"
    assert rec["registered_status"] == "계속사업자"


def test_empty_coordinates_yield_no_location_but_keep_address(monkeypatch):
    """위도·경도는 문자열로 오고 값이 없으면 "" 다 — 49곳 중 2곳이 그랬다."""
    payload = {"data": {**APICK_OK["data"], "위도": "", "경도": ""}}
    monkeypatch.setattr(shared_http, "get_client", _responder(payload))

    rec = asyncio.run(apick.lookup("1111111111"))

    assert rec["location"] is None
    assert rec["address"]


@pytest.mark.parametrize("lat,lng", [
    ("abc", "127.08"),      # 숫자가 아님
    ("0", "0"),             # Null Island — 한국 밖
    ("37.556", "0"),
    ("90", "127.08"),       # 위도 범위 밖
])
def test_unusable_coordinates_are_dropped(monkeypatch, lat, lng):
    """좌표가 틀리면 '없음'으로 떨어뜨린다. 엉뚱한 좌표로 매장을 고르는 것이
    사용자에게 묻는 것보다 훨씬 나쁘다."""
    payload = {"data": {**APICK_OK["data"], "위도": lat, "경도": lng}}
    monkeypatch.setattr(shared_http, "get_client", _responder(payload))

    assert asyncio.run(apick.lookup("2222222222"))["location"] is None


def test_road_address_missing_falls_back_to_jibun(monkeypatch):
    payload = {"data": {**APICK_OK["data"], "도로명주소": ""}}
    monkeypatch.setattr(shared_http, "get_client", _responder(payload))

    assert asyncio.run(apick.lookup("3333333333"))["address"].startswith(
        "서울특별시 광진구 능동 220-13")


def test_http_error_and_empty_name_return_none(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _responder({}, status_code=500))
    assert asyncio.run(apick.lookup("4444444444")) is None

    monkeypatch.setattr(shared_http, "get_client",
                        _responder({"data": {"회사명": ""}}))
    assert asyncio.run(apick.lookup("5555555555")) is None


def test_point_exhaustion_arrives_as_http_200_and_degrades(monkeypatch, caplog):
    """실측 응답: 포인트가 떨어져도 상태코드는 200 이고 본문에만 사유가 있다.
    bizno 일일 한도와 같은 함정 — 조용히 전 번호가 실패하면 원인을 못 찾는다."""
    payload = {"result": {"error": "사용 가능한 포인트이 부족합니다."},
               "api": {"cost": 0, "success": True}}
    monkeypatch.setattr(shared_http, "get_client", _responder(payload))

    with caplog.at_level("ERROR"):
        assert asyncio.run(apick.lookup("1212121212")) is None
    assert "포인트" in caplog.text


def test_error_body_is_never_cached(monkeypatch):
    """실패를 캐시하면 포인트를 충전해도 TTL 동안 계속 실패한다."""
    monkeypatch.setattr(shared_http, "get_client",
                        _responder({"result": {"error": "사용 가능한 포인트이 부족합니다."}}))
    asyncio.run(apick.lookup("1313131313"))
    assert "1313131313" not in get_cache("apick")


def test_no_key_skips_the_call_entirely(monkeypatch):
    class _NoKey(_Settings):
        apick_api_key = ""
    monkeypatch.setattr(apick, "get_settings", lambda: _NoKey())

    def _boom():
        raise AssertionError("키가 없으면 호출하면 안 된다 — 호출당 50포인트다")
    monkeypatch.setattr(shared_http, "get_client", _boom)

    assert asyncio.run(apick.lookup("6666666666")) is None


# ------------------------------------------------------------------ 좌표 기반 선택

def _cand(name, lat, lng):
    return PlaceCandidate(place_id=name, place_name=name,
                          location=None if lat is None else {"lat": lat, "lng": lng})


ORIGIN = {"lat": 37.55617, "lng": 127.08001}


def test_location_pick_takes_the_store_at_the_same_address():
    """실측 모양: 정답 수 m, 2등 수 km."""
    cands = [_cand("먼곳", 37.65, 127.20), _cand("진짜매장", 37.556175, 127.080015)]
    chosen, reason = kakao.pick_by_location(cands, ORIGIN)
    assert reason == "location" and chosen.place_name == "진짜매장"


def test_two_equally_close_candidates_stay_ambiguous():
    """같은 건물에 두 후보가 있으면 좌표로는 못 가른다 — 물어본다."""
    cands = [_cand("A", 37.55618, 127.08002), _cand("B", 37.55616, 127.08000)]
    chosen, reason = kakao.pick_by_location(cands, ORIGIN)
    assert chosen is None and reason == "ambiguous"


def test_nearest_but_far_away_is_rejected():
    """화계장터 사례: 가장 가까운 Kakao 매장이 34km 떨어져 있었다."""
    cands = [_cand("엉뚱한곳", 37.80, 127.50)]
    chosen, reason = kakao.pick_by_location(cands, ORIGIN)
    assert chosen is None and reason == "ambiguous"


def test_candidates_without_location_are_skipped_not_treated_as_zero():
    cands = [_cand("좌표없음", None, None), _cand("진짜매장", 37.556175, 127.080015)]
    chosen, reason = kakao.pick_by_location(cands, ORIGIN)
    assert chosen is not None and chosen.place_name == "진짜매장"


def test_no_origin_or_no_candidates_is_ambiguous():
    assert kakao.pick_by_location([], ORIGIN)[0] is None
    assert kakao.pick_by_location([_cand("A", 37.556, 127.080)], None)[0] is None


# ------------------------------------------------------------------ 조회 체인

def test_apick_hit_populates_address_and_location(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _responder(APICK_OK))

    ident = asyncio.run(biz.resolve_identity("3020870922"))

    assert ident.source == biz.SOURCE_APICK
    assert ident.company_name == "테라다식당 군자점"
    assert ident.location == pytest.approx(
        {"lat": 37.55617306102622, "lng": 127.0800150120533})
    assert ident.address and ident.needs_user_input is False
    assert ident.lookup_error == ""


def test_apick_failure_falls_back_to_bizno(monkeypatch):
    """APICK 이 죽어도 어제까지의 경로가 그대로 살아 있어야 한다."""
    def _client():
        async def _post(url, headers=None, files=None, timeout=None):
            return types.SimpleNamespace(status_code=500, json=lambda: {}, text="err")
        async def _get(url, params=None, timeout=None):
            return types.SimpleNamespace(status_code=200, text="{}", json=lambda: {
                "resultCode": 0, "items": [{"company": "별빛카페", "bstt": "계속사업자"}]})
        return types.SimpleNamespace(post=_post, get=_get)
    monkeypatch.setattr(shared_http, "get_client", _client)

    ident = asyncio.run(biz.resolve_identity("7777777777"))

    assert ident.source == biz.SOURCE_BIZNO
    assert ident.company_name == "별빛카페"
    assert ident.location is None


def test_both_sources_down_still_reports_the_outage_message(monkeypatch):
    def _client():
        async def _post(url, headers=None, files=None, timeout=None):
            return types.SimpleNamespace(status_code=500, json=lambda: {}, text="err")
        async def _get(url, params=None, timeout=None):
            return types.SimpleNamespace(status_code=500, text="err", json=lambda: {})
        return types.SimpleNamespace(post=_post, get=_get)
    monkeypatch.setattr(shared_http, "get_client", _client)

    ident = asyncio.run(biz.resolve_identity("8888888888"))

    assert ident.needs_user_input is True
    assert ident.lookup_error == biz.ERR_HTTP
    assert ident.message == biz.MSG_LOOKUP_UNAVAILABLE


def test_without_an_apick_key_the_chain_is_unchanged(monkeypatch):
    """회귀 방어: 키가 없으면 어제와 완전히 같은 bizno → needs_input 경로."""
    class _NoApick(_Settings):
        apick_api_key = ""
    monkeypatch.setattr(apick, "get_settings", lambda: _NoApick())
    monkeypatch.setattr(biz, "get_settings", lambda: _NoApick())

    def _client():
        async def _post(url, headers=None, files=None, timeout=None):
            raise AssertionError("APICK 키가 없는데 POST 가 나갔다")
        async def _get(url, params=None, timeout=None):
            return types.SimpleNamespace(status_code=200, text="{}", json=lambda: {
                "resultCode": 0, "items": [{"company": "별빛카페"}]})
        return types.SimpleNamespace(post=_post, get=_get)
    monkeypatch.setattr(shared_http, "get_client", _client)

    ident = asyncio.run(biz.resolve_identity("9999999999"))

    assert ident.source == biz.SOURCE_BIZNO
    assert ident.location is None


def test_user_supplied_name_still_short_circuits_everything(monkeypatch):
    def _boom():
        raise AssertionError("사용자가 상호명을 줬으면 조회하면 안 된다")
    monkeypatch.setattr(shared_http, "get_client", _boom)

    ident = asyncio.run(biz.resolve_identity("1010101010", user_company_name="직접입력"))

    assert ident.source == biz.SOURCE_USER and ident.company_name == "직접입력"
