"""Runtime configuration loaded from environment variables.

Secrets must never be hard-coded. Copy `.env.example` -> `.env` and fill in
real keys locally. `.env` is git-ignored.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

from dotenv import load_dotenv

from .utils.logging import get_logger

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(dotenv_path=ENV_FILE, override=False)


def _get_service_key(name: str) -> str:
    """data.go.kr 인증키를 읽어 URL 인코딩되어 있으면 디코딩한다.

    data.go.kr은 인증키를 Encoding / Decoding 두 형태로 보여준다. 이 코드는
    키를 httpx `params`로 넘겨 자동 URL 인코딩하므로 **Decoding 키**가 맞다.
    Encoding 키를 넣으면 `%2B`가 `%252B`로 이중 인코딩되어 401/403이 난다
    (2026-08-04 실측: Encoding 키 → 국세청 401·기상청 403, 디코딩 → 둘 다 200).

    data.go.kr 키는 base64(A–Z a–z 0–9 + / =)라 '%'가 들어올 수 없다.
    따라서 '%'가 있으면 Encoding 키가 확실하므로 디코딩해 준다. 다만 자격증명을
    조용히 바꾸면 설정 오류를 감추게 되므로 경고를 남긴다.
    """
    raw = (os.getenv(name, "") or "").strip()
    if "%" not in raw:
        return raw
    decoded = unquote(raw)
    logger.warning(
        "%s 가 Encoding 키로 보입니다 — Decoding 키로 자동 변환했습니다. "
        ".env를 Decoding 키로 바꿔두는 것을 권장합니다.", name,
    )
    return decoded


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _get_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


@dataclass
class Settings:
    # API keys
    data_go_kr_api_key: str = field(default_factory=lambda: _get_service_key("DATA_GO_KR_API_KEY"))
    google_maps_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_MAPS_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    kma_api_key: str = field(default_factory=lambda: _get_service_key("KMA_API_KEY"))
    kakao_rest_api_key: str = field(default_factory=lambda: os.getenv("KAKAO_REST_API_KEY", ""))
    bizno_api_key: str = field(default_factory=lambda: os.getenv("BIZNO_API_KEY", ""))

    # Endpoints
    nts_api_url: str = field(default_factory=lambda: os.getenv(
        "NTS_API_URL",
        "https://api.odcloud.kr/api/nts-businessman/v1/status",
    ))
    text_search_url: str = field(default_factory=lambda: os.getenv(
        "TEXT_SEARCH_URL",
        "https://places.googleapis.com/v1/places:searchText",
    ))
    place_details_url: str = field(default_factory=lambda: os.getenv(
        "PLACE_DETAILS_URL",
        "https://places.googleapis.com/v1/{place_resource}",
    ))
    geocode_url: str = field(default_factory=lambda: os.getenv(
        "GEOCODE_URL",
        "https://maps.googleapis.com/maps/api/geocode/json",
    ))
    kma_ultra_ncst_url: str = field(default_factory=lambda: os.getenv(
        "KMA_ULTRA_NCST_URL",
        "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst",
    ))
    bizno_api_url: str = field(default_factory=lambda: os.getenv(
        "BIZNO_API_URL", "https://bizno.net/api/fapi",
    ))
    kakao_keyword_url: str = field(default_factory=lambda: os.getenv(
        "KAKAO_KEYWORD_URL", "https://dapi.kakao.com/v2/local/search/keyword.json",
    ))
    kakao_address_url: str = field(default_factory=lambda: os.getenv(
        "KAKAO_ADDRESS_URL", "https://dapi.kakao.com/v2/local/search/address.json",
    ))
    kakao_category_url: str = field(default_factory=lambda: os.getenv(
        "KAKAO_CATEGORY_URL", "https://dapi.kakao.com/v2/local/search/category.json",
    ))
    # 좌표 → 행정동. 상권 엑셀이 행정동 기준이라 법정동(지번 주소)만으로는 매칭이 안 된다.
    kakao_coord2region_url: str = field(default_factory=lambda: os.getenv(
        "KAKAO_COORD2REGION_URL", "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
    ))

    # 분석 수집(Analysis Data Collection) — Google Apps Script 웹앱 → 시트 append.
    # URL 자체가 자격증명이다: 아는 사람은 누구나 시트에 행을 쓸 수 있으므로
    # 프론트 번들에 넣지 않고 서버에서만 부른다. 토큰은 스크립트 쪽에서 대조한다.
    sheets_webhook_url: str = field(default_factory=lambda: os.getenv("SHEETS_WEBHOOK_URL", "").strip())
    sheets_webhook_token: str = field(default_factory=lambda: os.getenv("SHEETS_WEBHOOK_TOKEN", "").strip())
    sheets_logging_enabled: bool = field(default_factory=lambda: _get_bool("SHEETS_LOGGING_ENABLED", True))
    # 캐시 히트도 '사용자가 분석을 돌린' 사건이므로 기본으로 함께 남긴다.
    sheets_log_cache_hits: bool = field(default_factory=lambda: _get_bool("SHEETS_LOG_CACHE_HITS", True))
    # `needs_input` 은 중간 플로우 상태다. 켜면 한 분석이 2행 이상을 만든다.
    sheets_log_needs_input: bool = field(default_factory=lambda: _get_bool("SHEETS_LOG_NEEDS_INPUT", False))
    sheets_timeout_sec: float = field(default_factory=lambda: float(_get_int("SHEETS_TIMEOUT_SEC", 10)))

    # Runtime
    mock_mode: bool = field(default_factory=lambda: _get_bool("MOCK_MODE", False))
    llm_review_cap: int = field(default_factory=lambda: _get_int("LLM_REVIEW_CAP", 25))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    # LLM 제공자 전환점. OpenAI 호환 엔드포인트면 여기만 바꾸면 된다
    # (Groq: https://api.groq.com/openai/v1 · OpenRouter: https://openrouter.ai/api/v1).
    #
    # 예전에는 이 값을 코드에서 읽지 않고 OpenAI SDK 가 환경변수에서 알아서
    # 집어가게 두었다. 동작은 했지만 어떤 제공자를 쓰는지 코드 어디에도 드러나지
    # 않아, 모델이 폐기됐을 때 원인을 찾기 어려웠다. 이제 명시적으로 넘긴다.
    openai_base_url: str = field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "").strip())
    # OpenRouter 가 순위 페이지에 노출할 때 쓰는 선택 헤더. 없어도 호출은 된다.
    openrouter_site_url: str = field(default_factory=lambda: os.getenv("OPENROUTER_SITE_URL", "").strip())
    openrouter_app_name: str = field(default_factory=lambda: os.getenv("OPENROUTER_APP_NAME", "Yielda TPO").strip())
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    # Google Places 일별 호출 상한.
    # Places API (New)는 할당량을 아래로 낮출 수 없고(콘솔 '조정 가능 여부: 아니요'),
    # 예산 알림은 사후 통보라 앱에서 직접 막는다. 상한에 닿으면 실패시키지 않고
    # Kakao + 웹검색으로 degrade 해서 분석은 계속 성공하게 한다.
    places_daily_cap: int = field(default_factory=lambda: _get_int("PLACES_DAILY_CAP", 40))

    # Paths
    project_root: Path = field(default_factory=lambda: PROJECT_ROOT)
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    templates_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "templates")
    static_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "static")
    cache_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "cache")

    # Files
    trade_area_xlsx: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "상권특성_행정동_전국_FINAL.xlsx")
    prompt_version: str = field(default="v1")

    def effective_mock_mode(self) -> bool:
        """필수 키가 없으면 자동으로 mock 모드로 떨어진다.

        게이트 기준이 **Kakao + LLM**이다. Google Places는 하이브리드에서
        리뷰·영업시간 전담이고 없으면 Kakao+웹검색으로 degrade하도록 설계했으므로
        (설계 결정 2) 실모드 진입 조건에서 제외한다. 예전에는
        `google_maps_api_key`를 요구해서, Kakao 키를 넣어도 계속 mock으로
        동작하는 함정이 있었다.

        Kakao가 없으면 업종·주소·좌표를 얻을 방법이 없어 파이프라인이 성립하지 않는다.
        """
        if self.mock_mode:
            return True
        if not self.kakao_rest_api_key or not self.openai_api_key:
            return True
        return False

    def google_places_enabled(self) -> bool:
        """리뷰·영업시간을 Google에서 받을 수 있는 상태인지 (하이브리드의 상위 경로)."""
        return bool(self.google_maps_api_key) and not self.effective_mock_mode()

    def mask(self, key: str) -> str:
        if not key:
            return ""
        return key[:4] + "***" + key[-2:] if len(key) > 6 else "***"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
