import { Clock3, Play } from "lucide-react"

import type { TrackRecommendation } from "@/lib/api"
import { mmss, trackArtistLine } from "@/lib/format"
import { cn } from "@/lib/utils"

/** Spotify-style track table for the analysis result.
 *  Rows navigate to /stream on click. */
export function ResultTrackList({
  tracks,
  covers,
  onSelect,
}: {
  tracks: TrackRecommendation[]
  covers: Map<string, string>
  onSelect: (index: number) => void
}) {
  return (
    <div>
      {/* column header */}
      <div className="mt-5 grid grid-cols-[2rem_1fr_3rem] items-center gap-4 border-b border-border px-4 pb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase lg:grid-cols-[2rem_1.2fr_1fr_5rem_3.5rem]">
        <span className="text-center">#</span>
        <span>제목</span>
        <span className="hidden lg:block">추천 이유</span>
        <span className="hidden text-center lg:block">적합도</span>
        <span className="flex justify-end">
          <Clock3 className="size-3.5" aria-label="재생 시간" />
        </span>
      </div>

      <ul className="flex flex-col gap-0.5 pt-1">
        {tracks.map((t, i) => {
          const dots = Math.max(1, Math.min(5, Math.round((t.score || 0) * 5)))
          const sub = [
            trackArtistLine(t),
            t.bpm ? `${Math.round(t.bpm)} BPM` : "",
          ]
            .filter(Boolean)
            .join(" · ")
          return (
            <li key={t.track_id}>
              <button
                type="button"
                onClick={() => onSelect(i)}
                className="group grid w-full grid-cols-[2rem_1fr_3rem] items-center gap-4 rounded-lg px-4 py-3 text-left transition-colors hover:bg-card lg:grid-cols-[2rem_1.2fr_1fr_5rem_3.5rem]"
              >
                {/* # / hover play */}
                <span className="relative flex items-center justify-center text-sm text-muted-foreground tabular-nums">
                  <span className="transition-opacity group-hover:opacity-0">
                    {i + 1}
                  </span>
                  <Play className="absolute size-4 fill-current text-primary opacity-0 transition-opacity group-hover:opacity-100" />
                </span>

                {/* artwork + title + sub */}
                <span className="flex min-w-0 items-center gap-3">
                  <img
                    src={covers.get(t.track_id)}
                    alt=""
                    aria-hidden
                    className="size-11 shrink-0 rounded-md object-cover shadow-sm"
                    loading="lazy"
                  />
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-bold group-hover:text-primary">
                      {t.title_ko || t.title || t.track_id}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {sub}
                    </span>
                  </span>
                </span>

                {/* reason */}
                <span className="hidden min-w-0 truncate text-xs leading-relaxed text-muted-foreground lg:block">
                  {t.reason}
                </span>

                {/* match dots */}
                <span
                  className="hidden justify-center gap-1 lg:flex"
                  title={`적합도 ${dots}/5`}
                >
                  {Array.from({ length: 5 }, (_, k) => (
                    <i
                      key={k}
                      className={cn(
                        "size-2 rounded-full transition-colors",
                        k < dots ? "bg-primary" : "bg-border"
                      )}
                    />
                  ))}
                </span>

                {/* duration */}
                <span className="text-right text-xs text-muted-foreground tabular-nums">
                  {mmss(t.duration_sec) || "-:--"}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
