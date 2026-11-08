import { useEffect, useRef } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Cancel01Icon } from "@hugeicons/core-free-icons"

import { useCareState } from "@/lib/use-care-state"
import { CareHeader } from "@/components/care/care-header"
import { CreditCard } from "@/components/care/credit-card"
import { GradeCard } from "@/components/care/grade-card"
import { MFinancialBanner } from "@/components/care/m-financial-banner"
import { NewsList } from "@/components/care/news-list"
import { StoreQuestions } from "@/components/care/store-questions"
import { TodoList } from "@/components/care/todo-list"
import { WeatherStrip } from "@/components/care/weather-strip"

/** 챙김(Care) 화면 — 스트림 위에 덮는 오버레이.
 *
 *  **왜 새 라우트가 아니라 오버레이인가.** `AudioPlayerProvider` 가
 *  `StreamPage` 안에 있다(stream-page.tsx). 별도 라우트로 열면 StreamPage 가
 *  언마운트되면서 재생이 끊긴다 — 기획이 "가능하면 음악이 계속 나오게"를
 *  요청했으므로(항목 1-(3)) 같은 트리 안에 덮는다. 덤으로 /stream 의 세션
 *  가드를 그대로 물려받아 항목 1-(5)가 따로 구현 없이 충족된다.
 *
 *  상태는 `useCareState` 안에만 있고, 닫으면 언마운트되어 사라진다 —
 *  "다시 열 때마다 처음 상태"(규칙 3-(2))가 자동으로 성립한다. */
export function CareOverlay({ onClose }: { onClose: () => void }) {
  const state = useCareState()
  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  // Esc 로 닫기 + 열려 있는 동안 뒤 배경 스크롤 잠금.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = "hidden"
    closeRef.current?.focus()
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-background"
      role="dialog"
      aria-modal="true"
      aria-label="오늘 챙길 것"
      ref={panelRef}
    >
      {/* 닫기 — 데모의 기존 패턴(우상단 ✕). 항목 1-(4)
          폭은 분석 결과 화면(96rem)보다 한 단계 좁은 88rem. 챙김은 글 중심이라
          꽉 채우면 한 줄이 너무 길어진다. 닫기 버튼도 같은 컬럼에 맞춰야
          본문 오른쪽 끝과 줄이 맞는다. */}
      <div className="sticky top-0 z-10 bg-background/85 px-4 py-3 backdrop-blur-[4px]">
        <div className="mx-auto flex w-full max-w-[88rem] justify-end">
          <button
            type="button"
            ref={closeRef}
            onClick={onClose}
            aria-label="챙김 화면 닫기"
            className="flex size-10 items-center justify-center rounded-full bg-card text-foreground transition-[filter,transform] hover:brightness-125 active:scale-[.98] motion-reduce:transition-none"
          >
            <HugeiconsIcon icon={Cancel01Icon} size={20} />
          </button>
        </div>
      </div>

      <div className="mx-auto w-full max-w-[88rem] px-4 pb-16">
        {/* 레이아웃 규칙 3-(4): 2-1 → 두 열(1.45fr / 1fr) → 가로 꽉 찬 2-7, 2-8.
            760px 미만에서는 블록 순서대로 한 열. */}
        <div className="flex flex-col gap-4">
          <WeatherStrip />

          <div className="grid grid-cols-1 gap-4 min-[760px]:grid-cols-[1.45fr_1fr]">
            <div className="flex min-w-0 flex-col gap-4">
              <CareHeader state={state} />
              <TodoList state={state} />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <CreditCard state={state} />
              <GradeCard state={state} />
              <MFinancialBanner />
            </div>
          </div>

          <StoreQuestions state={state} />
          <NewsList state={state} />
        </div>
      </div>
    </div>
  )
}
