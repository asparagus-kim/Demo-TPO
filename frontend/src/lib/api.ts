/** Types mirroring `app/schemas.py` (only the fields the UI consumes). */

export interface LatLng {
  lat: number
  lng: number
}

/** `app/schemas.py` RegisteredBusiness — 보험 상담 페이지가 리드 정보·추정 매칭에 쓴다. */
export interface RegisteredBusiness {
  source: string
  company_name: string
  address: string
  business_type: string
  registered_status: string
  tax_type: string
  /** APICK 대표명·전화번호 — 서버에서 마스킹된 값만 온다 (김** · 010-****-5678). */
  representative_masked: string
  phone_masked: string
}

export interface PlaceCandidate {
  place_id: string
  place_name: string
  category_name: string
  business_type: string
  address: string
  region_address: string
  phone: string
  place_url: string
  location?: LatLng | null
  score: number
}

export interface NeedsInput {
  reason: "company_name" | "place_choice" | "not_found" | string
  message: string
  fields: string[]
  place_candidates: PlaceCandidate[]
}

export interface PlaceReview {
  author?: string | null
  rating?: number | null
  text: string
  relative_time?: string | null
}

export interface TrackRecommendation {
  track_id: string
  title: string
  title_ko: string
  audio_url: string
  duration_sec?: number | null
  bpm?: number | null
  energy_level?: number | null
  genre_primary?: string | null
  mood_primary?: string | null
  vocal_type?: string | null
  score: number
  reason: string
}

export interface MusicRecommendation {
  tracks: TrackRecommendation[]
  playlist_label: string
  target: { industry_group_label?: string } & Record<string, unknown>
  industry_matched: boolean
  pool_size: number
  notes: string[]
}

/** 반경 내 업종 집계 원본 수치 — '분석 근거' 10줄 템플릿의 데이터 소스.
 *  주변 분포 방식일 때만 온다(엑셀 폴백·구버전 캐시 응답에는 없다). */
export interface TradeAreaSurroundings {
  radius_m: number
  total: number
  counts: Record<string, number>
  cafe_pct: number
  food_pct: number
  edu_pct: number
  bank_pct: number
  tour_pct: number
  hospital_pct: number
  cafe_bank_ratio: number
  univ_count: number
  density: string // "낮음" | "보통" | "높음"
  own_code: string
  own_count?: number | null
  own_pct?: number | null
}

/** 상권 판정에 실제 사용된 판별 기준 1건 (백엔드 분류 로직에서 도출). */
export interface TradeAreaCriterion {
  indicator: string
  value: string
  threshold: string
  label: string
  met: boolean
  decided: boolean
}

export interface ReviewKeywordMention {
  keyword: string
  count: number
}

export interface AnalyseResponse {
  success: boolean
  business_number: string
  nts_status: string
  business_info: {
    company_name: string
    business_type: string
    address: string
  }
  trade_area: {
    label: string
    match_method: string
    confidence: number
    surroundings?: TradeAreaSurroundings | null
    criteria?: TradeAreaCriterion[]
  }
  google_places: {
    business_hours: string[]
    rating?: number | null
    review_count?: number | null
    reviews: PlaceReview[]
    location?: LatLng | null
  }
  weather: { summary: string; condition: string }
  tpo_profile: {
    time_label: string
    place_label: string
    occasion_label: string
    peak_slots: string[]
  }
  ambience: {
    energy: number
    tempo: number
    mood: number
    confidence: number
    explanations: string[]
  }
  entity_validation: {
    is_consistent: boolean
    score: number
    reasons: string[]
  }
  evidence_provenance: {
    text_source: string
    google_review_count: number
    web_evidence_count: number
    notes: string[]
    review_keywords?: ReviewKeywordMention[]
    reviews_analyzed?: number
  }
  web_evidence: {
    title?: string | null
    url?: string | null
    text: string
    source?: string | null
  }[]
  music: MusicRecommendation
  /** 확정된 Kakao 매장 — 지도 표시와 카카오맵 딥링크의 근거. 구버전 캐시 응답에는 없다. */
  resolved_place?: PlaceCandidate | null
  /** 사업자등록 기준 신원 (registered identity — APICK or bizno). 대표자명·전화번호는 없다. */
  registered_business?: RegisteredBusiness | null
  needs_input?: NeedsInput | null
  debug: Record<string, unknown>
  error?: string | null
}

export interface AnalyseParams {
  business_number: string
  company_name?: string
  address_hint?: string
  place_id?: string
}

/**
 * Backend origin. Empty locally so requests hit same-origin `/api` and get
 * proxied by Vite; set `VITE_API_BASE_URL` in the deploy env to point at Render.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(
  /\/$/,
  ""
)

export async function analyse(params: AnalyseParams): Promise<AnalyseResponse> {
  const res = await fetch(`${API_BASE_URL}/api/analyse`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      // 분석 수집 시트의 `client` 열 — 레거시 데모(templates/demo.html)와
      // 이 프론트를 구분한다. 백엔드가 없으면 "api" 로 남긴다.
      "X-Yielda-Client": "web",
    },
    body: JSON.stringify(params),
  })
  const data = (await res.json()) as AnalyseResponse & { detail?: string }
  if (!res.ok && !data.error && !data.needs_input) {
    throw new Error(data.detail || "분석에 실패했습니다.")
  }
  return data
}
