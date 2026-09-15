"""debug.llm — LLM 이 실제로 돌았는지 응답에서 알 수 있어야 한다.

주의: `_last_stats` 는 ContextVar 다. `asyncio.run()` 은 컨텍스트를 **복사**해서 태스크를
돌리므로, 통계는 반드시 같은 코루틴 안에서 읽어야 한다 — 라우터가 실제로 그렇게 한다.
"""
from __future__ import annotations

import asyncio
import json
import types

from app.config import get_settings
from app.schemas import PlaceReview
from app.services import llm_service as L

KW = dict(business_type="카페", trade_area="t", weather_summary="w", business_hours="")


class _RateLimited(Exception):
    status_code = 429


def _fake_client(behaviour):
    async def create(**_kw):
        return behaviour()
    return types.SimpleNamespace(chat=types.SimpleNamespace(
        completions=types.SimpleNamespace(create=create)))


def _ok_response(n):
    payload = {"scores": [{"i": i + 1, "energy": 0.2, "tempo": 0.3, "mood": 0.8,
                           "informativeness": 0.7, "keywords": ["k"], "occasion_labels": ["o"]}
                          for i in range(n)]}
    msg = types.SimpleNamespace(content=json.dumps(payload))
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


def _real_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "mock_mode", False)
    monkeypatch.setattr(s, "kakao_rest_api_key", "kakao")
    monkeypatch.setattr(s, "openai_api_key", "llm")
    monkeypatch.setattr(L, "LLM_RETRY_BASE_SEC", 0.0)   # 테스트에서 백오프 대기 없음


async def _score_and_stats(reviews):
    scores = await L.score_reviews(reviews, **KW)
    return scores, L.last_call_stats()


def test_rate_limit_exhaustion_is_visible_in_stats(monkeypatch):
    _real_mode(monkeypatch)
    def boom():
        raise _RateLimited("429")
    monkeypatch.setattr(L, "_get_llm_client", lambda: _fake_client(boom))
    reviews = [PlaceReview(text=f"stats-429-리뷰-{i} 조용하고 아늑해요", rating=5) for i in range(3)]

    scores, st = asyncio.run(_score_and_stats(reviews))

    assert len(scores) == 3, "실패해도 휴리스틱으로 3건 모두 채워져야 한다"
    assert st["status"] == "rate_limited"
    assert st["attempts"] == L.LLM_MAX_ATTEMPTS
    assert st["batch_size"] == 3


def test_long_retry_after_fails_fast_instead_of_waiting(monkeypatch):
    """Groq 가 30초 뒤에 오라고 하면 기다리지 않고 바로 휴리스틱으로 — 데모에서 30초는 죽음이다."""
    _real_mode(monkeypatch)
    def boom():
        raise _RateLimited("Rate limit reached ... Please try again in 30.5s.")
    monkeypatch.setattr(L, "_get_llm_client", lambda: _fake_client(boom))
    reviews = [PlaceReview(text=f"stats-slowra-리뷰-{i} 붐비고 활기차요", rating=5) for i in range(2)]

    t0 = asyncio.get_event_loop().time() if False else None
    import time
    t0 = time.perf_counter()
    scores, st = asyncio.run(_score_and_stats(reviews))

    assert len(scores) == 2
    assert st["status"] == "rate_limited"
    assert st["attempts"] == 1, "요구 대기가 예산을 넘으면 재시도하지 않는다"
    assert time.perf_counter() - t0 < 1.0


def test_success_is_visible_in_stats(monkeypatch):
    _real_mode(monkeypatch)
    monkeypatch.setattr(L, "_get_llm_client", lambda: _fake_client(lambda: _ok_response(2)))
    reviews = [PlaceReview(text=f"stats-ok-리뷰-{i} 재즈가 흘러요", rating=5) for i in range(2)]

    scores, st = asyncio.run(_score_and_stats(reviews))

    assert [round(s.mood, 1) for s in scores] == [0.8, 0.8]
    assert st["status"] == "ok" and st["attempts"] == 1 and st["batch_size"] == 2


def test_second_run_is_served_from_cache(monkeypatch):
    _real_mode(monkeypatch)
    calls = {"n": 0}
    def ok():
        calls["n"] += 1
        return _ok_response(2)
    monkeypatch.setattr(L, "_get_llm_client", lambda: _fake_client(ok))
    reviews = [PlaceReview(text=f"stats-cache-리뷰-{i} 친절해요", rating=5) for i in range(2)]

    async def twice():
        await L.score_reviews(reviews, **KW)
        return await _score_and_stats(reviews)
    _, st = asyncio.run(twice())

    assert calls["n"] == 1, "두 번째 실행은 리뷰 단위 캐시로 LLM 을 부르지 않아야 한다"
    assert st["status"] == "cached" and st["cache_hits"] == 2 and st["batch_size"] == 0
