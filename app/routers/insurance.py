"""`GET /api/insurance/estimate` — licence-data estimate for the consult page.

Returns LOCALDATA facts for the analysed shop (matched by address + name) so
`insurance.html` can show an ESTIMATED insurance assessment for business
numbers outside the curated table. Read-only, no paid upstream, no personal
data: inputs are the store name and addresses the analysis already produced.

Per-IP rate limit: the endpoint is public (the page calls it from the browser),
so a cap keeps it from being used to page through the nationwide data.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..services import insurance_estimate_service as svc
from ..utils.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_MAX = 200                # longer inputs are not shop names or addresses
_RATE_LIMIT = 30          # requests …
_RATE_WINDOW_SEC = 60     # … per IP per minute — one consult page makes one call
_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    # Render terminates TLS in front of the app; the first X-Forwarded-For hop is the caller.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > _RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= _RATE_LIMIT:
        return True
    q.append(now)
    if len(_hits) > 10_000:          # bound memory: drop idle callers
        for key in [k for k, v in _hits.items() if not v or now - v[-1] > _RATE_WINDOW_SEC]:
            _hits.pop(key, None)
    return False


@router.get("/api/insurance/estimate")
async def insurance_estimate(
    request: Request,
    name: str = Query("", max_length=_MAX),
    place: str = Query("", max_length=_MAX),
    addr: str = Query("", max_length=_MAX),
    jibun: str = Query("", max_length=_MAX),
    gu: str = Query("", max_length=_MAX),
    reg: str = Query("", max_length=_MAX),
):
    if _rate_limited(_client_ip(request)):
        return JSONResponse(status_code=429, content={"status": "error", "message": "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요"})
    try:
        return await svc.estimate(name=name, place=place, addr=addr, jibun=jibun, gu=gu, reg=reg)
    except svc.EstimateUnavailable as exc:
        # Fixed message only — never echo connection strings or driver errors.
        logger.warning("insurance estimate unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"status": "error", "message": "추정 데이터를 사용할 수 없습니다"})
