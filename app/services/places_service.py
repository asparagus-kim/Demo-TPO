"""Google Places (New) + Geocoding API integration.

Flow:
    1. `places:searchText` with "{company_name} {address}"
    2. `places/{id}` for detailed fields (reviews, hours, rating, types, lat/lng)

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..schemas import GooglePlaces, PlaceReview
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

_PLACE_DETAIL_FIELDS = ",".join([
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "rating",
    "userRatingCount",
    "regularOpeningHours",
    "currentOpeningHours",
    "types",
    "reviews",
])

_SEARCH_FIELDS = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.types",
    "places.rating",
    "places.userRatingCount",
])


def _cache_key(company: str, address: str) -> str:
    raw = f"{company}|{address}".strip().lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 일별 호출 상한
#
# Places API (New)는 콘솔에서 할당량을 **아래로 낮출 수 없다**
# (2026-08-05 확인: '조정 가능 여부' 전 행 '아니요', SearchTextRequest per day = 75,000).
# 무료 한도는 SKU별 월 1,000건이라 콘솔 할당량은 방어선이 되지 못하고,
# 예산 알림은 사후 통보인데 마침 비용 데이터 지연 이슈까지 진행 중이었다.
# 그래서 호출 수를 앱에서 직접 세고 상한에 닿으면 **호출을 멈추되 분석은 계속**한다
# (Kakao + 웹검색으로 degrade). 실패시키면 D2D 현장에서 화면이 깨진다.

_call_log: Dict[str, int] = {}


def _today_key() -> str:
    from datetime import date
    return date.today().isoformat()


def calls_today() -> int:
    return _call_log.get(_today_key(), 0)


def _record_calls(n: int = 1) -> None:
    k = _today_key()
    _call_log[k] = _call_log.get(k, 0) + n
    # 날짜가 바뀌면 과거 키는 필요 없다.
    for old in [d for d in _call_log if d != k]:
        _call_log.pop(old, None)


def reset_call_log() -> None:
    """테스트용."""
    _call_log.clear()


def availability() -> tuple[bool, str]:
    """Google Places를 지금 쓸 수 있는지. (사용가능, 사유)"""
    settings = get_settings()
    if settings.effective_mock_mode():
        return False, "mock_mode"
    if not settings.google_maps_api_key:
        return False, "no_key"
    cap = settings.places_daily_cap
    if cap > 0 and calls_today() >= cap:
        return False, "daily_cap"
    return True, "ok"


SKIP_REASON_TEXT = {
    "mock_mode": "",
    "no_key": "Google 키가 없어 리뷰·영업시간은 웹 검색으로 대체했습니다.",
    "daily_cap": "무료 한도 보호를 위해 Google 호출을 중단하고 웹 검색으로 대체했습니다.",
}


async def _retrying_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    async for attempt in AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=6),
        retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
    ):
        with attempt:
            resp = await client.request(method, url, timeout=20, **kwargs)
            return resp
    raise RuntimeError("unreachable")


async def _text_search(client: httpx.AsyncClient, query: str, api_key: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _SEARCH_FIELDS,
    }
    payload = {"textQuery": query, "languageCode": "ko", "regionCode": "KR"}
    try:
        resp = await _retrying_request(
            client, "POST", settings.text_search_url, headers=headers, json=payload,
        )
    except Exception as exc:
        logger.warning("Places text search failed: %s", exc)
        return None
    if resp.status_code != 200:
        logger.warning("Places text search %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json() or {}
    places = data.get("places") or []
    return places[0] if places else None


async def _place_details(client: httpx.AsyncClient, place_id: str, api_key: str) -> Optional[Dict[str, Any]]:
    settings = get_settings()
    url = settings.place_details_url.format(place_resource=f"places/{place_id}")
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _PLACE_DETAIL_FIELDS,
    }
    try:
        resp = await _retrying_request(client, "GET", url, headers=headers, params={"languageCode": "ko"})
    except Exception as exc:
        logger.warning("Places detail failed: %s", exc)
        return None
    if resp.status_code != 200:
        logger.warning("Places detail %s: %s", resp.status_code, resp.text[:200])
        return None
    return resp.json()


def _review_limit(cap: int) -> int:
    """LLM에 넘길 리뷰 상한.

    참고 — Places API (New)는 `reviews` 필드로 **매장당 최대 5건**만 반환한다
    (2026-08-05 실측: 리뷰수 1,686건인 매장도 본문은 5건). 킥오프 문서가 전제한
    "리뷰 25건"은 성립하지 않으므로, 텍스트 근거가 얇아지는 만큼 웹검색 보강이
    예외 경로가 아니라 상시 경로가 된다.
    """
    return max(5, min(cap, 40))


def _convert_place(details: Dict[str, Any], cap: int) -> GooglePlaces:
    name = (details.get("displayName") or {}).get("text") or ""
    hours = []
    hours_src = details.get("currentOpeningHours") or details.get("regularOpeningHours") or {}
    for desc in hours_src.get("weekdayDescriptions") or []:
        hours.append(desc)

    reviews: List[PlaceReview] = []
    for rv in (details.get("reviews") or [])[: _review_limit(cap)]:
        text_obj = rv.get("text") or {}
        author_obj = rv.get("authorAttribution") or {}
        reviews.append(PlaceReview(
            author=author_obj.get("displayName"),
            rating=rv.get("rating"),
            text=text_obj.get("text") or text_obj.get("originalText") or "",
            language=text_obj.get("languageCode"),
            relative_time=rv.get("relativePublishTimeDescription"),
            publish_time=rv.get("publishTime"),
        ))

    loc = details.get("location") or {}
    return GooglePlaces(
        place_id=details.get("id"),
        place_name=name,
        formatted_address=details.get("formattedAddress"),
        business_hours=hours,
        rating=details.get("rating"),
        review_count=details.get("userRatingCount"),
        reviews=reviews,
        place_types=details.get("types") or [],
        location={"lat": loc.get("latitude"), "lng": loc.get("longitude")} if loc else None,
    )


async def lookup_place(company_name: str, address: str) -> GooglePlaces:
    """Google Places에서 리뷰·영업시간을 가져온다.

    하이브리드 구조에서 Google의 역할은 **리뷰와 영업시간뿐**이다. 업종·주소·좌표는
    Kakao가 canonical이므로(`kakao_local_service`) 여기서 온 주소는 검증용으로만 쓴다.

    키가 없거나 일별 상한에 닿으면 빈 결과를 돌려주고 호출자가 웹검색으로 degrade한다.
    """
    settings = get_settings()
    cache = get_cache("places")
    ck = _cache_key(company_name, address)
    if ck in cache:
        # 캐시 히트는 호출로 세지 않는다 — 실제 과금이 없다.
        return cache[ck]

    if settings.effective_mock_mode():
        places = _mock_place(company_name, address)
        cache[ck] = places
        return places

    ok, reason = availability()
    if not ok:
        logger.info("Places 건너뜀 (%s, 오늘 호출 %d/%d)",
                    reason, calls_today(), settings.places_daily_cap)
        return GooglePlaces(place_name=None, formatted_address=None)

    query = f"{company_name} {address}".strip()
    async with httpx.AsyncClient() as client:
        _record_calls(1)                      # Text Search 1건
        hit = await _text_search(client, query, settings.google_maps_api_key)
        if not hit:
            logger.info("No Places hit for %s", query)
            empty = GooglePlaces(place_name=company_name, formatted_address=address)
            cache[ck] = empty
            return empty

        place_id = hit.get("id")
        details = None
        if place_id:
            _record_calls(1)                  # Place Details 1건
            details = await _place_details(client, place_id, settings.google_maps_api_key)
        if not details:
            details = hit
        places = _convert_place(details, settings.llm_review_cap)
    logger.info("Places 조회 완료 '%s' (리뷰 %d건, 영업시간 %d일, 오늘 호출 %d)",
                places.place_name, len(places.reviews), len(places.business_hours), calls_today())
    cache[ck] = places
    return places


async def geocode(address: str) -> Optional[Dict[str, float]]:
    settings = get_settings()
    if settings.effective_mock_mode() or not settings.google_maps_api_key:
        return {"lat": 37.5665, "lng": 126.9780}
    async with httpx.AsyncClient() as client:
        try:
            resp = await _retrying_request(
                client, "GET", settings.geocode_url,
                params={"address": address, "key": settings.google_maps_api_key, "language": "ko"},
            )
        except Exception as exc:
            logger.warning("Geocode failed: %s", exc)
            return None
    if resp.status_code != 200:
        logger.warning("Geocode %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json() or {}
    results = data.get("results") or []
    if not results:
        return None
    loc = results[0].get("geometry", {}).get("location") or {}
    return {"lat": loc.get("lat"), "lng": loc.get("lng")}


def _mock_place(company_name: str, address: str) -> GooglePlaces:
    reviews = [
        "점심시간마다 붐비지만 회전이 빨라 테이크아웃이 편합니다.",
        "오피스 사이에 위치해 업무 미팅하러 자주 들러요.",
        "바리스타가 친절하고 분위기가 아늑해서 좋아요.",
        "자리가 넓지 않지만 커피 맛이 좋아 재방문 의사 있음.",
        "혼자 공부하기 좋고 콘센트가 충분합니다.",
        "비 오는 날 창가 자리가 특히 무드 있어요.",
        "샷 추가 취향 맞춰줘서 고마웠어요. 빠른 서비스.",
        "친구랑 수다 떨기 좋고 디저트도 맛있어요.",
        "저녁에는 한산해서 조용히 책 읽기 좋음.",
        "직장인 점심 피크엔 자리 잡기 어려움.",
        "아침 오픈 시간에 모닝커피 마시러 자주 옵니다.",
        "테이블 회전 빠르고 직원들이 에너지 넘치네요.",
    ]
    parsed_reviews = [
        PlaceReview(author=f"user{i+1}", rating=4.0 + (i % 3) * 0.3, text=t, language="ko",
                    relative_time=f"{(i % 4) + 1}주 전")
        for i, t in enumerate(reviews)
    ]
    return GooglePlaces(
        place_id="mock-place-id-0001",
        place_name=company_name or "샘플카페 강남점",
        formatted_address=address or "서울특별시 강남구 역삼동",
        business_hours=[
            "월요일: 07:00 – 22:00",
            "화요일: 07:00 – 22:00",
            "수요일: 07:00 – 22:00",
            "목요일: 07:00 – 22:00",
            "금요일: 07:00 – 23:00",
            "토요일: 10:00 – 23:00",
            "일요일: 10:00 – 21:00",
        ],
        rating=4.3,
        review_count=3214,
        reviews=parsed_reviews,
        place_types=["cafe", "food", "point_of_interest"],
        location={"lat": 37.5006, "lng": 127.0363},
    )


def dump_place_debug(place: GooglePlaces, tag: str) -> None:
    settings = get_settings()
    debug_dir = settings.cache_dir / "places"
    debug_dir.mkdir(parents=True, exist_ok=True)
    try:
        (debug_dir / f"{tag}.json").write_text(
            json.dumps(place.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8",
        )
    except OSError:
        pass
