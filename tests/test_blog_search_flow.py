"""Provider-independent review acceptance, hours isolation, and cache identity."""
import asyncio
from types import SimpleNamespace

import pytest
import httpx

from app.schemas import WebEvidenceItem
from app.services import web_search_service as W


def post(url="https://blog.naver.com/reviewer/12345"):
    return WebEvidenceItem(title="역삼동 별빛커피 방문", text="서울 강남구 역삼동 별빛커피에 다녀왔어요. 커피가 맛있고 좌석이 편안했어요.", url=url, source="duckduckgo")


def directory():
    return WebEvidenceItem(title="별빛커피 사업자 정보", text="서울 강남구 역삼동 별빛커피 사업자등록번호 조회. 영업시간 09:00 - 22:00", url="https://directory.example/business/123", source="kakao_blog")


@pytest.fixture
def setup(monkeypatch):
    settings = SimpleNamespace(kakao_rest_api_key="synthetic", effective_mock_mode=lambda: False, web_fallback_budget_sec=4)
    monkeypatch.setattr(W, "get_settings", lambda: settings)
    monkeypatch.setattr(W, "get_cache", lambda _: cache)
    cache = {}
    for key in ["SERPAPI_KEY", "GOOGLE_CSE_KEY", "GOOGLE_CSE_CX"]:
        monkeypatch.delenv(key, raising=False)
    return cache


def search(**kwargs):
    return asyncio.run(W.search_business_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", **kwargs))


def test_rejected_first_provider_continues_and_deduplicates_naver(monkeypatch, setup):
    calls = []
    async def kakao(client, query, *args, **kwargs):
        calls.append(("kakao", query))
        return [directory()]
    async def ddg(client, query, *args, **kwargs):
        calls.append(("ddg", query))
        return [post(), post("https://m.blog.naver.com/reviewer/12345")]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    monkeypatch.setattr(W, "_duckduckgo_search", ddg)
    results = search()
    assert len(results) == 1
    assert results[0].source == "naver_blog"
    assert [c[0] for c in calls] == ["kakao", "ddg"]
    assert "site:blog.naver.com" in calls[1][1]


def test_accepted_first_provider_stops_other_providers(monkeypatch, setup):
    async def kakao(*args, **kwargs): return [post()]
    async def must_not_run(*args, **kwargs): raise AssertionError("fallback after accepted posts")
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    monkeypatch.setattr(W, "_duckduckgo_search", must_not_run)
    assert len(search()) == 1


def test_hours_directory_never_becomes_review_or_score_input(monkeypatch, setup):
    async def kakao(client, query, *args, **kwargs): return [directory()]
    async def ddg(*args, **kwargs): return []
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    monkeypatch.setattr(W, "_duckduckgo_search", ddg)
    evidence, hours = asyncio.run(W.collect_fallback_evidence(
        "별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=True, budget_sec=2))
    assert evidence == []
    assert hours
    assert W.to_place_reviews(evidence) == []


def test_context_conflict_abstains_before_network(monkeypatch, setup):
    async def must_not_run(*args, **kwargs): raise AssertionError("identity conflict sent a request")
    monkeypatch.setattr(W, "_kakao_blog_search", must_not_run)
    monkeypatch.setattr(W, "_duckduckgo_search", must_not_run)
    diagnostics = {}
    evidence, hours = asyncio.run(W.collect_fallback_evidence(
        "다른카페", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=True, budget_sec=2, diagnostics=diagnostics))
    assert evidence == hours == []
    assert diagnostics["identity_reason"]


def test_search_cache_is_rechecked_and_separates_purposes(monkeypatch, setup):
    calls = []
    async def kakao(client, query, *args, **kwargs):
        calls.append(query)
        return [post()]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    assert len(search()) == 1
    assert len(search()) == 1
    assert len(calls) == 1
    # Corrupted/stale entries cannot bypass acceptance simply by hitting a cache.
    for key in setup: setup[key] = [directory()]
    assert len(search()) == 1
    assert len(calls) == 2
    asyncio.run(W.search_hours_evidence("별빛커피", "서울 강남구 역삼동 1", store_name="별빛커피"))
    assert len(calls) == 3


def test_analysis_cache_version_keeps_reanalyse_prefix():
    from app.routers import analyse as router
    from app.services.blog_search_policy import POLICY_VERSION
    key = router._cache_key("1234567890", place_id="test-store")
    assert key.startswith("analyse:1234567890:")
    assert POLICY_VERSION in key


def test_hours_fallback_continues_after_post_without_hours(monkeypatch, setup):
    calls = []
    async def kakao(*args, **kwargs):
        calls.append("kakao")
        return [post()]
    async def ddg(*args, **kwargs):
        calls.append("ddg")
        return [directory()]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    monkeypatch.setattr(W, "_duckduckgo_search", ddg)
    items = asyncio.run(W.search_hours_evidence("별빛커피", "서울 강남구 역삼동 1", store_name="별빛커피"))
    assert W.extract_business_hours(items)
    assert calls == ["kakao", "ddg"]


def test_business_number_contaminated_context_does_not_search(monkeypatch, setup):
    from app.services.blog_search_policy import build_search_context
    context = build_search_context("별빛커피 123-45-67890", "서울 강남구 역삼동")
    assert context.reason == "business_number_in_store_name"
    assert not context.review_queries


@pytest.mark.parametrize("provider", ["serpapi", "google_cse", "duckduckgo"])
def test_real_provider_parsers_share_acceptance_policy(monkeypatch, setup, provider):
    monkeypatch.setenv("SERPAPI_KEY", "synthetic")
    monkeypatch.setenv("GOOGLE_CSE_KEY", "synthetic")
    monkeypatch.setenv("GOOGLE_CSE_CX", "synthetic")
    calls = []
    async def run():
        def handler(request):
            calls.append(request)
            host = request.url.host
            item = post()
            if host == "dapi.kakao.com":
                return httpx.Response(200, json={"documents": [{"title": directory().title, "contents": directory().text, "url": directory().url}]})
            if host == "serpapi.com":
                items = [{"title": item.title, "snippet": item.text, "link": item.url}] if provider == "serpapi" else []
                return httpx.Response(200, json={"organic_results": items})
            if host == "www.googleapis.com":
                items = [{"title": item.title, "snippet": item.text, "link": item.url}] if provider == "google_cse" else []
                return httpx.Response(200, json={"items": items})
            return httpx.Response(200, text=f'<a class="result__a" href="{item.url}">{item.title}</a><a class="result__snippet">{item.text}</a>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(W.shared_http, "get_client", lambda: client)
            diagnostics = {}
            results, _ = await W.collect_fallback_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=False, budget_sec=2, diagnostics=diagnostics)
            assert len(results) == 1
            assert results[0].source == "naver_blog"
            assert diagnostics["reviews_provider"] == provider
            assert diagnostics["requests"] == len(calls) <= 4
            for request in calls[1:]:
                assert "site:blog.naver.com" in request.url.params.get("q", "")
    asyncio.run(run())


@pytest.mark.parametrize("need_hours, review_calls", [(False, 8), (True, 6)])
def test_actual_search_requests_share_review_and_hours_cap(monkeypatch, setup, need_hours, review_calls):
    calls = []
    async def run():
        def handler(request):
            calls.append(request)
            return httpx.Response(503)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(W.shared_http, "get_client", lambda: client)
            diagnostics = {}
            results, hours = await W.collect_fallback_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=need_hours, budget_sec=2, diagnostics=diagnostics)
            assert results == hours == []
            assert len(calls) == diagnostics["requests"] == 8
            review_requests = [r for r in calls if "영업시간" not in (r.url.params.get("q", "") + r.url.params.get("query", ""))]
            assert len(review_requests) == review_calls
    asyncio.run(run())


def test_duckduckgo_is_called_directly_without_a_redirect_hop(monkeypatch, setup):
    monkeypatch.setattr(W, "get_settings", lambda: SimpleNamespace(
        kakao_rest_api_key="", effective_mock_mode=lambda: False, web_fallback_budget_sec=4))
    calls = []
    async def run():
        def handler(request):
            calls.append(request)
            item = post()
            return httpx.Response(200, text=f'<a class="result__a" href="{item.url}">{item.title}</a><a class="result__snippet">{item.text}</a>')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            monkeypatch.setattr(W.shared_http, "get_client", lambda: client)
            diagnostics = {}
            results, _ = await W.collect_fallback_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=False, budget_sec=2, diagnostics=diagnostics)
            assert len(results) == 1 and diagnostics["requests"] == 1
    asyncio.run(run())
    assert [r.url.host for r in calls] == ["html.duckduckgo.com"]


def test_hours_origin_distinguishes_reviews_from_verified_web(monkeypatch, setup):
    with_hours = post()
    with_hours = with_hours.model_copy(update={"text": with_hours.text + " 영업시간 09:00 - 22:00"})
    async def kakao_reviews(*args, **kwargs): return [with_hours]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao_reviews)
    diagnostics = {}
    _, hours = asyncio.run(W.collect_fallback_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=True, budget_sec=2, diagnostics=diagnostics))
    assert hours and diagnostics["hours_origin"] == "accepted_reviews"

    setup.clear()
    async def kakao(client, query, *args, **kwargs): return [directory()] if "영업시간" in query else []
    async def ddg(*args, **kwargs): return []
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    monkeypatch.setattr(W, "_duckduckgo_search", ddg)
    diagnostics = {}
    evidence, hours = asyncio.run(W.collect_fallback_evidence("별빛커피", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=True, budget_sec=2, diagnostics=diagnostics))
    assert evidence == [] and hours and diagnostics["hours_origin"] == "verified_web"


def test_user_picked_store_skips_registered_name_conflict(monkeypatch, setup):
    async def kakao(*args, **kwargs): return [post()]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    conflict = {}
    evidence, _ = asyncio.run(W.collect_fallback_evidence("다른상호", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", need_hours=False, budget_sec=2, diagnostics=conflict))
    assert evidence == [] and conflict["identity_reason"] == "registered_name_conflict"
    picked = {}
    evidence, _ = asyncio.run(W.collect_fallback_evidence("다른상호", "카페", "서울 강남구 역삼동 1", store_name="별빛커피", registered_name="", need_hours=False, budget_sec=2, diagnostics=picked))
    assert len(evidence) == 1 and not picked["identity_reason"]


def test_at_most_four_blogs_are_kept_and_exact_title_matches_rank_first(monkeypatch, setup):
    # Broader matches: the store is named in the title, but only the 동 is given.
    broader = "역삼동 별빛커피에 다녀왔어요. 커피가 맛있고 좌석이 편안했어요."
    broad = [post(f"https://blog.naver.com/writer{i}/{1000 + i}").model_copy(update={"title": "별빛커피 일기", "text": broader})
             for i in range(5)]
    exact = post("https://blog.naver.com/exact/999")
    async def kakao(*args, **kwargs): return broad + [exact]
    monkeypatch.setattr(W, "_kakao_blog_search", kakao)
    results = search()
    assert len(results) == W.DEFAULT_MAX_RESULTS == 4
    assert results[0].url == exact.url
