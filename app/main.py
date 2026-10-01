"""FastAPI application entrypoint.

Run with:

    conda activate tpo_etl
    uvicorn app.main:app --reload

The root path returns the onboarding HTML (`templates/yiedla_ambience.html`).
Static assets live under `/static`.
"""
from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_settings
from .routers import analyse, health, insurance
from .services import insurance_estimate_service, kakao_local_service, llm_service, sheets_logger, trade_area_service
from .utils import http as shared_http
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
app.include_router(insurance.router, tags=["insurance"])


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

    # 업스트림 연결 예열 — 백그라운드로. 헬스체크나 첫 요청을 막지 않는다.
    #   1) Kakao 는 상권 집계가 동시 9건이라 연결 9개를 연다 (2~6초 → 0.07초)
    #   2) 나머지 호스트는 각 1개 — 새 인스턴스의 첫 분석이 콜드 TLS 를 전부 물어
    #      14~21초가 나오던 것을 없앤다 (실측: 30초 뒤 같은 코드 2.8초)
    app.state.warm_task = asyncio.create_task(_warm_upstreams())


async def _warm_upstreams() -> None:
    hosts = [
        settings.nts_api_url, settings.bizno_api_url, settings.kakao_keyword_url,
        settings.text_search_url, settings.geocode_url, settings.kma_ultra_ncst_url,
        settings.openai_base_url, settings.sheets_webhook_url,
    ]
    try:
        _, n, llm_ready = await asyncio.gather(
            kakao_local_service.warm_connection_pool(),
            shared_http.warm_hosts(hosts),
            llm_service.warm_llm_client(),   # SDK 자체 풀까지 데운다 — 공유 풀 예열로는 안 닿는다
        )
        logger.info("업스트림 예열 완료: 호스트 %d개 연결, LLM 풀 %s", n, "준비" if llm_ready else "실패")
    except Exception as exc:  # pragma: no cover - 예열 실패는 느려질 뿐 틀리지 않는다
        logger.warning("업스트림 예열 실패: %s", type(exc).__name__)


@app.on_event("shutdown")
async def _shutdown() -> None:
    # 수집 전송은 fire-and-forget 이라 종료 시점에 날아갈 수 있다. 잠깐만 기다린다.
    await sheets_logger.drain()
    # 공유 httpx 연결 풀을 정리한다. 남겨 두면 종료 시 "Unclosed client" 경고가 난다.
    await shared_http.aclose()
    # 보험 추정 (insurance estimate) DB 풀 — 열려 있지 않으면 아무것도 안 한다.
    await insurance_estimate_service.pool.close()


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
