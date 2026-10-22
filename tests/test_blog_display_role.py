"""Blogs are always searched for display; they are scored only without Google reviews."""
from __future__ import annotations

import asyncio

import pytest

from app.routers import analyse as router_analyse
from app.schemas import AnalyseRequest, BizIdentity, GooglePlaces, PlaceCandidate, PlaceReview, Weather, WebEvidenceItem
from app.services import (
    biz_lookup_service,
    entity_validation_service,
    kakao_local_service,
    llm_service,
    nts_service,
    places_service,
    sheets_logger,
    weather_service,
    web_search_service,
)
from app.utils.cache import get_cache

BLOG = WebEvidenceItem(
    title="역삼동 별빛커피 방문", text="역삼동 별빛커피에 다녀왔어요. 조용하고 커피가 맛있어요.",
    url="https://blog.naver.com/reviewer/12345", source="naver_blog",
)
GOOGLE_REVIEWS = [
    PlaceReview(author="a", rating=5, text="분위기가 차분하고 커피가 정말 맛있어요."),
    PlaceReview(author="b", rating=5, text="좌석이 편하고 오래 머물기 좋은 카페입니다."),
]


def _score() -> llm_service.ReviewScore:
    return llm_service.ReviewScore(energy=0.3, tempo=0.3, mood=0.8, informativeness=0.9,
                                   occasion_labels=[], keywords=["차분"], evidence="test")


@pytest.fixture
def pipeline(monkeypatch):
    get_cache("analysis").clear()
    calls: dict = {"blog": []}

    async def nts(digits):
        return {"status_code": "01", "status_label": "계속사업자"}

    async def identity(digits, *, user_company_name=None, user_address=None):
        return BizIdentity(company_name="별빛커피", source="apick", confidence=1.0)

    async def candidates(name, *, address_hint=None, size=15):
        return [PlaceCandidate(place_id="1", place_name="별빛커피", business_type="카페",
                               category_name="음식점 > 카페", address="서울 강남구 테헤란로 1",
                               region_address="서울 강남구 역삼동 1", location={"lat": 37.5, "lng": 127.0},
                               score=1.0)]

    async def surroundings(location, own_code=""):
        return {"counts": {"CE7": 50, "FD6": 120}, "univ": 0, "radius": 500}

    async def weather(location):
        return Weather(condition="clear", summary="맑음")

    async def score(reviews, **kwargs):
        return [_score() for _ in reviews]

    async def blog_search(*args, need_hours, **kwargs):
        calls["blog"].append(need_hours)
        return [BLOG], []

    monkeypatch.setattr(nts_service, "lookup_status", nts)
    monkeypatch.setattr(biz_lookup_service, "resolve_identity", identity)
    monkeypatch.setattr(kakao_local_service, "search_candidates", candidates)
    monkeypatch.setattr(kakao_local_service, "surroundings", surroundings)
    monkeypatch.setattr(weather_service, "fetch_weather", weather)
    monkeypatch.setattr(llm_service, "score_reviews", score)
    monkeypatch.setattr(web_search_service, "collect_fallback_evidence", blog_search)
    monkeypatch.setattr(entity_validation_service, "validate_google_place_identity",
                        lambda *_: {"is_consistent": True, "score": 0.9})
    monkeypatch.setattr(sheets_logger, "log_analysis", lambda *args, **kwargs: None)

    def google(reviews, hours):
        async def lookup(company_name, address):
            return GooglePlaces(place_id="g", place_name="별빛커피", reviews=reviews, business_hours=hours)
        monkeypatch.setattr(places_service, "lookup_place", lookup)

    yield google, calls
    get_cache("analysis").clear()


def test_blogs_are_displayed_but_not_scored_when_google_reviews_exist(pipeline):
    google, calls = pipeline
    google(GOOGLE_REVIEWS, ["매일 09:00-22:00"])
    resp = asyncio.run(router_analyse.analyse(AnalyseRequest(business_number="1234567890")))
    assert resp.success
    assert [w.url for w in resp.web_evidence] == [BLOG.url]
    assert calls["blog"] == [False]
    assert resp.evidence_provenance.text_source == "google_reviews"
    assert resp.evidence_provenance.web_search_used is False
    assert resp.debug["reviews_used"] == len(GOOGLE_REVIEWS)
    assert resp.debug["blog_evidence_role"] == "display_only"


def test_blogs_stay_display_only_when_google_hours_are_missing(pipeline):
    google, calls = pipeline
    google(GOOGLE_REVIEWS, [])
    resp = asyncio.run(router_analyse.analyse(AnalyseRequest(business_number="1234567890")))
    assert calls["blog"] == [True]
    assert resp.evidence_provenance.text_source == "google_reviews"
    assert resp.debug["reviews_used"] == len(GOOGLE_REVIEWS)
    assert len(resp.web_evidence) == 1


def test_blogs_are_scored_as_fallback_without_google_reviews(pipeline):
    google, calls = pipeline
    google([], ["매일 09:00-22:00"])
    resp = asyncio.run(router_analyse.analyse(AnalyseRequest(business_number="1234567890")))
    assert calls["blog"] == [False]
    assert resp.evidence_provenance.text_source == "web_search"
    assert resp.debug["reviews_used"] == 1
    assert resp.debug["blog_evidence_role"] == "scored"
