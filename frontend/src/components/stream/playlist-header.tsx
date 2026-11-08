import { List, MoreHorizontal, Pause, Play, Plus, Shuffle } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { BrandMark } from "@/components/yielda/brand"

import type { StreamPlayback } from "./use-stream-playback"

/** Center-panel header (artwork + display title) + action row.
 *  Title = playlist name; `owner` (store name) plays the artist role in the
 *  meta line — the store name itself lives in the top nav / analysis card. */
export function PlaylistHeader({
  title,
  owner,
  meta,
  coverSrc,
  playback,
}: {
  title: string
  owner: string
  meta: string
  coverSrc: string
  playback: StreamPlayback
}) {
  return (
    <>
      {/* hero — scrolls with content */}
      <section className="bg-card px-6 pt-8 pb-6">
        <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-end">
          <img
            src={coverSrc}
            alt={`${title} 플레이리스트 커버`}
            className="size-44 shrink-0 rounded-md object-cover shadow-2xl sm:size-56"
          />
          <div className="flex min-w-0 flex-col items-center gap-2 text-center sm:items-start sm:text-left">
            <span className="text-sm font-semibold">플레이리스트</span>
            <h1 className="text-4xl leading-[1.05] font-black tracking-tight break-keep lg:text-6xl">
              {title}
            </h1>
            <p className="mt-2 flex flex-wrap items-center justify-center gap-x-1.5 text-sm text-white/70 sm:justify-start">
              <BrandMark className="size-6" />
              <span className="font-bold text-white">{owner}</span>
              <span aria-hidden>•</span>
              <span>{meta}</span>
            </p>
          </div>
        </div>
      </section>

      {/* action row */}
      <div className="flex items-center gap-5 px-6 py-5">
        <Button
          size="icon-lg"
          className="size-14 rounded-full shadow-lg transition-transform motion-safe:hover:scale-105"
          aria-label={playback.isPlaying ? "일시정지" : "재생"}
          onClick={playback.togglePlay}
        >
          {playback.isPlaying ? (
            <Pause className="size-6 fill-current" />
          ) : (
            <Play className="size-6 fill-current" />
          )}
        </Button>
        <Button
          variant="ghost"
          size="icon-lg"
          aria-label="셔플"
          aria-pressed={playback.shuffle}
          onClick={playback.toggleShuffle}
          className={cn(
            playback.shuffle ? "text-primary" : "text-muted-foreground",
            "hover:text-foreground"
          )}
        >
          <Shuffle className="size-6" />
        </Button>
        <Button
          variant="ghost"
          size="icon-lg"
          aria-label="라이브러리에 추가"
          className="text-muted-foreground hover:text-foreground"
        >
          <Plus className="size-6" />
        </Button>
        <Button
          variant="ghost"
          size="icon-lg"
          aria-label="더 보기"
          className="text-muted-foreground hover:text-foreground"
        >
          <MoreHorizontal className="size-6" />
        </Button>
        <span className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          목록
          <List className="size-4" />
        </span>
      </div>
    </>
  )
}
