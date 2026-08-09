from fastapi import APIRouter

from .. import __version__
from ..config import get_settings
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    missing = [
        name for name, val in [
            ("DATA_GO_KR_API_KEY", settings.data_go_kr_api_key),
            ("GOOGLE_MAPS_API_KEY", settings.google_maps_api_key),
            ("OPENAI_API_KEY", settings.openai_api_key),
            ("KMA_API_KEY", settings.kma_api_key),
        ] if not val
    ]
    return HealthResponse(
        status="ok",
        version=__version__,
        mock_mode=settings.effective_mock_mode(),
        missing_keys=missing,
    )
