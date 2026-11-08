import * as SliderPrimitive from "@radix-ui/react-slider"
import {
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
} from "lucide-react"

import { trackArtistLine } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import {
  AudioPlayerDuration,
  AudioPlayerProgress,
  AudioPlayerTime,
} from "@/components/ui/audio-player"

import type { StreamPlayback } from "./use-stream-playback"

/** 이 안에서 시작된 클릭은 곡 상세 열기로 이어지지 않는다.
 *  button/a/input은 자동으로 잡히고, 슬라이더처럼 시맨틱 태그가 아닌 컨트롤은
 *  data-player-control 로 표시한다. 컨트롤을 새로 추가할 때도 이 규칙만 지키면
 *  된다 — 개별 stopPropagation을 빠뜨려 생기는 사고를 막는다. */
const CONTROL_SELECTOR =
  'button, a, input, [role="slider"], [data-player-control]'

/** Bottom player bar — track info · transport+progress · volume/expand.
 *  컨트롤이 없는 빈 영역(과 왼쪽 곡 정보)을 누르면 곡 상세 뷰가 열린다. */
export function PlayerBar({
  playback,
  coverSrc,
  expanded,
  onToggleExpanded,
  onOpenDetail,
}: {
  playback: StreamPlayback
  coverSrc: string | undefined
  expanded: boolean
  onToggleExpanded: () => void
  /** 빈 영역 클릭 — 곡 상세 뷰 열기(이미 열려 있으면 아무 일도 없다) */
  onOpenDetail: () => void
}) {
  const active = playback.active

  const handleBarClick = (e: React.MouseEvent<HTMLElement>) => {
    if (!(e.target instanceof HTMLElement)) return
    // 컨트롤(재생·이전/다음·셔플·반복·탐색바·볼륨·확장 버튼) 클릭은 그대로 둔다
    if (e.target.closest(CONTROL_SELECTOR)) return
    onOpenDetail()
  }

  return (
    <footer
      onClick={handleBarClick}
      className="grid h-20 shrink-0 cursor-pointer grid-cols-[1fr_auto] items-center gap-4 px-4 sm:grid-cols-[1fr_2fr_1fr]"
    >
      {/* left: current track — 눌러서 곡 상세 열기.
          button이라 키보드로도 접근된다(빈 영역 클릭은 마우스 전용). */}
      <button
        type="button"
        onClick={onOpenDetail}
        aria-label={
          active
            ? `${active.title_ko || active.title} 곡 상세 보기`
            : "곡 상세 보기"
        }
        className="flex min-w-0 items-center gap-3 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {coverSrc ? (
          <img
            src={coverSrc}
            alt=""
            aria-hidden
            className="size-11 shrink-0 rounded-md object-cover"
          />
        ) : (
          <span className="size-11 shrink-0 rounded-md bg-card" />
        )}
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold">
            {active ? active.title_ko || active.title : "—"}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {active ? trackArtistLine(active) : ""}
          </span>
        </span>
      </button>

      {/* center: transport + progress */}
      <div className="flex flex-col items-center gap-1">
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="셔플"
            aria-pressed={playback.shuffle}
            onClick={playback.toggleShuffle}
            className={cn(
              "hidden sm:inline-flex",
              playback.shuffle ? "text-primary" : "text-muted-foreground"
            )}
          >
            <Shuffle className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="이전 곡"
            onClick={playback.prev}
            className="text-muted-foreground hover:text-foreground"
          >
            <SkipBack className="size-4 fill-current" />
          </Button>
          <Button
            size="icon"
            className="size-8 rounded-full bg-foreground text-background transition-transform hover:bg-foreground/90 motion-safe:hover:scale-105"
            aria-label={playback.isPlaying ? "일시정지" : "재생"}
            onClick={playback.togglePlay}
          >
            {playback.isPlaying ? (
              <Pause className="size-4 fill-current" />
            ) : (
              <Play className="size-4 fill-current" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="다음 곡"
            onClick={playback.next}
            className="text-muted-foreground hover:text-foreground"
          >
            <SkipForward className="size-4 fill-current" />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="반복"
            aria-pressed={playback.repeat !== "off"}
            onClick={playback.cycleRepeat}
            className={cn(
              "hidden sm:inline-flex",
              playback.repeat !== "off"
                ? "text-primary"
                : "text-muted-foreground"
            )}
          >
            {playback.repeat === "one" ? (
              <Repeat1 className="size-4" />
            ) : (
              <Repeat className="size-4" />
            )}
          </Button>
        </div>
        {/* 탐색바 — 슬라이더는 button이 아니므로 컨트롤로 표시해 둔다 */}
        <div
          data-player-control
          className="group/player hidden w-full max-w-xl cursor-default items-center gap-2 sm:flex"
        >
          <AudioPlayerTime className="w-10 text-right text-xs" />
          <AudioPlayerProgress className="flex-1" />
          <AudioPlayerDuration className="w-10 text-xs" />
        </div>
      </div>

      {/* right: volume + expand */}
      <div className="hidden items-center justify-end gap-2 sm:flex">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={playback.muted ? "음소거 해제" : "음소거"}
          onClick={playback.toggleMute}
          className="text-muted-foreground hover:text-foreground"
        >
          {playback.muted || playback.volume === 0 ? (
            <VolumeX className="size-4" />
          ) : (
            <Volume2 className="size-4" />
          )}
        </Button>
        <SliderPrimitive.Root
          data-player-control
          value={[playback.muted ? 0 : playback.volume]}
          min={0}
          max={1}
          step={0.02}
          onValueChange={(v) => playback.setVolume(v[0])}
          className="relative flex h-4 w-24 cursor-default items-center select-none"
          aria-label="볼륨"
        >
          <SliderPrimitive.Track className="relative h-1 w-full grow overflow-hidden rounded-full bg-muted">
            <SliderPrimitive.Range className="absolute h-full bg-foreground" />
          </SliderPrimitive.Track>
          <SliderPrimitive.Thumb className="block size-2.5 rounded-full bg-foreground outline-none" />
        </SliderPrimitive.Root>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={expanded ? "전체 화면 닫기" : "전체 화면"}
          aria-pressed={expanded}
          onClick={onToggleExpanded}
          className={cn(
            expanded ? "text-primary" : "text-muted-foreground",
            "hover:text-foreground"
          )}
        >
          {expanded ? (
            <Minimize2 className="size-4" />
          ) : (
            <Maximize2 className="size-4" />
          )}
        </Button>
      </div>
    </footer>
  )
}
