import { useState } from "react"

import { CREDIT_PER_CHECK, CREDIT_RULES, TODOS } from "@/lib/care-data"
import { ALL_TODOS_DONE, type CareState } from "@/lib/use-care-state"
import { GradeSheet } from "@/components/care/grade-sheet"

/** 2-4 오늘 챙김 크레딧 카드 — 오른쪽 열 맨 위.
 *  "크레딧은 어떻게 쌓이나요"는 카드 안에서 펼치고, "등급 기준"은 2-9 시트를 연다. */
export function CreditCard({ state }: { state: CareState }) {
  const [rulesOpen, setRulesOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)

  const earned = state.checked.length * CREDIT_PER_CHECK
  const max = TODOS.length * CREDIT_PER_CHECK
  const remaining = TODOS.length - state.checked.length
  const done = ALL_TODOS_DONE(state)

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <p className="text-sm text-muted-foreground">오늘 챙김 크레딧</p>

      <p className="mt-1 flex items-baseline gap-1">
        <span className="text-[34px] leading-none font-black text-accent-text">+{earned}</span>
        <span className="text-sm text-muted-foreground">/ +{max}</span>
      </p>

      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={state.checked.length}
        aria-valuemin={0}
        aria-valuemax={TODOS.length}
        aria-label="오늘 챙김 진행"
      >
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${(state.checked.length / TODOS.length) * 100}%` }}
        />
      </div>

      <p className="mt-3 text-sm break-keep text-muted-foreground">
        {done
          ? "오늘 몫을 다 모았어요. 나무에 바로 반영돼요"
          : `남은 ${remaining}개를 챙기면 +${remaining * CREDIT_PER_CHECK} 더 쌓여요`}
      </p>

      <div className="mt-4 flex flex-col gap-1">
        <button
          type="button"
          aria-expanded={rulesOpen}
          onClick={() => setRulesOpen((v) => !v)}
          className="min-h-10 text-left text-sm font-bold text-accent-text transition-transform active:scale-[.98] motion-reduce:transition-none"
        >
          크레딧은 어떻게 쌓이나요 {rulesOpen ? "⌃" : "›"}
        </button>

        {rulesOpen && (
          <dl className="mt-1 flex flex-col gap-2 rounded-lg bg-panel p-4 text-sm">
            {CREDIT_RULES.map((r) => (
              <div key={r.label} className="flex items-baseline justify-between gap-3">
                <dt className="min-w-0 break-keep text-muted-foreground">{r.label}</dt>
                <dd className="shrink-0 font-bold">{r.value}</dd>
              </div>
            ))}
          </dl>
        )}

        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          className="min-h-10 text-left text-sm font-bold text-accent-text transition-transform active:scale-[.98] motion-reduce:transition-none"
        >
          등급 기준 ›
        </button>
      </div>

      {sheetOpen && <GradeSheet state={state} onClose={() => setSheetOpen(false)} />}
    </section>
  )
}
