/** 분석 수집(Analysis Data Collection) — 시트에 쌓인 행을 읽어 대시보드용으로 가공.
 *
 *  행의 정본은 백엔드 `app/services/sheets_logger.py` 의 `COLUMNS` 다. 여기서는
 *  열 목록을 하드코딩하지 않고 응답이 준 `columns` 를 그대로 쓴다 — 기획이 열을
 *  바꿔도 프론트를 고칠 필요가 없다. 아래 상수는 '표에서 기본으로 보여줄 열'일 뿐이다.
 */

import { API_BASE_URL } from "@/lib/api"

/** 시트 한 행. 값은 Apps Script 가 준 그대로(문자열·숫자·불리언). */
export type CollectionRow = Record<string, string | number | boolean | null>

export interface CollectionResponse {
  columns: string[]
  rows: CollectionRow[]
  /** 시트가 설정되지 않았거나 읽기에 실패하면 false — 화면은 안내로 degrade 한다. */
  available: boolean
  /** 왜 false 인지. 둘을 뭉뚱그리면 화면이 엉뚱한 원인을 지목한다
   *  (설정은 멀쩡한데 "URL 을 설정하세요" 라고 안내하는 문제). */
  reason?: "ok" | "not_configured" | "read_failed"
  /** read_failed 일 때 예외 종류 (예: ReadTimeout). */
  error?: string
}

/** 표에 처음부터 보이는 열 (나머지는 '열 전체 보기'로 펼친다). */
export const DEFAULT_VISIBLE: string[] = [
  "timestamp",
  "biz_no",
  "store_name",
  "category",
  "address",
  "district_type",
  "rating",
  "review_count",
  "energy",
  "tempo",
  "mood",
  "playlist_track_count",
  "outcome",
]

/** 열 이름 → 화면 라벨 (한국어). 없으면 열 이름을 그대로 쓴다. */
export const COLUMN_LABELS: Record<string, string> = {
  timestamp: "수집 시각",
  outcome: "결과",
  client: "출처",
  biz_no: "사업자번호",
  input_company_name: "입력 상호명",
  input_address_hint: "입력 지역",
  input_place_id: "선택 매장 ID",
  nts_status: "국세청 상태",
  store_name: "상호명",
  category: "업종",
  category_full: "업종 전체경로",
  address: "주소",
  region_address: "지번 주소",
  phone: "전화",
  lat: "위도",
  lng: "경도",
  kakao_place_id: "Kakao ID",
  kakao_place_url: "Kakao 링크",
  district_type: "상권 유형",
  district_method: "상권 판정방식",
  district_confidence: "상권 신뢰도",
  district_density: "밀집도",
  district_total_places: "반경 내 업소수",
  district_cafe_pct: "카페 비중",
  district_food_pct: "음식점 비중",
  district_bank_pct: "은행 비중",
  district_edu_pct: "학원 비중",
  district_univ_count: "대학 수",
  district_criteria: "판정 기준",
  hours: "영업시간",
  hours_source: "영업시간 출처",
  weather: "날씨",
  weather_temp_c: "기온",
  weather_condition: "날씨 코드",
  rating: "평점",
  review_count: "리뷰 수",
  reviews_analyzed: "분석 리뷰 수",
  review_keywords: "리뷰 키워드",
  text_source: "텍스트 근거",
  web_evidence_count: "웹 근거 수",
  consistency: "동일업체 검증",
  consistency_score: "검증 점수",
  energy: "에너지",
  tempo: "템포",
  mood: "무드",
  ambience_confidence: "분위기 신뢰도",
  tpo_time: "TPO 시간",
  tpo_place: "TPO 장소",
  tpo_occasion: "TPO 상황",
  playlist_label: "플레이리스트",
  playlist_track_count: "곡 수",
  industry_matched: "업종풀 적중",
  music_pool_size: "후보 곡수",
  top_tracks: "상위 곡",
  duration_ms: "소요(ms)",
  cache_hit: "캐시",
  mock_mode: "목업",
  prompt_version: "프롬프트",
  error: "오류",
}

export function labelFor(column: string): string {
  return COLUMN_LABELS[column] ?? column
}

export async function fetchCollection(
  limit = 500
): Promise<CollectionResponse> {
  // 상대경로를 쓰면 Vercel 정적 호스팅에서 SPA rewrite 에 걸려 index.html 이
  // 돌아온다(404 도 아니라서 JSON 파싱 에러로만 보인다). 개발 중에는 Vite
  // 프록시가 가려 주므로 배포 전까지 드러나지 않는다 — 반드시 백엔드를 명시한다.
  const res = await fetch(`${API_BASE_URL}/api/collection?limit=${limit}`)
  if (!res.ok)
    throw new Error(`수집 데이터를 불러오지 못했습니다 (${res.status})`)
  return (await res.json()) as CollectionResponse
}

// ---------------------------------------------------------------------------
// 집계 — 차트가 먹는 형태로
// ---------------------------------------------------------------------------

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null
  const n = typeof v === "number" ? v : Number(String(v).replace(/,/g, ""))
  return Number.isFinite(n) ? n : null
}

export const asNumber = num

/** 문자열 열의 값별 건수 — 많은 순. `limit` 을 넘으면 나머지는 '기타'로 접는다. */
export function countBy(
  rows: CollectionRow[],
  column: string,
  limit = 8
): { name: string; count: number }[] {
  const tally = new Map<string, number>()
  for (const row of rows) {
    const key = String(row[column] ?? "").trim()
    if (!key) continue
    tally.set(key, (tally.get(key) ?? 0) + 1)
  }
  const sorted = [...tally.entries()]
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)

  if (sorted.length <= limit) return sorted
  // 9번째부터는 새 색을 만들지 않고 '기타'로 접는다.
  const head = sorted.slice(0, limit)
  const rest = sorted.slice(limit).reduce((sum, d) => sum + d.count, 0)
  return rest > 0 ? [...head, { name: "기타", count: rest }] : head
}

/** 날짜(YYYY-MM-DD)별 분석 건수 — 오래된 순. 빈 날짜도 0으로 채운다. */
export function countByDay(rows: CollectionRow[], column = "timestamp") {
  const tally = new Map<string, number>()
  for (const row of rows) {
    const raw = String(row[column] ?? "")
    const day = raw.slice(0, 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue
    tally.set(day, (tally.get(day) ?? 0) + 1)
  }
  if (tally.size === 0) return []

  const days = [...tally.keys()].sort()
  const out: { day: string; count: number }[] = []
  const cursor = new Date(`${days[0]}T00:00:00Z`)
  const last = new Date(`${days[days.length - 1]}T00:00:00Z`)
  // 빈 날을 건너뛰면 x축이 거짓말을 한다 — 0으로 메운다.
  while (cursor <= last) {
    const key = cursor.toISOString().slice(0, 10)
    out.push({ day: key, count: tally.get(key) ?? 0 })
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return out
}

export function average(rows: CollectionRow[], column: string): number | null {
  const values = rows
    .map((r) => num(r[column]))
    .filter((v): v is number => v !== null)
  if (values.length === 0) return null
  return values.reduce((a, b) => a + b, 0) / values.length
}

/** 그룹별 E/T/M 평균 — 표본이 `minSample` 이상인 그룹만. 기본 그룹은 업종. */
export function ambienceByCategory(
  rows: CollectionRow[],
  minSample = 2,
  limit = 6,
  groupBy = "category"
) {
  const groups = new Map<string, CollectionRow[]>()
  for (const row of rows) {
    const key = String(row[groupBy] ?? "").trim()
    if (!key) continue
    const list = groups.get(key)
    if (list) list.push(row)
    else groups.set(key, [row])
  }
  return [...groups.entries()]
    .filter(([, list]) => list.length >= minSample)
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, limit)
    .map(([name, list]) => ({
      name,
      n: list.length,
      energy: Math.round(average(list, "energy") ?? 0),
      tempo: Math.round(average(list, "tempo") ?? 0),
      mood: Math.round(average(list, "mood") ?? 0),
    }))
}

/** 시각(0–23시)별 분석 건수 — 운영이 '언제 몰리는지' 보는 용도. 24칸 고정. */
export function countByHour(rows: CollectionRow[]) {
  const buckets = Array.from({ length: 24 }, (_, hour) => ({
    hour: `${String(hour).padStart(2, "0")}시`,
    count: 0,
  }))
  for (const row of rows) {
    const m = String(row.timestamp ?? "").match(/T(\d{2}):/)
    if (m) buckets[Number(m[1])].count += 1
  }
  return buckets
}

/** 시트에 값이 없을 수 있으므로 불리언은 문자열도 함께 받는다 (Apps Script 는 "TRUE"). */
export function isTrue(value: CollectionRow[string]): boolean {
  return value === true || value === "TRUE" || value === "true"
}

/** 조건을 만족하는 비율(0–100). 표본이 없으면 null. */
export function rateOf(
  rows: CollectionRow[],
  predicate: (row: CollectionRow) => boolean
): number | null {
  if (rows.length === 0) return null
  return (rows.filter(predicate).length / rows.length) * 100
}

/** 최근 `days` 일 안의 행만. `days` 가 0 이면 전체. */
export function withinDays(rows: CollectionRow[], days: number) {
  if (days <= 0) return rows
  const cutoff = Date.now() - days * 86_400_000
  return rows.filter((row) => {
    const t = Date.parse(String(row.timestamp ?? ""))
    return Number.isFinite(t) && t >= cutoff
  })
}

/** 직전 동일 기간 대비 증감. KPI 카드의 배지에 쓴다. */
export function trend(rows: CollectionRow[], days: number) {
  if (days <= 0) return null
  const now = Date.now()
  const span = days * 86_400_000
  const inWindow = (from: number, to: number) =>
    rows.filter((row) => {
      const t = Date.parse(String(row.timestamp ?? ""))
      return Number.isFinite(t) && t >= from && t < to
    }).length

  const current = inWindow(now - span, now + 86_400_000)
  const previous = inWindow(now - span * 2, now - span)
  if (previous === 0)
    return current === 0 ? null : { current, previous, pct: null }
  return { current, previous, pct: ((current - previous) / previous) * 100 }
}

// ---------------------------------------------------------------------------
// CSV
// ---------------------------------------------------------------------------

/** RFC4180 이스케이프. 주소·업종에 쉼표가 흔하므로 반드시 거친다. */
function csvCell(value: unknown): string {
  const s = value === null || value === undefined ? "" : String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCsv(columns: string[], rows: CollectionRow[]): string {
  const header = columns.map((c) => csvCell(labelFor(c))).join(",")
  const body = rows.map((row) => columns.map((c) => csvCell(row[c])).join(","))
  return [header, ...body].join("\r\n")
}

export function downloadCsv(
  columns: string[],
  rows: CollectionRow[],
  filename: string
) {
  // Excel 이 UTF-8 을 알아보게 BOM 을 붙인다. 없으면 한글이 깨진다.
  const blob = new Blob(["﻿", toCsv(columns, rows)], {
    type: "text/csv;charset=utf-8",
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
