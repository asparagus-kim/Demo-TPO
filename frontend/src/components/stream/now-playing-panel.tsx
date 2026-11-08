import { HugeiconsIcon } from "@hugeicons/react"
import { Store01Icon } from "@hugeicons/core-free-icons"
import { CirclePlus, MoreHorizontal } from "lucide-react"

import type { AnalyseResponse, TrackRecommendation } from "@/lib/api"
import { scoreWord, trackArtistLine } from "@/lib/format"
import { Button } from "@/components/ui/button"
import { StoreMap } from "@/components/stream/store-map"

/** Right panel — current track artwork/info + "매장 분석" card
 *  (repurposes the reference's About-the-artist block). */
export function NowPlayingPanel({
  analysis,
  active,
  coverSrc,
  playlistLabel,
}: {
  analysis: AnalyseResponse
  active: TrackRecommendation | undefined
  coverSrc: string | undefined
  playlistLabel: string
}) {
  // 드로어와 같은 우선순위 — Kakao 좌표가 canonical, 없으면 Google Places 좌표
  const bi = analysis.business_info
  const place = analysis.resolved_place
  const mapLocation = place?.location ?? analysis.google_places.location ?? null

  return (
    <aside className="scrollbar-hidden hidden w-80 shrink-0 flex-col gap-4 overflow-y-auto rounded-lg bg-panel p-4 xl:flex">
      {/* panel title = playlist name (reference: album name) */}
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-base font-bold">{playlistLabel}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="더 보기"
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <MoreHorizontal className="size-4" />
        </Button>
      </div>

      {/* current track */}
      {coverSrc && (
        <img
          src={coverSrc}
          alt={active ? `${active.title_ko || active.title} 커버` : "커버"}
          className="aspect-square w-full rounded-lg object-cover shadow-xl"
        />
      )}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xl font-bold">
            {active ? active.title_ko || active.title : "—"}
          </p>
          <p className="truncate text-sm text-muted-foreground">
            {active ? trackArtistLine(active) : ""}
          </p>
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="보관함에 추가"
          className="shrink-0 text-muted-foreground hover:text-foreground"
        >
          <CirclePlus className="size-5" />
        </Button>
      </div>

      <StoreAnalysisCard analysis={analysis} active={active} />

      {/* 매장 위치 — 분석 카드 아래 추가 블록 (기존 내용 대체 아님) */}
      <StoreMap
        name={place?.place_name || bi.company_name || "매장"}
        address={place?.address || bi.address}
        placeUrl={place?.place_url || undefined}
        location={mapLocation}
      />
    </aside>
  )
}

/** "매장 분석" — the About-the-artist analog fed by the AnalyseResponse. */
export function StoreAnalysisCard({
  analysis,
  active,
}: {
  analysis: AnalyseResponse
  active: TrackRecommendation | undefined
}) {
  const bi = analysis.business_info
  const amb = analysis.ambience
  const tpo = analysis.tpo_profile

  return (
    <div className="flex flex-col gap-4 rounded-lg bg-card p-4">
      <p className="text-base font-bold">매장 분석</p>

      {/* store identity (reference: artist avatar + name + follow) */}
      <div className="flex items-center gap-3">
        <span className="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
          <HugeiconsIcon
            icon={Store01Icon}
            strokeWidth={2}
            className="size-6"
          />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-bold">
            {bi.company_name}
          </span>
          <span className="block truncate text-sm text-muted-foreground">
            {[bi.business_type, analysis.trade_area.label]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </span>
      </div>

      {/* E/T/M ambience bars */}
      <div className="flex flex-col gap-2">
        {(
          [
            ["에너지", amb.energy],
            ["템포", amb.tempo],
            ["무드", amb.mood],
          ] as const
        ).map(([label, v]) => {
          const val = Math.max(0, Math.min(100, v || 0))
          return (
            <div key={label} className="flex items-center gap-2 text-xs">
              <b className="w-9 shrink-0 font-semibold">{label}</b>
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-secondary">
                <i
                  className="block h-full rounded-full bg-primary"
                  style={{ width: `${val}%` }}
                />
              </span>
              <span className="w-14 shrink-0 text-right text-muted-foreground">
                {scoreWord(val)}
              </span>
            </div>
          )
        })}
      </div>

      {/* context lines: weather + TPO */}
      <dl className="flex flex-col gap-1.5 border-t border-border pt-3 text-sm">
        <ContextRow label="날씨" value={analysis.weather.summary || "-"} />
        <ContextRow label="시간대" value={tpo.time_label || "-"} />
        <ContextRow label="상황" value={tpo.occasion_label || "-"} />
      </dl>

      {/* interpretation (reference: artist bio) */}
      {amb.explanations?.length > 0 && (
        <p className="line-clamp-3 text-sm leading-relaxed text-muted-foreground">
          {amb.explanations.slice(0, 2).join(" ")}
        </p>
      )}

      {/* current track reason (reference: credits) */}
      {active?.reason && (
        <div className="border-t border-border pt-3">
          <p className="text-sm font-bold">이 곡을 추천한 이유</p>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            {active.reason}
          </p>
        </div>
      )}
    </div>
  )
}

function ContextRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="w-12 shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 flex-1 truncate font-medium">{value}</dd>
    </div>
  )
}
