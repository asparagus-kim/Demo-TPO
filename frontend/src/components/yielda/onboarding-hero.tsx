import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import { Field, FieldInput } from "@/components/yielda/field"
import { cn } from "@/lib/utils"

/** Onboarding steps mirrored from the real analyse flow (idle → needs_input → done). */
const STEPS = [
  { n: 1, label: "사업자번호 입력", active: true },
  { n: 2, label: "매장 확인 · 동명 매장 좁히기", active: false },
  { n: 3, label: "맞춤 플레이리스트 재생", active: false },
]

/** Screen 1 (v0.7) — auth split-card.
 *  One large rounded card centered on the dark page, split 50/50:
 *  left = accent brand panel (primary→primary-deep sweep, chip, display
 *  headline, sub-copy, 3 step cards — step 1 active/white, 2·3 frosted);
 *  right = elevated dark form panel (title, business-number field, pill CTA).
 *  Below lg the halves stack: brand panel on top, form below. */
export function OnboardingHero({
  bno,
  error,
  onBnoChange,
  onSubmit,
  hasPrevious,
  onShowPrevious,
}: {
  bno: string
  error: string
  onBnoChange: (v: string) => void
  onSubmit: () => void
  hasPrevious: boolean
  onShowPrevious: () => void
}) {
  return (
    <div className="m-auto w-full max-w-6xl py-8 lg:py-10">
      <div className="grid overflow-hidden rounded-3xl border border-border bg-panel shadow-2xl lg:min-h-[38rem] lg:grid-cols-2">
        {/* ── left: gradient brand panel ── */}
        <section className="relative flex flex-col gap-10 overflow-hidden bg-linear-to-br from-primary via-primary via-30% to-primary-deep p-6 sm:p-10">
          {/* luminous bloom anchoring the bright top-left corner */}
          <div className="pointer-events-none absolute inset-0 bg-radial-[at_10%_0%] from-foreground/30 via-transparent to-transparent" />
          {/* soft secondary glow keeping the mid-panel from going flat */}
          <div className="pointer-events-none absolute inset-0 bg-radial-[at_85%_45%] from-foreground/10 via-transparent to-transparent" />
          {/* deep vignette grounding the bottom-right corner */}
          <div className="pointer-events-none absolute inset-0 bg-radial-[at_105%_115%] from-background/50 via-transparent to-transparent" />

          {/* brand — top-left; the accent "a" flips to on-accent ink over the fill */}
          <BrandWordmark className="relative z-10 text-2xl [&>span]:text-primary-foreground" />

          {/* vertically centered message block */}
          <div className="relative z-10 flex flex-1 flex-col justify-center gap-5">
            <span className="inline-flex w-fit items-center rounded-full bg-foreground/15 px-4 py-1.5 text-sm font-semibold backdrop-blur-sm">
              매장 음악, 사업자번호 하나로 🎵
            </span>
            <h1 className="text-4xl leading-[1.12] font-black tracking-tight break-keep xl:text-[3.25rem] xl:leading-[1.08]">
              사업자 번호 하나로
              <br />
              매장음악 시작
            </h1>
            <p className="max-w-md text-[15px] leading-relaxed break-keep text-foreground/75">
              업종·상권·영업시간·현재 날씨를 분석해 매장 분위기를 산출하고, 그
              분위기에 맞는 곡을 골라 재생합니다.
            </p>
          </div>

          {/* step cards — 1 active (white), 2 & 3 frosted translucent */}
          <ol className="relative z-10 grid gap-3 sm:grid-cols-3">
            {STEPS.map((step) => (
              <li
                key={step.n}
                className={cn(
                  "flex items-center gap-3 rounded-xl p-4 sm:flex-col sm:items-start sm:gap-4",
                  step.active
                    ? "bg-foreground text-background shadow-lg"
                    : "bg-foreground/10 text-foreground/85 backdrop-blur-sm"
                )}
              >
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-full text-sm font-bold",
                    step.active
                      ? "bg-primary text-primary-foreground"
                      : "border border-foreground/40 text-foreground/90"
                  )}
                >
                  {step.n}
                </span>
                <span className="text-sm leading-snug font-bold break-keep">
                  {step.label}
                </span>
              </li>
            ))}
          </ol>
        </section>

        {/* ── right: form panel — calm elevated dark surface ── */}
        <section className="flex flex-col justify-center p-6 py-12 sm:p-12 lg:p-14">
          <div className="mx-auto flex w-full max-w-sm flex-col gap-8">
            <div className="flex flex-col gap-2">
              <h2 className="text-3xl font-extrabold tracking-tight">
                시작하기
              </h2>
              <p className="text-sm text-muted-foreground">
                사업자등록번호만 있으면 준비 끝 — 가입 없이 바로 분석합니다.
              </p>
            </div>

            <form
              className="flex flex-col gap-3"
              onSubmit={(e) => {
                e.preventDefault()
                onSubmit()
              }}
            >
              <Field label="사업자등록번호" htmlFor="bno">
                <FieldInput
                  id="bno"
                  name="business_number"
                  value={bno}
                  onChange={(e) => onBnoChange(e.target.value)}
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

            {hasPrevious && (
              <button
                type="button"
                onClick={onShowPrevious}
                className="mx-auto w-fit text-sm text-muted-foreground underline underline-offset-4 transition-colors hover:text-foreground"
              >
                이전 분석 결과 다시 보기
              </button>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
