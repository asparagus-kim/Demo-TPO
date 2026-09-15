"""warm_hosts — 예열은 실패해도 조용해야 하고, 같은 호스트는 한 번만 연다."""
from __future__ import annotations

import asyncio
import types

import httpx

from app.utils import http as shared_http


def test_warm_hosts_dedups_and_swallows_failures(monkeypatch):
    seen = []

    async def fake_get(url, timeout=None):
        seen.append(url)
        if "bad.example" in url:
            raise httpx.ConnectError("refused")
        return types.SimpleNamespace(status_code=404)   # 404 여도 연결은 열린 것

    monkeypatch.setattr(shared_http, "get_client", lambda: types.SimpleNamespace(get=fake_get))

    n = asyncio.run(shared_http.warm_hosts([
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        "https://dapi.kakao.com/v2/local/search/category.json",   # 같은 호스트 → 1회
        "https://api.groq.com/openai/v1",
        "https://bad.example/x",
        "",                                                         # 빈 값은 무시
    ]))

    assert sorted(seen) == ["https://api.groq.com/", "https://bad.example/", "https://dapi.kakao.com/"]
    assert n == 2


def test_warm_hosts_with_nothing_is_a_noop():
    assert asyncio.run(shared_http.warm_hosts([])) == 0
