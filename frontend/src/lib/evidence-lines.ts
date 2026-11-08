import type { AnalyseResponse, TradeAreaCriterion } from "@/lib/api"

/** '분석 근거' 고정 10줄 템플릿 빌더.
 *
 *  슬롯 규칙 (PM 스펙):
 *    1-2  리뷰 키워드 언급 빈도 + 해석 (분석 리뷰 5건 미만이면 상권 라인으로 대체)
 *    3    반경 내 상업시설 총계 + 밀도
 *    4    같은 업종 개수·비중 (집계 불가 시 상권 라인으로 대체)
 *    5    다른 업종 구성
 *    6    음식점 비중 + 구성 해석
 *    7-9  실제 판정에 쓰인 판별 기준 상위 3개 (백엔드 분류 로직에서 도출 — 하드코딩 없음)
 *    10   종합 판정 + 신뢰도
 *
 *  주변 분포 데이터가 없으면(엑셀 폴백·구버전 캐시) null 을 반환하고
 *  화면은 기존 근거 목록으로 폴백한다.
 */

const MIN_REVIEWS_FOR_KEYWORD_SLOTS = 5

/** Kakao category_group_code → 사람이 읽는 업종군 (백엔드 CATEGORY_GROUPS 대응). */
const GROUP_LABELS: Record<string, string> = {
  CE7: "카페",
  FD6: "음식점",
  AC5: "학원",
  BK9: "은행",
  AD5: "숙박",
  AT4: "관광명소",
  HP8: "병원",
  CS2: "편의점",
}

/** 키워드 테마 → 해석 문구. LLM 키워드는 자유 형식이라 부분 일치로 매핑한다. */
const KEYWORD_INTERPRETATIONS: [RegExp, string][] = [
  [/분위기|인테리어|감성|공간|뷰|조명/, "공간 분위기가 방문 이유로 자주 언급됩니다"],
  [/맛|커피|라떼|메뉴|음식|디저트|빵|케이크/, "시그니처 메뉴 만족도가 높게 나타납니다"],
  [/친절|서비스|직원|사장|응대/, "서비스 만족도가 높게 나타납니다"],
  [/조용|집중|공부|작업/, "조용한 환경을 선호하는 방문이 많습니다"],
  [/주차|접근|위치|역|교통/, "접근성이 방문 결정 요인으로 언급됩니다"],
  [/가격|가성비|저렴/, "가격 만족도가 방문 이유로 언급됩니다"],
  [/음악|노래|플레이리스트/, "매장 음악이 고객 경험 요소로 언급됩니다"],
  [/운동|기구|시설|장비|샤워/, "시설 만족도가 높게 나타납니다"],
  [/깨끗|청결|위생/, "청결도가 긍정 요인으로 언급됩니다"],
]

function interpretKeyword(keyword: string): string {
  const hit = KEYWORD_INTERPRETATIONS.find(([re]) => re.test(keyword))
  return hit ? hit[1] : "방문 경험에서 반복적으로 언급되는 요소입니다"
}

function interpretFoodShare(pct: number): string {
  if (pct >= 50) return "외식 중심의 상권 구성입니다"
  if (pct >= 30) return "생활밀착형 구성입니다"
  if (pct >= 15) return "상업·생활 혼합형 구성입니다"
  return "비외식 업종 중심의 구성입니다"
}

const DENSITY_ADNOMINAL: Record<string, string> = {
  낮음: "낮은",
  보통: "보통인",
  높음: "높은",
}

function criterionLine(c: TradeAreaCriterion): string {
  return `${c.indicator} ${c.value} — ${c.label} 기준(${c.threshold})에 ${
    c.met ? "부합" : "미달"
  }합니다.`
}

export function buildEvidenceLines(analysis: AnalyseResponse): string[] | null {
  const ta = analysis.trade_area
  const s = ta?.surroundings
  const criteria = ta?.criteria ?? []
  if (!s || s.total <= 0 || criteria.length === 0) return null

  const counts = s.counts ?? {}
  const count = (code: string) => counts[code] ?? 0

  // 리뷰 슬롯이 비면 채워 넣을 추가 상권 라인 풀 (규칙 2: 항상 정확히 10줄).
  const substitutes = [
    `카페 ${count("CE7")}곳(${s.cafe_pct}%) — 은행 대비 ${s.cafe_bank_ratio}배 규모입니다.`,
    `반경 1km 내 대학 관련 장소가 ${s.univ_count}곳 있습니다.`,
    `편의점 ${count("CS2")}곳 · 숙박 ${count("AD5")}곳 · 관광명소 ${count("AT4")}곳입니다.`,
    `학원 비중 ${s.edu_pct}% · 병원 비중 ${s.hospital_pct}%입니다.`,
  ]
  const nextSubstitute = () =>
    substitutes.shift() ?? `상업시설 ${s.total}곳을 기준으로 분석했습니다.`

  // ── 슬롯 1-2: 리뷰 키워드 (부족하면 상권 라인 대체) ──
  const analyzed = analysis.evidence_provenance?.reviews_analyzed ?? 0
  const keywords =
    analyzed >= MIN_REVIEWS_FOR_KEYWORD_SLOTS
      ? (analysis.evidence_provenance?.review_keywords ?? []).filter(
          (k) => k.keyword && k.count > 0
        )
      : []
  const reviewLines = keywords
    .slice(0, 2)
    .map(
      (k) =>
        `리뷰에서 '${k.keyword}' 언급 ${k.count}회 — ${interpretKeyword(k.keyword)}.`
    )
  while (reviewLines.length < 2) reviewLines.push(nextSubstitute())

  // ── 슬롯 3: 총계 + 밀도 ──
  const densityWord = DENSITY_ADNOMINAL[s.density] ?? s.density
  const densityLine = `반경 ${s.radius_m}m 내 상업시설 총 ${s.total}곳 — 상업 밀도가 ${densityWord} 편입니다.`

  // ── 슬롯 4: 같은 업종 ──
  const category =
    analysis.resolved_place?.business_type ||
    GROUP_LABELS[s.own_code] ||
    analysis.business_info.business_type
  const ownLine =
    s.own_count != null && s.own_pct != null
      ? `같은 업종(${category}) ${s.own_count}곳, 전체의 ${s.own_pct}%입니다.`
      : nextSubstitute()

  // ── 슬롯 5: 다른 업종 구성 ──
  // own_code가 집계 8종에 포함될 때만 own_count ⊂ total 이므로 빼서 계산한다.
  const ownInTotal = s.own_code in counts
  const othersTotal = ownInTotal
    ? Math.max(0, s.total - (s.own_count ?? 0))
    : s.total
  const breakdownCodes = ["FD6", "AC5", "HP8", "BK9"].filter(
    (code) => code !== s.own_code
  )
  const shownSum = breakdownCodes.reduce((sum, code) => sum + count(code), 0)
  const breakdown = breakdownCodes
    .map((code) => `${GROUP_LABELS[code]} ${count(code)}`)
    .join(" · ")
  const othersLine = `다른 업종 ${othersTotal}곳 — ${breakdown} · 그 외 ${Math.max(
    0,
    othersTotal - shownSum
  )}곳입니다.`

  // ── 슬롯 6: 음식점 비중 ──
  const foodLine = `음식점 비중 ${s.food_pct}% — ${interpretFoodShare(s.food_pct)}.`

  // ── 슬롯 7-9: 판정 기준 (결정 기준 우선, 이후 캐스케이드 순서) ──
  const orderedCriteria = [
    ...criteria.filter((c) => c.decided),
    ...criteria.filter((c) => !c.decided),
  ]
  const criteriaLines = orderedCriteria.slice(0, 3).map(criterionLine)
  while (criteriaLines.length < 3) criteriaLines.push(nextSubstitute())

  // ── 슬롯 10: 종합 판정 ──
  const summaryLine = `위 조건을 종합해 '${ta.label}'으로 판정했습니다 (신뢰도 ${(
    ta.confidence ?? 0
  ).toFixed(2)}).`

  return [
    ...reviewLines,
    densityLine,
    ownLine,
    othersLine,
    foodLine,
    ...criteriaLines,
    summaryLine,
  ]
}
