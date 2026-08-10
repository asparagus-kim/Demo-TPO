"""National Tax Service (국세청) status lookup.

Uses the odcloud.kr `nts-businessman/v1/status` endpoint. Returns the raw
status string plus a normalised label (`계속사업자`, `휴업자`, `폐업자`,
`조회실패`, `형식오류`).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import get_settings
from ..utils import http as shared_http
from ..utils.logging import get_logger

logger = get_logger(__name__)

STATUS_ACTIVE = "계속사업자"
STATUS_CLOSED = "폐업자"
STATUS_SUSPENDED = "휴업자"
STATUS_LOOKUP_FAILED = "조회실패"
STATUS_INVALID = "형식오류"


def normalize_business_number(value: str) -> str:
    """10 digits only. Raises ValueError if wrong length."""
    if value is None:
        raise ValueError("business_number is required.")
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 10:
        raise ValueError("business_number must contain exactly 10 digits.")
    return digits


def format_business_number(digits: str) -> str:
    if len(digits) != 10:
        return digits
    return f"{digits[:3]}-{digits[3:5]}-{digits[5:]}"


async def _post_batch(client: httpx.AsyncClient, url: str, api_key: str, batch: List[str]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    payload = {"b_no": batch}

    async for attempt in AsyncRetrying(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=6),
        retry=retry_if_exception_type((httpx.TransportError, httpx.ReadTimeout)),
    ):
        with attempt:
            resp = await client.post(
                url,
                params={"serviceKey": api_key, "returnType": "JSON"},
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning("NTS batch status %s — %s", resp.status_code, resp.text[:200])
                return out
            data = (resp.json() or {}).get("data", [])
            for item in data:
                b_no = item.get("b_no")
                if b_no:
                    out[b_no] = item
            return out
    return out


async def lookup_status(business_number: str) -> Dict[str, Optional[str]]:
    """Return {"b_no", "status_label", "raw_status", "tax_type", "end_dt", "message"}."""
    settings = get_settings()
    try:
        digits = normalize_business_number(business_number)
    except ValueError as exc:
        return {
            "b_no": business_number,
            "status_label": STATUS_INVALID,
            "raw_status": "",
            "tax_type": "",
            "end_dt": "",
            "message": str(exc),
        }

    if settings.effective_mock_mode():
        logger.info("NTS mock mode active for %s", digits)
        return _mock_status(digits)

    if not settings.data_go_kr_api_key:
        logger.warning("DATA_GO_KR_API_KEY missing — falling back to mock NTS response")
        return _mock_status(digits)

    try:
        results = await _post_batch(shared_http.get_client(), settings.nts_api_url,
                                    settings.data_go_kr_api_key, [digits])
    except Exception:
        # `message` 는 API 응답(debug.nts)에 실려 브라우저까지 간다. 예외 문자열을
        # 넣으면 httpx 예외에 담긴 요청 URL(= serviceKey 포함)이 노출되므로 고정 문구만
        # 쓴다. 원인은 서버 로그에만 남긴다.
        #
        # `message` reaches the browser via debug.nts, so it must not carry the
        # exception text — an httpx error embeds the request URL, which for
        # data.go.kr contains the serviceKey. Cause goes to the server log only.
        logger.exception("NTS lookup failed for %s", digits)
        return {
            "b_no": digits,
            "status_label": STATUS_LOOKUP_FAILED,
            "raw_status": "",
            "tax_type": "",
            "end_dt": "",
            "message": "국세청 조회에 실패했습니다.",
        }

    item = results.get(digits)
    if not item:
        return {
            "b_no": digits,
            "status_label": STATUS_LOOKUP_FAILED,
            "raw_status": "",
            "tax_type": "",
            "end_dt": "",
            "message": "국세청 응답에 데이터가 없습니다.",
        }

    raw = item.get("b_stt") or ""
    label = raw.strip() or STATUS_LOOKUP_FAILED
    return {
        "b_no": digits,
        "status_label": label,
        "raw_status": raw,
        "tax_type": item.get("tax_type") or "",
        "end_dt": item.get("end_dt") or "",
        "message": f"상태: {raw or '미상'} / 과세유형: {item.get('tax_type', '')}",
    }


def _mock_status(digits: str) -> Dict[str, Optional[str]]:
    # For demo, the "closed" test number from moneypin_service.py's sample
    # returns 폐업자 so the UI can exercise the closed-business branch.
    closed = digits == "3878103190"
    if closed:
        return {
            "b_no": digits,
            "status_label": STATUS_CLOSED,
            "raw_status": STATUS_CLOSED,
            "tax_type": "부가가치세 일반과세자",
            "end_dt": "20240131",
            "message": "모의 국세청 응답: 폐업자",
        }
    return {
        "b_no": digits,
        "status_label": STATUS_ACTIVE,
        "raw_status": STATUS_ACTIVE,
        "tax_type": "부가가치세 일반과세자",
        "end_dt": "",
        "message": "모의 국세청 응답: 계속사업자",
    }
