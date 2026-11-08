import { Clock3, Play } from "lucide-react"

import { mmss, trackArtistLine } from "@/lib/format"
import { cn } from "@/lib/utils"

import type { StreamPlayback } from "./use-stream-playback"

/** Spotify-style track table — #/eq column, artwork+title, reason, BPM, duration. */
export function TrackTable({
  playback,
  covers,
  query,
}: {
  playback: StreamPlayback
  covers: Map<string, string>
  query: string
}) {
  const q = query.trim().toLowerCase()
  const rows = playback.tracks
    .map((track, index) => ({ track, index }))
    .filter(
      ({ track }) =>
        !q ||
        [track.title_ko, track.title, track.genre_primary, track.mood_primary]
          .filter(Boolean)
          .some((s) => String(s).toLowerCase().includes(q))
    )

  return (
    <div className="px-4 pb-6 sm:px-6">
      {/* header */}
      <div className="grid grid-cols-[2rem_1fr_3rem] items-center gap-4 border-b border-border px-3 pb-2 text-sm text-muted-foreground lg:grid-cols-[2rem_1.4fr_1fr_3rem_3rem]">
        <span className="text-center">#</span>
        <span>제목</span>
        <span className="hidden lg:block">추천 이유</span>
        <span className="hidden text-right lg:block">BPM</span>
        <span className="flex justify-end">
          <Clock3 className="size-4" aria-label="재생 시간" />
        </span>
      </div>

      <ul className="pt-2">
        {rows.map(({ track: t, index: i }) => {
          const isActive = playback.isTrackActive(t.track_id)
          const isPlayingThis = isActive && playback.isPlaying
          return (
            <li key={t.track_id}>
              <button
                type="button"
                onClick={() =>
                  isPlayingThis ? playback.togglePlay() : playback.playAt(i)
                }
                className={cn(
                  "group grid w-full grid-cols-[2rem_1fr_3rem] items-center gap-4 rounded-md px-3 py-2 text-left transition-colors hover:bg-foreground/8 lg:grid-cols-[2rem_1.4fr_1fr_3rem_3rem]",
                  isActive && "bg-foreground/5"
                )}
              >
                {/* # / equalizer / hover play */}
                <span className="flex items-center justify-center text-sm text-muted-foreground tabular-nums">
                  {isPlayingThis ? (
                    <>
                      <EqBars className="group-hover:hidden" />
                      <Play className="hidden size-4 fill-current text-foreground group-hover:block" />
                    </>
                  ) : (
                    <>
                      <span
                        className={cn(
                          "group-hover:hidden",
                          isActive && "text-primary"
                        )}
                      >
                        {i + 1}
                      </span>
                      <Play className="hidden size-4 fill-current text-foreground group-hover:block" />
                    </>
                  )}
                </span>

                {/* artwork + title + sub */}
                <span className="flex min-w-0 items-center gap-3">
                  <img
                    src={covers.get(t.track_id)}
                    alt=""
                    aria-hidden
                    className="size-10 shrink-0 rounded object-cover"
                    loading="lazy"
                  />
                  <span className="min-w-0">
                    <span
                      className={cn(
                        "block truncate text-base font-semibold",
                        isActive && "text-primary"
                      )}
                    >
                      {t.title_ko || t.title || t.track_id}
                    </span>
                    <span className="block truncate text-sm text-muted-foreground">
                      {trackArtistLine(t)}
                    </span>
                  </span>
                </span>

                <span className="hidden min-w-0 truncate text-sm text-muted-foreground lg:block">
                  {t.reason}
                </span>
                <span className="hidden text-right text-sm text-muted-foreground tabular-nums lg:block">
                  {t.bpm ? Math.round(t.bpm) : "-"}
                </span>
                <span className="text-right text-sm text-muted-foreground tabular-nums">
                  {mmss(t.duration_sec) || "-:--"}
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      {rows.length === 0 && (
        <p className="px-3 py-8 text-center text-sm text-muted-foreground">
          "{query}" 검색 결과가 없습니다.
        </p>
      )}

      {playback.error && (
        <p className="px-3 pt-2 text-sm text-destructive">
          이 곡을 재생할 수 없습니다 (음원 준비 중). 다른 곡을 선택해 주세요.
        </p>
      )}
    </div>
  )
}

/** Animated 3-bar equalizer shown on the playing row. */
export function EqBars({ className }: { className?: string }) {
  return (
    <span
      className={cn("flex h-3.5 items-end gap-0.5", className)}
      aria-label="재생 중"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-0.5 animate-pulse rounded-sm bg-primary motion-reduce:animate-none"
          style={{
            height: `${[70, 100, 55][i]}%`,
            animationDelay: `${i * 150}ms`,
            animationDuration: "800ms",
          }}
        />
      ))}
    </span>
  )
}
