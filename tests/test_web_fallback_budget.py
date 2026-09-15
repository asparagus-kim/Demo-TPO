"""웹검색 폴백 벽시계 예산 — 검색 엔진이 느리거나 막혔을 때 파이프라인이 기다리지 않는지."""
from __future__ import annotations

import asyncio
import time

from app.schemas import WebEvidenceItem
from app.services import web_search_service as W


def _item(text: str) -> WebEvidenceItem:
    return WebEvidenceItem(title="t", url="https://example.com", text=text, source="search_snippet")


def _run(coro):
    return asyncio.run(coro)


def test_slow_evidence_search_is_cut_at_budget(monkeypatch):
    """근거 검색이 예산을 넘기면 빈 결과로 **즉시** 돌아온다 — 63초 분석의 재발 방지."""
    async def slow(*_a, **_k):
        await asyncio.sleep(5)
        return [_item("never")]
    monkeypatch.setattr(W, "search_business_evidence", slow)

    t0 = time.perf_counter()
    evidence, hours = _run(W.collect_fallback_evidence(
        "가게", "카페", "서울", need_hours=True, budget_sec=0.2))
    elapsed = time.perf_counter() - t0

    assert evidence == [] and hours == []
    assert elapsed < 1.0, f"예산 0.2s 인데 {elapsed:.2f}s 걸렸다"


def test_fast_evidence_without_hours_does_not_search_hours(monkeypatch):
    async def fast(*_a, **_k):
        return [_item("조용하고 아늑해요")]
    async def must_not_run(*_a, **_k):
        raise AssertionError("need_hours=False 인데 영업시간 검색이 호출됐다")
    monkeypatch.setattr(W, "search_business_evidence", fast)
    monkeypatch.setattr(W, "search_hours_evidence", must_not_run)

    evidence, hours = _run(W.collect_fallback_evidence(
        "가게", "카페", "서울", need_hours=False, budget_sec=2.0))

    assert len(evidence) == 1 and hours == []


def test_partial_results_survive_when_hours_search_is_slow(monkeypatch):
    """근거 검색은 끝났고 영업시간 검색만 늦으면 근거는 살려서 돌려준다."""
    async def fast(*_a, **_k):
        return [_item("치즈케이크가 맛있어요")]          # 영업시간 패턴 없음 → 재검색으로 진행
    async def slow_hours(*_a, **_k):
        await asyncio.sleep(5)
        return [_item("영업시간 09:00 - 22:00")]
    monkeypatch.setattr(W, "search_business_evidence", fast)
    monkeypatch.setattr(W, "search_hours_evidence", slow_hours)

    t0 = time.perf_counter()
    evidence, hours = _run(W.collect_fallback_evidence(
        "가게", "카페", "서울", need_hours=True, budget_sec=0.3))

    assert len(evidence) == 1, "예산 초과 전에 끝난 근거 검색 결과는 보존돼야 한다"
    assert hours == []
    assert time.perf_counter() - t0 < 1.0


def test_search_exception_does_not_propagate(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(W, "search_business_evidence", boom)

    evidence, hours = _run(W.collect_fallback_evidence(
        "가게", "카페", "서울", need_hours=True, budget_sec=2.0))
    assert evidence == [] and hours == []
