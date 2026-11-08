import { Clock01Icon } from "@hugeicons/core-free-icons"
import { HugeiconsIcon } from "@hugeicons/react"
import { Volume2 } from "lucide-react"

import type { TimeSlot } from "@/lib/time-slots"
import { cn } from "@/lib/utils"

/** 시간대별 플레이리스트 — 영업시간을 3~4구간으로 나눈 카드 목록.
 *  현재 시각에 해당하는 구간이 기본 선택되고, 다른 항목을 누르면
 *  가운데 뷰가 그 플레이리스트로 바뀐다. */
export function TimeSlotList({
  slots,
  selectedId,
  nowId,
  onSelect,
  coverFor,
  trackCount,
  isPlaying,
}: {
  slots: TimeSlot[]
  selectedId: string
  /** 지금 시각이 속한 구간 — "지금" 배지를 붙인다 */
  nowId: string
  onSelect: (id: string) => void
  coverFor: (slotId: string) => string
  trackCount: number
  isPlaying: boolean
}) {
  if (!slots.length) return null

  return (
    <div className="flex flex-col gap-2 px-2 pb-2">
      <p className="flex items-center gap-1.5 px-2 text-xs font-bold tracking-wide text-muted-foreground">
        <HugeiconsIcon
          icon={Clock01Icon}
          strokeWidth={2}
          className="size-3.5"
        />
        시간대별 플레이리스트
      </p>

      <ul className="flex flex-col gap-1">
        {slots.map((slot) => {
          const selected = slot.id === selectedId
          const isNow = slot.id === nowId
          return (
            <li key={slot.id}>
              <button
                type="button"
                aria-current={selected}
                onClick={() => onSelect(slot.id)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md p-2 text-left transition-colors",
                  selected ? "bg-foreground/10" : "hover:bg-foreground/5"
                )}
              >
                <img
                  src={coverFor(slot.id)}
                  alt=""
                  loading="lazy"
                  className="size-11 shrink-0 rounded-md object-cover"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        "truncate text-sm font-semibold",
                        selected && isPlaying && "text-primary"
                      )}
                    >
                      {slot.label}
                    </span>
                    {isNow && (
                      <span className="shrink-0 rounded-full bg-primary/15 px-1.5 py-0.5 text-[10px] font-bold text-primary">
                        지금
                      </span>
                    )}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {slot.rangeLabel} · {trackCount}곡
                  </span>
                </span>
                {selected && isPlaying && (
                  <Volume2
                    className="size-4 shrink-0 text-primary"
                    aria-label="재생 중"
                  />
                )}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
