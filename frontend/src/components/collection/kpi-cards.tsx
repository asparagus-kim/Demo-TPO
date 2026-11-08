import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, ArrowUp01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import type { CollectionRow } from "@/lib/collection"
import { average, isTrue, rateOf, trend } from "@/lib/collection"

interface Kpi {
  label: string
  value: string
  footnote: string
  delta?: { pct: number | null; current: number; previous: number } | null
}

function formatPct(value: number | null): string {
  return value === null ? "–" : `${Math.round(value)}%`
}

function TrendBadge({ delta }: { delta: NonNullable<Kpi["delta"]> }) {
  if (delta.pct === null) {
    return <Badge variant="secondary">신규</Badge>
  }
  const up = delta.pct >= 0
  return (
    <Badge variant={up ? "secondary" : "outline"}>
      <HugeiconsIcon icon={up ? ArrowUp01Icon : ArrowDown01Icon} />
      {up ? "+" : ""}
      {Math.round(delta.pct)}%
    </Badge>
  )
}

/** 하나의 숫자가 곧 답인 지표는 차트가 아니라 카드로 낸다.
 *  증감 배지는 선택한 기간과 **직전 동일 기간**을 비교한다. */
export function KpiCards({
  rows,
  days,
}: {
  rows: CollectionRow[]
  days: number
}) {
  const volumeTrend = trend(rows, days)
  const successRate = rateOf(rows, (r) => String(r.outcome ?? "") === "success")
  const uniqueStores = new Set(
    rows.map((r) => String(r.biz_no ?? "")).filter(Boolean)
  ).size

  // 캐시 히트는 0ms 라 실제 파이프라인 시간을 왜곡한다 — 빼고 잰다.
  const fresh = rows.filter((r) => !isTrue(r.cache_hit))
  const durationMs = average(fresh, "duration_ms")

  const energy = average(rows, "energy")
  const tempo = average(rows, "tempo")
  const mood = average(rows, "mood")

  const kpis: Kpi[] = [
    {
      label: "분석 건수",
      value: String(rows.length),
      footnote:
        volumeTrend && volumeTrend.pct !== null
          ? `직전 동일 기간 ${volumeTrend.previous}건`
          : "선택한 기간 기준",
      delta: volumeTrend,
    },
    {
      label: "고유 매장",
      value: String(uniqueStores),
      footnote: `사업자번호 중복 제외 · 재분석 ${Math.max(rows.length - uniqueStores, 0)}건`,
    },
    {
      label: "분석 성공률",
      value: formatPct(successRate),
      footnote: `매장 확정 실패 ${rows.filter((r) => String(r.outcome ?? "") === "needs_input").length}건`,
    },
    {
      label: "평균 소요",
      value: durationMs === null ? "–" : `${(durationMs / 1000).toFixed(1)}s`,
      footnote: `캐시 히트 ${rows.length - fresh.length}건 제외`,
    },
    {
      label: "평균 E · T · M",
      value:
        energy === null || tempo === null || mood === null
          ? "–"
          : `${Math.round(energy)} · ${Math.round(tempo)} · ${Math.round(mood)}`,
      footnote: "에너지 · 템포 · 무드 (0–100)",
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
      {kpis.map((kpi) => (
        <Card key={kpi.label}>
          <CardHeader>
            <CardDescription>{kpi.label}</CardDescription>
            <CardTitle className="text-2xl font-extrabold tabular-nums @[250px]/card:text-3xl">
              {kpi.value}
            </CardTitle>
            {kpi.delta ? (
              <CardAction>
                <TrendBadge delta={kpi.delta} />
              </CardAction>
            ) : null}
          </CardHeader>
          <CardFooter>
            <p className="text-xs text-muted-foreground">{kpi.footnote}</p>
          </CardFooter>
        </Card>
      ))}
    </div>
  )
}

/** 파이프라인 품질 지표 — 비율만 모아서 보는 작은 카드 묶음. */
export function QualityCards({ rows }: { rows: CollectionRow[] }) {
  const done = rows.filter((r) => String(r.outcome ?? "") === "success")
  const stats = [
    {
      label: "동일업체 검증 통과",
      value: formatPct(rateOf(done, (r) => isTrue(r.consistency))),
      hint: "Kakao 확정 매장 vs Google 후보",
    },
    {
      label: "Google 리뷰 사용",
      value: formatPct(
        rateOf(done, (r) =>
          ["google_reviews", "mixed"].includes(String(r.text_source ?? ""))
        )
      ),
      hint: "나머지는 웹검색·prior 로 대체",
    },
    {
      label: "영업시간 확보",
      value: formatPct(
        rateOf(done, (r) => String(r.hours_source ?? "") !== "none")
      ),
      hint: "Google 또는 웹검색에서 회수",
    },
    {
      label: "캐시 히트율",
      value: formatPct(rateOf(rows, (r) => isTrue(r.cache_hit))),
      hint: "같은 번호·같은 선택의 재요청",
    },
  ]

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {stats.map((stat) => (
        <Card key={stat.label}>
          <CardHeader>
            <CardDescription>{stat.label}</CardDescription>
            <CardTitle className="text-2xl font-extrabold tabular-nums">
              {stat.value}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-muted-foreground">{stat.hint}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
