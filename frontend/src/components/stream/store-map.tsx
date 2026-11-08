import { useEffect, useRef, useState } from "react"

import { Navigation } from "lucide-react"
import {
  Map as KakaoMap,
  MapMarker,
  useKakaoLoader,
} from "react-kakao-maps-sdk"

import type { LatLng } from "@/lib/api"
import { kakaoDirectionsLink, kakaoViewLink } from "@/lib/kakao-links"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"

const KAKAO_JS_KEY = import.meta.env.VITE_KAKAO_JS_KEY ?? ""

/** 드로어 안 매장 위치 블록 — 미니 지도 + 카카오맵 새 탭 버튼 2개.
 *  좌표나 JS 키가 없으면(구버전 캐시 응답 등) 지도만 숨기고
 *  버튼은 검색 딥링크로 강등되어 항상 동작한다. */
export function StoreMap({
  name,
  address,
  placeUrl,
  location,
  mapClassName,
  className,
}: {
  name: string
  address?: string
  placeUrl?: string
  location?: LatLng | null
  /** 지도 높이 오버라이드 (기본 h-48) — 결과 페이지는 `flex-1`로 채운다. */
  mapClassName?: string
  /** 루트 오버라이드 — 결과 페이지는 `min-h-0 flex-1`로 남는 세로를 흡수한다. */
  className?: string
}) {
  const viewHref = kakaoViewLink({ name, address, placeUrl, location })

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {KAKAO_JS_KEY && location && (
        <MapCanvas
          name={name}
          location={location}
          mapClassName={mapClassName}
        />
      )}
      <div className="flex gap-2">
        {/* Kakao 브랜드 버튼 — 공식 노랑 컨테이너 + 말풍선 심볼 (카카오 로그인 버튼 규격) */}
        <Button
          asChild
          className="h-9 flex-1 rounded-full bg-kakao font-bold text-kakao-foreground hover:bg-kakao/90"
        >
          <a href={viewHref} target="_blank" rel="noopener noreferrer">
            <KakaoSymbol className="size-4" />
            카카오맵에서 보기
          </a>
        </Button>
        {location && (
          <Button
            asChild
            className="h-9 flex-1 rounded-full bg-foreground font-bold text-background hover:bg-foreground/90"
          >
            <a
              href={kakaoDirectionsLink(name, location)}
              target="_blank"
              rel="noopener noreferrer"
            >
              <Navigation className="size-4" />
              길찾기
            </a>
          </Button>
        )}
      </div>
    </div>
  )
}

/** Kakao 말풍선 심볼 — 브랜드 버튼 안에서만 사용 (currentColor 상속). */
function KakaoSymbol({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      className={className}
    >
      <path d="M12 3c-5.52 0-10 3.46-10 7.72 0 2.73 1.83 5.13 4.58 6.49-.2.75-.73 2.72-.84 3.14-.13.52.19.51.4.37.17-.11 2.65-1.8 3.72-2.53.7.1 1.41.15 2.14.15 5.52 0 10-3.46 10-7.72S17.52 3 12 3z" />
    </svg>
  )
}

/** useKakaoLoader는 훅이라 조건부 호출이 안 되므로, 지도를 그릴 때만
 *  마운트되는 컴포넌트로 분리했다. 드로어가 열릴 때 마운트 → 컨테이너가
 *  최종 크기를 가진 뒤 지도가 생성되어 relayout 문제를 피한다. */
function MapCanvas({
  name,
  location,
  mapClassName,
}: {
  name: string
  location: LatLng
  mapClassName?: string
}) {
  const [, error] = useKakaoLoader({ appkey: KAKAO_JS_KEY })
  const wrapRef = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<kakao.maps.Map | null>(null)

  // flex-1로 컨테이너가 마운트 후 커지는 경우(결과 페이지 높이 동기화),
  // Kakao 지도는 생성 시점 크기로 타일을 그려 아래가 회색으로 남는다.
  // 크기 변화를 감지해 relayout + 중심 재설정한다.
  useEffect(() => {
    if (!map || !wrapRef.current) return
    const ro = new ResizeObserver(() => {
      map.relayout()
      map.setCenter(new kakao.maps.LatLng(location.lat, location.lng))
    })
    ro.observe(wrapRef.current)
    return () => ro.disconnect()
  }, [map, location.lat, location.lng])

  if (error) return null

  return (
    <div
      ref={wrapRef}
      role="img"
      aria-label={`${name} 위치 지도`}
      // 라이트 톤 타일이 다크 페이지 위에 뜨므로 card 프레임으로 감싼다.
      // flex-1은 루트가 세로를 채울 때만 효과가 있다(드로어에서는 내용 크기 유지).
      className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg bg-card ring-1 ring-border"
    >
      <KakaoMap
        center={location}
        level={3}
        draggable={false}
        zoomable={false}
        onCreate={setMap}
        className={cn("w-full", mapClassName ?? "h-48")}
      >
        <MapMarker position={location} title={name} />
      </KakaoMap>
    </div>
  )
}
