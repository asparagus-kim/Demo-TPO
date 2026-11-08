import { Minimize2 } from "lucide-react"

import type { AnalyseResponse } from "@/lib/api"
import { mmss } from "@/lib/format"
import { Button } from "@/components/ui/button"

import { MusicCarousel } from "./music-carousel"
import { StoreAnalysisCard } from "./now-playing-panel"
import type { StreamPlayback } from "./use-stream-playback"

/** Expanded now-playing view (music detail) — 3D 뮤직 캐러셀이 중앙을 차지하고,
 *  아래 2단(매장 분석 / 곡 정보)은 곡 전환에 따라 함께 갱신된다. */
export function ExpandedView({
  analysis,
  playback,
  covers,
  playlistLabel,
  onCollapse,
}: {
  analysis: AnalyseResponse
  playback: StreamPlayback
  covers: Map<string, string>
  playlistLabel: string
  onCollapse: () => void
}) {
  const active = playback.active
  const bgCover =
    (active && covers.get(active.track_id)) || "/image/cover-01.jpg"

  return (
    <section className="relative scrollbar-hidden min-w-0 flex-1 overflow-x-hidden overflow-y-auto rounded-lg bg-panel">
      {/* 배경 — 현재 재생 곡의 커버를 블러 처리해 페이지 배경으로 사용.
          곡이 바뀔 때마다 페이드인. scale로 블러 가장자리 여백을 가린다.
          z-0(음수 아님)이어야 section의 bg-panel 위에 그려진다 — -z-10이면
          부모 배경 뒤로 들어가 보이지 않는다. */}
      <div
        key={active?.track_id}
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 animate-in duration-700 fade-in"
        style={{
          backgroundImage: `url(${bgCover})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: "blur(40px) saturate(2.1) brightness(0.95)",
          transform: "scale(1.15)",
        }}
      />
      {/* 스크림 — 상단 텍스트 대비를 확보하고, 아래쪽은 panel 색으로 완전히
          수렴시켜 스크롤로 배경이 끝나는 경계가 보이지 않게 한다. */}
      <div className="pointer-events-none absolute inset-0 z-0 bg-linear-to-b from-panel/45 via-panel/20 to-panel" />

      {/* top row: context + collapse */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4">
        <span className="truncate text-sm font-bold">{playlistLabel}</span>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="전체 화면 닫기"
          onClick={onCollapse}
          className="text-muted-foreground hover:text-foreground"
        >
          <Minimize2 className="size-4" />
        </Button>
      </div>

      {/* 3D 뮤직 캐러셀 — 가운데 카드 = 현재 재생 곡.
          relative z-10: 배경 레이어(z-0)가 positioned라 static 콘텐츠보다
          위에 그려지므로, 콘텐츠도 명시적으로 띄워야 한다. */}
      <div className="relative z-10 flex min-h-[60svh] flex-col items-center justify-center overflow-hidden px-6 pb-6">
        <MusicCarousel playback={playback} covers={covers} />
      </div>

      {/* below the fold: analysis + credits (reference: About the artist / Credits) */}
      <div className="relative z-10 grid gap-4 px-6 pb-8 lg:grid-cols-2">
        <StoreAnalysisCard analysis={analysis} active={active} />
        {active && (
          <div className="flex h-fit flex-col gap-3 rounded-lg bg-card p-4">
            <p className="text-base font-bold">곡 정보</p>
            <dl className="flex flex-col gap-2 text-sm">
              {/* 제목은 바로 위 대형 아트워크 블록에 이미 표시됨 — 원제부터 */}
              {(
                [
                  ["원제", active.title],
                  ["장르", active.genre_primary?.replace(/_/g, " ") || "-"],
                  ["무드", active.mood_primary || "-"],
                  ["BPM", active.bpm ? String(Math.round(active.bpm)) : "-"],
                  ["길이", mmss(active.duration_sec) || "-"],
                  ["적합도", `${Math.round((active.score || 0) * 100)}점`],
                ] as const
              ).map(([k, v]) => (
                <div key={k} className="flex items-baseline gap-3">
                  <dt className="w-14 shrink-0 text-xs text-muted-foreground">
                    {k}
                  </dt>
                  <dd className="min-w-0 flex-1 font-medium break-words">
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}
      </div>
    </section>
  )
}
