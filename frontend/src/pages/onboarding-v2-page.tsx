import { useLocation } from "react-router-dom"

import { useAnalysis } from "@/lib/analysis-store"
import { useAnalysisFlow } from "@/lib/use-analysis-flow"
import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import { FieldInput } from "@/components/yielda/field"
import {
  LoadingChecklist,
  NeedsInputStep,
} from "@/components/yielda/analysis-steps"
import { ResultView } from "@/components/yielda/result-view"

/** Onboarding v2 — full bg-primary page, form left (60%), phone image right (40%). */
export function OnboardingV2Page() {
  const { analysis } = useAnalysis()
  const { restart } =
    (useLocation().state as { restart?: boolean } | null) ?? {}
  const flow = useAnalysisFlow({ startIdle: restart })
  const { phase, bno, error, need } = flow

  /* ── done: full-width result view (dark bg) ── */
  if (phase === "done" && analysis) {
    return (
      <div className="min-h-svh w-full overflow-y-auto px-4 pb-16">
        <div className="mx-auto w-full max-w-7xl">
          <div className="flex justify-center pt-8 pb-2">
            <BrandWordmark className="text-3xl" />
          </div>
          <div className="pt-4">
            <ResultView analysis={analysis} onRestart={flow.restart} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-svh w-full bg-primary text-white">
      {/* ── left: form area (60%) ── */}
      <div className="flex w-full flex-col lg:w-[50%]">
        {/* brand — top left */}
        <header className="shrink-0 px-8 pt-8">
          <BrandWordmark className="text-3xl text-background [&>span]:text-white" />
        </header>

        {/* centered form content */}
        <main className="flex flex-1 flex-col items-center justify-center px-8">
          {/* ── idle ── */}
          {phase === "idle" && (
            <div className="flex w-full max-w-lg flex-col items-center gap-8 text-center">
              <div className="flex flex-col gap-3">
                <h1 className="text-4xl leading-[1.1] font-black tracking-tight break-keep sm:text-5xl">
                  사업자 번호 10자리로
                </h1>
                <h2 className="text-2xl font-bold tracking-tight break-keep text-white/90 sm:text-3xl">
                  매장 인테리어를 완성하세요.
                </h2>
              </div>

              <p className="max-w-md text-sm leading-relaxed text-white/60">
                유튜브는 '아무 매장'에나 어울리는 음악을 틀고,
                <br />
                우리는 '당신 매장'에만 어울리는 음악을 듭니다.
                <br />
                사업자번호 10자리면 됩니다.
              </p>

              <form
                className="flex w-full max-w-md flex-col gap-4"
                onSubmit={(e) => {
                  e.preventDefault()
                  void flow.runAnalyse()
                }}
              >
                <FieldInput
                  id="bno"
                  name="business_number"
                  value={bno}
                  onChange={(e) => flow.setBno(e.target.value)}
                  inputMode="numeric"
                  placeholder="000-00-00000"
                  aria-label="사업자등록번호"
                  aria-invalid={Boolean(error)}
                  className="h-14 rounded-full border-white/30 bg-transparent px-6 text-center text-lg text-white placeholder:text-white/40 focus:border-white"
                  autoFocus
                />
                {error && <p className="text-sm text-white/80">{error}</p>}
                <Button
                  type="submit"
                  size="lg"
                  className="h-14 w-full rounded-full bg-white text-base font-bold text-primary hover:bg-white/90 hover:text-primary"
                >
                  시작하기
                </Button>
              </form>

              {analysis?.success && (
                <button
                  type="button"
                  onClick={flow.showPrevious}
                  className="text-sm text-white/50 underline underline-offset-4 transition-colors hover:text-white"
                >
                  이전 분석 결과 다시 보기
                </button>
              )}
            </div>
          )}

          {/* ── loading ── */}
          {phase === "loading" && (
            <div className="flex w-full max-w-md flex-col gap-6">
              <LoadingChecklist bno={bno} progress={flow.progress} />
            </div>
          )}

          {/* ── needs_input ── */}
          {phase === "needs_input" && need && (
            <div className="w-full max-w-md">
              <NeedsInputStep
                need={need}
                name={flow.needName}
                hint={flow.needHint}
                onName={flow.setNeedName}
                onHint={flow.setNeedHint}
                onBack={flow.restart}
                onPick={(placeId) =>
                  void flow.runAnalyse({ place_id: placeId })
                }
                onSubmit={flow.submitNeedInput}
              />
            </div>
          )}
        </main>
      </div>

      {/* ── right: phone image (50%) ── */}
      <div className="hidden p-2.5 lg:block lg:w-[50%]">
        <div className="h-full w-full overflow-hidden rounded-2xl">
          <img
            src="/phone.png"
            alt="Yielda 매장 음악 앱 화면"
            className="h-full w-full object-cover"
          />
        </div>
      </div>
    </div>
  )
}
