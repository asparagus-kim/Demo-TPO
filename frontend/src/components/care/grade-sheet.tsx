import { useEffect, useRef } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Cancel01Icon } from "@hugeicons/core-free-icons"

import { GRADES, GRADE_SHEET_FOOTNOTE } from "@/lib/care-data"
import type { CareState } from "@/lib/use-care-state"
import { cn } from "@/lib/utils"

/** 2-9 등급 기준 시트 — 2-4의 "등급 기준 ›" 으로 연다.
 *  ✕ 와 바깥 어두운 영역 클릭으로 닫힌다(기획 명시). */
export function GradeSheet({ state, onClose }: { state: CareState; onClose: () => void }) {
  const { grade, gradeIndex, nextGrade, totalCredits, remainingToNext } = state
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    closeRef.current?.focus()
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])

  // 지금 등급 구간 안에서의 진행률. 마지막 등급이면 가득 찬 것으로 본다.
  const progress = nextGrade
    ? (totalCredits - grade.min) / (nextGrade.min - grade.min)
    : 1

  return (
    <div
      className="fixed inset-0 z-[60] flex items-end justify-center bg-black/60 p-0 min-[760px]:items-center min-[760px]:p-6"
      onClick={onClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="일다 등급 기준"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85svh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-panel p-6 min-[760px]:rounded-2xl"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs text-muted-foreground">일다 등급</p>
            <h2 className="mt-0.5 text-xl font-bold break-keep">
              {grade.name} · {totalCredits.toLocaleString("ko-KR")} 크레딧
            </h2>
          </div>
          <button
            type="button"
            ref={closeRef}
            onClick={onClose}
            aria-label="등급 기준 닫기"
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-card transition-[filter,transform] hover:brightness-125 active:scale-[.98] motion-reduce:transition-none"
          >
            <HugeiconsIcon icon={Cancel01Icon} size={18} />
          </button>
        </div>

        <div
          className="mt-4 h-2 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={Math.round(progress * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none"
            style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
          />
        </div>

        {nextGrade && (
          <p className="mt-2 text-sm text-muted-foreground">
            {nextGrade.name}까지 {remainingToNext.toLocaleString("ko-KR")} 크레딧 남았어요
          </p>
        )}

        <ul className="mt-5 flex flex-col gap-2">
          {GRADES.map((g, i) => (
            <li
              key={g.name}
              className={cn(
                "flex items-center gap-3 rounded-xl border p-3",
                i === gradeIndex ? "border-primary bg-primary/[.18]" : "border-border bg-card",
                // 지금보다 아래 등급은 흐리게 — 이미 지나온 구간이다.
                i < gradeIndex && "opacity-50",
              )}
            >
              <img src={g.image} alt="" aria-hidden="true" className="size-11 shrink-0 object-contain" />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 font-bold break-keep">
                  {g.name}
                  {i === gradeIndex && (
                    <span className="rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">
                      지금
                    </span>
                  )}
                </p>
                <p className="text-xs text-muted-foreground">
                  {g.min.toLocaleString("ko-KR")} 크레딧부터
                </p>
                <p className="mt-0.5 text-sm break-keep">{g.perk}</p>
              </div>
            </li>
          ))}
        </ul>

        <p className="mt-5 text-xs leading-relaxed break-keep text-muted-foreground">
          {GRADE_SHEET_FOOTNOTE}
        </p>
      </div>
    </div>
  )
}
