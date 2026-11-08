import { Check, ChevronLeft, ChevronRight } from "lucide-react"

import type { NeedsInput } from "@/lib/api"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Field, FieldInput, OrDivider } from "@/components/yielda/field"
import { OrbitLoader } from "@/components/yielda/progress-bar"

/** Wizard bodies for the analysis flow — layout-agnostic, token-only colors,
 *  so every onboarding shell (dark v1, light v2) can drop them in. */

/** 분석 중 순서대로 켜지는 체크리스트 (legacy home-page와 동일) */
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

/* ── 분석 중: 진행 바 + 스텝 헤더 + 요건 체크리스트 ── */
export function LoadingChecklist({
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
    <div className="flex w-full max-w-md flex-col gap-6 text-left">
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

      {/* 유일한 진행 표시기 — 진행률은 ARIA로만 노출한다 */}
      <div
        role="progressbar"
        aria-label="분석 진행률"
        aria-valuenow={Math.round(Math.max(0, Math.min(1, progress)) * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        className="flex items-center justify-center py-2 opacity-60"
      >
        <OrbitLoader size={32} />
      </div>
    </div>
  )
}

/* ── 추가 입력: 매장 후보 선택 / 상호명·지역 직접 입력 ── */
export function NeedsInputStep({
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
    <div className="flex w-full max-w-md flex-col gap-5 text-left">
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
          <Field
            label="상호명"
            helper="등록된 법인명이 실제 매장명과 다르면 고쳐 주세요"
          >
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
