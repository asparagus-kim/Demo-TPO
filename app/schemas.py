"""Pydantic request / response models for the analyse API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class AnalyseRequest(BaseModel):
    business_number: str = Field(..., description="사업자등록번호 (hyphens allowed)")
    # --- 2단계 플로우용 (모두 optional) ---
    company_name: Optional[str] = Field(
        default=None, description="상호명 조회 실패 시 사용자가 직접 입력한 상호명")
    address_hint: Optional[str] = Field(
        default=None, description="지역 힌트(시/군/구). 동명 매장을 좁히는 데 사용")
    place_id: Optional[str] = Field(
        default=None, description="Kakao 후보가 여러 건일 때 사용자가 고른 매장의 place_id")

    @field_validator("business_number")
    @classmethod
    def strip_number(cls, v: str) -> str:
        if v is None:
            raise ValueError("business_number is required")
        return v.strip()


class BusinessInfo(BaseModel):
    company_name: str = ""
    business_type: str = ""
    address: str = ""
    company_intro: Optional[str] = None


class BizCandidate(BaseModel):
    """상호명 후보 1건 (NPS 다건 조회 등에서 사용). 사용자가 고를 대상."""
    company_name: str
    address: str = ""
    business_type: str = ""
    source: str = ""
    hint: str = ""


class BizIdentity(BaseModel):
    """사업자번호에서 확정한 매장 신원.

    bizno 무료 플랜은 상호명만 주므로 `business_type`·`address`는 보통 빈 값이고,
    이후 `kakao_local_service`가 채운다.
    """
    company_name: str = ""
    business_type: str = ""
    address: str = ""
    company_intro: Optional[str] = None
    location: Optional[Dict[str, float]] = None
    source: str = "none"              # bizno | user_input | nps | mock | none
    confidence: float = 0.0
    registered_status: str = ""       # bizno가 함께 주는 사업 상태 (국세청과 교차확인용)
    tax_type: str = ""
    candidates: List[BizCandidate] = Field(default_factory=list)
    needs_user_input: bool = False
    message: str = ""


class PlaceCandidate(BaseModel):
    """Kakao 키워드 검색 결과 1건. 여러 건일 때 사용자가 고른다."""
    place_id: str = ""
    place_name: str = ""
    category_name: str = ""
    category_group_code: str = ""
    business_type: str = ""           # category_name의 말단 토큰
    address: str = ""                 # 도로명 우선 — 표시·검증용
    # 지번 주소(행정동 포함). 상권 매칭 엑셀이 행정동 기준이라 도로명으로는 매칭되지 않는다.
    region_address: str = ""
    phone: str = ""
    place_url: str = ""
    location: Optional[Dict[str, float]] = None
    score: float = 0.0                # 상호명 유사도 기반 선택 점수 (0~1)


class NeedsInput(BaseModel):
    """분석을 계속하려면 사용자 입력이 필요한 상태."""
    reason: str = ""                  # "company_name" | "place_choice" | "not_found"
    message: str = ""
    fields: List[str] = Field(default_factory=list)
    biz_candidates: List[BizCandidate] = Field(default_factory=list)
    place_candidates: List[PlaceCandidate] = Field(default_factory=list)


class TradeAreaMatch(BaseModel):
    label: str = "주거 밀집 상권"
    matched_address: Optional[str] = None
    match_method: str = "fallback"
    confidence: float = 0.0


class PlaceReview(BaseModel):
    author: Optional[str] = None
    rating: Optional[float] = None
    text: str = ""
    language: Optional[str] = None
    relative_time: Optional[str] = None
    publish_time: Optional[str] = None


class GooglePlaces(BaseModel):
    place_id: Optional[str] = None
    place_name: Optional[str] = None
    formatted_address: Optional[str] = None
    business_hours: List[str] = Field(default_factory=list)
    rating: Optional[float] = None
    review_count: Optional[int] = None
    reviews: List[PlaceReview] = Field(default_factory=list)
    place_types: List[str] = Field(default_factory=list)
    location: Optional[Dict[str, float]] = None  # {"lat": ..., "lng": ...}


class EntityValidation(BaseModel):
    """Result of comparing moneypin canonical identity against Google Places candidate."""
    is_consistent: bool = False
    name_similarity: float = 0.0
    address_similarity: float = 0.0
    business_type_compatible: bool = False
    score: float = 0.0
    reasons: List[str] = Field(default_factory=list)
    moneypin_summary: Dict[str, Any] = Field(default_factory=dict)
    google_summary: Dict[str, Any] = Field(default_factory=dict)


class WebEvidenceItem(BaseModel):
    """A textual snippet pulled from web search used as ambience evidence."""
    title: Optional[str] = None
    url: Optional[str] = None
    text: str = ""
    source: Optional[str] = None  # e.g. "naver_blog", "tistory", "instagram", "search_snippet"


class EvidenceProvenance(BaseModel):
    """Tells the UI/debug where the ambience text-evidence actually came from."""
    text_source: str = "none"   # "google_reviews" | "web_search" | "mixed" | "none"
    google_used: bool = False
    google_metadata_used: bool = False  # hours / lat-lng / type even if reviews not used
    web_search_used: bool = False
    google_review_count: int = 0
    web_evidence_count: int = 0
    notes: List[str] = Field(default_factory=list)


class Weather(BaseModel):
    summary: str = ""
    temperature_c: Optional[float] = None
    condition: str = "cloudy"
    precipitation_mm: Optional[float] = None
    humidity: Optional[float] = None
    source_time: Optional[str] = None


class TpoProfile(BaseModel):
    time_label: str = ""
    place_label: str = ""
    occasion_label: str = ""
    peak_slots: List[str] = Field(default_factory=list)


class Ambience(BaseModel):
    energy: int = 0
    tempo: int = 0
    mood: int = 0
    component_scores: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    confidence: float = 0.0
    explanations: List[str] = Field(default_factory=list)


class TrackRecommendation(BaseModel):
    """추천된 곡 1건. `audio_url`은 바로 재생 가능한 R2 공개 URL."""
    track_id: str
    title: str = ""
    title_ko: str = ""
    audio_url: str = ""
    duration_sec: Optional[float] = None
    bpm: Optional[float] = None
    energy_level: Optional[float] = None
    valence: Optional[float] = None
    arousal: Optional[float] = None
    genre_primary: Optional[str] = None
    mood_primary: Optional[str] = None
    vocal_type: Optional[str] = None
    score: float = 0.0                 # 0~1, 1이 완전 일치
    reason: str = ""                   # 사용자에게 보여줄 한 줄 근거
    match_detail: Dict[str, float] = Field(default_factory=dict)


class MusicRecommendation(BaseModel):
    """분석 결과 → 음원 추천 결과."""
    tracks: List[TrackRecommendation] = Field(default_factory=list)
    playlist_label: str = ""           # 예: "차분한 오후 · 카페"
    target: Dict[str, Any] = Field(default_factory=dict)   # 목표 벡터와 파생 선호
    industry_matched: bool = False     # 업종 전용 풀을 썼는지
    pool_size: int = 0                 # 최종 후보 수
    notes: List[str] = Field(default_factory=list)


class AnalyseResponse(BaseModel):
    success: bool = True
    business_number: str
    nts_status: str = ""
    business_info: BusinessInfo = Field(default_factory=BusinessInfo)
    trade_area: TradeAreaMatch = Field(default_factory=TradeAreaMatch)
    google_places: GooglePlaces = Field(default_factory=GooglePlaces)
    weather: Weather = Field(default_factory=Weather)
    tpo_profile: TpoProfile = Field(default_factory=TpoProfile)
    ambience: Ambience = Field(default_factory=Ambience)
    entity_validation: EntityValidation = Field(default_factory=EntityValidation)
    evidence_provenance: EvidenceProvenance = Field(default_factory=EvidenceProvenance)
    web_evidence: List[WebEvidenceItem] = Field(default_factory=list)
    music: MusicRecommendation = Field(default_factory=MusicRecommendation)
    needs_input: Optional[NeedsInput] = None
    debug: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    mock_mode: bool
    missing_keys: List[str] = Field(default_factory=list)
