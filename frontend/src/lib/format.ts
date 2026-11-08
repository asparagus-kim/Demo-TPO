/** Display helpers ported from templates/demo.html (same rules as backend normalizers). */

import type { TrackRecommendation } from "@/lib/api"

/** Genre · mood · (연주곡) — the "artist" line for our system tracks. */
export function trackArtistLine(t: TrackRecommendation): string {
  const parts = [t.genre_primary?.replace(/_/g, " "), t.mood_primary].filter(
    Boolean
  ) as string[]
  if (t.vocal_type === "instrumental") parts.push("연주곡")
  return parts.join(" · ")
}

export function formatBno(v: string): string {
  const d = (v || "").replace(/\D/g, "").slice(0, 10)
  if (d.length <= 3) return d
  if (d.length <= 5) return `${d.slice(0, 3)}-${d.slice(3)}`
  return `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}`
}

export function scoreWord(v: number): string {
  if (v >= 78) return "매우 높음"
  if (v >= 62) return "높은 편"
  if (v >= 45) return "보통"
  if (v >= 30) return "낮은 편"
  return "매우 낮음"
}

export function mmss(sec?: number | null): string {
  if (sec === null || sec === undefined) return ""
  const s = Math.max(0, Math.round(sec))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
}

const HR_RANGE = /(\d{1,2}:\d{2})\s*[-–~]\s*(\d{1,2}:\d{2})/
const ALL_DAY = /(?:24\s*시간(?:\s*영업)?|open\s*24\s*hours|24\s*hours)/i
const DAYS = ["월", "화", "수", "목", "금", "토", "일"]

/** "오전 8:00 ~ 오후 9:00" → "08:00 ~ 21:00"; "24시간 영업" → "00:00 ~ 24:00". */
export function to24h(line: string): string {
  let out = String(line || "").replace(
    /(오전|오후)\s*(\d{1,2})(?::(\d{2}))?/g,
    (_, ap: string, h: string, m?: string) => {
      let hh = parseInt(h, 10)
      if (ap === "오후" && hh !== 12) hh += 12
      if (ap === "오전" && hh === 12) hh = 0
      return `${String(hh).padStart(2, "0")}:${m || "00"}`
    }
  )
  if (!HR_RANGE.test(out)) out = out.replace(ALL_DAY, "00:00 ~ 24:00")
  return out
}

/** Group consecutive weekdays sharing a range: "월–금 08:00~21:00 / 토·일 11:00~19:00". */
export function summarizeHours(lines: string[]): string {
  if (!lines || !lines.length) return "정보 없음"

  const parsed: { day: string; range: string }[] = []
  lines.forEach((raw) => {
    const l = to24h(raw)
    const day = (l.match(/([월화수목금토일])요일/) || [])[1]
    const m = l.match(HR_RANGE)
    const closed = /휴무|휴일|closed/i.test(l)
    if (!day) return
    const range = m
      ? m[1] === "00:00" && m[2] === "24:00"
        ? "24시간"
        : `${m[1]}~${m[2]}`
      : closed
        ? "휴무"
        : l.split(":").slice(1).join(":").trim() || "-"
    parsed.push({ day, range })
  })

  if (!parsed.length) {
    const uniq = [
      ...new Set(
        lines
          .map((l) => to24h(l))
          .map((l) => (l.match(HR_RANGE) || [])[0])
          .filter(Boolean)
      ),
    ]
    return uniq.length ? uniq.join(" · ") : to24h(lines[0])
  }

  parsed.sort((a, b) => DAYS.indexOf(a.day) - DAYS.indexOf(b.day))

  const groups: { range: string; days: string[] }[] = []
  parsed.forEach((p) => {
    const last = groups[groups.length - 1]
    if (
      last &&
      last.range === p.range &&
      DAYS.indexOf(p.day) === DAYS.indexOf(last.days[last.days.length - 1]) + 1
    ) {
      last.days.push(p.day)
    } else {
      groups.push({ range: p.range, days: [p.day] })
    }
  })
  return groups
    .map((g) => {
      const label =
        g.days.length === 1
          ? g.days[0]
          : g.days.length === 2
            ? g.days.join("·")
            : `${g.days[0]}–${g.days[g.days.length - 1]}`
      return `${label} ${g.range}`
    })
    .join(" / ")
}
