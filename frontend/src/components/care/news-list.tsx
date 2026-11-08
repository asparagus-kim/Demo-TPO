import { useState } from "react"

import { NEWS, NEWS_PREVIEW, type NewsTone } from "@/lib/care-data"
import type { CareState } from "@/lib/use-care-state"
import { cn } from "@/lib/utils"

/** 칩 색 — 지원 초록 · 주의 주황 · 그 외 회색 (색 대응표). */
const TONE: Record<NewsTone, string> = {
  support: "bg-chart-3/20 text-chart-3",
  alert: "bg-chart-2/20 text-chart-2",
  neutral: "bg-muted text-muted-foreground",
}

/** 2-8 사장님 소식 — 카드 3개 + 전체 보기.
 *  어떤 카드도 화면 이동이 없다. 읽으면 버튼 문구가 바뀌고 카드가 흐려진다. */
export function NewsList({ state }: { state: CareState }) {
  const [expanded, setExpanded] = useState(false)
  const cards = expanded ? NEWS : NEWS.slice(0, NEWS_PREVIEW)

  return (
    <section className="flex flex-col gap-3" aria-label="사장님 소식">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-bold">사장님 소식</h2>
        <p className="text-sm text-muted-foreground">우리 업종 · 동네 기준 · 읽으면 +2</p>
      </div>

      <ul className="grid grid-cols-1 gap-3 min-[760px]:grid-cols-3">
        {cards.map((n) => {
          const isRead = state.read.includes(n.id)
          return (
            <li
              key={n.id}
              className={cn(
                "flex flex-col gap-2 rounded-xl border border-border p-4 transition-colors motion-reduce:transition-none",
                isRead ? "bg-panel opacity-70" : "bg-card",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span
                  className={cn("rounded-full px-2.5 py-0.5 text-xs font-bold", TONE[n.tone])}
                >
                  {n.tag}
                </span>
                <span className="shrink-0 text-xs text-muted-foreground">{n.timing}</span>
              </div>

              <p className="font-bold break-keep">{n.title}</p>
              <p className="flex-1 text-sm leading-relaxed break-keep text-muted-foreground">
                {n.description}
              </p>

              <button
                type="button"
                aria-pressed={isRead}
                onClick={() => state.markRead(n.id)}
                className="min-h-10 self-start rounded-full border border-border px-4 py-1.5 text-sm font-bold transition-[filter,transform] hover:brightness-125 active:scale-[.98] motion-reduce:transition-none"
              >
                {isRead ? "읽었어요 ✓" : n.button}{" "}
                <span className="text-accent-text">+2</span>
              </button>
            </li>
          )
        })}
      </ul>

      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((v) => !v)}
        className="min-h-10 self-start text-sm font-bold text-accent-text transition-transform active:scale-[.98] motion-reduce:transition-none"
      >
        {expanded ? "접기" : `전체 보기 (${NEWS.length}) ›`}
      </button>
    </section>
  )
}
