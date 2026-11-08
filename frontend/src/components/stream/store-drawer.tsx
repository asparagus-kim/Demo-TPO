import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, Store01Icon } from "@hugeicons/core-free-icons"

import type { AnalyseResponse } from "@/lib/api"
import { formatBno } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { StoreMap } from "@/components/stream/store-map"
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer"

/** 상단 프로필 아이콘 → 매장 정보 드로어.
 *  분석 결과 요약과 두 갈래 이동(결과 화면 / 새 분석)을 담는다. */
export function StoreDrawer({
  analysis,
  onOpenCare,
}: {
  analysis: AnalyseResponse
  /** 챙김 화면 열기. 드로어를 닫고 스트림 위에 오버레이로 띄운다. */
  onOpenCare?: () => void
}) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const bi = analysis.business_info
  const amb = analysis.ambience
  const tpo = analysis.tpo_profile
  const places = analysis.google_places
  // Kakao 좌표가 canonical — 없을 때만 Google Places 좌표로 대체 (백엔드와 같은 우선순위)
  const place = analysis.resolved_place
  const mapLocation = place?.location ?? places.location ?? null

  const rating =
    typeof places.rating === "number"
      ? `${places.rating.toFixed(1)}${places.review_count ? ` (리뷰 ${places.review_count})` : ""}`
      : ""

  const rows: [string, string][] = [
    ["사업자등록번호", formatBno(analysis.business_number)],
    ["국세청 상태", analysis.nts_status],
    ["업종", bi.business_type],

    ["상권", analysis.trade_area.label],
    [
      "TPO",
      [tpo.time_label, tpo.place_label, tpo.occasion_label]
        .filter(Boolean)
        .join(" · "),
    ],
    ["날씨", analysis.weather.summary],
    ["구글 평점", rating],
    ["주소", bi.address],
  ]

  // 상호 첫 글자를 아바타로 — 없으면 매장 아이콘으로 대체한다
  const initial = [...(bi.company_name || "").trim()][0] ?? ""

  return (
    <Drawer direction="right" open={open} onOpenChange={setOpen}>
      <DrawerTrigger asChild>
        <Button
          variant="ghost"
          size="lg"
          aria-label={`${bi.company_name || "매장"} 정보 열기`}
          className={cn(
            "group h-11 shrink-0 gap-2 rounded-full py-0 pr-2 pl-1",
            // 기본은 페이지 표면과 같은 톤 → hover 에서 한 단계 떠오른다
            "bg-card ring-1 ring-border transition-[background-color,box-shadow] duration-200",
            "hover:bg-secondary hover:text-foreground hover:ring-primary/50",
            "lg:pr-3",
            open && "bg-secondary ring-primary/50"
          )}
        >
          <span
            className={cn(
              "flex size-9 shrink-0 items-center justify-center rounded-full",
              "bg-primary text-sm font-black text-primary-foreground",
              // 아바타만 살짝 커지며 accent 후광이 번진다
              "shadow-[0_0_0_0_var(--color-primary)] transition-all duration-200",
              "group-hover:scale-105 group-hover:shadow-[0_0_12px_0_var(--color-primary)]",
              open && "scale-105 shadow-[0_0_12px_0_var(--color-primary)]"
            )}
          >
            {initial || (
              <HugeiconsIcon
                icon={Store01Icon}
                strokeWidth={2}
                className="size-4.5"
              />
            )}
          </span>
          <span className="hidden max-w-32 truncate text-sm font-semibold lg:block">
            {bi.company_name || "매장"}
          </span>
          <HugeiconsIcon
            icon={ArrowDown01Icon}
            strokeWidth={2}
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-200",
              "group-hover:text-foreground",
              open && "-rotate-180 text-foreground"
            )}
          />
        </Button>
      </DrawerTrigger>

      <DrawerContent>
        <DrawerHeader>
          <div className="flex items-center gap-3">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
              <HugeiconsIcon
                icon={Store01Icon}
                strokeWidth={2}
                className="size-6"
              />
            </span>
            <span className="min-w-0 flex-1">
              <DrawerTitle className="truncate text-lg font-bold">
                {bi.company_name || "매장"}
              </DrawerTitle>
              <DrawerDescription className="truncate">
                {[bi.business_type, analysis.trade_area.label]
                  .filter(Boolean)
                  .join(" · ") || "분석 완료"}
              </DrawerDescription>
            </span>
          </div>
        </DrawerHeader>

        <div className="scrollbar-hidden flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4">
          {/* E/T/M — 분석으로 산출된 매장 분위기 */}
          <div className="grid grid-cols-3 gap-2">
            {(
              [
                ["에너지", amb.energy],
                ["템포", amb.tempo],
                ["무드", amb.mood],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                className="flex flex-col items-center gap-1 rounded-lg bg-card p-3"
              >
                <span className="text-xs text-muted-foreground">{label}</span>
                <span className="text-lg font-bold">
                  {Math.round(Math.max(0, Math.min(100, value || 0)))}
                </span>
              </div>
            ))}
          </div>

          <dl className="flex flex-col gap-2.5">
            {rows
              .filter(([, value]) => Boolean(value))
              .map(([label, value]) => (
                <div key={label} className="flex items-start gap-3 text-sm">
                  <dt className="w-24 shrink-0 text-muted-foreground">
                    {label}
                  </dt>
                  <dd className="min-w-0 flex-1 break-keep">{value}</dd>
                </div>
              ))}
          </dl>

          <StoreMap
            name={place?.place_name || bi.company_name || "매장"}
            address={place?.address || bi.address}
            placeUrl={place?.place_url || undefined}
            location={mapLocation}
          />
        </div>

        <DrawerFooter>
          {/* 챙김 진입 — [카카오맵에서 보기 · 길찾기] 아래, [분석 결과 보기] 위.
              보조(테두리형)로 두어 파란 메인 버튼은 [분석 결과 보기] 하나만 남긴다. */}
          {onOpenCare && (
            <DrawerClose asChild>
              <Button
                variant="outline"
                size="lg"
                className="h-11 w-full rounded-full font-bold"
                onClick={onOpenCare}
              >
                오늘 챙길 것 보기
              </Button>
            </DrawerClose>
          )}
          <DrawerClose asChild>
            <Button
              size="lg"
              className="h-11 w-full rounded-full font-bold"
              onClick={() => navigate("/")}
            >
              분석 결과 보기
            </Button>
          </DrawerClose>
          <DrawerClose asChild>
            <Button
              variant="outline"
              size="lg"
              className="h-11 w-full rounded-full font-bold"
              onClick={() => navigate("/", { state: { restart: true } })}
            >
              새 사업자번호로 분석
            </Button>
          </DrawerClose>
        </DrawerFooter>
      </DrawerContent>
    </Drawer>
  )
}
