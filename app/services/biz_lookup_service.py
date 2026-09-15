"""사업자번호 → 상호명. `moneypin_service`(Playwright 크롤링)의 대체 모듈.

## 왜 상호명만인가

무료 경로에서 사업자번호로 얻을 수 있는 것은 **상호명뿐**이다 (2026-08-05 실측).

    국세청 상태조회  → 계속/휴업/폐업만. 상호명은 입력 항목이지 출력 항목이 아니다
    bizno OPEN API   → 상호명 + 사업상태 + 과세유형. **업종·주소·좌표는 무료 플랜에 없음**
    NPS              → 사업장명 + 주소. 단 사업자번호 앞 6자리만 조회되고
                       수록 범위가 3인↑ 법인 / 10인↑ 개인사업장이라 소규모 매장은 대부분 없음

따라서 업종·주소·좌표는 상호명으로 Kakao를 검색해 얻는다(`kakao_local_service`).
이 모듈의 책임은 "사업자번호에서 신뢰할 수 있는 상호명을 뽑는 것"까지다.

## 체인

    0. 사용자가 상호명을 직접 입력했으면 그것으로 확정 (재요청 경로)
    1. bizno  (BIZNO_API_KEY 있을 때)
    2. 실패 → needs_user_input=True 로 돌려주고 호출자가 입력을 요청

NPS는 후순위(구현 순서 10번)라 아직 구현하지 않는다 — 활용신청도 미완이다.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import get_settings
from ..schemas import BizCandidate, BizIdentity
from ..utils import http as shared_http
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

# bizno 정책상 과도한 연속 호출을 피한다. 무료 플랜 200건/일.
_BIZNO_GAP_SEC = 0.4
_bizno_lock = asyncio.Lock()

SOURCE_USER = "user_input"
SOURCE_BIZNO = "bizno"
SOURCE_MOCK = "mock"
SOURCE_NONE = "none"

# bizno 조회 실패 사유. 사용자 문구와 `debug.biz_lookup_error` 가 이걸로 갈린다.
ERR_NO_KEY = "no_key"
ERR_QUOTA = "quota_exceeded"      # resultCode -3 — 무료 플랜 200건/일 소진
ERR_HTTP = "http_error"
ERR_REQUEST = "request_failed"
ERR_NOT_FOUND = "not_found"       # 조회는 됐고 해당 번호가 없다

# 한도 초과·장애는 '번호를 못 찾음'과 전혀 다른 사건이다. 같은 문구로 묶으면
# 모든 번호가 조회 실패로 보여 입력값을 의심하게 된다(2026-09-15 실측: 한도가
# 소진되자 전체 분석이 이 화면으로 떨어졌는데 문구는 번호 탓을 하고 있었다).
_UNAVAILABLE_ERRORS = frozenset({ERR_NO_KEY, ERR_QUOTA, ERR_HTTP, ERR_REQUEST})

MSG_NEED_NAME = (
    "사업자등록번호로 상호명을 찾지 못했습니다. 매장 상호명을 입력해 주세요."
)
MSG_LOOKUP_UNAVAILABLE = (
    "사업자 정보 조회 서비스를 일시적으로 사용할 수 없습니다. "
    "매장 상호명을 직접 입력하시면 분석을 계속합니다."
)


def normalize_business_number(value: str) -> str:
    """10자리 숫자만 남긴다. 자리수가 다르면 ValueError."""
    if value is None:
        raise ValueError("business_number is required.")
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 10:
        raise ValueError("business_number must contain exactly 10 digits.")
    return digits


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


# ---------------------------------------------------------------- bizno

def parse_bizno_payload(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """bizno JSON 응답에서 첫 유효 항목을 뽑는다.

    `items` 배열에 `null` 패딩이 섞여 나오므로(10슬롯 중 1개만 채워지는 식)
    반드시 걸러야 한다. 이걸 안 하면 `items[0]`이 None이라 즉시 터진다.
    """
    if not payload:
        return None
    if payload.get("resultCode") not in (0, "0"):
        logger.warning("bizno resultCode=%s msg=%s",
                       payload.get("resultCode"), payload.get("resultMsg"))
        return None
    items = [i for i in (payload.get("items") or []) if i]
    if not items:
        return None
    it = items[0]
    return {
        "company_name": _clean(it.get("company")),
        "business_number": _clean(it.get("bno")),
        "status": _clean(it.get("bstt")),
        "tax_type": _clean(it.get("taxtype")),
        "corp_number": _clean(it.get("cno")),
        "end_date": _clean(it.get("EndDt")),
    }


async def _lookup_bizno(digits: str) -> Tuple[Optional[Dict[str, str]], str]:
    """(조회 결과, 실패 사유). 성공하면 사유는 빈 문자열이다."""
    settings = get_settings()
    if not settings.bizno_api_key:
        return None, ERR_NO_KEY

    cache = get_cache("bizno")
    if digits in cache:
        logger.info("bizno cache hit for %s", digits)
        return cache[digits], ""

    params = {"key": settings.bizno_api_key, "q": digits, "type": "json"}
    async with _bizno_lock:
        try:
            resp = await shared_http.get_client().get(
                settings.bizno_api_url, params=params, timeout=20)
        except Exception as exc:
            logger.warning("bizno 호출 실패: %s", exc)
            return None, ERR_REQUEST
        await asyncio.sleep(_BIZNO_GAP_SEC)

    if resp.status_code != 200:
        logger.warning("bizno HTTP %s: %s", resp.status_code, resp.text[:160])
        return None, ERR_HTTP
    try:
        payload = resp.json() or {}
    except ValueError:
        logger.warning("bizno JSON 파싱 실패: %s", resp.text[:160])
        return None, ERR_HTTP

    # 한도 초과는 개별 번호의 문제가 아니라 전면 중단이다 — WARNING 으로는
    # 다른 조회 실패에 묻히므로 ERROR 로 올려 로그에서 바로 보이게 한다.
    if payload.get("resultCode") in (-3, "-3"):
        logger.error("bizno 일일 조회 한도 초과 — 모든 상호명 조회가 실패한다: %s",
                     payload.get("resultMsg"))
        return None, ERR_QUOTA

    parsed = parse_bizno_payload(payload)
    if parsed and parsed.get("company_name"):
        cache[digits] = parsed
        return parsed, ""
    return None, ERR_NOT_FOUND


# ---------------------------------------------------------------- mock

def _mock_identity(digits: str) -> BizIdentity:
    return BizIdentity(
        company_name="별빛카페 달빛차",
        business_type="",
        address="",
        source=SOURCE_MOCK,
        confidence=1.0,
        message="모의 사업자 조회 응답",
    )


# ---------------------------------------------------------------- 공개 API

async def resolve_identity(
    business_number: str,
    *,
    user_company_name: Optional[str] = None,
    user_address: Optional[str] = None,
) -> BizIdentity:
    """사업자번호에서 상호명을 확정한다. 실패 시 `needs_user_input=True`.

    `user_company_name`이 주어지면 조회를 건너뛰고 그대로 확정한다
    (사용자가 상호명을 직접 입력한 재요청 경로).
    """
    settings = get_settings()
    digits = normalize_business_number(business_number)

    # 0) 사용자 입력 우선. 검증 수단이 없으므로 confidence를 1.0으로 두지 않는다.
    if user_company_name and user_company_name.strip():
        return BizIdentity(
            company_name=user_company_name.strip(),
            address=(user_address or "").strip(),
            source=SOURCE_USER,
            confidence=0.9,
            message="사용자가 입력한 상호명을 사용했습니다.",
        )

    if settings.effective_mock_mode():
        logger.info("biz_lookup -> MOCK for %s", digits)
        return _mock_identity(digits)

    # 1) bizno
    parsed, lookup_error = await _lookup_bizno(digits)
    if parsed and parsed.get("company_name"):
        logger.info("biz_lookup: bizno hit '%s' (%s)",
                    parsed["company_name"], parsed.get("status"))
        return BizIdentity(
            company_name=parsed["company_name"],
            business_type="",     # 무료 플랜에 없음 — Kakao가 채운다
            address="",           # 무료 플랜에 없음 — Kakao가 채운다
            source=SOURCE_BIZNO,
            confidence=1.0,
            registered_status=parsed.get("status", ""),
            tax_type=parsed.get("tax_type", ""),
            message=f"사업자등록 상호명: {parsed['company_name']}",
        )

    # 2) 실패 → 사용자 입력 요청. 어느 쪽이든 상호명을 직접 받으면 분석은 이어지지만,
    #    문구는 원인을 정직하게 말해야 한다(번호 탓 vs 조회 서비스 탓).
    logger.info("biz_lookup: 상호명 확보 실패 (%s, %s) — 사용자 입력 필요",
                digits, lookup_error)
    return BizIdentity(
        source=SOURCE_NONE,
        confidence=0.0,
        needs_user_input=True,
        lookup_error=lookup_error,
        message=(MSG_LOOKUP_UNAVAILABLE if lookup_error in _UNAVAILABLE_ERRORS
                 else MSG_NEED_NAME),
    )


def candidates_from_identity(identity: BizIdentity) -> List[BizCandidate]:
    """NPS 경로가 붙으면 여기서 후보 목록을 만든다. 지금은 항상 빈 리스트."""
    return list(identity.candidates or [])
