import { useLocation } from "react-router-dom"

import { useAnalysis } from "@/lib/analysis-store"
import { PRIVACY_POLICY_URL } from "@/lib/legal-links"
import { useAnalysisFlow } from "@/lib/use-analysis-flow"
import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import { FieldInput } from "@/components/yielda/field"
import {
  LoadingChecklist,
  NeedsInputStep,
} from "@/components/yielda/analysis-steps"
import { ResultView } from "@/components/yielda/result-view"

/** Onboarding v3 — 50/50 split: primary left (form), dark right (player image). */
export function OnboardingV3Page() {
  const { analysis } = useAnalysis()
  const { restart } =
    (useLocation().state as { restart?: boolean } | null) ?? {}
  const flow = useAnalysisFlow({ startIdle: restart })
  const { phase, bno, error, need } = flow

  /* ── done: full-width result view ── */
  if (phase === "done" && analysis) {
    return (
      <div className="min-h-svh w-full overflow-y-auto px-4 pb-16">
        <div className="mx-auto w-full max-w-[96rem]">
          <div className="flex justify-center pt-8 pb-2">
            <button
              type="button"
              onClick={flow.restart}
              className="cursor-pointer"
              aria-label="온보딩 페이지로 돌아가기"
            >
              <BrandWordmark className="text-3xl" />
            </button>
          </div>
          <div className="pt-4">
            <ResultView analysis={analysis} onRestart={flow.restart} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-svh w-full">
      {/* ── left: primary bg + form (50%) ── */}
      <div className="flex w-full flex-col bg-primary text-white lg:w-1/2">
        <header className="shrink-0 px-8 pt-8">
          <BrandWordmark className="text-3xl text-white [&>span]:text-white" />
        </header>

        {/* 후보가 많으면(동명 매장 8~9건) 내용이 뷰포트보다 길어진다. 예전에는
            h-svh 밖으로 흘러넘쳐 파란 패널 아래가 잘린 것처럼 보였다 — 패널 안에서
            스크롤시킨다. 세로 정렬은 justify-center 대신 자식의 m-auto 로 한다:
            justify-center 는 내용이 넘칠 때 위쪽이 스크롤로 닿지 않는다. */}
        <main className="flex min-h-0 flex-1 flex-col items-center overflow-y-auto px-8 py-8">
          {/* ── idle ── */}
          {phase === "idle" && (
            <div className="m-auto flex w-full max-w-lg flex-col items-center gap-8 text-center">
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
            <div className="m-auto flex w-full max-w-md flex-col gap-6">
              <LoadingChecklist bno={bno} progress={flow.progress} />
            </div>
          )}

          {/* ── needs_input ── */}
          {phase === "needs_input" && need && (
            <div className="m-auto w-full max-w-md">
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

        {/* Privacy policy link — this screen collects the business number. Opens in a new tab so the form state survives. */}
        <footer className="shrink-0 px-8 pb-6 text-center text-xs text-white/60">
          <a
            href={PRIVACY_POLICY_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="underline underline-offset-4 transition-colors hover:text-white"
          >
            개인정보 처리방침
          </a>
        </footer>
      </div>

      {/* ── right: dark bg + centered player image (50%) ── */}
      <div className="hidden items-center justify-center bg-background lg:flex lg:w-1/2">
        <img
          src="/playermobile.png"
          alt="Yielda 매장 음악 플레이어"
          className="max-h-[80%] w-auto max-w-[85%] object-contain"
        />
      </div>
    </div>
  )
}
