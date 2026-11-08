import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Tick02Icon } from "@hugeicons/core-free-icons"

import {
  QUESTIONS,
  QUESTION_INTRO,
  QUESTION_VISIBLE,
  SKIP_CONFIRM,
  type CareQuestion,
} from "@/lib/care-data"
import { ALL_QUESTIONS_DONE, visibleQuestions, type CareState } from "@/lib/use-care-state"

/** 가장 최근 처리 결과 1건만 보여 준다(기획 명시). */
type Confirm =
  | { kind: "answered"; question: CareQuestion }
  | { kind: "skipped" }
  | null

/** 2-7 우리 가게 더 알려주기 — 7문항, 2개씩. */
export function StoreQuestions({ state }: { state: CareState }) {
  const [confirm, setConfirm] = useState<Confirm>(null)
  const cards = visibleQuestions(state, QUESTION_VISIBLE)
  const done = ALL_QUESTIONS_DONE(state)

  const answer = (q: CareQuestion) => {
    state.answerQuestion(q.id)
    setConfirm({ kind: "answered", question: q })
  }
  const skip = (q: CareQuestion) => {
    state.skipQuestion(q.id)
    setConfirm({ kind: "skipped" })
  }

  return (
    <section className="flex flex-col gap-3" aria-label="우리 가게 더 알려주기">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-bold">우리 가게 더 알려주기</h2>
        <p className="text-sm text-muted-foreground">
          {state.answered.length}/{QUESTIONS.length} 완료 · 하루 2문항
        </p>
      </div>

      <p className="max-w-3xl text-sm leading-relaxed break-keep text-muted-foreground">
        {QUESTION_INTRO}
      </p>

      {confirm && (
        <div className="flex items-start gap-3 rounded-xl bg-primary/[.18] px-4 py-3">
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <HugeiconsIcon icon={Tick02Icon} size={13} strokeWidth={3} />
          </span>
          <div className="min-w-0">
            {confirm.kind === "answered" ? (
              <>
                <p className="font-bold break-keep">{confirm.question.result}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  +10 크레딧
                  {confirm.question.source ? ` · ${confirm.question.source}` : ""}
                </p>
              </>
            ) : (
              <>
                <p className="font-bold break-keep">{SKIP_CONFIRM.title}</p>
                <p className="mt-0.5 text-xs text-muted-foreground">{SKIP_CONFIRM.sub}</p>
              </>
            )}
          </div>
        </div>
      )}

      {done ? (
        <div className="rounded-xl border border-border bg-card px-5 py-8 text-center">
          <p className="text-lg font-bold">가게 정보를 다 알려 주셨어요</p>
          <p className="mt-1 text-sm text-muted-foreground">챙길 것 추천이 더 정확해져요</p>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 min-[760px]:grid-cols-2">
          {cards.map((q) => (
            <li
              key={q.id}
              className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
            >
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 font-bold break-keep">{q.question}</p>
                <span className="shrink-0 text-sm font-bold text-accent-text">+10</span>
              </div>

              <p className="text-sm break-keep text-muted-foreground">{q.why}에 써요</p>

              <ul className="flex flex-wrap gap-2">
                {q.options.map((opt) => (
                  <li key={opt}>
                    <button
                      type="button"
                      aria-pressed={false}
                      onClick={() => answer(q)}
                      className="min-h-10 rounded-full border border-border px-4 py-1.5 text-sm transition-[filter,transform] hover:brightness-125 active:scale-[.98] motion-reduce:transition-none"
                    >
                      {opt}
                    </button>
                  </li>
                ))}
              </ul>

              {/* 건너뛰기는 따로 한 줄 — 선택지와 같은 무게로 보이면 안 된다. */}
              <button
                type="button"
                onClick={() => skip(q)}
                className="min-h-10 self-start text-sm text-muted-foreground underline underline-offset-4 transition-transform active:scale-[.98] motion-reduce:transition-none"
              >
                답하지 않을래요
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
