import { useCallback, useEffect, useMemo, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Alert02Icon, InformationCircleIcon } from "@hugeicons/core-free-icons"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  AmbienceByCategoryChart,
  CategoryChart,
  DailyVolumeChart,
  DistrictChart,
  DistrictMethodChart,
  HourlyChart,
  HoursSourceChart,
  PlaylistChart,
  TextSourceChart,
} from "@/components/collection/collection-charts"
import { CollectionTable } from "@/components/collection/collection-table"
import { DashboardHeader } from "@/components/collection/dashboard-header"
import { DashboardSidebar } from "@/components/collection/dashboard-sidebar"
import type { Section } from "@/components/collection/dashboard-nav"
import { KpiCards, QualityCards } from "@/components/collection/kpi-cards"
import { RowDetailSheet } from "@/components/collection/row-detail-sheet"
import {
  DEFAULT_VISIBLE,
  downloadCsv,
  fetchCollection,
  withinDays,
  type CollectionResponse,
  type CollectionRow,
} from "@/lib/collection"

const OUTCOMES = [
  { value: "all", label: "전체" },
  { value: "success", label: "성공" },
  { value: "needs_input", label: "입력 필요" },
  { value: "closed", label: "폐업" },
  { value: "suspended", label: "휴업" },
] as const

const SEARCH_COLUMNS = [
  "biz_no",
  "store_name",
  "category",
  "address",
  "district_type",
]

/** 분석 수집 대시보드 — 시트에 쌓인 분석 기록을 지표·차트·표로 검수한다.
 *
 *  데이터는 백엔드 `GET /api/collection` 이 Apps Script 를 프록시해서 준다
 *  (웹훅 URL 은 자격증명이라 프론트 번들에 넣지 않는다). */
export function CollectionPage() {
  const [data, setData] = useState<CollectionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [section, setSection] = useState<Section>("overview")
  const [query, setQuery] = useState("")
  const [outcome, setOutcome] = useState<string>("all")
  const [range, setRange] = useState("0")
  const [visible, setVisible] = useState<string[]>(DEFAULT_VISIBLE)
  const [detail, setDetail] = useState<CollectionRow | null>(null)
  // 새로고침 버튼이 올리는 카운터. 이펙트는 이 값에만 반응한다.
  const [reloadKey, setReloadKey] = useState(0)

  // setState 는 전부 프로미스 콜백 안에서만 부른다 — 이펙트 본문에서 동기로
  // 부르면 연쇄 렌더가 난다(react-hooks/set-state-in-effect).
  useEffect(() => {
    let cancelled = false
    fetchCollection()
      .then((next) => {
        if (cancelled) return
        setData(next)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "알 수 없는 오류")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    // 뒤늦게 도착한 응답이 상태를 덮어쓰지 않게 한다.
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  const reload = useCallback(() => {
    setLoading(true)
    setReloadKey((n) => n + 1)
  }, [])

  const allColumns = useMemo(
    () => (data?.columns?.length ? data.columns : DEFAULT_VISIBLE),
    [data]
  )

  const days = Number(range)

  /** 기간 → 검색어 → outcome 순으로 좁힌다. 모든 섹션이 같은 결과를 본다. */
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return withinDays(data?.rows ?? [], days).filter((row) => {
      if (outcome !== "all" && String(row.outcome ?? "") !== outcome)
        return false
      if (!needle) return true
      return SEARCH_COLUMNS.some((c) =>
        String(row[c] ?? "")
          .toLowerCase()
          .includes(needle)
      )
    })
  }, [data, days, query, outcome])

  const visibleColumns = useMemo(
    () => visible.filter((c) => allColumns.includes(c)),
    [visible, allColumns]
  )

  const exportCsv = () => {
    const stamp = new Date().toISOString().slice(0, 10)
    downloadCsv(allColumns, rows, `yielda-analyses-${stamp}.csv`)
  }

  return (
    <SidebarProvider className="dark">
      <DashboardSidebar
        section={section}
        onSectionChange={setSection}
        recordCount={rows.length}
      />

      <SidebarInset className="min-w-0 bg-background">
        <DashboardHeader
          section={section}
          query={query}
          onQueryChange={setQuery}
          range={range}
          onRangeChange={setRange}
          onRefresh={reload}
          onExport={exportCsv}
          loading={loading}
          exportDisabled={rows.length === 0}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-4 p-4 md:p-6">
          {error ? (
            <Alert variant="destructive">
              <HugeiconsIcon icon={Alert02Icon} />
              <AlertTitle>수집 데이터를 불러오지 못했습니다</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {data && !data.available && data.reason === "read_failed" ? (
            <Alert variant="destructive">
              <HugeiconsIcon icon={Alert02Icon} />
              <AlertTitle>시트를 불러오지 못했습니다</AlertTitle>
              <AlertDescription>
                설정은 정상입니다. 시트 응답이 늦거나 일시적으로 실패했습니다
                {data.error ? ` (${data.error})` : ""} — 새로고침해 주세요.
              </AlertDescription>
            </Alert>
          ) : data && !data.available ? (
            <Alert>
              <HugeiconsIcon icon={InformationCircleIcon} />
              <AlertTitle>수집 시트가 연결되지 않았습니다</AlertTitle>
              <AlertDescription>
                <code>SHEETS_WEBHOOK_URL</code> 을 설정하세요 — 절차는{" "}
                <code>scripts/apps_script/README.md</code> 에 있습니다.
              </AlertDescription>
            </Alert>
          ) : null}

          {/* outcome 필터는 2–5지선다 → ToggleGroup */}
          <div className="flex flex-wrap items-center gap-3">
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              value={outcome}
              onValueChange={(next) => setOutcome(next || "all")}
            >
              {OUTCOMES.map((item) => (
                <ToggleGroupItem key={item.value} value={item.value}>
                  {item.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <Badge variant="outline">{rows.length}건 표시 중</Badge>
          </div>

          {loading && !data ? (
            <DashboardSkeleton />
          ) : (
            <SectionBody
              section={section}
              rows={rows}
              days={days}
              allColumns={allColumns}
              visible={visibleColumns}
              onVisibleChange={setVisible}
              onRowSelect={setDetail}
            />
          )}
        </div>
      </SidebarInset>

      <RowDetailSheet
        row={detail}
        onOpenChange={(open) => !open && setDetail(null)}
      />
    </SidebarProvider>
  )
}

function SectionBody({
  section,
  rows,
  days,
  allColumns,
  visible,
  onVisibleChange,
  onRowSelect,
}: {
  section: Section
  rows: CollectionRow[]
  days: number
  allColumns: string[]
  visible: string[]
  onVisibleChange: (next: string[]) => void
  onRowSelect: (row: CollectionRow) => void
}) {
  if (section === "records") {
    return (
      <CollectionTable
        columns={allColumns}
        visible={visible}
        onVisibleChange={onVisibleChange}
        rows={rows}
        onRowSelect={onRowSelect}
      />
    )
  }

  if (section === "ambience") {
    return (
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <AmbienceByCategoryChart rows={rows} />
        <AmbienceByCategoryChart
          rows={rows}
          groupBy="district_type"
          title="상권별 분위기 평균"
          description="표본 2건 이상 · 상권 라벨 기준"
        />
        <PlaylistChart rows={rows} />
        <CategoryChart rows={rows} />
      </div>
    )
  }

  if (section === "pipeline") {
    return (
      <div className="flex flex-col gap-4">
        <QualityCards rows={rows} />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
          <TextSourceChart rows={rows} />
          <HoursSourceChart rows={rows} />
          <DistrictMethodChart rows={rows} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <KpiCards rows={rows} days={days} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <DailyVolumeChart rows={rows} />
        <HourlyChart rows={rows} />
        <CategoryChart rows={rows} />
        <DistrictChart rows={rows} />
      </div>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-80 rounded-xl" />
        ))}
      </div>
    </div>
  )
}
