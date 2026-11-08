import { HugeiconsIcon } from "@hugeicons/react"
import { Tick02Icon } from "@hugeicons/core-free-icons"

import { STREAK_DAYS, TODOS } from "@/lib/care-data"
import { ALL_TODOS_DONE, type CareState } from "@/lib/use-care-state"
import { cn } from "@/lib/utils"

/** 요일 7칸. "오늘"은 테두리 원이고, 5개를 다 체크하면 채워진 원이 된다.
 *  각 칸의 모양이 달라 `as const` 로 두면 유니온이 되어 d.done 접근이 깨진다 —
 *  공통 형태를 명시해 둔다. */
interface WeekDay {
  label: string
  /** 이미 지난 날 — 채워진 원 + 체크 */
  done?: boolean
  /** 오늘 칸 — 다 챙기기 전까지는 테두리만 */
  today?: boolean
}

const WEEK: readonly WeekDay[] = [
  { label: "월", done: true },
  { label: "화", done: true },
  { label: "수", done: true },
  { label: "오늘", today: true },
  { label: "금" },
  { label: "토" },
  { label: "일" },
]

/** 2-2 머리 영역 — 제목 · 요일 7칸 · 연속 챙김 줄. */
export function CareHeader({ state }: { state: CareState }) {
  const done = ALL_TODOS_DONE(state)
  const remaining = TODOS.length - state.checked.length

  return (
    <header className="flex flex-col gap-5 pt-2">
      <h1 className="text-[40px] leading-[1.1] font-black tracking-tight break-keep">
        {done ? "오늘 다 챙겼어요" : `챙길 것 ${remaining}개 남았어요`}
      </h1>

      <ul className="flex flex-wrap gap-3" aria-label="이번 주 챙김 현황">
        {WEEK.map((d) => {
          // "오늘"은 다 챙기기 전까지 테두리만, 다 챙기면 채워진다.
          const filled = Boolean(d.done) || (Boolean(d.today) && done)
          return (
            <li key={d.label} className="flex flex-col items-center gap-1">
              <span
                className={cn(
                  "flex size-9 items-center justify-center rounded-full border",
                  filled && "border-primary bg-primary text-primary-foreground",
                  !filled &&
                    ("today" in d && d.today
                      ? "border-2 border-primary text-primary"
                      : "border-muted bg-muted/40 text-muted-foreground")
                )}
              >
                {filled && (
                  <HugeiconsIcon icon={Tick02Icon} size={16} strokeWidth={3} />
                )}
              </span>
              <span
                className={cn(
                  "text-xs",
                  "today" in d && d.today
                    ? "font-bold text-foreground"
                    : "text-muted-foreground"
                )}
              >
                {d.label}
              </span>
            </li>
          )
        })}
      </ul>

      <p className="text-sm text-muted-foreground">
        {done ? (
          <>
            <b className="text-foreground">{STREAK_DAYS + 1}일</b> 연속 다
            챙겼어요 · 내일도 이어가요
          </>
        ) : (
          <>
            <b className="text-foreground">{STREAK_DAYS}일</b> 연속 챙김 중 ·
            오늘 챙기면 <b className="text-foreground">{STREAK_DAYS + 1}일</b>{" "}
            연속
          </>
        )}
      </p>
    </header>
  )
}
