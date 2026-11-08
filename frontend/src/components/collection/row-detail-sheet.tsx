import { HugeiconsIcon } from "@hugeicons/react"
import { LinkSquare02Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import type { CollectionRow } from "@/lib/collection"
import { labelFor } from "@/lib/collection"

/** 표에서는 접히는 긴 열들(영업시간·판정 기준·상위 곡)을 여기서는 전부 편다. */
const GROUPS: { title: string; columns: string[] }[] = [
  {
    title: "입력값",
    columns: [
      "biz_no",
      "input_company_name",
      "input_address_hint",
      "input_place_id",
      "client",
    ],
  },
  {
    title: "매장 신원",
    columns: [
      "nts_status",
      "store_name",
      "category",
      "category_full",
      "address",
      "region_address",
      "phone",
      "lat",
      "lng",
      "kakao_place_id",
    ],
  },
  {
    title: "상권",
    columns: [
      "district_type",
      "district_method",
      "district_confidence",
      "district_density",
      "district_total_places",
      "district_cafe_pct",
      "district_food_pct",
      "district_bank_pct",
      "district_edu_pct",
      "district_univ_count",
      "district_criteria",
    ],
  },
  {
    title: "외부 신호",
    columns: [
      "hours",
      "hours_source",
      "weather",
      "weather_temp_c",
      "weather_condition",
      "rating",
      "review_count",
      "reviews_analyzed",
      "review_keywords",
      "text_source",
      "web_evidence_count",
      "consistency",
      "consistency_score",
    ],
  },
  {
    title: "분석 결과",
    columns: [
      "energy",
      "tempo",
      "mood",
      "ambience_confidence",
      "tpo_time",
      "tpo_place",
      "tpo_occasion",
    ],
  },
  {
    title: "추천",
    columns: [
      "playlist_label",
      "playlist_track_count",
      "industry_matched",
      "music_pool_size",
      "top_tracks",
    ],
  },
  {
    title: "진단",
    columns: [
      "duration_ms",
      "cache_hit",
      "mock_mode",
      "prompt_version",
      "error",
    ],
  },
]

function value(row: CollectionRow, column: string) {
  const raw = row[column]
  if (raw === null || raw === undefined || raw === "") return null
  if (typeof raw === "boolean") return raw ? "예" : "아니오"
  return String(raw)
}

export function RowDetailSheet({
  row,
  onOpenChange,
}: {
  row: CollectionRow | null
  onOpenChange: (open: boolean) => void
}) {
  const outcome = String(row?.outcome ?? "")
  const mapUrl = String(row?.kakao_place_url ?? "")

  return (
    <Sheet open={row !== null} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {String(row?.store_name ?? "분석 상세")}
            <Badge variant={outcome === "success" ? "secondary" : "outline"}>
              {outcome}
            </Badge>
          </SheetTitle>
          <SheetDescription>
            {String(row?.biz_no ?? "")} · {String(row?.timestamp ?? "")}
          </SheetDescription>
        </SheetHeader>

        <ScrollArea className="min-h-0 flex-1">
          <div className="flex flex-col gap-6 px-4 pb-6">
            {mapUrl ? (
              <Button
                variant="outline"
                size="sm"
                className="self-start"
                asChild
              >
                <a href={mapUrl} target="_blank" rel="noreferrer">
                  <HugeiconsIcon
                    icon={LinkSquare02Icon}
                    data-icon="inline-start"
                  />
                  카카오맵에서 보기
                </a>
              </Button>
            ) : null}

            {GROUPS.map((group) => {
              const entries = group.columns
                .map((column) => [column, value(row ?? {}, column)] as const)
                .filter(([, v]) => v !== null)
              if (entries.length === 0) return null

              return (
                <section key={group.title} className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-bold tracking-wide text-muted-foreground">
                      {group.title}
                    </h3>
                    <Separator className="flex-1" />
                  </div>
                  <dl className="grid grid-cols-[minmax(0,7.5rem)_1fr] gap-x-3 gap-y-1.5 text-sm">
                    {entries.map(([column, v]) => (
                      <div key={column} className="contents">
                        <dt className="truncate text-muted-foreground">
                          {labelFor(column)}
                        </dt>
                        <dd className="break-words">{v}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )
            })}
          </div>
        </ScrollArea>
      </SheetContent>
    </Sheet>
  )
}
