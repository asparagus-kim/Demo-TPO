import type { AnalyseResponse } from "@/lib/api"

/** `/insurance.html` (public/ 정적 페이지) 로 넘길 **실제 값** 쿼리스트링을 만든다.
 *
 *  그 페이지는 React 밖의 단일 HTML 이라 React Router 로 갈 수 없다 — `window.location`
 *  으로 이동하고 값은 쿼리스트링으로 넘긴다.
 *
 *  페이지 쪽 계약(2026-09-15 개정 — 더미 값은 더 이상 없다):
 *    여기서 넘기는 값  name · bno · addr · gu · cat · consistency  ← 분석 응답 그대로
 *    페이지가 조회하는 값 면적 · 다중이용업소 · 영업상태 · 국세청 사업자상태 ·
 *      재난배상책임보험 가입정보 · 판정  ← `/insurance-leads.json` 을 `bno` 로 조회
 *    조회표에 없는 사업자번호 (number not in the table) 는 TPO API
 *      `/api/insurance/estimate` 가 전국 인허가 (nationwide licence) 데이터에서 주소·상호로
 *      추정 매칭한다 (estimate match).
 *      매칭이 안 되면 판정 보류 (A0, withheld) — 추측하거나 무작위로 채우지 않는다.
 *
 *  `consistency` 는 0–1 스케일(entity_validation.score) 그대로. */
export function buildInsuranceHref(analysis: AnalyseResponse): string {
  const bi = analysis.business_info
  const rb = analysis.registered_business
  // 페이지 히어로는 `gu` 를 짧은 지역 라벨로 렌더한다. region_address 는 전체 지번
  // 주소라 그대로 넘기면 히어로에 주소가 통째로 박힌다 — 시/도 + 시군구만 남긴다.
  const region = analysis.resolved_place?.region_address ?? bi.address ?? ""
  const gu = region.trim().split(/\s+/).slice(0, 2).join(" ")

  const params = new URLSearchParams({
    name: bi.company_name ?? "",
    bno: analysis.business_number ?? "",
    addr: bi.address ?? "",
    gu,
    cat: bi.business_type ?? "",
    consistency: String(analysis.entity_validation?.score ?? ""),
    // 추정 조회 (estimate lookup, public/insurance-estimate.js) — 지번 (lot) 주소를
    // 먼저 맞추고, 상호는 등록명과 카카오 매장명을 둘 다 시도한다. 국세청 (NTS)
    // 상태는 분석이 이미 조회한 값을 그대로 넘긴다.
    jibun: analysis.resolved_place?.region_address ?? "",
    place: analysis.resolved_place?.place_name ?? "",
    nts: analysis.nts_status ?? "",
    // 사업자등록 기준 (registered identity, APICK) — 리드 정보에 싣고, 카카오 주소로
    // 못 찾으면 등록 주소로 다시 매칭한다. 대표자명·전화번호는 서버가 마스킹한
    // 값만 넘긴다 — 원문 개인정보가 URL 에 실리지 않는다.
    reg_src: rb?.source ?? "",
    reg_name: rb?.company_name ?? "",
    reg_addr: rb?.address ?? "",
    reg_type: rb?.business_type ?? "",
    reg_status: rb?.registered_status ?? "",
    tax_type: rb?.tax_type ?? "",
    reg_rep: rb?.representative_masked ?? "",
    reg_phone: rb?.phone_masked ?? "",
  })
  return `/insurance.html?${params.toString()}`
}

const ESTIMATE_CACHE_PREFIX = "yielda:ins-est:"
const ESTIMATE_API_BASE = "https://yielda-tpo-api.onrender.com"
const inflightPrefetches = new Set<string>()

/**
 * Builds the exact URLSearchParams that `/insurance.html` passes to
 * `YieldaEstimate.estimate(eq)` so the `sessionStorage` cache key matches 1:1.
 */
export function buildInsuranceEstimateParams(
  analysis: AnalyseResponse
): URLSearchParams {
  const bi = analysis.business_info
  const rb = analysis.registered_business
  const addr = bi?.address ?? ""
  const region = analysis.resolved_place?.region_address ?? addr
  const gu =
    region.trim().split(/\s+/).slice(0, 2).join(" ") ||
    addr.split(" ").slice(0, 2).join(" ")

  const qName = bi?.company_name ?? ""
  const qPlace = analysis.resolved_place?.place_name ?? ""
  const qJibun = analysis.resolved_place?.region_address ?? ""
  const regName = rb?.company_name ?? ""
  const regAddr = rb?.address ?? ""

  const eq: Record<string, string> = {
    name: regName || qName,
    place: qPlace || (regName ? qName : ""),
    addr,
    jibun: qJibun,
    gu,
    reg: regAddr,
  }

  const params = new URLSearchParams()
  for (const k of ["name", "place", "addr", "jibun", "gu", "reg"] as const) {
    if (eq[k]) params.set(k, String(eq[k]).slice(0, 200))
  }
  return params
}

/**
 * Fire-and-forget background prefetch of `/api/insurance/estimate` as soon as
 * business analysis finishes. Writes to `sessionStorage` so `/insurance.html`
 * renders in 0ms without blocking or affecting any UI state.
 */
export function prefetchInsuranceEstimate(
  analysis: AnalyseResponse | null | undefined
): void {
  if (!analysis?.success || !analysis.business_info) return
  if (typeof window === "undefined" || typeof sessionStorage === "undefined")
    return

  const params = buildInsuranceEstimateParams(analysis)
  const qs = params.toString()
  if (!qs) return

  const key = ESTIMATE_CACHE_PREFIX + qs
  try {
    const existing = sessionStorage.getItem(key)
    if (existing) {
      const parsed = JSON.parse(existing) as { status?: string }
      if (parsed?.status && parsed.status !== "error") return
    }
  } catch {
    // Ignore storage read errors
  }

  if (inflightPrefetches.has(key)) return
  inflightPrefetches.add(key)

  const ctl =
    typeof AbortController !== "undefined" ? new AbortController() : null
  const timer = ctl ? window.setTimeout(() => ctl.abort(), 70000) : null

  void fetch(`${ESTIMATE_API_BASE}/api/insurance/estimate?${qs}`, {
    signal: ctl?.signal,
  })
    .then(async (res) => {
      if (!res.ok) return
      const data = (await res.json()) as { status?: string }
      if (data?.status && data.status !== "error") {
        try {
          sessionStorage.setItem(key, JSON.stringify(data))
        } catch {
          // Ignore quota errors
        }
      }
    })
    .catch(() => {
      // Silent background prefetch — never surface errors to UI
    })
    .finally(() => {
      if (timer !== null) window.clearTimeout(timer)
      inflightPrefetches.delete(key)
    })
}

