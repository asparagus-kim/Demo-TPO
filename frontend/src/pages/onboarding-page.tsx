import { useAnalysis } from "@/lib/analysis-store"
import { useAnalysisFlow } from "@/lib/use-analysis-flow"
import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import { Field, FieldInput } from "@/components/yielda/field"
import {
  LoadingChecklist,
  NeedsInputStep,
} from "@/components/yielda/analysis-steps"
import { ResultView } from "@/components/yielda/result-view"

/** Onboarding v1 (dark) — desk photo full-bleed, gradient panel over its empty
 *  right side. Superseded by `onboarding-v2-page.tsx`; kept at /onboarding-v1. */
export function OnboardingPage() {
  const { analysis } = useAnalysis()
  const flow = useAnalysisFlow()
  const { phase, bno, error, need } = flow

  /* ── done: 결과 화면이 전체를 차지 (legacy 레이아웃과 동일한 폭) ── */
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
    <div className="relative h-svh w-full overflow-hidden">
      <img
        src="/onboarding-2.png"
        alt="Yielda 매장 음악 서비스 미리보기"
        className="absolute inset-0 h-full w-full object-cover object-left"
      />

      {/* Right-side panel over the image's empty area */}
      <div className="absolute inset-y-0 right-0 flex w-[54%] items-center p-4">
        <section className="flex h-full w-full flex-col items-center justify-center gap-6 overflow-y-auto rounded-3xl bg-primary-deep p-8 text-center shadow-2xl sm:p-12">
          {phase === "idle" && (
            <>
              <BrandWordmark className="text-3xl" />

              <h1 className="text-4xl leading-[1.12] font-black tracking-tight break-keep xl:text-[3.25rem] xl:leading-[1.08]">
                사업자 번호 하나로
                <br />
                매장음악 시작
              </h1>
              <p className="max-w-md text-[15px] leading-relaxed break-keep text-foreground/75">
                업종·상권·영업시간·현재 날씨를 분석해 매장 분위기를 산출하고, 그
                분위기에 맞는 곡을 골라 재생합니다.
              </p>

              <form
                className="mt-2 flex w-full max-w-sm flex-col gap-3 text-left"
                onSubmit={(e) => {
                  e.preventDefault()
                  void flow.runAnalyse()
                }}
              >
                <Field label="사업자등록번호" htmlFor="bno">
                  <FieldInput
                    id="bno"
                    name="business_number"
                    value={bno}
                    onChange={(e) => flow.setBno(e.target.value)}
                    inputMode="numeric"
                    placeholder="000-00-00000"
                    aria-invalid={Boolean(error)}
                    autoFocus
                  />
                </Field>
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button
                  type="submit"
                  size="lg"
                  className="mt-2 h-12 w-full rounded-full text-base font-bold"
                >
                  시작하기
                </Button>
              </form>

              {analysis?.success && (
                <button
                  type="button"
                  onClick={flow.showPrevious}
                  className="text-sm text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground"
                >
                  이전 분석 결과 다시 보기
                </button>
              )}
            </>
          )}

          {phase === "loading" && (
            <LoadingChecklist bno={bno} progress={flow.progress} />
          )}

          {phase === "needs_input" && need && (
            <NeedsInputStep
              need={need}
              name={flow.needName}
              hint={flow.needHint}
              onName={flow.setNeedName}
              onHint={flow.setNeedHint}
              onBack={flow.restart}
              onPick={(placeId) => void flow.runAnalyse({ place_id: placeId })}
              onSubmit={flow.submitNeedInput}
            />
          )}
        </section>
      </div>
    </div>
  )
}
