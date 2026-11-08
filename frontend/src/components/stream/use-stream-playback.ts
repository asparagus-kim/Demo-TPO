import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { TrackRecommendation } from "@/lib/api"
import { useAudioPlayer } from "@/components/ui/audio-player"

export type RepeatMode = "off" | "all" | "one"

/** <audio> 엘리먼트(외부 시스템)에 볼륨/음소거를 반영한다. */
function applyVolume(
  el: HTMLAudioElement | null,
  volume: number,
  muted: boolean
) {
  if (!el) return
  el.volume = volume
  el.muted = muted
}

export interface StreamPlayback {
  tracks: TrackRecommendation[]
  /** Track shown in UI (rAF-synced activeItem is fine for display purposes). */
  active: TrackRecommendation | undefined
  isPlaying: boolean
  error: MediaError | null
  shuffle: boolean
  repeat: RepeatMode
  volume: number
  muted: boolean
  isTrackActive: (trackId: string) => boolean
  playAt: (index: number) => void
  togglePlay: () => void
  next: () => void
  prev: () => void
  toggleShuffle: () => void
  cycleRepeat: () => void
  setVolume: (v: number) => void
  toggleMute: () => void
}

interface BootState {
  index?: number
  autoplay?: boolean
}

/** All playback behaviour for /stream — extracted from the original page.
 *
 *  CRITICAL: the current track index is tracked in `currentIndexRef`, never
 *  derived from the provider's `activeItem`. The provider syncs UI state via
 *  requestAnimationFrame, which freezes in background tabs — and playing music
 *  with the tab in the background is the primary usage in a store. If
 *  auto-advance read rAF-derived state, the same song would repeat forever. */
export function useStreamPlayback(
  tracks: TrackRecommendation[],
  boot: BootState
): StreamPlayback {
  const player = useAudioPlayer<TrackRecommendation>()

  const items = useMemo(
    () =>
      tracks.map((t) => ({
        id: t.track_id,
        src: t.audio_url,
        data: t,
      })),
    [tracks]
  )

  const [shuffle, setShuffle] = useState(false)
  const [repeat, setRepeat] = useState<RepeatMode>("off")
  const [volume, setVolumeState] = useState(1)
  const [muted, setMuted] = useState(false)

  // 셔플 순서 — 켤 때마다 새로 섞는다 (현재 곡을 맨 앞에 둔다)
  const orderRef = useRef<number[]>(tracks.map((_, i) => i))
  // 현재 곡 인덱스는 ref로 직접 추적한다 (배경 탭에서 rAF가 멈추기 때문).
  const currentIndexRef = useRef(0)

  const toggleShuffle = useCallback(() => {
    setShuffle((s) => {
      const next = !s
      const cur = currentIndexRef.current
      if (next) {
        const rest = tracks.map((_, i) => i).filter((i) => i !== cur)
        for (let i = rest.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1))
          ;[rest[i], rest[j]] = [rest[j], rest[i]]
        }
        orderRef.current = [cur, ...rest]
      } else {
        orderRef.current = tracks.map((_, i) => i)
      }
      return next
    })
  }, [tracks])

  const playAt = useCallback(
    (index: number) => {
      const item = items[index]
      if (!item) return
      currentIndexRef.current = index
      void player.play(item)
    },
    [items, player]
  )

  const step = useCallback(
    (dir: 1 | -1) => {
      const order = orderRef.current
      const pos = order.indexOf(currentIndexRef.current)
      if (pos === -1) {
        playAt(order[0] ?? 0)
        return
      }
      let nextPos = pos + dir
      if (nextPos >= order.length) {
        if (repeat === "off") return
        nextPos = 0
      }
      if (nextPos < 0) nextPos = order.length - 1
      playAt(order[nextPos])
    },
    [playAt, repeat]
  )

  const prev = useCallback(() => {
    // Spotify 규칙: 3초 이상 재생됐으면 처음으로, 아니면 이전 곡
    const el = player.ref.current
    if (el && el.currentTime > 3) {
      player.seek(0)
      return
    }
    step(-1)
  }, [player, step])

  // 곡이 끝나면 repeat/shuffle 규칙대로 다음 곡 — refs라 배경 탭에서도 동작
  const stepRef = useRef(step)
  const repeatRef = useRef(repeat)
  useEffect(() => {
    stepRef.current = step
    repeatRef.current = repeat
  }, [step, repeat])
  useEffect(() => {
    const el = player.ref.current
    if (!el) return
    const onEnded = () => {
      if (repeatRef.current === "one") {
        el.currentTime = 0
        void el.play()
        return
      }
      stepRef.current(1)
    }
    el.addEventListener("ended", onEnded)
    return () => el.removeEventListener("ended", onEnded)
  }, [player.ref])

  // 볼륨 반영 (외부 시스템인 <audio> 엘리먼트 동기화)
  useEffect(() => {
    applyVolume(player.ref.current, volume, muted)
  }, [volume, muted, player.ref])

  // 진입 시 지정 곡 로드 (+autoplay)
  const bootRef = useRef(false)
  useEffect(() => {
    if (bootRef.current) return
    bootRef.current = true
    const idx = Math.min(Math.max(boot.index ?? 0, 0), items.length - 1)
    currentIndexRef.current = idx
    if (boot.autoplay) {
      playAt(idx)
    } else {
      void player.setActiveItem(items[idx])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const togglePlay = useCallback(() => {
    if (player.isPlaying) {
      player.pause()
    } else {
      void player.play(player.activeItem ?? items[0])
    }
  }, [player, items])

  const active = player.activeItem?.data ?? tracks[0]

  return {
    tracks,
    active,
    isPlaying: player.isPlaying,
    error: player.error,
    shuffle,
    repeat,
    volume,
    muted,
    isTrackActive: (trackId) => player.isItemActive(trackId),
    playAt,
    togglePlay,
    next: () => step(1),
    prev,
    toggleShuffle,
    cycleRepeat: () =>
      setRepeat((r) => (r === "off" ? "all" : r === "all" ? "one" : "off")),
    setVolume: (v) => {
      setVolumeState(v)
      if (v > 0) setMuted(false)
    },
    toggleMute: () => setMuted((m) => !m),
  }
}
