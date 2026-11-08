import { useEffect, useMemo, useRef, useState } from "react"
import { Pause, Play } from "lucide-react"

import { trackArtistLine } from "@/lib/format"
import { cn } from "@/lib/utils"

import type { StreamPlayback } from "./use-stream-playback"

/** 3D 뮤직 캐러셀 — V자 원근 배치의 "매트 카드" 스와이퍼.
 *  마우스 드래그·터치 스와이프로 카드가 손끝을 실시간으로 따라오고, 놓으면 가장
 *  가까운 카드로 스냅한다. 방향키·카드 클릭도 동일하게 동작하며, 휠 구조라 양옆에
 *  항상 카드가 있고 끝에서 반대편으로 감긴다. 가운데 카드 = 현재 재생 곡 —
 *  카드 전환은 실제 재생(playAt)도 함께 바꾼다.
 *  배경 블러 이미지는 ExpandedView(페이지 전체)가 담당한다. */

const CARD_W = 280 // 커버 한 변(px)
const STEP_X = 200 // 카드 1칸당 가로 이동량
const ANGLE = 26 // 옆 카드 rotateY 각도 — V자 원근의 핵심
const DEPTH = 110 // 카드 1칸당 뒤로 밀리는 translateZ
const VISIBLE = 2 // 중앙 기준 좌우로 보이는 카드 수 — 총 5장(중앙 1 + 양쪽 2)
/** 이 비율 이상 끌면 다음 카드로 넘어간다 (STEP_X 대비) */
const COMMIT_RATIO = 0.22
/** 이 픽셀 이상 움직여야 드래그로 본다. 마우스·트랙패드는 클릭할 때도 몇 px
 *  흔들리므로 너무 작게 잡으면 재생 버튼 클릭이 드래그로 오인돼 삼켜진다. */
const DRAG_SLOP = 8

/** 정수·소수 offset 모두를 받는다 — 드래그 중에는 소수라 카드가 연속으로 움직인다. */
function cardTransform(offset: number): string {
  const abs = Math.abs(offset)
  // 1 = 정중앙, 0 = 한 칸 이상 떨어짐 — 중앙 강조 효과를 연속적으로 보간한다
  const center = Math.max(0, 1 - abs)
  const rotate = -Math.sign(offset) * ANGLE * Math.min(abs, 1)
  const z = 24 * center - DEPTH * abs
  const y = -6 * center
  const scale = 1 + 0.05 * center
  return [
    `translateX(calc(-50% + ${offset * STEP_X}px))`,
    `translateY(${y}px)`,
    `translateZ(${z}px)`,
    `rotateY(${rotate}deg)`,
    `scale(${scale})`,
  ].join(" ")
}

/** 이벤트가 발생한 지점의 카드 인덱스. 카드 밖이면 null. */
function cardIndexFromEvent(target: EventTarget | null): number | null {
  if (!(target instanceof HTMLElement)) return null
  const card = target.closest('[id^="carousel-card-"]')
  if (!card) return null
  const n = Number(card.id.replace("carousel-card-", ""))
  return Number.isNaN(n) ? null : n
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.isContentEditable
  )
}

export function MusicCarousel({
  playback,
  covers,
}: {
  playback: StreamPlayback
  covers: Map<string, string>
}) {
  const { tracks, active, isPlaying, playAt, togglePlay } = playback
  const count = tracks.length

  const activeIndex = useMemo(() => {
    const i = tracks.findIndex((t) => t.track_id === active?.track_id)
    return i === -1 ? 0 : i
  }, [tracks, active])

  // 휠 구조: 최단 경로의 부호 있는 원형 거리 (예: 10곡이면 -5..+4)
  const circularOffset = (index: number): number => {
    let off = (index - activeIndex) % count
    const half = count / 2
    if (off > half) off -= count
    if (off < -half) off += count
    return off
  }

  const goTo = (index: number) => {
    const target = ((index % count) + count) % count
    if (target === activeIndex) return
    playAt(target)
  }

  // 방향키 내비 — 검색창 등 입력 중에는 무시한다. 끝에서는 반대편으로 감긴다.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return
      e.preventDefault()
      const next = e.key === "ArrowLeft" ? activeIndex - 1 : activeIndex + 1
      const target = ((next % count) + count) % count
      if (target !== activeIndex) playAt(target)
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [activeIndex, count, playAt])

  // ── 드래그 스와이퍼 ────────────────────────────────────────────────
  // dragX(px)를 state로 들고 카드 transform에 실시간 반영한다. 드래그 중에는
  // transition을 꺼서 손끝을 1:1로 따라오게 하고, 놓는 순간 다시 켜서 스냅한다.
  const [dragX, setDragX] = useState(0)
  const [dragging, setDragging] = useState(false)
  // 실제로 끌기 시작했는지 — 단순 클릭(누르기)과 구분한다. hover 재생 버튼을
  // 숨기는 기준은 이 값이어야 한다. `dragging`으로 숨기면 버튼을 누르는 순간
  // 커서 아래에서 버튼이 사라져 클릭이 불가능해 보인다.
  const [dragMoved, setDragMoved] = useState(false)
  const startXRef = useRef(0)
  const draggingRef = useRef(false)
  const movedRef = useRef(false)
  /** pointerdown이 어느 카드 위에서 시작됐는지 — 탭 판정에 쓴다 */
  const downIndexRef = useRef<number | null>(null)

  const onPointerDown = (e: React.PointerEvent) => {
    // 마우스는 주 버튼만 — 우클릭/가운데 클릭으로 드래그가 시작되면 안 된다
    if (e.pointerType === "mouse" && e.button !== 0) return
    draggingRef.current = true
    movedRef.current = false
    startXRef.current = e.clientX
    downIndexRef.current = cardIndexFromEvent(e.target)
    setDragging(true)
    setDragMoved(false)
    setDragX(0)
    // 커서가 카드 밖으로 나가도 계속 이벤트를 받도록 고정한다.
    // 브라우저가 pointerId를 활성으로 보지 않으면 throw할 수 있어 무시한다.
    try {
      e.currentTarget.setPointerCapture(e.pointerId)
    } catch {
      // 캡처 실패해도 아래 delta 계산은 그대로 동작한다
    }
  }

  const onPointerMove = (e: React.PointerEvent) => {
    if (!draggingRef.current) return
    const dx = e.clientX - startXRef.current
    if (Math.abs(dx) > DRAG_SLOP) {
      movedRef.current = true
      setDragMoved(true)
    }
    setDragX(dx)
  }

  const endDrag = (e: React.PointerEvent) => {
    if (!draggingRef.current) return
    draggingRef.current = false
    setDragging(false)
    // 시각 상태만 즉시 복구한다 — 클릭 억제는 movedRef가 담당하며 다음
    // pointerdown 까지 유지되므로, 드래그 직후의 클릭은 여전히 무시된다.
    setDragMoved(false)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // 캡처하지 못했던 포인터를 해제할 때도 여기로 온다 — 무시
    }
    const dx = e.clientX - startXRef.current
    setDragX(0)

    // 움직이지 않았으면 탭 — 눌렀던 카드를 활성화한다.
    // 포인터 캡처 중에는 click 이벤트가 캡처 대상(무대 div)으로 가기 때문에
    // 카드 버튼의 onClick이 아예 발생하지 않는다. 그래서 탭도 여기서 처리한다.
    if (!movedRef.current) {
      const index = downIndexRef.current
      downIndexRef.current = null
      if (index !== null) activateCard(index)
      return
    }
    downIndexRef.current = null

    if (Math.abs(dx) < STEP_X * COMMIT_RATIO) return
    // 멀리 끌었으면 여러 칸 이동 — 왼쪽으로 밀면 다음 곡
    const steps = Math.max(1, Math.round(Math.abs(dx) / STEP_X))
    goTo(activeIndex + (dx < 0 ? steps : -steps))
  }

  /** 가운데 카드면 재생/일시정지, 옆 카드면 그 곡으로 이동해 재생한다. */
  const activateCard = (index: number) => {
    if (index === activeIndex) {
      togglePlay()
      return
    }
    goTo(index)
  }

  // 드래그 중에는 카드 전체가 dragX만큼 밀린다 (칸 단위로 환산)
  const dragOffset = dragX / STEP_X

  return (
    <div
      className={cn(
        "relative w-full touch-pan-y select-none",
        dragging ? "cursor-grabbing" : "cursor-grab"
      )}
      style={{ height: CARD_W + 190 }}
      role="listbox"
      aria-label="추천 트랙 캐러셀"
      aria-activedescendant={`carousel-card-${activeIndex}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
    >
      {/* 원근 무대 — 자식 카드들이 하나의 3D 공간을 공유한다.
          pointer-events-none이 필수다: preserve-3d 공간에서 옆 카드는
          translateZ가 음수라 이 무대 평면(z=0)보다 뒤에 있고, 무대가 히트
          테스트를 가로채 옆 카드의 hover·클릭이 통째로 죽는다. 카드에서만
          pointer-events를 다시 켠다. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{ perspective: "1200px", transformStyle: "preserve-3d" }}
      >
        {tracks.map((track, i) => {
          const offset = circularOffset(i) + dragOffset
          const abs = Math.abs(offset)
          const hidden = abs > VISIBLE + 0.5
          const cover = covers.get(track.track_id) ?? "/image/cover-01.jpg"
          const isCenter = Math.round(offset) === 0
          const isCurrent = i === activeIndex
          const title = track.title_ko || track.title
          return (
            <button
              key={track.track_id}
              id={`carousel-card-${i}`}
              type="button"
              role="option"
              aria-selected={isCurrent}
              aria-label={
                isCurrent
                  ? `${title} — ${isPlaying ? "일시정지" : "재생"}`
                  : `${title} 재생`
              }
              tabIndex={hidden ? -1 : 0}
              // 포인터 입력은 endDrag의 탭 판정이 처리한다. 여기서는 키보드로
              // 발생한 클릭(Enter/Space — detail === 0)만 받아 중복 실행을 막는다.
              onClick={(e) => {
                if (e.detail === 0) activateCard(i)
              }}
              className={cn(
                "group absolute top-4 left-1/2 flex flex-col rounded-2xl bg-popover p-2.5 shadow-2xl ring-1 ring-border outline-none",
                // 드래그 중에는 transition을 완전히 끈다 — 손끝을 1:1로 따라와야 한다
                dragging
                  ? "transition-none"
                  : "transition-[transform,opacity] duration-500 ease-out motion-reduce:transition-none",
                hidden ? "pointer-events-none" : "pointer-events-auto"
              )}
              style={{
                width: CARD_W,
                transform: cardTransform(offset),
                transformStyle: "preserve-3d",
                zIndex: 50 - Math.round(abs),
                opacity: hidden ? 0 : Math.max(0, 1 - abs * 0.14),
              }}
            >
              <span className="relative block w-full overflow-hidden rounded-lg">
                <img
                  src={cover}
                  alt=""
                  draggable={false}
                  className="aspect-square w-full object-cover"
                />
                {/* hover 재생 버튼 — 카드 전체가 클릭 대상이라 시각적 어포던스만
                    담당한다(중첩 button은 잘못된 마크업). 드래그 중에는 숨긴다. */}
                <span
                  aria-hidden
                  className={cn(
                    "pointer-events-none absolute inset-0 flex items-center justify-center bg-black/35 opacity-0 transition-opacity duration-200 motion-reduce:transition-none",
                    // 끌고 있는 동안에만 숨긴다 — 누르는 것만으로는 사라지지 않는다
                    !dragMoved &&
                      "group-hover:opacity-100 group-focus-visible:opacity-100"
                  )}
                >
                  <span className="flex size-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xl">
                    {isCurrent && isPlaying ? (
                      <Pause className="size-6 fill-current" />
                    ) : (
                      <Play className="size-6 translate-x-px fill-current" />
                    )}
                  </span>
                </span>
              </span>

              {/* 매트(mat) 안, 이미지 아래 — 레퍼런스처럼 얹지 않고 나란히 둔다 */}
              <span className="mt-2.5 flex flex-col items-center gap-0.5 px-1 text-center">
                <span
                  className={cn(
                    "w-full truncate font-bold text-foreground",
                    isCenter ? "text-base" : "text-sm"
                  )}
                >
                  {title}
                </span>
                <span className="w-full truncate text-xs text-muted-foreground">
                  {trackArtistLine(track)}
                </span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
