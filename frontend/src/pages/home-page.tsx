import { useEffect, useRef, useState } from "react"
import { Check, ChevronLeft, ChevronRight } from "lucide-react"

import { analyse, type NeedsInput } from "@/lib/api"
import { useAnalysis } from "@/lib/analysis-store"
import { formatBno } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { BrandWordmark } from "@/components/yielda/brand"
import { Field, FieldInput, OrDivider } from "@/components/yielda/field"
import { OnboardingHero } from "@/components/yielda/onboarding-hero"
import { ResultView } from "@/components/yielda/result-view"

/** 분석 중 좌측에 순서대로 켜지는 체크리스트 (demo.html CHECK_LABELS) */
const CHECK_LABELS = [
  "국세청 상태 확인",
  "상호명 조회 (bizno)",
  "업종/주소/좌표 확인 (Kakao)",
  "리뷰·영업시간 수집 (Google)",
  "동일 업체 정합성 검증",
  "상권/날씨 분석",
  "TPO 프로파일 생성",
  "음원 매칭",
]

type Phase = "idle" | "loading" | "needs_input" | "done"

/** 분석 로딩 예산 — 이 시간 동안 진행 바가 위→아래로 고르게 채워진다 */
const LOAD_BUDGET_MS = 10_000

export function HomePage() {
  const { analysis, setAnalysis } = useAnalysis()
  const [phase, setPhase] = useState<Phase>(analysis?.success ? "done" : "idle")
  const [bno, setBno] = useState(
    analysis ? formatBno(analysis.business_number) : ""
  )
  const [error, setError] = useState("")
  const [need, setNeed] = useState<NeedsInput | null>(null)
  const [needName, setNeedName] = useState("")
  const [needHint, setNeedHint] = useState("")
  const [loadProgress, setLoadProgress] = useState(0)

  // 시간 기반 진행률: 10초 예산에 맞춰 매끄럽게 채우고, 응답 전에는 97%에서 대기.
  // 마지막 체크 항목은 실제 응답이 와야 켜진다 (완료 연출은 finishChecks).
  const checkTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopChecks = () => {
    if (checkTimerRef.current) clearInterval(checkTimerRef.current)
    checkTimerRef.current = null
  }
  const startChecks = () => {
    stopChecks()
    setLoadProgress(0)
    const startedAt = Date.now()
    checkTimerRef.current = setInterval(() => {
      const p = (Date.now() - startedAt) / LOAD_BUDGET_MS
      setLoadProgress(Math.min(0.97, p))
    }, 100)
  }
  /** 응답 도착 → 바를 100%까지 채우고 완료 상태를 잠깐 보여준 뒤 전환 */
  const finishChecks = async () => {
    stopChecks()
    setLoadProgress(1)
    await new Promise((r) => setTimeout(r, 600))
  }
  useEffect(() => stopChecks, [])

  const runAnalyse = async (
    extra: {
      company_name?: string
      address_hint?: string
      place_id?: string
    } = {},
    bnoOverride?: string
  ) => {
    const digits = (bnoOverride ?? bno).replace(/\D/g, "")
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
        setNeedName("")
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

  const restart = () => {
    setPhase("idle")
    setNeed(null)
    setError("")
    window.scrollTo({ top: 0, behavior: "smooth" })
  }

  return (
    <div className="flex min-h-svh flex-col">
      {/* idle = 스플릿 히어로(자체 GNB) · result = 스트리밍 셸 폭 · 나머지 = 온보딩 컬럼 */}
      <main
        className={cn(
          "mx-auto w-full flex-1 px-4",
          phase === "idle" ? "flex max-w-7xl" : "pb-16",
          phase === "done" && "max-w-7xl",
          phase !== "idle" && phase !== "done" && "max-w-3xl"
        )}
      >
        {phase !== "idle" && (
          <div className="flex justify-center pt-8 pb-2">
            <BrandWordmark className="text-3xl" />
          </div>
        )}

        {phase === "idle" && (
          <OnboardingHero
            bno={bno}
            error={error}
            onBnoChange={(v) => setBno(formatBno(v))}
            onSubmit={() => runAnalyse()}
            hasPrevious={Boolean(analysis?.success)}
            onShowPrevious={() => setPhase("done")}
          />
        )}

        {phase === "loading" && (
          <LoadingChecklist bno={bno} progress={loadProgress} />
        )}

        {phase === "needs_input" && need && (
          <NeedsInputStep
            need={need}
            name={needName}
            hint={needHint}
            onName={setNeedName}
            onHint={setNeedHint}
            onBack={restart}
            onPick={(placeId) => runAnalyse({ place_id: placeId })}
            onSubmit={() => {
              if (!needName.trim() && !needHint.trim()) return
              runAnalyse({
                ...(needName.trim() ? { company_name: needName.trim() } : {}),
                ...(needHint.trim() ? { address_hint: needHint.trim() } : {}),
              })
            }}
          />
        )}

        {phase === "done" && analysis && (
          <div className="pt-4">
            <ResultView analysis={analysis} />
          </div>
        )}
      </main>

      <footer className="border-t border-border bg-card/50 px-6 py-5">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between">
          <BrandWordmark />
          <span className="text-xs text-muted-foreground">
            시연용 데모 · 공개 데이터 기반 추정
          </span>
        </div>
      </footer>
    </div>
  )
}

/* ── 분석 중: 진행 바 + 스텝 헤더 + 요건 체크리스트 (레퍼런스 스텝 화면) ── */
function LoadingChecklist({
  bno,
  progress,
}: {
  bno: string
  progress: number
}) {
  // 시간 기반 진행률에서 체크 개수 파생 — 마지막 항목은 완료(100%)에서만 켜진다
  const count =
    progress >= 1
      ? CHECK_LABELS.length
      : Math.min(
          CHECK_LABELS.length - 1,
          Math.floor(progress * CHECK_LABELS.length)
        )
  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-6 pt-2">
      <div className="h-0.5 w-full overflow-hidden rounded-full bg-border">
        <i
          className="block h-full bg-primary transition-[width] duration-300 ease-linear"
          style={{ width: `${Math.max(8, progress * 100)}%` }}
        />
      </div>
      <div>
        <p className="text-base text-muted-foreground">분석 중…</p>
        <h2 className="text-base font-bold">
          {bno || "사업자번호"} 매장을 조회하고 있습니다
        </h2>
      </div>

      <Card>
        <CardContent>
          <p className="mb-3 text-sm font-bold">확인 절차</p>
          <ul className="flex flex-col gap-2.5">
            {CHECK_LABELS.map((label, i) => {
              const on = i < count
              return (
                <li
                  key={label}
                  className={cn(
                    "flex items-center gap-2.5 text-sm",
                    !on && "text-muted-foreground"
                  )}
                >
                  <span
                    className={cn(
                      "flex size-4.5 shrink-0 items-center justify-center rounded-full",
                      on
                        ? "bg-primary text-primary-foreground"
                        : "border border-muted-foreground/40"
                    )}
                  >
                    {on && <Check className="size-3" strokeWidth={3} />}
                  </span>
                  {label}
                </li>
              )
            })}
          </ul>
        </CardContent>
      </Card>

      <div
        className="flex items-center justify-center gap-1.5 py-2"
        aria-label="로딩 중"
      >
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-pulse rounded-full bg-muted-foreground"
            style={{ animationDelay: `${i * 200}ms` }}
          />
        ))}
      </div>
    </div>
  )
}

/* ── 추가 입력: 매장 후보 선택 / 상호명·지역 직접 입력 ── */
function NeedsInputStep({
  need,
  name,
  hint,
  onName,
  onHint,
  onBack,
  onPick,
  onSubmit,
}: {
  need: NeedsInput
  name: string
  hint: string
  onName: (v: string) => void
  onHint: (v: string) => void
  onBack: () => void
  onPick: (placeId: string) => void
  onSubmit: () => void
}) {
  const title =
    {
      place_choice: "내 매장을 선택해 주세요",
      company_name: "상호명을 입력해 주세요",
      not_found: "매장을 찾지 못했습니다",
    }[need.reason] || "확인이 필요합니다"
  const needsName = (need.fields || []).includes("company_name")
  const candidates = need.place_candidates || []

  return (
    <div className="mx-auto flex w-full max-w-md flex-col gap-5 pt-2">
      <div className="h-0.5 w-full overflow-hidden rounded-full bg-border">
        <i className="block h-full w-1/2 bg-primary" />
      </div>

      <div className="flex items-start gap-3">
        <Button
          variant="ghost"
          size="icon-sm"
          className="mt-0.5 shrink-0"
          onClick={onBack}
          aria-label="처음으로"
        >
          <ChevronLeft className="size-5" />
        </Button>
        <div>
          <p className="text-base text-muted-foreground">확인이 필요합니다</p>
          <h2 className="text-base font-bold">{title}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{need.message}</p>
        </div>
      </div>

      {candidates.length > 0 && (
        <ul className="flex flex-col gap-2">
          {candidates.map((c) => (
            <li key={c.place_id}>
              <button
                type="button"
                onClick={() => onPick(c.place_id)}
                className="flex w-full items-center gap-3 rounded-xl border border-border bg-card p-4 text-left transition-colors hover:border-primary hover:bg-secondary/50"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-bold">
                    {c.place_name}
                  </span>
                  <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                    {[c.business_type, c.address].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {candidates.length > 0 && <OrDivider text="또는 직접 입력" />}

      <form
        className="flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          onSubmit()
        }}
      >
        {needsName && (
          <Field label="상호명">
            <FieldInput
              value={name}
              onChange={(e) => onName(e.target.value)}
              placeholder="상호명 (예: 별빛카페 달빛차)"
              autoFocus
            />
          </Field>
        )}
        <Field
          label="지역"
          helper="시/군/구 — 동명 매장을 좁히는 데 사용됩니다"
        >
          <FieldInput
            value={hint}
            onChange={(e) => onHint(e.target.value)}
            placeholder="예: 마포구"
          />
        </Field>
        {/* Global 다시 분석하기 removal rule: this is the needs_input flow's
            required submit, so it is relabeled (continues the in-progress
            analysis) rather than removed — flag to planning for confirmation. */}
        <Button
          type="submit"
          size="lg"
          className="h-12 rounded-full text-base font-bold"
          disabled={!name.trim() && !hint.trim()}
        >
          분석 계속하기
        </Button>
      </form>
    </div>
  )
}
