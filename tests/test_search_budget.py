"""The search-only transport must count redirects and stop all later sends."""
import asyncio

import httpx
import pytest

from app.services.search_budget import BudgetedClient, SearchBudget, SearchBudgetExceeded


def test_redirect_hops_use_the_shared_request_cap():
    async def run():
        calls = []
        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(302, headers={"location": "/again"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            budget = SearchBudget(10)
            bounded = BudgetedClient(client, budget, "reviews")
            with pytest.raises(SearchBudgetExceeded):
                await bounded.get("https://duckduckgo.com/html/")
            assert len(calls) == budget.used == 8
            with pytest.raises(SearchBudgetExceeded):
                await bounded.get("https://duckduckgo.com/html/")
            assert len(calls) == 8
    asyncio.run(run())


def test_hours_reservation_and_global_cap():
    async def run():
        calls = []
        def handler(request):
            calls.append(request.url)
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            budget = SearchBudget(10, need_hours=True)
            reviews = BudgetedClient(client, budget, "reviews")
            hours = BudgetedClient(client, budget, "hours")
            for _ in range(6):
                await reviews.get("https://example.com/search")
            with pytest.raises(SearchBudgetExceeded):
                await reviews.get("https://example.com/search")
            for _ in range(2):
                await hours.get("https://example.com/search")
            with pytest.raises(SearchBudgetExceeded):
                await hours.get("https://example.com/search")
            assert len(calls) == 8
    asyncio.run(run())


def test_redirect_does_not_forward_provider_auth_to_another_origin():
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={"location": "https://other.example/search"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            bounded = BudgetedClient(client, SearchBudget(10), "reviews")
            response = await bounded.get("https://provider.example/search", headers={"Authorization": "KakaoAK synthetic"})
            assert response.status_code == 302
            assert len(calls) == 1
    asyncio.run(run())


def test_transport_is_cancelled_at_deadline_and_cannot_restart():
    async def run():
        cancelled = False
        calls = []
        async def handler(request):
            nonlocal cancelled
            calls.append(request)
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled = True
                raise
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            budget = SearchBudget(0.03)
            bounded = BudgetedClient(client, budget, "reviews")
            with pytest.raises(asyncio.TimeoutError):
                await bounded.get("https://example.com/search")
            assert cancelled
            with pytest.raises(SearchBudgetExceeded):
                await bounded.get("https://example.com/search")
            assert len(calls) == 1
    asyncio.run(run())


def test_known_ddg_html_redirect_is_counted_and_followed():
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            if request.url.host == "duckduckgo.com":
                return httpx.Response(302, headers={"location": "https://html.duckduckgo.com/html/"})
            return httpx.Response(200)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            budget = SearchBudget(10)
            response = await BudgetedClient(client, budget, "reviews").get("https://duckduckgo.com/html/")
            assert response.status_code == 200
            assert len(calls) == budget.used == 2
    asyncio.run(run())
