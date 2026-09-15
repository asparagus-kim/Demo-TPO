"""프로세스 전역 httpx 클라이언트 (연결 풀 재사용).

왜 필요한가 — 측정값:

    요청마다 `httpx.AsyncClient()` 를 새로 만들면 생성 자체가 **CPU 38ms**
    (SSL 컨텍스트 + CA 번들 로드)이고, 이 비용은 GIL에 묶여 **직렬화**된다.
    게다가 매번 TLS 핸드셰이크를 새로 한다. `surroundings()` 는 카테고리 9건을
    동시에 부르므로 이 비용을 9배로 냈다.

        기존(호출마다 클라이언트)  : 3321ms
        공유 클라이언트(워밍 후)   :   60–82ms   → 약 3.2초 단축

Why this exists — measured: constructing `httpx.AsyncClient()` per request costs
~38ms of pure CPU (SSL context + CA bundle) and that cost is GIL-bound, so
concurrent construction serialises. `surroundings()` fanned out 9 of them at
once and paid 3321ms; the same fan-out on a warm shared pool takes 60–82ms.

사용법: `await get_client().get(...)`. `async with` 로 감싸면 안 된다 —
컨텍스트를 벗어날 때 공유 풀이 닫혀 다음 요청이 느려진다.
Never wrap the returned client in `async with`: that closes the shared pool.

타임아웃은 호출 지점에서 `timeout=` 로 넘기면 요청별로 그대로 적용된다.
"""
from __future__ import annotations

from typing import Optional

import httpx

# 업스트림이 6종(Kakao·Google·data.go.kr·bizno·Groq·웹검색)이고 Kakao 상권 집계가
# 한 번에 9건을 부르므로 keepalive 여유를 넉넉히 둔다.
_LIMITS = httpx.Limits(
    max_keepalive_connections=32,
    max_connections=64,
    # 60초였다. 데모에서 분석 사이 간격이 1~5분이라 그 사이에 Kakao 연결이 전부
    # 만료되고, 다음 분석은 새 연결 9개를 다시 열며 2~6초를 냈다(1초 계단, 실측).
    # 5분으로 늘려 시작 시 예열한 풀이 데모 내내 살아 있게 한다.
    keepalive_expiry=300.0,
)

# 호출 지점 대부분이 `timeout=20` 을 명시하므로 기본값도 같게 맞춘다.
_DEFAULT_TIMEOUT = httpx.Timeout(20.0)

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """공유 클라이언트를 돌려준다. 없거나 닫혀 있으면 새로 만든다.

    `is_closed` 를 확인하는 이유: 테스트가 `aclose()` 를 부른 뒤에도 다음 호출이
    살아 있는 클라이언트를 받아야 한다.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(limits=_LIMITS, timeout=_DEFAULT_TIMEOUT)
    return _client


async def aclose() -> None:
    """앱 종료 시 연결을 정리한다 (main.py shutdown 훅)."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
