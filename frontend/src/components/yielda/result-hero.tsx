import { RotateCcw } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/yielda/brand"

/** Top-of-page store identity hero — the store name owns this block.
 *  No cover art / playlist info here (that lives in the playlist panel).
 *  `onRestart` (optional) surfaces the "다시 분석하기" pill that returns the
 *  flow to its entry screen; omit it and the pill is not rendered.
 *  `onStream` (optional) renders the "지금 스트리밍하기" CTA stacked directly
 *  below the restart pill (UI 변경요청: 플레이 버튼을 재분석 버튼 아래로). */
export function ResultStoreHero({
  title,
  badge,
  badgeStatus = "ok",
  meta,
  onRestart,
  canPlay = true,
  onStream,
}: {
  title: string
  badge: string
  badgeStatus?: "ok" | "warn" | "bad"
  meta: string
  onRestart?: () => void
  canPlay?: boolean
  onStream?: () => void
}) {
  return (
    <section className="flex flex-col items-center gap-4 bg-card px-4 pt-8 pb-6 sm:flex-row sm:items-start sm:justify-between sm:px-6">
      <div className="flex min-w-0 flex-col items-center gap-2 text-center sm:items-start sm:text-left">
        <span className="flex flex-wrap items-center justify-center gap-2 text-sm font-semibold sm:justify-start">
          매장 분석 완료
          {badge && (
            <span
              className={cn(
                "rounded-full px-3 py-0.5 text-xs font-bold",
                badgeStatus === "ok"
                  ? "bg-primary/15 text-primary"
                  : badgeStatus === "warn"
                    ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                    : "bg-destructive/15 text-destructive"
              )}
            >
              {badge}
            </span>
          )}
        </span>
        <h1 className="text-4xl leading-[1.05] font-black tracking-tight break-keep lg:text-6xl">
          {title}
        </h1>
        {meta && (
          <p className="mt-2 flex flex-wrap items-center justify-center gap-x-1.5 text-sm text-muted-foreground sm:justify-start">
            <BrandMark className="size-6" />
            <span>{meta}</span>
          </p>
        )}
      </div>

      {(onRestart || onStream) && (
        <div className="flex w-full shrink-0 flex-col gap-2 sm:mt-1 sm:w-auto">
          {onRestart && (
            <Button
              variant="outline"
              size="lg"
              className="w-full rounded-full font-bold"
              onClick={onRestart}
            >
              <RotateCcw data-icon="inline-start" />
              다시 분석하기
            </Button>
          )}
          {onStream && (
            <Button
              size="lg"
              className="h-12 w-full rounded-full px-8 text-base font-bold"
              aria-label="추천 플레이리스트 재생"
              disabled={!canPlay}
              onClick={onStream}
            >
              추천 플레이리스트 재생
            </Button>
          )}
        </div>
      )}
    </section>
  )
}
