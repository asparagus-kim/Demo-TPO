"""분석 수집(Analysis Data Collection) — 결과 1건을 Google Sheet 한 행으로 적재한다.

목적: 사용자가 분석을 돌릴 때마다 **입력값 + 분석 결과 전체**를 기획·운영이
시트에서 검수할 수 있게 남긴다. 서버도 DB도 새로 두지 않는다 — Apps Script
웹앱(`doPost`)이 시트에 append 하고, 같은 스크립트의 `doGet`이 다시 읽어 준다.
스크립트 원본과 배포 절차는 `scripts/apps_script/` 참고.

## 설계 규칙

1. **파이프라인을 절대 실패시키지 않는다.** 전송은 fire-and-forget 이고 모든
   예외를 삼킨다. 시트가 죽어도 분석 응답은 그대로 나간다.
2. **열은 여기 한 곳에서만 정의한다** (`COLUMNS`). 기획이 열을 확정하면
   이 튜플과 `build_row()` 만 고치면 되고 라우터는 건드리지 않는다.
3. **행은 평평(flat)해야 한다.** 시트 셀에 dict/list 를 넣을 수 없으므로
   리스트는 ' · ' 로 접고, 소수는 자리수를 고정한다.
4. **웹훅 URL은 자격증명이다.** 이 URL을 아는 사람은 누구나 시트에 행을 쓸 수
   있다. 로그·응답에 절대 싣지 않는다(`app/utils/logging.py` 가 값도 스크럽한다).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from ..config import get_settings
from ..schemas import AnalyseRequest, AnalyseResponse
from ..utils.http import get_client
from ..utils.logging import get_logger

logger = get_logger(__name__)

KST = timezone(timedelta(hours=9), "KST")

# 셀 안에서 리스트를 접을 때 쓰는 구분자. 쉼표는 업종명·주소에 이미 들어 있어
# 시트에서 눈으로 나눌 때 헷갈린다.
JOIN = " · "

# ---------------------------------------------------------------------------
# 열 정의 — 기획이 확정하는 단일 지점.
# 순서가 곧 시트 헤더 순서다. Apps Script 는 이 순서를 그대로 신뢰한다.
# ---------------------------------------------------------------------------
COLUMNS: tuple[str, ...] = (
    # -- 메타
    "timestamp",             # KST ISO8601 (수집 시각)
    "outcome",               # success | closed | suspended | needs_input | error
    "client",                # 요청 출처 (web | legacy | api)
    # -- 입력값
    "biz_no",                # 사용자가 입력한 사업자등록번호 (하이픈 포함 정규화)
    "input_company_name",    # 사용자가 직접 입력한 상호명 (2단계 플로우)
    "input_address_hint",    # 사용자가 입력한 지역 힌트
    "input_place_id",        # 사용자가 고른 Kakao 후보
    # -- 매장 신원
    "nts_status",            # 국세청 사업 상태
    "store_name",
    "category",              # Kakao 업종 말단 토큰
    "category_full",         # Kakao category_name 전체 경로
    "address",               # 도로명
    "region_address",        # 지번(행정동 포함)
    "phone",
    "lat",
    "lng",
    "kakao_place_id",
    "kakao_place_url",
    # -- 상권
    "district_type",         # trade_area.label
    "district_method",       # surroundings | fallback | ...
    "district_confidence",
    "district_density",
    "district_total_places",
    "district_cafe_pct",
    "district_food_pct",
    "district_bank_pct",
    "district_edu_pct",
    "district_univ_count",
    "district_criteria",     # 판정 기준 트레이스 (사람이 읽는 요약)
    # -- 외부 신호
    "hours",
    "hours_source",          # google | web | none
    "weather",
    "weather_temp_c",
    "weather_condition",
    "rating",
    "review_count",
    "reviews_analyzed",
    "review_keywords",       # "웨이팅(4) · 분위기(3) ..."
    "text_source",           # google_reviews | web_search | mixed | none
    "web_evidence_count",
    "consistency",           # 동일 업체 검증 통과 여부
    "consistency_score",
    # -- 분석 결과
    "energy",
    "tempo",
    "mood",
    "ambience_confidence",
    "tpo_time",
    "tpo_place",
    "tpo_occasion",
    # -- 추천
    "playlist_label",
    "playlist_track_count",
    "industry_matched",
    "music_pool_size",
    "top_tracks",            # 상위 3곡 제목
    # -- 운영 진단
    "duration_ms",
    "cache_hit",
    "mock_mode",
    "prompt_version",
    "error",
)


def now_kst() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# 평탄화 헬퍼
# ---------------------------------------------------------------------------
def _num(value: Any, digits: int = 2) -> Any:
    """소수를 고정 자리수로 줄인다. None 은 빈 셀로 남긴다."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def _join(items: Optional[List[Any]], limit: Optional[int] = None) -> str:
    if not items:
        return ""
    values = [str(i).strip() for i in items if str(i).strip()]
    if limit is not None:
        values = values[:limit]
    return JOIN.join(values)


def _criteria_text(criteria: List[Any]) -> str:
    """판정 기준 트레이스를 한 셀에 담는다. 결정타에는 ◀ 를 붙인다."""
    parts = []
    for c in criteria or []:
        mark = "◀" if getattr(c, "decided", False) else ("✓" if getattr(c, "met", False) else "·")
        parts.append(f"{mark} {c.indicator} {c.value}/{c.threshold}→{c.label}")
    return _join(parts)


def build_row(
    response: AnalyseResponse,
    *,
    request: Optional[AnalyseRequest] = None,
    outcome: str = "success",
    client: str = "api",
    duration_ms: Optional[int] = None,
    cache_hit: bool = False,
) -> Dict[str, Any]:
    """`AnalyseResponse` 를 시트 한 행(열 이름 → 값)으로 평탄화한다.

    실패/`needs_input` 응답도 그대로 받는다 — 비어 있는 하위 객체는 기본값이라
    빈 셀이 될 뿐 예외가 나지 않는다.
    """
    info = response.business_info
    place = response.resolved_place
    ta = response.trade_area
    sur = ta.surroundings
    gp = response.google_places
    weather = response.weather
    tpo = response.tpo_profile
    amb = response.ambience
    prov = response.evidence_provenance
    music = response.music
    debug = response.debug or {}
    loc = (place.location if place else None) or gp.location or {}

    return {
        "timestamp": now_kst(),
        "outcome": outcome,
        "client": client,
        "biz_no": response.business_number,
        "input_company_name": (request.company_name if request else "") or "",
        "input_address_hint": (request.address_hint if request else "") or "",
        "input_place_id": (request.place_id if request else "") or "",
        "nts_status": response.nts_status,
        "store_name": info.company_name or (place.place_name if place else ""),
        "category": info.business_type,
        "category_full": place.category_name if place else "",
        "address": info.address,
        "region_address": place.region_address if place else "",
        "phone": place.phone if place else "",
        "lat": _num(loc.get("lat"), 6),
        "lng": _num(loc.get("lng"), 6),
        "kakao_place_id": place.place_id if place else "",
        "kakao_place_url": place.place_url if place else "",
        "district_type": ta.label,
        "district_method": ta.match_method,
        "district_confidence": _num(ta.confidence),
        "district_density": sur.density if sur else "",
        "district_total_places": sur.total if sur else "",
        "district_cafe_pct": _num(sur.cafe_pct, 1) if sur else "",
        "district_food_pct": _num(sur.food_pct, 1) if sur else "",
        "district_bank_pct": _num(sur.bank_pct, 1) if sur else "",
        "district_edu_pct": _num(sur.edu_pct, 1) if sur else "",
        "district_univ_count": sur.univ_count if sur else "",
        "district_criteria": _criteria_text(ta.criteria),
        "hours": _join(gp.business_hours),
        "hours_source": debug.get("hours_source", ""),
        "weather": weather.summary,
        "weather_temp_c": _num(weather.temperature_c, 1),
        "weather_condition": weather.condition,
        "rating": _num(gp.rating, 1),
        "review_count": gp.review_count if gp.review_count is not None else "",
        "reviews_analyzed": prov.reviews_analyzed,
        "review_keywords": _join([f"{k.keyword}({k.count})" for k in prov.review_keywords]),
        "text_source": prov.text_source,
        "web_evidence_count": prov.web_evidence_count,
        "consistency": response.entity_validation.is_consistent,
        "consistency_score": _num(response.entity_validation.score),
        "energy": amb.energy,
        "tempo": amb.tempo,
        "mood": amb.mood,
        "ambience_confidence": _num(amb.confidence),
        "tpo_time": tpo.time_label,
        "tpo_place": tpo.place_label,
        "tpo_occasion": tpo.occasion_label,
        "playlist_label": music.playlist_label,
        "playlist_track_count": len(music.tracks),
        "industry_matched": music.industry_matched,
        "music_pool_size": music.pool_size,
        "top_tracks": _join([t.title_ko or t.title for t in music.tracks], limit=3),
        "duration_ms": duration_ms if duration_ms is not None else "",
        "cache_hit": cache_hit,
        "mock_mode": bool(debug.get("mock_mode", False)),
        "prompt_version": debug.get("llm_prompt_version", ""),
        "error": response.error or "",
    }


# ---------------------------------------------------------------------------
# 전송
# ---------------------------------------------------------------------------
# create_task 로 띄운 태스크는 참조가 없으면 GC 가 중간에 회수할 수 있다.
_pending: Set[asyncio.Task] = set()

# 읽기 재시도 — 대시보드가 빈 화면으로 뜨는 것을 막는다. 쓰기는 fire-and-forget
# 이라 재시도하지 않는다(중복 행이 생기는 편이 더 나쁘다).
READ_MAX_ATTEMPTS = 3
READ_RETRY_SEC = 1.0


def enabled() -> bool:
    settings = get_settings()
    return bool(settings.sheets_webhook_url) and settings.sheets_logging_enabled


def should_log(outcome: str, *, cache_hit: bool = False) -> bool:
    """어떤 종류의 결과를 시트에 남길지 — 정책은 라우터가 아니라 여기 있다.

    `needs_input` 은 사용자가 매장을 고르는 **중간 단계**라 기본으로 끈다.
    켜면 분석 한 건이 2행 이상을 만든다.
    """
    if not enabled():
        return False
    settings = get_settings()
    if outcome == "needs_input" and not settings.sheets_log_needs_input:
        return False
    if cache_hit and not settings.sheets_log_cache_hits:
        return False
    return True


async def send_row(row: Dict[str, Any]) -> bool:
    """행 1건을 Apps Script 웹앱에 POST 한다. 성공 여부를 돌려주고 예외는 삼킨다.

    Apps Script 웹앱은 POST 에 302 로 응답한 뒤 `script.googleusercontent.com`
    으로 넘기므로 리다이렉트를 따라가야 한다.
    """
    settings = get_settings()
    if not settings.sheets_webhook_url:
        return False
    try:
        resp = await get_client().post(
            settings.sheets_webhook_url,
            json={
                "token": settings.sheets_webhook_token,
                "columns": list(COLUMNS),
                "row": row,
            },
            timeout=settings.sheets_timeout_sec,
            follow_redirects=True,
        )
        if resp.status_code >= 400:
            # 본문은 Apps Script 의 HTML 오류 페이지일 수 있다 — 상태 코드만 남긴다.
            logger.warning("sheets webhook responded %s", resp.status_code)
            return False
        return True
    except Exception as exc:  # pragma: no cover - 네트워크 예외는 삼킨다
        logger.warning("sheets webhook failed: %s", type(exc).__name__)
        return False


def log_analysis(
    response: AnalyseResponse,
    *,
    request: Optional[AnalyseRequest] = None,
    outcome: str = "success",
    client: str = "api",
    duration_ms: Optional[int] = None,
    cache_hit: bool = False,
) -> None:
    """분석 1건을 시트에 적재한다 — **호출자를 절대 블록하지 않는다**.

    행 조립까지도 예외를 삼킨다. 수집 기능의 버그가 분석 응답을 깨면 안 된다.
    """
    if not should_log(outcome, cache_hit=cache_hit):
        return

    # 코루틴을 만들기 **전에** 루프를 확인한다. 먼저 만들면 스케줄에 실패했을 때
    # "coroutine was never awaited" 경고가 남는다.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 이벤트 루프 밖(동기 컨텍스트)에서 불린 경우 — 조용히 건너뛴다.
        return

    try:
        row = build_row(
            response,
            request=request,
            outcome=outcome,
            client=client,
            duration_ms=duration_ms,
            cache_hit=cache_hit,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("sheets row build failed: %s", type(exc).__name__)
        return

    task = asyncio.create_task(send_row(row))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def drain(timeout: float = 5.0) -> None:
    """진행 중인 전송을 기다린다 (앱 종료 훅·테스트용)."""
    if not _pending:
        return
    await asyncio.wait(set(_pending), timeout=timeout)


# ---------------------------------------------------------------------------
# 읽기 (수집 대시보드용)
# ---------------------------------------------------------------------------
async def fetch_rows(limit: int = 200) -> Dict[str, Any]:
    """같은 Apps Script 의 `doGet` 으로 최근 행을 되읽는다.

    프론트가 직접 부르지 않고 백엔드가 프록시하는 이유: 웹훅 URL·토큰이
    번들에 박히면 누구나 시트에 쓸 수 있고, Apps Script 는 CORS 프리플라이트도
    받지 않는다.
    """
    settings = get_settings()
    if not settings.sheets_webhook_url:
        return {"columns": list(COLUMNS), "rows": [], "available": False}

    # Apps Script 는 302 로 script.googleusercontent.com 에 넘기므로 왕복이 두 번이다.
    # 로컬에선 2~4초지만 Render(싱가포르·무료 플랜)에서는 이를 넘겨 간헐적으로
    # 타임아웃이 났다 — 3번 중 2번 실패(2026-09-15 실측). 한 번 더 시도한다.
    data = None
    last_error = ""
    for attempt in range(READ_MAX_ATTEMPTS):
        try:
            resp = await get_client().get(
                settings.sheets_webhook_url,
                params={"token": settings.sheets_webhook_token, "limit": limit},
                timeout=settings.sheets_timeout_sec,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < READ_MAX_ATTEMPTS - 1:
                await asyncio.sleep(READ_RETRY_SEC)
    if data is None:
        logger.warning("sheets read failed after %d attempts: %s",
                       READ_MAX_ATTEMPTS, last_error)
        return {"columns": list(COLUMNS), "rows": [], "available": False}

    return {
        "columns": data.get("columns") or list(COLUMNS),
        "rows": data.get("rows") or [],
        "available": True,
    }
