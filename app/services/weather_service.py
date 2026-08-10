"""KMA (기상청) current-weather helper.

Uses the 초단기실황(getUltraSrtNcst) endpoint from data.go.kr. Converts
a lat/lng to the KMA nx/ny grid via the standard LCC projection used by
the service.

The condition string is mapped to one of the buckets expected by
`ambience_service.WEATHER_PRIORS`:

    sunny | cloudy | rainy | snowy | hot_humid | cold_clear
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..schemas import Weather
from ..utils import http as shared_http
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9))

# KMA Lambert conformal conic projection parameters (v1.0)
_RE = 6371.00877
_GRID = 5.0
_SLAT1 = 30.0
_SLAT2 = 60.0
_OLON = 126.0
_OLAT = 38.0
_XO = 43
_YO = 136
_DEGRAD = math.pi / 180.0


def lat_lng_to_grid(lat: float, lng: float) -> Dict[str, int]:
    re_ = _RE / _GRID
    slat1 = _SLAT1 * _DEGRAD
    slat2 = _SLAT2 * _DEGRAD
    olon = _OLON * _DEGRAD
    olat = _OLAT * _DEGRAD

    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5)
    sf = (sf ** sn) * math.cos(slat1) / sn
    ro = math.tan(math.pi * 0.25 + olat * 0.5)
    ro = re_ * sf / (ro ** sn)

    ra = math.tan(math.pi * 0.25 + lat * _DEGRAD * 0.5)
    ra = re_ * sf / (ra ** sn)
    theta = lng * _DEGRAD - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn

    nx = int(ra * math.sin(theta) + _XO + 0.5)
    ny = int(ro - ra * math.cos(theta) + _YO + 0.5)
    return {"nx": nx, "ny": ny}


def _nearest_ncst_timeslot(now: Optional[datetime] = None) -> Dict[str, str]:
    now = (now or datetime.now(KST)).astimezone(KST)
    # 초단기실황 is published every hour on the hour (available ~:40 after).
    if now.minute < 40:
        now = now - timedelta(hours=1)
    return {"base_date": now.strftime("%Y%m%d"), "base_time": now.strftime("%H00")}


def _classify(temp: float, precip: float, rn_type: str) -> str:
    if rn_type in {"1", "2", "4", "5"}:
        return "rainy"
    if rn_type in {"3", "6", "7"}:
        return "snowy"
    if temp is not None:
        if temp >= 28:
            return "hot_humid"
        if temp <= 2:
            return "cold_clear"
    if precip and precip > 0:
        return "rainy"
    return "cloudy"


def _summarise(condition: str, temp: Optional[float]) -> str:
    label = {
        "sunny": "맑음",
        "cloudy": "흐림",
        "rainy": "비",
        "snowy": "눈",
        "hot_humid": "무더움",
        "cold_clear": "맑고 추움",
    }.get(condition, condition)
    if temp is None:
        return label
    return f"{label} · {temp:.1f}℃"


async def _fetch(client: httpx.AsyncClient, base_date: str, base_time: str, nx: int, ny: int) -> Optional[dict]:
    settings = get_settings()
    params = {
        "serviceKey": settings.kma_api_key,
        "dataType": "JSON",
        "numOfRows": 20,
        "pageNo": 1,
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }
    async for attempt in AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=6),
        retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
    ):
        with attempt:
            resp = await client.get(settings.kma_ultra_ncst_url, params=params, timeout=20)
    if resp.status_code != 200:
        logger.warning("KMA status %s: %s", resp.status_code, resp.text[:200])
        return None
    try:
        return resp.json()
    except Exception:
        logger.warning("KMA non-JSON response: %s", resp.text[:200])
        return None


async def fetch_weather(location: Optional[Dict[str, float]]) -> Weather:
    settings = get_settings()
    cache = get_cache("weather")

    if not location or location.get("lat") is None or location.get("lng") is None:
        return _mock_weather(reason="no-location")

    ck = f"{location['lat']:.3f},{location['lng']:.3f}"
    if ck in cache:
        return cache[ck]

    if settings.effective_mock_mode() or not settings.kma_api_key:
        w = _mock_weather(reason="mock")
        cache[ck] = w
        return w

    grid = lat_lng_to_grid(location["lat"], location["lng"])
    slot = _nearest_ncst_timeslot()
    try:
        payload = await _fetch(shared_http.get_client(), slot["base_date"],
                               slot["base_time"], grid["nx"], grid["ny"])
    except Exception as exc:
        logger.exception("KMA fetch failed: %s", exc)
        payload = None

    if not payload:
        w = _mock_weather(reason="kma-error")
        cache[ck] = w
        return w

    items = ((payload.get("response") or {}).get("body") or {}).get("items") or {}
    rows = items.get("item") or []
    readings = {r.get("category"): r.get("obsrValue") for r in rows}

    def _f(key: str) -> Optional[float]:
        v = readings.get(key)
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    temp = _f("T1H")
    rn1 = _f("RN1") or 0.0
    reh = _f("REH")
    pty = str(readings.get("PTY") or "0")

    condition = _classify(temp or 0.0, rn1, pty)
    w = Weather(
        summary=_summarise(condition, temp),
        temperature_c=temp,
        condition=condition,
        precipitation_mm=rn1,
        humidity=reh,
        source_time=f"{slot['base_date']} {slot['base_time']}",
    )
    cache[ck] = w
    return w


def _mock_weather(reason: str = "mock") -> Weather:
    return Weather(
        summary="흐림 · 18.4℃",
        temperature_c=18.4,
        condition="cloudy",
        precipitation_mm=0.0,
        humidity=62.0,
        source_time=datetime.now(KST).strftime("%Y%m%d %H00") + f" (mock:{reason})",
    )
