"""FastAPI application entrypoint.

Run with:

    conda activate tpo_etl
    uvicorn app.main:app --reload

The root path returns the onboarding HTML (`templates/yiedla_ambience.html`).
Static assets live under `/static`.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .routers import analyse, health
from .services import trade_area_service
from .utils.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(
    title="Yielda Ambience Profiling API",
    version=__version__,
    description=(
        "End-to-end pipeline: 사업자번호 → 국세청 → bizno(상호명) → Kakao(업종·주소·좌표) "
        "→ 상권 → Google Places(리뷰·영업시간) → 기상청 → LLM → TPO/Ambience → 음원 추천"
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")
templates = Jinja2Templates(directory=str(settings.templates_dir))

app.include_router(health.router, tags=["health"])
app.include_router(analyse.router, tags=["analyse"])


@app.on_event("startup")
async def _startup() -> None:
    logger.info("Yielda backend startup — version %s", __version__)
    logger.info("Mock mode: %s", settings.effective_mock_mode())
    logger.info("DATA_GO_KR key: %s", settings.mask(settings.data_go_kr_api_key))
    logger.info("KAKAO key: %s", settings.mask(settings.kakao_rest_api_key))
    logger.info("BIZNO key: %s", settings.mask(settings.bizno_api_key))
    logger.info("GOOGLE_MAPS key: %s (하이브리드 상위 경로, 일별 상한 %d)",
                settings.mask(settings.google_maps_api_key), settings.places_daily_cap)
    logger.info("OPENAI key: %s", settings.mask(settings.openai_api_key))
    logger.info("KMA key: %s", settings.mask(settings.kma_api_key))

    # Warm up the trade-area lookup at startup so the first request is fast.
    try:
        trade_area_service.get_trade_area_service().load()
    except Exception as exc:  # pragma: no cover
        logger.exception("Failed to preload trade-area dataset: %s", exc)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """엠금융 전달용 시연 화면 (모바일 우선 · 태블릿/데스크톱 반응형)."""
    return templates.TemplateResponse(request, "demo.html")


@app.get("/legacy", response_class=HTMLResponse)
async def legacy(request: Request) -> HTMLResponse:
    """이전 온보딩 UI. 회귀 비교용으로만 남겨 둔다."""
    return templates.TemplateResponse(request, "yiedla_ambience.html")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):  # pragma: no cover
    # 예외 문자열을 그대로 돌려주지 않는다. httpx 예외 메시지에는 요청 URL이 들어가고,
    # data.go.kr·bizno·Google Geocode 는 인증키를 쿼리 파라미터로 받으므로 그대로
    # 노출하면 키가 브라우저까지 간다. 상세는 서버 로그에만 남긴다(로그도 마스킹됨).
    #
    # Never echo the exception back. httpx error messages embed the request URL, and
    # three of our upstreams authenticate via query parameter — so echoing would put a
    # credential in the browser. Details stay in the (redacted) server log.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"success": False,
                 "error": "서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."},
    )
