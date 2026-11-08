import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  XAxis,
  YAxis,
} from "recharts"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import type { CollectionRow } from "@/lib/collection"
import {
  ambienceByCategory,
  countBy,
  countByDay,
  countByHour,
  labelFor,
} from "@/lib/collection"

/** 차트 한 장 = Card 한 장. 제목이 시리즈를 지목하므로 단일 시리즈에는 범례가 없다. */
function ChartCard({
  title,
  description,
  isEmpty,
  emptyText,
  className,
  children,
}: {
  title: string
  description: string
  isEmpty: boolean
  emptyText: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {isEmpty ? (
          <Empty className="border-0 py-10">
            <EmptyHeader>
              <EmptyTitle>표시할 데이터가 없습니다</EmptyTitle>
              <EmptyDescription>{emptyText}</EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  )
}

/** 범례 순서를 막대 그리는 순서와 맞춘다.
 *  recharts 가 넘겨주는 payload 순서는 Bar 선언 순서와 어긋나서, 그대로 두면
 *  범례가 "에너지 · 무드 · 템포" 로 나와 막대(E·T·M)와 읽는 순서가 달라진다.
 *  recharts 는 content 엘리먼트를 payload 와 함께 clone 하므로 여기서 정렬한다. */
function OrderedLegend({
  seriesOrder,
  ...props
}: { seriesOrder: string[] } & React.ComponentProps<
  typeof ChartLegendContent
>) {
  const payload = [...(props.payload ?? [])].sort(
    (a, b) =>
      seriesOrder.indexOf(String(a.dataKey)) -
      seriesOrder.indexOf(String(b.dataKey))
  )
  return <ChartLegendContent {...props} payload={payload} />
}

/** 일자별 분석 건수 — 시간축이므로 면적. 시리즈가 하나라 범례 없음. */
export function DailyVolumeChart({ rows }: { rows: CollectionRow[] }) {
  const data = countByDay(rows)
  const config = {
    count: { label: "분석 건수", color: "var(--chart-1)" },
  } satisfies ChartConfig

  return (
    <ChartCard
      title="일자별 분석 건수"
      description="빈 날짜는 0으로 채워 축이 거짓말하지 않게 했습니다"
      isEmpty={data.length === 0}
      emptyText="선택한 기간에 수집된 분석이 없습니다."
    >
      <ChartContainer config={config} className="h-60 w-full">
        <AreaChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
          <defs>
            <linearGradient id="fill-volume" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--color-count)"
                stopOpacity={0.35}
              />
              <stop
                offset="100%"
                stopColor="var(--color-count)"
                stopOpacity={0.02}
              />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="day"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            minTickGap={24}
            tickFormatter={(v: string) => v.slice(5)}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={28}
            allowDecimals={false}
          />
          <ChartTooltip
            cursor
            content={<ChartTooltipContent indicator="line" />}
          />
          <Area
            dataKey="count"
            type="monotone"
            stroke="var(--color-count)"
            strokeWidth={2}
            fill="url(#fill-volume)"
            dot={data.length === 1}
            activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--card)" }}
          />
        </AreaChart>
      </ChartContainer>
    </ChartCard>
  )
}

/** 시각대별 분포 — 운영이 '언제 몰리는지' 본다. */
export function HourlyChart({ rows }: { rows: CollectionRow[] }) {
  const data = countByHour(rows)
  const config = {
    count: { label: "건수", color: "var(--chart-1)" },
  } satisfies ChartConfig
  const peak = data.reduce((a, b) => (b.count > a.count ? b : a), data[0])

  return (
    <ChartCard
      title="시간대별 분석 요청"
      description={
        peak && peak.count > 0
          ? `가장 몰리는 시간대는 ${peak.hour} (${peak.count}건)`
          : "KST 기준 0–23시"
      }
      isEmpty={rows.length === 0}
      emptyText="선택한 기간에 요청이 없습니다."
    >
      <ChartContainer config={config} className="h-60 w-full">
        <BarChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="hour"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            interval={2}
            tickFormatter={(v: string) => v.replace("시", "")}
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={28}
            allowDecimals={false}
          />
          <ChartTooltip
            cursor
            content={<ChartTooltipContent hideIndicator />}
          />
          <Bar
            dataKey="count"
            fill="var(--color-count)"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  )
}

/** 값별 건수 가로 막대 — 라벨이 길고(업종·상권명) 순위 비교가 목적. */
function RankedBarChart({
  rows,
  column,
  title,
  description,
  color,
  limit = 8,
}: {
  rows: CollectionRow[]
  column: string
  title: string
  description: string
  color: string
  limit?: number
}) {
  const data = countBy(rows, column, limit)
  const config = { count: { label: "건수", color } } satisfies ChartConfig

  return (
    <ChartCard
      title={title}
      description={description}
      isEmpty={data.length === 0}
      emptyText={`${labelFor(column)} 값이 있는 행이 없습니다.`}
    >
      <ChartContainer
        config={config}
        className="w-full"
        style={{ height: Math.max(data.length * 34 + 20, 160) }}
      >
        <BarChart data={data} layout="vertical" margin={{ left: 4, right: 32 }}>
          <CartesianGrid horizontal={false} strokeDasharray="3 3" />
          <XAxis type="number" hide allowDecimals={false} />
          <YAxis
            type="category"
            dataKey="name"
            tickLine={false}
            axisLine={false}
            width={110}
            tickMargin={6}
          />
          <ChartTooltip
            cursor
            content={<ChartTooltipContent hideIndicator />}
          />
          <Bar
            dataKey="count"
            fill="var(--color-count)"
            radius={[0, 4, 4, 0]}
            barSize={16}
          >
            {/* 막대 끝에 값을 직접 붙인다 — 눈금축을 읽게 만들지 않는다. */}
            <LabelList
              dataKey="count"
              position="right"
              offset={8}
              className="fill-muted-foreground"
              fontSize={12}
            />
          </Bar>
        </BarChart>
      </ChartContainer>
    </ChartCard>
  )
}

export function CategoryChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="category"
      title="업종 분포"
      description="상위 8개 · 나머지는 '기타'로 접습니다"
      color="var(--chart-1)"
    />
  )
}

export function DistrictChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="district_type"
      title="상권 유형 분포"
      description="파이프라인이 판정한 상권 라벨 기준"
      color="var(--chart-3)"
    />
  )
}

export function PlaylistChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="playlist_label"
      title="플레이리스트 분포"
      description="추천 엔진이 최종적으로 붙인 라벨"
      color="var(--chart-4)"
      limit={6}
    />
  )
}

export function TextSourceChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="text_source"
      title="분석 근거 출처"
      description="google_reviews · web_search · mixed · none"
      color="var(--chart-2)"
      limit={5}
    />
  )
}

export function HoursSourceChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="hours_source"
      title="영업시간 확보 경로"
      description="google = 그대로 · web = 검색으로 보강 · none = 실패"
      color="var(--chart-5)"
      limit={5}
    />
  )
}

export function DistrictMethodChart({ rows }: { rows: CollectionRow[] }) {
  return (
    <RankedBarChart
      rows={rows}
      column="district_method"
      title="상권 판정 방식"
      description="surroundings = 주변 분포 · fallback = 사전 분류표"
      color="var(--chart-3)"
      limit={4}
    />
  )
}

/** 업종별 E/T/M 평균 — 세 시리즈이므로 범례가 반드시 붙는다. */
export function AmbienceByCategoryChart({
  rows,
  groupBy = "category",
  title = "업종별 분위기 평균",
  description = "표본 2건 이상 · 0–100 스케일 하나로 통일",
}: {
  rows: CollectionRow[]
  groupBy?: string
  title?: string
  description?: string
}) {
  const data = ambienceByCategory(rows, 2, 6, groupBy)
  const config = {
    energy: { label: "에너지", color: "var(--chart-1)" },
    tempo: { label: "템포", color: "var(--chart-2)" },
    mood: { label: "무드", color: "var(--chart-3)" },
  } satisfies ChartConfig

  return (
    <ChartCard
      title={title}
      description={description}
      isEmpty={data.length === 0}
      emptyText="표본이 2건 이상인 그룹이 아직 없습니다."
    >
      <ChartContainer config={config} className="h-65 w-full">
        <BarChart data={data} margin={{ left: 4, right: 12, top: 8 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis
            dataKey="name"
            tickLine={false}
            axisLine={false}
            tickMargin={8}
            interval={0}
            tickFormatter={(v: string) =>
              v.length > 7 ? `${v.slice(0, 6)}…` : v
            }
          />
          <YAxis
            tickLine={false}
            axisLine={false}
            width={28}
            domain={[0, 100]}
          />
          <ChartTooltip cursor content={<ChartTooltipContent />} />
          <ChartLegend
            content={
              <OrderedLegend seriesOrder={["energy", "tempo", "mood"]} />
            }
          />
          {/* 막대 사이 2px 은 표면색 간격 — 붙여 놓으면 경계가 사라진다. */}
          <Bar
            dataKey="energy"
            fill="var(--color-energy)"
            radius={[4, 4, 0, 0]}
            barSize={14}
          />
          <Bar
            dataKey="tempo"
            fill="var(--color-tempo)"
            radius={[4, 4, 0, 0]}
            barSize={14}
          />
          <Bar
            dataKey="mood"
            fill="var(--color-mood)"
            radius={[4, 4, 0, 0]}
            barSize={14}
          />
        </BarChart>
      </ChartContainer>
    </ChartCard>
  )
}
