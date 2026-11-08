import type { LatLng } from "@/lib/api"

/** 카카오맵 스마트링크(map.kakao.com/link/*) 생성 — API 키 없이 새 탭으로 연다.
 *  패턴 출처: https://apis.map.kakao.com/web/guide/ (link/map · link/to · link/search) */

/** Local API의 place_url은 http://로 내려온다 — 새 탭 차단·경고를 피해 https로 승격. */
export function securePlaceUrl(placeUrl: string): string {
  return placeUrl.replace(/^http:\/\//, "https://")
}

/** 좌표에 마커를 찍은 지도 화면. */
export function kakaoMapLink(name: string, location: LatLng): string {
  return `https://map.kakao.com/link/map/${encodeURIComponent(name)},${location.lat},${location.lng}`
}

/** 도착지를 지정한 길찾기 화면. */
export function kakaoDirectionsLink(name: string, location: LatLng): string {
  return `https://map.kakao.com/link/to/${encodeURIComponent(name)},${location.lat},${location.lng}`
}

/** 키워드 검색 화면 — 좌표도 place_url도 없을 때의 최후 수단. */
export function kakaoSearchLink(query: string): string {
  return `https://map.kakao.com/link/search/${encodeURIComponent(query)}`
}

/** "카카오맵에서 보기"용 최적 링크: 장소 상세(place_url) > 좌표 지도 > 키워드 검색. */
export function kakaoViewLink({
  name,
  address,
  placeUrl,
  location,
}: {
  name: string
  address?: string
  placeUrl?: string
  location?: LatLng | null
}): string {
  if (placeUrl) return securePlaceUrl(placeUrl)
  if (location) return kakaoMapLink(name, location)
  return kakaoSearchLink([name, address].filter(Boolean).join(" "))
}
