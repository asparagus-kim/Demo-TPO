"""biz_lookup — 조회 실패의 '이유'가 문구와 debug 로 구분되어 나가야 한다.

2026-09-15: bizno 무료 플랜의 일일 200건 한도가 소진되자 모든 사업자번호가
"상호명을 찾지 못했습니다"로 떨어졌다. 번호가 잘못된 것처럼 보여 원인을
찾는 데 시간이 걸렸다 — 한도 초과/장애는 '번호 없음'과 다른 사건이다.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.services import biz_lookup_service as biz
from app.utils import http as shared_http
from app.utils.cache import get_cache


class _Settings:
    bizno_api_key = "test-key"
    bizno_api_url = "https://bizno.net/api/fapi"

    def effective_mock_mode(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(biz, "get_settings", lambda: _Settings())
    monkeypatch.setattr(biz, "_BIZNO_GAP_SEC", 0)
    get_cache("bizno").clear()


def _respond(payload, status_code=200):
    def _client():
        async def _get(url, params=None, timeout=None):
            return types.SimpleNamespace(
                status_code=status_code, json=lambda: payload, text=str(payload))
        return types.SimpleNamespace(get=_get)
    return _client


def test_quota_exceeded_is_not_reported_as_missing_number(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _respond(
        {"resultCode": -3, "resultMsg": "1일 200건 조회수 초과.", "items": []}))

    identity = asyncio.run(biz.resolve_identity("2018205114"))

    assert identity.needs_user_input is True
    assert identity.lookup_error == biz.ERR_QUOTA
    assert identity.message == biz.MSG_LOOKUP_UNAVAILABLE


def test_unknown_number_keeps_the_not_found_message(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _respond(
        {"resultCode": 0, "resultMsg": "OK", "items": [None, None]}))

    identity = asyncio.run(biz.resolve_identity("1068214787"))

    assert identity.needs_user_input is True
    assert identity.lookup_error == biz.ERR_NOT_FOUND
    assert identity.message == biz.MSG_NEED_NAME


def test_http_failure_reads_as_a_lookup_outage(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _respond({}, status_code=500))

    identity = asyncio.run(biz.resolve_identity("2118891185"))

    assert identity.lookup_error == biz.ERR_HTTP
    assert identity.message == biz.MSG_LOOKUP_UNAVAILABLE


def test_hit_still_resolves_and_carries_no_error(monkeypatch):
    monkeypatch.setattr(shared_http, "get_client", _respond(
        {"resultCode": 0, "resultMsg": "OK",
         "items": [None, {"company": "별빛카페", "bno": "1234567890", "bstt": "계속사업자"}]}))

    identity = asyncio.run(biz.resolve_identity("1234567890"))

    assert identity.company_name == "별빛카페"
    assert identity.source == biz.SOURCE_BIZNO
    assert identity.lookup_error == ""
    assert identity.needs_user_input is False
