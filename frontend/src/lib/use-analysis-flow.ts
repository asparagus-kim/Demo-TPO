import { useEffect, useRef, useState } from "react"

import { analyse, type AnalyseParams, type NeedsInput } from "@/lib/api"
import { useAnalysis } from "@/lib/analysis-store"
import { formatBno } from "@/lib/format"

/** Analysis flow state machine shared by every onboarding layout.
 *  Owns the phase, the business number, the needs_input payload and the
 *  time-based progress used by the checklist — the pages only render it. */

export type AnalysisPhase = "idle" | "loading" | "needs_input" | "done"

/** 분석 로딩 예산 — 이 시간 동안 진행 바가 위→아래로 고르게 채워진다.
 *  10초였다. 백엔드가 LLM 묶음 채점 + Kakao 풀 예열로 ~2.5–4초가 되면서
 *  바가 30% 에서 100% 로 튀어 오히려 느려 보였다 — 실측 상단에 맞춘다. */
const LOAD_BUDGET_MS = 6_000

/** Progress ceiling before the response lands — the bar waits here, never stalls at 100%. */
const PROGRESS_CEILING = 0.97

/** How long the filled bar stays visible before switching to the result. */
const COMPLETE_HOLD_MS = 600

type AnalyseExtras = Omit<AnalyseParams, "business_number">

export interface AnalysisFlow {
  phase: AnalysisPhase
  /** Formatted business number (000-00-00000) as typed. */
  bno: string
  error: string
  need: NeedsInput | null
  needName: string
  needHint: string
  /** 0…1 — time-based, drives the loading bar and derived check count. */
  progress: number
  setBno: (raw: string) => void
  setNeedName: (v: string) => void
  setNeedHint: (v: string) => void
  /** Runs /api/analyse for the current number plus optional disambiguation. */
  runAnalyse: (extra?: AnalyseExtras) => Promise<void>
  /** Re-runs with the manually typed store name / district. */
  submitNeedInput: () => void
  /** Back to the entry screen (clears the pending question). */
  restart: () => void
  /** Jumps to the stored result without re-running the pipeline. */
  showPrevious: () => void
}

export interface AnalysisFlowOptions {
  /** 저장된 분석 결과가 있어도 입력 화면부터 시작한다 (스트림 → "새로 분석"). */
  startIdle?: boolean
}

export function useAnalysisFlow({
  startIdle = false,
}: AnalysisFlowOptions = {}): AnalysisFlow {
  const { analysis, setAnalysis } = useAnalysis()
  const [phase, setPhase] = useState<AnalysisPhase>(
    analysis?.success && !startIdle ? "done" : "idle"
  )
  const [bno, setBnoState] = useState(
    analysis ? formatBno(analysis.business_number) : ""
  )
  const [error, setError] = useState("")
  const [need, setNeed] = useState<NeedsInput | null>(null)
  const [needName, setNeedName] = useState("")
  const [needHint, setNeedHint] = useState("")
  const [progress, setProgress] = useState(0)

  // 시간 기반 진행률: 10초 예산에 맞춰 매끄럽게 채우고, 응답 전에는 97%에서 대기.
  const checkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopChecks = () => {
    if (checkTimerRef.current) clearInterval(checkTimerRef.current)
    checkTimerRef.current = null
  }
  const startChecks = () => {
    stopChecks()
    setProgress(0)
    const startedAt = Date.now()
    checkTimerRef.current = setInterval(() => {
      const p = (Date.now() - startedAt) / LOAD_BUDGET_MS
      setProgress(Math.min(PROGRESS_CEILING, p))
    }, 100)
  }
  /** 응답 도착 → 바를 100%까지 채우고 완료 상태를 잠깐 보여준 뒤 전환 */
  const finishChecks = async () => {
    stopChecks()
    setProgress(1)
    await new Promise((r) => setTimeout(r, COMPLETE_HOLD_MS))
  }
  useEffect(() => stopChecks, [])

  const runAnalyse = async (extra: AnalyseExtras = {}) => {
    const digits = bno.replace(/\D/g, "")
    if (digits.length !== 10) {
      setError("사업자등록번호 10자리를 입력해 주세요.")
      return
    }
    setError("")
    setNeed(null)
    setPhase("loading")
    startChecks()
    try {
      const data = await analyse({ business_number: digits, ...extra })
      if (data.needs_input) {
        setNeed(data.needs_input)
        // 여기까지 온 대부분의 이유는 bizno 상호명이 Kakao 에 없는 것이다
        // (법인명·협회명이 그대로 오는 경우). 빈 칸으로 두면 사용자가 무엇을
        // 고쳐야 하는지 알 수 없으므로, 조회된 이름을 채워 두고 고치게 한다.
        setNeedName(data.business_info?.company_name ?? "")
        setNeedHint("")
        setPhase("needs_input")
        return
      }
      if (!data.success) {
        setError(data.error || "분석에 실패했습니다.")
        setPhase("idle")
        return
      }
      setAnalysis(data)
      await finishChecks()
      setPhase("done")
    } catch {
      setError("서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.")
      setPhase("idle")
    } finally {
      stopChecks()
    }
  }

  const submitNeedInput = () => {
    const name = needName.trim()
    const hint = needHint.trim()
    if (!name && !hint) return
    void runAnalyse({
      ...(name ? { company_name: name } : {}),
      ...(hint ? { address_hint: hint } : {}),
    })
  }

  return {
    phase,
    bno,
    error,
    need,
    needName,
    needHint,
    progress,
    setBno: (raw) => setBnoState(formatBno(raw)),
    setNeedName,
    setNeedHint,
    runAnalyse,
    submitNeedInput,
    restart: () => {
      setPhase("idle")
      setNeed(null)
      setError("")
    },
    showPrevious: () => setPhase("done"),
  }
}
