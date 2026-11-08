import type { AnalyseResponse, TrackRecommendation } from "@/lib/api"
import { to24h } from "@/lib/format"

/** 영업시간을 3~4개 시간대로 쪼개 시간대별 플레이리스트를 만든다.
 *
 *  경계는 하루의 의미 있는 지점(점심 12시, 오후 2시, 저녁 5시)을 영업시간
 *  안으로 잘라서 쓴다. 그래야 "11–21시 카페"가 스펙 예시대로
 *  11–12 / 12–14 / 14–17 / 17–21 로 갈린다. 의미 경계가 영업시간 밖이면
 *  (심야 영업 등) 균등 분할로 물러난다. */

/** 하루 안의 의미 경계 — 점심 시작 · 오후 시작 · 저녁 시작 */
const ANCHORS = [12, 14, 17]
/** 이 시간 이상 영업하면 4구간, 아니면 3구간 */
const FOUR_SLOT_MIN_HOURS = 8

export interface TimeSlot {
  id: string
  label: string
  /** 영업일 기준 시작 시각(시). 자정을 넘기면 24 이상일 수 있다. */
  startHour: number
  endHour: number
  /** "12–14시" */
  rangeLabel: string
}

export interface BusinessHours {
  open: number
  close: number
}

const HOURS_LINE = /(\d{1,2}):(\d{2})\s*[~\-–]\s*(\d{1,2}):(\d{2})/
/** business_hours 줄은 월요일부터 온다 — Date.getDay()(일=0)와 맞추기 위한 순서 */
const DAY_TOKENS = ["월", "화", "수", "목", "금", "토", "일"]

/** 오늘 요일의 영업시간. 휴무거나 못 읽으면 null. */
function parseTodayHours(lines: string[], now: Date): BusinessHours | null {
  if (!lines?.length) return null
  // Date.getDay(): 일=0 … 토=6 → DAY_TOKENS 인덱스(월=0)로 변환
  const token = DAY_TOKENS[(now.getDay() + 6) % 7]
  const line = lines.find((l) => l.includes(`${token}요일`))
  if (!line || /휴무|휴일|closed/i.test(line)) return null
  const m = to24h(line).match(HOURS_LINE)
  if (!m) return null
  const open = Number(m[1]) + Number(m[2]) / 60
  const close = Number(m[3]) + Number(m[4]) / 60
  return { open, close }
}

/** tpo_profile.time_label("영업시간 9시–22시") 폴백. */
function parseTimeLabel(label: string): BusinessHours | null {
  const m = String(label || "").match(
    /(\d{1,2})\s*시\s*[~\-–]\s*(\d{1,2})\s*시/
  )
  if (!m) return null
  return { open: Number(m[1]), close: Number(m[2]) }
}

/** 분석 결과에서 오늘의 영업시간을 뽑는다. 정보가 없으면 09–22시로 가정. */
export function resolveBusinessHours(
  analysis: AnalyseResponse,
  now: Date = new Date()
): BusinessHours {
  const fromDay = parseTodayHours(
    analysis.google_places?.business_hours ?? [],
    now
  )
  if (fromDay) return fromDay
  const fromLabel = parseTimeLabel(analysis.tpo_profile?.time_label ?? "")
  if (fromLabel) return fromLabel
  return { open: 9, close: 22 }
}

function dayPart(hour: number): string {
  const h = ((hour % 24) + 24) % 24
  if (h < 5) return "심야" // 새벽 마감(예: 02시)은 '오전'이 아니라 '심야'
  if (h < 12) return "오전" // 11시도 오전 — 스펙 예시의 "오픈 · 오전"
  if (h < 14) return "점심"
  if (h < 17) return "오후"
  if (h < 21) return "저녁"
  return "심야"
}

function slotLabel(index: number, count: number, startHour: number): string {
  if (index === 0) return `오픈 · ${dayPart(startHour)}`
  if (index === count - 1) return `${dayPart(startHour)} 마감`
  const h = ((startHour % 24) + 24) % 24
  if (h >= 11 && h < 14) return "점심 피크"
  if (h >= 14 && h < 17) return "차분한 오후"
  return `${dayPart(startHour)} 시간대`
}

function hourText(hour: number): string {
  return String(Math.round(((hour % 24) + 24) % 24))
}

/** 영업시간을 3~4구간으로 나눈다. */
export function buildTimeSlots({ open, close }: BusinessHours): TimeSlot[] {
  // 자정을 넘기는 영업(예: 18–02시)은 close에 24를 더해 단조 증가로 만든다
  const end = close <= open ? close + 24 : close
  const total = end - open
  const wanted = total >= FOUR_SLOT_MIN_HOURS ? 4 : 3

  // 의미 경계(오늘/내일 양쪽)를 영업시간 안쪽만 남긴다
  const anchors = [...ANCHORS, ...ANCHORS.map((a) => a + 24)]
    .filter((a) => a > open + 0.5 && a < end - 0.5)
    .sort((a, b) => a - b)

  let bounds = [open, ...anchors, end]
  // 의미 경계로 원하는 구간 수가 안 나오면 균등 분할
  if (bounds.length - 1 !== wanted) {
    const step = total / wanted
    bounds = Array.from({ length: wanted + 1 }, (_, i) => open + step * i)
  }

  return bounds.slice(0, -1).map((startHour, i) => {
    const endHour = bounds[i + 1]
    return {
      id: `slot-${i}`,
      label: slotLabel(i, bounds.length - 1, startHour),
      startHour,
      endHour,
      rangeLabel: `${hourText(startHour)}–${hourText(endHour)}시`,
    }
  })
}

/** 지금 시각이 속한 구간. 영업시간 밖이면 첫 구간(오픈). */
export function currentSlotIndex(
  slots: TimeSlot[],
  now: Date = new Date()
): number {
  if (!slots.length) return 0
  const h = now.getHours() + now.getMinutes() / 60
  const found = slots.findIndex((s) => {
    // 자정을 넘긴 구간은 startHour가 24 이상이라 now에도 24를 더해 비교한다
    const inToday = h >= s.startHour && h < s.endHour
    const inNextDay = h + 24 >= s.startHour && h + 24 < s.endHour
    return inToday || inNextDay
  })
  return found === -1 ? 0 : found
}

/** 문자열 → 32bit 시드 (비암호용). */
function seedFrom(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

/** mulberry32 — 시드가 같으면 항상 같은 순열이 나온다. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** 구간별 트랙 목록.
 *
 *  TODO(백엔드): 지금은 자리표시자다. 실제로는 구간별 energy/BPM 파라미터로
 *  TPO 추천 로직을 다시 태워야 한다. 프론트가 가진 곡이 추천된 10곡뿐이라
 *  여기서는 같은 곡들을 구간마다 다른 순서로 섞어 보여준다. */
export function slotTracks(
  tracks: TrackRecommendation[],
  slotId: string
): TrackRecommendation[] {
  const rand = mulberry32(seedFrom(slotId))
  const out = [...tracks]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}
