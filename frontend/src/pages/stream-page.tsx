import { useMemo, useState } from "react"
import { Navigate, useLocation } from "react-router-dom"

import { useAnalysis } from "@/lib/analysis-store"
import { assignCovers } from "@/lib/covers"
import {
  buildTimeSlots,
  currentSlotIndex,
  resolveBusinessHours,
  slotTracks,
} from "@/lib/time-slots"
import { AudioPlayerProvider } from "@/components/ui/audio-player"
import { CareOverlay } from "@/components/care/care-overlay"
import { ExpandedView } from "@/components/stream/expanded-view"
import { LibrarySidebar } from "@/components/stream/library-sidebar"
import { buildInsuranceHref } from "@/lib/insurance-link"
import { NowPlayingPanel } from "@/components/stream/now-playing-panel"
import { PlayerBar } from "@/components/stream/player-bar"
import { PlaylistHeader } from "@/components/stream/playlist-header"
import { TopNav } from "@/components/stream/top-nav"
import { TrackTable } from "@/components/stream/track-table"
import { useStreamPlayback } from "@/components/stream/use-stream-playback"

interface StreamNavState {
  index?: number
  autoplay?: boolean
}

/** 음악 스트림 페이지 — Spotify 웹 셸(3-패널 + 플레이어 바) 스타일.
 *  전체 뷰포트를 채우고 패널마다 내부 스크롤; 바깥 스크롤 없음. */
export function StreamPage() {
  const { analysis } = useAnalysis()
  if (!analysis?.success || !analysis.music.tracks.length) {
    return <Navigate to="/" replace />
  }
  return (
    <AudioPlayerProvider>
      <StreamContent />
    </AudioPlayerProvider>
  )
}

function StreamContent() {
  const { analysis } = useAnalysis()
  // 챙김 오버레이. StreamPage 안에 두어야 AudioPlayerProvider 가 유지되고
  // 음악이 끊기지 않는다 — care-overlay.tsx 설명 참고.
  const [careOpen, setCareOpen] = useState(false)
  const location = useLocation()
  const navState = (location.state as StreamNavState | null) ?? {}

  const music = analysis!.music
  const bi = analysis!.business_info

  // 영업시간을 3~4구간으로 나눈 시간대별 플레이리스트.
  // 마운트 시각으로 한 번만 계산한다 — 매 렌더 new Date()를 쓰면 결과가 흔들린다.
  const { slots, nowSlotId } = useMemo(() => {
    const now = new Date()
    const built = buildTimeSlots(resolveBusinessHours(analysis!, now))
    return {
      slots: built,
      nowSlotId: built[currentSlotIndex(built, now)]?.id ?? "",
    }
  }, [analysis])

  // 기본 선택 = 지금 시각이 속한 구간
  const [selectedSlotId, setSelectedSlotId] = useState(nowSlotId)
  const activeSlotId =
    slots.find((s) => s.id === selectedSlotId)?.id ?? slots[0]?.id ?? ""

  // 선택된 구간의 트랙이 가운데 뷰(헤더 + 트랙 테이블 + 플레이어)를 채운다
  const tracks = useMemo(
    () =>
      activeSlotId ? slotTracks(music.tracks, activeSlotId) : music.tracks,
    [music.tracks, activeSlotId]
  )

  const playback = useStreamPlayback(tracks, navState)
  const [query, setQuery] = useState("")
  const [expanded, setExpanded] = useState(false)

  // Deterministic artwork per track; playlist art = first track's cover.
  // 곡 목록 순서가 구간마다 달라도 곡별 커버는 그대로여야 하므로 원본 순서로 배정한다.
  const covers = useMemo(
    () => assignCovers(music.tracks.map((t) => t.track_id)),
    [music.tracks]
  )
  const playlistCover = covers.get(tracks[0]?.track_id) ?? "/image/cover-01.jpg"
  const activeCover = playback.active
    ? covers.get(playback.active.track_id)
    : playlistCover

  const playlistLabel = music.playlist_label || "매장 추천 플레이리스트"
  // 가운데 뷰 제목은 선택된 시간대를 따른다 (사이드바 상단은 매장 플레이리스트 유지)
  const activeSlot = slots.find((s) => s.id === activeSlotId)
  const centerTitle = activeSlot ? activeSlot.label : playlistLabel
  const region = (bi.address || "").split(/\s+/).slice(0, 2).join(" ")
  const totalSec = tracks.reduce((s, t) => s + (t.duration_sec || 0), 0)
  const meta = [
    activeSlot?.rangeLabel,
    [bi.business_type, region].filter(Boolean).join(" · "),
    `${tracks.length}곡${totalSec ? `, 약 ${Math.round(totalSec / 60)}분` : ""}`,
  ]
    .filter(Boolean)
    .join(" • ")

  return (
    <div className="flex h-svh flex-col overflow-hidden bg-background">
      <TopNav
        analysis={analysis!}
        query={query}
        onQueryChange={setQuery}
        onOpenCare={() => setCareOpen(true)}
      />
      {careOpen && <CareOverlay onClose={() => setCareOpen(false)} />}

      {/* 3-panel body — 8px gutters, each panel scrolls internally */}
      <div className="flex min-h-0 flex-1 gap-2 px-2">
        <LibrarySidebar
          playlistLabel={playlistLabel}
          storeName={bi.company_name}
          insuranceHref={buildInsuranceHref(analysis!)}
          businessType={bi.business_type}
          trackCount={tracks.length}
          coverSrc={playlistCover}
          isPlaying={playback.isPlaying}
          slots={slots}
          selectedSlotId={activeSlotId}
          nowSlotId={nowSlotId}
          onSelectSlot={setSelectedSlotId}
          slotCover={(id) =>
            covers.get(slotTracks(music.tracks, id)[0]?.track_id ?? "") ??
            "/image/cover-01.jpg"
          }
        />

        {expanded ? (
          <ExpandedView
            analysis={analysis!}
            playback={playback}
            covers={covers}
            playlistLabel={centerTitle}
            onCollapse={() => setExpanded(false)}
          />
        ) : (
          <>
            <main className="scrollbar-hidden min-w-0 flex-1 overflow-y-auto rounded-lg bg-panel">
              <PlaylistHeader
                title={centerTitle}
                owner={bi.company_name || "매장"}
                meta={meta}
                coverSrc={playlistCover}
                playback={playback}
              />
              <TrackTable playback={playback} covers={covers} query={query} />
            </main>
            <NowPlayingPanel
              analysis={analysis!}
              active={playback.active}
              coverSrc={activeCover}
              playlistLabel={centerTitle}
            />
          </>
        )}
      </div>

      <PlayerBar
        playback={playback}
        coverSrc={activeCover}
        expanded={expanded}
        onOpenDetail={() => setExpanded(true)}
        onToggleExpanded={() => setExpanded((e) => !e)}
      />
    </div>
  )
}
