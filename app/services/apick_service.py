"""사업자번호 → 상호명 **+ 주소 + 좌표**. `biz_lookup_service` 의 1순위 경로.

## 왜 bizno 위에 이것을 두는가

bizno 무료 플랜은 상호명만 준다(`biz_lookup_service` 모듈 설명 참고). 그래서
업종·주소·좌표를 Kakao 에서 상호명만으로 찾아야 하는데, **상호명은 전국에서
유일하지 않다**. 동명 매장 두 곳이 똑같이 1.000 점을 받아 격차가 0.000 이 되면
`pick_best` 가 자동 확정을 포기하고 사용자에게 고르라고 묻는다.

2026-10-01 광진구 카페·선술집 49곳 실측:

    bizno 만:        28곳 자동 확정 · **20곳(41%) 이 '매장 선택' 화면**
    APICK 좌표 추가:  20곳 중 **17곳 자동 확정** (정답 3~8m, 2등 153m~238km)
                     1곳은 정당하게 보류(좌표 근처에 Kakao 매장 없음)
                     2곳은 APICK 에도 좌표가 없어 그대로 보류

즉 이 모듈의 값어치는 상호명이 아니라 **좌표**다. 상호명만 필요하면 bizno 로 충분하다.

## 비용

호출당 50포인트의 **유료** API 다. 캐시 TTL 을 길게 잡아 같은 사업자번호를
반복 조회하지 않는다. 테스트는 절대 실제 API 를 때리지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import get_settings
from ..utils import http as shared_http
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

# 대한민국 좌표 범위. 이 밖이면 파싱에 성공했어도 쓰지 않는다 — 엉뚱한 좌표로
# 매장을 '자동 확정' 하는 것이 사용자에게 묻는 것보다 훨씬 나쁘다.
_LAT_MIN, _LAT_MAX = 33.0, 39.0
_LNG_MIN, _LNG_MAX = 124.0, 132.0


def _clean(value: Any) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _parse_location(lat_raw: Any, lng_raw: Any) -> Optional[Dict[str, float]]:
    """APICK 의 위/경도는 **문자열**이고 값이 없으면 "" 로 온다.

    빈 값·숫자 아님·한국 밖은 전부 None 으로 떨어뜨린다. 좌표가 없으면
    상호명 점수 경로로 degrade 할 뿐, 파이프라인은 그대로 성공한다.
    """
    lat_s, lng_s = _clean(lat_raw), _clean(lng_raw)
    if not lat_s or not lng_s:
        return None
    try:
        lat, lng = float(lat_s), float(lng_s)
    except ValueError:
        logger.warning("APICK 좌표 파싱 실패 — 좌표 없이 진행한다")
        return None
    if not (_LAT_MIN <= lat <= _LAT_MAX and _LNG_MIN <= lng <= _LNG_MAX):
        logger.warning("APICK 좌표가 한국 범위 밖이다 — 좌표 없이 진행한다")
        return None
    return {"lat": lat, "lng": lng}


def payload_error(payload: Dict[str, Any]) -> str:
    """APICK 은 실패도 **HTTP 200** 으로 준다 — 본문의 `result.error` 를 봐야 한다.

        {"result":{"error":"사용 가능한 포인트이 부족합니다."},"api":{...}}

    상태코드만 보면 포인트 소진을 '그 번호는 자료가 없다' 와 구분할 수 없다.
    bizno 일일 한도 때 똑같이 당했다(2026-09-15): 전 번호가 조용히 실패하는데
    원인이 응답 어디에도 안 보였다. 여기서 사유를 꺼내 ERROR 로 올린다.
    """
    return _clean(((payload or {}).get("result") or {}).get("error"))


def parse_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """APICK 응답 → 내부 표준 dict. 한글 키를 여기서 한 번만 번역한다."""
    data = (payload or {}).get("data") or {}
    company = _clean(data.get("회사명")) or _clean(data.get("기업명"))
    if not company:
        return None
    # 도로명이 비는 사업자가 있다(실측 49곳 중 일부). 지번으로 메운다.
    address = _clean(data.get("도로명주소")) or _clean(data.get("지번주소"))
    return {
        "company_name": company,
        "address": address,
        "location": _parse_location(data.get("위도"), data.get("경도")),
        "business_type": _clean(data.get("업태")) or _clean(data.get("업종")),
        "registered_status": _clean(data.get("사업자상태")),
        "tax_type": _clean(data.get("과세유형")),
        "representative": _clean(data.get("대표명")),
        "phone": _clean(data.get("전화번호")),
    }


async def lookup(digits: str) -> Optional[Dict[str, Any]]:
    """사업자번호 10자리로 조회. 실패하면 None — 호출자가 bizno 로 내려간다.

    키가 없으면 **호출 자체를 하지 않는다**(유료 API 다).
    """
    settings = get_settings()
    if not settings.apick_api_key:
        return None

    cache = get_cache("apick")
    if digits in cache:
        logger.info("apick cache hit for %s", digits)
        return cache[digits]

    try:
        resp = await shared_http.get_client().post(
            settings.apick_biz_detail_url,
            headers={"CL_AUTH_KEY": settings.apick_api_key},
            files={"biz_no": (None, digits)},
            timeout=30,
        )
    except Exception as exc:
        # 예외 문자열에 키가 섞여 나올 수 있는 경로는 만들지 않는다 — 타입만 남긴다.
        logger.warning("APICK 호출 실패: %s", type(exc).__name__)
        return None

    if resp.status_code != 200:
        logger.warning("APICK HTTP %s", resp.status_code)
        return None
    try:
        payload = resp.json() or {}
    except ValueError:
        logger.warning("APICK JSON 파싱 실패")
        return None

    err = payload_error(payload)
    if err:
        # 포인트 소진은 개별 번호의 문제가 아니라 전면 중단이다 — 모든 조회가
        # 조용히 bizno 로 떨어지고 '매장 선택' 화면이 다시 늘어난다. ERROR 로 올려
        # 로그에서 바로 보이게 한다.
        logger.error("APICK 조회 실패 — bizno 로 degrade 한다: %s", err)
        return None

    parsed = parse_payload(payload)

    if parsed:
        logger.info("apick hit '%s' (좌표 %s)",
                    parsed["company_name"], "있음" if parsed["location"] else "없음")
        cache[digits] = parsed
    return parsed
