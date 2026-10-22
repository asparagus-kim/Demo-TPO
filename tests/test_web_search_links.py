"""Search-result links must open the source instead of DuckDuckGo's tracker."""
import asyncio
from urllib.parse import quote

import httpx
import pytest

from app.services import web_search_service as W


TARGET = "https://blog.naver.com/PostView.nhn?blogId=sso_ii&logNo=222152065862"
BROKEN_LINK = f"https://duckduckgo.com/l/?uddg={quote(TARGET, safe='')}&amp;rut=tracker"


@pytest.mark.parametrize("link", [
    BROKEN_LINK,
    BROKEN_LINK.replace("https://", "//", 1),
    BROKEN_LINK.replace("duckduckgo.com", "html.duckduckgo.com"),
    TARGET.replace("&", "&amp;"),
])
def test_ddg_provider_returns_original_blog_url(monkeypatch, link):
    async def response(*args, **kwargs):
        return httpx.Response(200, text=(
            f'<a class="result__a" href="{link}">A blog review</a>'
            '<a class="result__snippet">A quiet cafe with comfortable seating.</a>'
        ))

    monkeypatch.setattr(W, "_retrying_get", response)
    items = asyncio.run(W._duckduckgo_search(None, "cafe", 12))
    assert len(items) == 1
    assert items[0].url == TARGET
    assert items[0].source == "duckduckgo"


@pytest.mark.parametrize("link, expected", [
    ("https://example.com/review?q=a%26b%2Bc&lang=ko#review", "https://example.com/review?q=a%26b%2Bc&lang=ko#review"),
    (f"https://duckduckgo.com/l/?uddg={quote(BROKEN_LINK, safe='')}", TARGET),
    ("https://duckduckgo.com/l/?rut=tracker", None),
    ("https://duckduckgo.com/l/?uddg=javascript%3Aalert(1)", None),
    ("https://duckduckgo.com/l/?uddg=%2Frelative", None),
    ("javascript:alert(1)", None),
    ("https://[invalid", None),
    (None, None),
])
def test_result_url_boundaries(link, expected):
    assert W._normalize_result_url(link) == expected


@pytest.mark.parametrize("target", [
    "https://example.com/review?currency=USD&notional=100",
    "https://example.com/review?x=1&amp;literal=2",
    "https://example.com/review?q=a%26b%2Bc&lang=ko#review",
])
def test_extracted_destination_is_not_html_decoded_again(target):
    wrapped = f"https://duckduckgo.com/l/?uddg={quote(target, safe='')}&amp;rut=tracker"
    assert W._normalize_result_url(wrapped) == target


def test_ddg_result_without_snippet_does_not_borrow_next_snippet(monkeypatch):
    async def response(*args, **kwargs):
        return httpx.Response(200, text=(
            '<a class="result__a" href="https://example.com/directory">Directory</a>'
            f'<a class="result__a" href="{TARGET}">A blog review</a>'
            '<a class="result__snippet">A quiet cafe with comfortable seating.</a>'
        ))

    monkeypatch.setattr(W, "_retrying_get", response)
    items = asyncio.run(W._duckduckgo_search(None, "cafe", 12))
    assert [(i.url, i.text) for i in items] == [(TARGET, "A quiet cafe with comfortable seating.")]
