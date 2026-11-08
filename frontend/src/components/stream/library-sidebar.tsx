import { useNavigate } from "react-router-dom"
import { Library, Plus, Volume2 } from "lucide-react"

import type { TimeSlot } from "@/lib/time-slots"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { TimeSlotList } from "@/components/stream/time-slot-list"

/** Left panel — "내 라이브러리": the analysed store as a playlist + promo cards
 *  + 시간대별 플레이리스트 목록. */
export function LibrarySidebar({
  playlistLabel,
  storeName,
  businessType,
  trackCount,
  coverSrc,
  isPlaying,
  slots,
  selectedSlotId,
  nowSlotId,
  onSelectSlot,
  slotCover,
  insuranceHref,
}: {
  playlistLabel: string
  storeName: string
  businessType: string
  trackCount: number
  coverSrc: string
  isPlaying: boolean
  slots: TimeSlot[]
  selectedSlotId: string
  nowSlotId: string
  onSelectSlot: (id: string) => void
  slotCover: (slotId: string) => string
  /** `/insurance.html?...` — 분석된 매장의 실제 값이 쿼리스트링에 실린 링크. */
  insuranceHref: string
}) {
  const navigate = useNavigate()

  return (
    <aside className="scrollbar-hidden hidden w-72 shrink-0 flex-col overflow-y-auto rounded-lg bg-panel md:flex xl:w-80">
      {/* header */}
      <div className="flex items-center justify-between px-4 pt-4 pb-2">
        <span className="flex items-center gap-2 text-base font-bold">
          <Library className="size-5 text-muted-foreground" />내 라이브러리
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="rounded-full text-muted-foreground hover:text-foreground"
          aria-label="새 매장 분석"
          onClick={() => navigate("/")}
        >
          <Plus className="size-4" />
        </Button>
      </div>

      {/* the analysed store as a playlist entry */}
      <div className="px-2">
        <div
          className={cn(
            "flex w-full items-center gap-3 rounded-md p-2 text-left",
            "bg-foreground/5"
          )}
        >
          <img
            src={coverSrc}
            alt={`${playlistLabel} 커버`}
            className="size-12 shrink-0 rounded-md object-cover"
            loading="lazy"
          />
          <span className="min-w-0 flex-1">
            <span
              className={cn(
                "block truncate text-sm font-semibold",
                isPlaying && "text-primary"
              )}
            >
              {playlistLabel}
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              플레이리스트 · {storeName} · {trackCount}곡
            </span>
          </span>
          {isPlaying && (
            <Volume2
              className="size-4 shrink-0 text-primary"
              aria-label="재생 중"
            />
          )}
        </div>
      </div>

      {/* promo card (PM v0.6 3-①: "다른 매장도 분석해 보세요" card removed) */}
      <div className="mt-4 p-2">
        <div className="rounded-lg bg-card p-5">
          <p className="text-base font-bold">매장 분석 리포트</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {businessType || "매장"} 기준 상권·날씨·분위기 분석 결과를 다시 볼
            수 있어요.
          </p>
          <Button
            onClick={() => navigate("/")}
            className="mt-4 h-8 rounded-full bg-foreground px-4 text-xs font-bold text-background hover:bg-foreground/90"
          >
            리포트 보기
          </Button>
        </div>
        {/* 사업장 보험 상담 — public/insurance.html (React 밖 단일 페이지).
            React Router 가 아니라 전체 이동이다: 분석 매장의 실제 값은 쿼리스트링으로 넘긴다. */}
        <div className="mt-2 rounded-lg bg-card p-5">
          <p className="text-base font-bold">사업장 보험 상담</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {storeName || "이 매장"}의 화재·재난배상 보험 대상 여부를 확인하고
            상담을 신청할 수 있어요.
          </p>
          <Button
            onClick={() => window.location.assign(insuranceHref)}
            className="mt-4 h-8 rounded-full bg-foreground px-4 text-xs font-bold text-background hover:bg-foreground/90"
          >
            보험 상담 신청
          </Button>
        </div>
      </div>

      {/* 시간대별 플레이리스트 — 리포트 카드 아래 */}
      <div className="mt-2 pb-4">
        <TimeSlotList
          slots={slots}
          selectedId={selectedSlotId}
          nowId={nowSlotId}
          onSelect={onSelectSlot}
          coverFor={slotCover}
          trackCount={trackCount}
          isPlaying={isPlaying}
        />
      </div>
    </aside>
  )
}
