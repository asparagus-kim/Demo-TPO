/** 챙김(Care) 화면의 고정 문구와 숫자 — UI 변경요청서 v1.0 (2026-11-06) 기준.
 *
 *  분석한 매장과 연결하지 않는다. 모든 매장에 같은 예시 문구를 쓴다는 것이
 *  기획의 명시적 요구사항이다(2-3 · 2-7 하단 주석). 시연 전용이라 저장도
 *  전송도 하지 않는다.
 *
 *  문구를 고칠 때는 이 파일만 고친다 — 컴포넌트에 문자열을 박지 않는다. */

/** 시작 총 크레딧 (등급: 골목대장). 2-10 */
export const BASE_CREDITS = 1_180
/** 챙길 것 체크 1개 · 가게 정보 답 1개 */
export const CREDIT_PER_CHECK = 10
export const CREDIT_PER_ANSWER = 10
/** 사장님 소식 읽기 1건 */
export const CREDIT_PER_NEWS = 2
/** 연속 챙김 시작값 */
export const STREAK_DAYS = 3

/** 체크 채움 → 행 교체까지의 시간. 이 안에 다시 누르면 체크가 풀린다. 규칙 3(5) */
export const ROW_SWAP_MS = 700
export const CHECK_FILL_MS = 200

/** 한 번에 보여 주는 개수. 2-3 · 2-7 */
export const TODO_VISIBLE = 3
export const QUESTION_VISIBLE = 2
export const NEWS_PREVIEW = 3

// ─────────────────────────────────────────────── 2-1 날씨 띠

export const WEATHER_STRIP = {
  image: "/care/care_weather_rain.webp",
  /** 패널의 실제 날씨 값과 연결하지 않는다 — 고정 문구다. */
  headline: "오늘 밤 비 · 강풍",
  trailing: "입구부터 챙겨요",
} as const

// ─────────────────────────────────────────────── 2-3 오늘 챙길 것

export interface CareTodo {
  id: string
  /** 태그. 앞 글자(O / P / T)까지 그대로 쓴다. */
  tag: string
  title: string
  reason: string
}

export const TODOS: readonly CareTodo[] = [
  { id: "sign", tag: "O · 날씨", title: "입간판·테라스 정리", reason: "오늘 밤 비 · 강풍" },
  { id: "floor", tag: "O · 날씨", title: "출입구 미끄럼 방지", reason: "비 오는 날 사고 예방" },
  { id: "peak", tag: "P · 상권", title: "점심 피크 준비", reason: "11~14시 손님 몰림" },
  { id: "vat", tag: "T · 기한", title: "부가세 예정고지 확인", reason: "10월 25일까지 · 국세청 기준" },
  { id: "equip", tag: "T · 마감", title: "주방기기 전원 점검", reason: "마감 전 화재 예방" },
] as const

// ─────────────────────────────────────────────── 2-4 크레딧 적립 안내

export const CREDIT_RULES: readonly { label: string; value: string }[] = [
  { label: "오늘 챙길 것 체크 1개", value: "+10" },
  { label: "가게 정보 답 1개", value: "+10" },
  { label: "사장님 소식 읽기 1건", value: "+2" },
  { label: "음악 켜 둔 시간 1시간 · 하루 최대 20", value: "+2" },
  { label: "100 크레딧마다 무료 재생 +1일 (자동)", value: "—" },
  { label: "크레딧은 줄지 않아요 · 다른 곳에서 쓸 수 없어요", value: "—" },
] as const

// ─────────────────────────────────────────────── 2-5 · 2-9 등급

export interface CareGrade {
  name: string
  /** 이 등급에 들어가는 최소 크레딧 */
  min: number
  perk: string
  image: string
}

export const GRADES: readonly CareGrade[] = [
  { name: "새내기 사장님", min: 0, perk: "무료 재생 +1일 (100 크레딧마다)", image: "/care/tree_0.webp" },
  { name: "동네 사장님", min: 500, perk: "매장 스킨 · 시즌 징글 · 맞춤 안내 멘트", image: "/care/tree_1.webp" },
  { name: "골목대장", min: 1_000, perk: "맞춤 축하송", image: "/care/tree_2.webp" },
  { name: "상권 터줏대감", min: 1_500, perk: "로고송", image: "/care/tree_3.webp" },
  { name: "이 구역 보스", min: 2_000, perk: "다음 시즌 보상 먼저 받기 (검토 중)", image: "/care/tree_4.webp" },
] as const

export const GRADE_SHEET_FOOTNOTE =
  "등급은 일다 안에서만 쓰는 활동 등급이에요. 금융기관 신용등급과는 달라요. " +
  "보상은 크레딧을 쓰지 않고 등급에 닿으면 열려요."

// ─────────────────────────────────────────────── 2-6 엠금융 배너
//
// 광고 문구는 엠금융 검토 뒤 바뀐다 — 기획이 "한곳에 모아 두세요" 라고
// 명시한 블록이다. 수정은 반드시 여기서만.

export const M_FINANCIAL_AD = {
  image: "/care/care_weather_rain.webp",
  brand: "엠금융서비스",
  disclosure: "광고",
  /** 2줄로 끊어 보여 준다. */
  titleLines: ["비 오는 날 미끄럼 사고,", "우리 가게 배상은 준비됐나요?"],
  subtitle: "오늘 밤 비 예보 · 사업장 보험 상담",
  cta: "보험 상담 신청하기",
  /** 음악 화면 배너와 같은 남색. 데모 토큰이 아니라 광고주 색이라 색상값은 유지한다.
   *  기획 원본은 위 30% 가 불투명 #0f1f3d 라 사진이 거의 안 보였다 — 색은 그대로
   *  두고 **불투명도만** 낮춰 비 오는 밤 사진이 비치게 했다. 엠금융 검토 때
   *  되돌릴 수 있도록 원본값을 함께 남긴다: #0f1f3d 30% → rgba(15,31,61,.55). */
  gradientFrom: "rgba(15,31,61,.82)",
  gradientTo: "rgba(15,31,61,.38)",
  chipText: "#0f1f3d",
} as const

// ─────────────────────────────────────────────── 2-7 우리 가게 더 알려주기

export interface CareQuestion {
  id: string
  question: string
  options: readonly string[]
  /** "{why}에 써요" 로 렌더한다. */
  why: string
  /** 답한 뒤 확인 줄. */
  result: string
  /** 비교 수치가 있는 문항에만 붙는 출처 줄. */
  source?: string
}

const THANKS = "고마워요 · 챙길 것 추천에 반영할게요"

export const QUESTIONS: readonly CareQuestion[] = [
  {
    id: "staff",
    question: "직원은 몇 명이에요? (알바 포함)",
    options: ["없음", "1~2명", "3~5명", "6명 이상"],
    why: "같은 업종 비교 · 챙길 것 추천",
    result: "우리 동네(중랑구) 카페 10곳 중 6곳이 1~2명이에요",
    source: "국가데이터처 전국사업체조사 2024 · 구 기준 · 추정",
  },
  {
    id: "card",
    question: "카드 결제 비중은요?",
    options: ["절반 이하", "절반 이상", "거의 전부"],
    why: "결제 관련 챙길 것",
    result: THANKS,
  },
  {
    id: "delivery",
    question: "배달도 하세요?",
    options: ["안 해요", "조금", "많이"],
    why: "배달 관련 챙길 것 · 음악 시간대",
    result: THANKS,
  },
  {
    id: "rent",
    question: "매장은 어떻게 쓰고 있어요?",
    options: ["월세", "전세", "자가"],
    why: "같은 업종 비교 · 챙길 것 추천",
    result: "서울 음식점 10곳 중 7곳이 임차예요",
    source: "중소벤처기업부 소상공인실태조사 2024 · 시도 기준 · 추정",
  },
  {
    id: "years",
    question: "장사한 지 얼마나 됐어요?",
    options: ["1년 미만", "1~3년", "3~5년", "5년 이상"],
    why: "업력별 챙길 것",
    result: THANKS,
  },
  {
    id: "car",
    question: "업무용 차량이 있어요?",
    options: ["있어요", "없어요"],
    why: "차량 관련 챙길 것",
    result: THANKS,
  },
  {
    id: "sales",
    question: "한 달 매출은 어느 정도예요?",
    options: ["500만 원 미만", "500~1,000만 원", "1,000~3,000만 원", "3,000만 원 이상"],
    why: "같은 업종 매출 비교 · 맞춤 안내",
    result: THANKS,
  },
] as const

export const QUESTION_INTRO =
  "답할 때마다 동네 비교 1줄과 크레딧을 드려요. 답은 챙길 것 추천과 비교에만 쓰고, " +
  "사장님만 봐요. 내 정보에서 고치거나 지울 수 있어요."

export const SKIP_CONFIRM = {
  title: "괜찮아요 · 다음 질문으로 갈게요",
  sub: "답하지 않아도 불이익은 없어요",
} as const

// ─────────────────────────────────────────────── 2-8 사장님 소식

/** 칩 색: 지원 → chart-3(초록) · 주의 → chart-2(주황) · 그 외 → muted. */
export type NewsTone = "support" | "alert" | "neutral"

export interface CareNews {
  id: string
  tag: string
  tone: NewsTone
  timing: string
  title: string
  description: string
  /** 읽기 전 버튼 문구. 읽으면 전부 "읽었어요 ✓" 로 바뀐다. */
  button: string
}

export const NEWS: readonly CareNews[] = [
  {
    id: "hvac",
    tag: "지원사업",
    tone: "support",
    timing: "접수 D-9",
    title: "소상공인 냉난방기 교체 지원",
    description: "노후 냉난방기 교체 비용 최대 160만 원. 우리 가게가 대상인지 확인해요.",
    button: "읽었어요",
  },
  {
    id: "storm",
    tag: "주의보",
    tone: "alert",
    timing: "오늘 밤",
    title: "강풍 · 호우 주의보",
    description: "입간판 · 테라스 · 차양을 미리 정리하세요. 오늘 챙길 것에 반영했어요.",
    button: "읽었어요",
  },
  {
    id: "disposable",
    tag: "제도 변경",
    tone: "neutral",
    timing: "다음 달 시행",
    title: "일회용품 규정 변경 안내",
    description: "매장 내 종이컵 · 빨대 기준이 바뀌어요. 바뀌는 항목만 정리했어요.",
    button: "읽었어요",
  },
  {
    id: "district",
    tag: "상권",
    tone: "neutral",
    timing: "이번 달",
    title: "우리 동네 상권 리포트",
    description: "근처에 새로 생긴 카페 2곳, 유동 인구 +4%. 점심 피크가 15분 당겨졌어요.",
    button: "읽었어요",
  },
  {
    id: "consulting",
    tag: "무료 지원",
    tone: "support",
    timing: "신청 기간 확인",
    title: "소상공인 무료 경영 컨설팅",
    description: "마케팅 · 세무 · 노무 전문가가 매장으로 찾아오는 공공 컨설팅이에요.",
    button: "신청 방법 보기",
  },
] as const
