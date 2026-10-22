"""One deadline and request counter for a search fallback, including redirects."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import urljoin, urlsplit

import httpx


class SearchBudgetExceeded(RuntimeError):
    """No additional search request may be sent."""


class SearchBudget:
    def __init__(self, seconds: float, *, need_hours: bool = False) -> None:
        self.deadline = time.monotonic() + max(0, seconds)
        self.used = 0
        self.review_used = 0
        self.review_limit = 6 if need_hours else 8
        self.stop_reason = ""

    @property
    def remaining(self) -> float:
        return max(0, self.deadline - time.monotonic())

    def consume(self, purpose: str) -> None:
        if self.remaining <= 0:
            self.stop_reason = "timeout"
        elif self.used >= 8:
            self.stop_reason = "request_cap"
        elif purpose == "reviews" and self.review_used >= self.review_limit:
            self.stop_reason = "review_request_cap"
        else:
            self.used += 1
            self.review_used += purpose == "reviews"
            return
        raise SearchBudgetExceeded(self.stop_reason)


class BudgetedClient:
    """Wrap only search requests; do not change the app's shared HTTP client."""
    def __init__(self, client: httpx.AsyncClient, budget: SearchBudget, purpose: str) -> None:
        self.client = client
        self.budget = budget
        self.purpose = purpose

    async def get(self, url: str, **kwargs) -> httpx.Response:
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        while True:
            self.budget.consume(self.purpose)
            remaining = self.budget.remaining
            try:
                response = await asyncio.wait_for(
                    self.client.get(url, follow_redirects=False, timeout=remaining, **kwargs),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                self.budget.stop_reason = "timeout"
                raise
            if response.status_code not in {301, 302, 303, 307, 308} or "location" not in response.headers:
                return response
            target = urljoin(str(response.url), response.headers["location"])
            source_parts, target_parts = urlsplit(str(response.url)), urlsplit(target)
            same_origin = (source_parts.scheme, source_parts.netloc) == (target_parts.scheme, target_parts.netloc)
            ddg_html = (
                source_parts.hostname in {"duckduckgo.com", "www.duckduckgo.com"}
                and target_parts.hostname == "html.duckduckgo.com"
                and target_parts.scheme == "https"
                and target_parts.port in {None, 443}
                and not (target_parts.username or target_parts.password)
                and not any(key.lower() == "authorization" for key in kwargs.get("headers", {}))
                and not kwargs.get("params")
            )
            if not same_origin and not ddg_html:
                return response
            # The Location header supplies the next query; never reattach an API key.
            kwargs.pop("params", None)
            url = target
