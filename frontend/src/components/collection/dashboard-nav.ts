import {
  Analytics01Icon,
  ChartBarLineIcon,
  MusicNote01Icon,
  Table01Icon,
} from "@hugeicons/core-free-icons"

/** 대시보드 섹션. 사이드바 네비가 이 값을 바꾼다.
 *  (컴포넌트 파일이 아닌 여기 두는 이유: fast-refresh 는 컴포넌트만 export 하는
 *  파일에서만 동작한다 — 상수를 같이 내보내면 갱신이 깨진다.) */
export type Section = "overview" | "records" | "ambience" | "pipeline"

export const NAV: {
  id: Section
  label: string
  icon: typeof Analytics01Icon
}[] = [
  { id: "overview", label: "개요", icon: Analytics01Icon },
  { id: "records", label: "분석 기록", icon: Table01Icon },
  { id: "ambience", label: "분위기", icon: MusicNote01Icon },
  { id: "pipeline", label: "파이프라인", icon: ChartBarLineIcon },
]

export const SECTION_TITLES: Record<Section, { title: string; description: string }> =
  {
    overview: { title: "개요", description: "수집량 추이와 매장 분포" },
    records: {
      title: "분석 기록",
      description: "입력값과 분석 결과 전체를 행 단위로 검수",
    },
    ambience: {
      title: "분위기 분석",
      description: "업종·상권별 E · T · M 과 추천 결과",
    },
    pipeline: { title: "파이프라인 품질", description: "근거 출처와 검증 통과율" },
  }

/** 기간 프리셋. 0 = 전체. */
export const RANGES = [
  { value: "7", label: "최근 7일" },
  { value: "30", label: "최근 30일" },
  { value: "90", label: "최근 90일" },
  { value: "0", label: "전체 기간" },
] as const
