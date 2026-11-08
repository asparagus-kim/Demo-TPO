import { useMemo, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  ArrowLeft01Icon,
  ArrowRight01Icon,
  ArrowUp01Icon,
  Settings01Icon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { cn } from "@/lib/utils"
import type { CollectionRow } from "@/lib/collection"
import { labelFor } from "@/lib/collection"

const PAGE_SIZE = 25

/** 자리를 많이 먹는 열은 폭을 제한하고 title 로 전문을 남긴다. */
const WIDE_COLUMNS = new Set([
  "address",
  "region_address",
  "hours",
  "district_criteria",
  "top_tracks",
  "playlist_label",
  "review_keywords",
  "category_full",
  "error",
  "kakao_place_url",
])

const NUMERIC_COLUMNS = new Set([
  "rating",
  "review_count",
  "reviews_analyzed",
  "energy",
  "tempo",
  "mood",
  "playlist_track_count",
  "music_pool_size",
  "duration_ms",
  "web_evidence_count",
  "lat",
  "lng",
  "weather_temp_c",
  "district_total_places",
  "district_univ_count",
  "district_confidence",
  "consistency_score",
  "ambience_confidence",
  "district_cafe_pct",
  "district_food_pct",
  "district_bank_pct",
  "district_edu_pct",
])

function OutcomeBadge({ outcome }: { outcome: string }) {
  if (outcome === "success") return <Badge variant="secondary">성공</Badge>
  if (outcome === "needs_input")
    return <Badge variant="outline">입력 필요</Badge>
  return <Badge variant="destructive">{outcome || "오류"}</Badge>
}

function renderCell(column: string, value: CollectionRow[string]) {
  if (value === null || value === undefined || value === "") {
    return <span className="text-muted-foreground/50">–</span>
  }
  if (column === "outcome") return <OutcomeBadge outcome={String(value)} />
  if (typeof value === "boolean") return value ? "Y" : "N"

  const text = String(value)
  if (column === "timestamp") {
    // "2026-08-11T14:49:29+09:00" → "08-11 14:49"
    const m = text.match(/^\d{4}-(\d{2}-\d{2})T(\d{2}:\d{2})/)
    return m ? `${m[1]} ${m[2]}` : text
  }
  if (
    column === "cache_hit" ||
    column === "mock_mode" ||
    column === "consistency"
  ) {
    return text === "TRUE" ? "Y" : text === "FALSE" ? "N" : text
  }
  return text
}

export function CollectionTable({
  columns,
  visible,
  onVisibleChange,
  rows,
  onRowSelect,
}: {
  columns: string[]
  visible: string[]
  onVisibleChange: (next: string[]) => void
  rows: CollectionRow[]
  onRowSelect: (row: CollectionRow) => void
}) {
  const [sort, setSort] = useState<{ column: string; desc: boolean } | null>(
    null
  )
  const [page, setPage] = useState(0)

  // 필터·정렬이 바뀌면 현재 페이지가 범위 밖일 수 있다. 이펙트로 되돌리면
  // 한 프레임 동안 빈 표가 보이고 연쇄 렌더가 난다 — 렌더 중에 바로 맞춘다
  // (React 의 "props 가 바뀌면 state 조정" 패턴).
  const signature = `${rows.length}|${sort?.column ?? ""}|${sort?.desc ?? ""}`
  const [prevSignature, setPrevSignature] = useState(signature)
  if (signature !== prevSignature) {
    setPrevSignature(signature)
    setPage(0)
  }

  const sorted = useMemo(() => {
    if (!sort) return rows
    const { column, desc } = sort
    // 원본을 건드리지 않는다 — 정렬은 새 배열로.
    return [...rows].sort((a, b) => {
      const av = a[column]
      const bv = b[column]
      const an = Number(av)
      const bn = Number(bv)
      const numeric =
        av !== "" && bv !== "" && Number.isFinite(an) && Number.isFinite(bn)
      const cmp = numeric
        ? an - bn
        : String(av ?? "").localeCompare(String(bv ?? ""), "ko")
      return desc ? -cmp : cmp
    })
  }, [rows, sort])

  const pageCount = Math.max(Math.ceil(sorted.length / PAGE_SIZE), 1)
  const pageRows = sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)

  const toggleSort = (column: string) =>
    setSort((prev) =>
      prev?.column === column
        ? { column, desc: !prev.desc }
        : { column, desc: true }
    )

  const toggleColumn = (column: string, checked: boolean) =>
    onVisibleChange(
      checked
        ? [...columns.filter((c) => visible.includes(c) || c === column)]
        : visible.filter((c) => c !== column)
    )

  return (
    <Card>
      <CardHeader>
        <CardTitle>분석 기록</CardTitle>
        <CardDescription>
          {sorted.length}건 · 행을 클릭하면 59개 필드 전체를 볼 수 있습니다
        </CardDescription>
        <CardAction>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <HugeiconsIcon icon={Settings01Icon} data-icon="inline-start" />
                표시 열 {visible.length}/{columns.length}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="max-h-105 overflow-y-auto"
            >
              <DropdownMenuLabel>표시할 열</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {columns.map((column) => (
                  <DropdownMenuCheckboxItem
                    key={column}
                    checked={visible.includes(column)}
                    onCheckedChange={(checked) =>
                      toggleColumn(column, Boolean(checked))
                    }
                    onSelect={(e) => e.preventDefault()}
                  >
                    {labelFor(column)}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </CardAction>
      </CardHeader>

      <CardContent className="px-0">
        {sorted.length === 0 ? (
          <Empty className="border-0">
            <EmptyHeader>
              <EmptyTitle>조건에 맞는 기록이 없습니다</EmptyTitle>
              <EmptyDescription>
                검색어나 기간 필터를 넓혀 보세요.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="overflow-x-auto border-y">
            <Table className="text-sm">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  {visible.map((column) => (
                    <TableHead
                      key={column}
                      onClick={() => toggleSort(column)}
                      className={cn(
                        "cursor-pointer whitespace-nowrap select-none",
                        NUMERIC_COLUMNS.has(column) && "text-right",
                        sort?.column === column && "text-foreground"
                      )}
                    >
                      <span className="inline-flex items-center gap-1">
                        {labelFor(column)}
                        {sort?.column === column ? (
                          <HugeiconsIcon
                            icon={sort.desc ? ArrowDown01Icon : ArrowUp01Icon}
                            className="size-3.5"
                          />
                        ) : null}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {pageRows.map((row, i) => (
                  <TableRow
                    key={`${row.timestamp ?? ""}-${row.biz_no ?? ""}-${i}`}
                    onClick={() => onRowSelect(row)}
                    className="cursor-pointer"
                  >
                    {visible.map((column) => (
                      <TableCell
                        key={column}
                        title={String(row[column] ?? "")}
                        className={cn(
                          "whitespace-nowrap",
                          NUMERIC_COLUMNS.has(column) &&
                            "text-right tabular-nums",
                          WIDE_COLUMNS.has(column) && "max-w-60 truncate"
                        )}
                      >
                        {renderCell(column, row[column])}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      {sorted.length > PAGE_SIZE ? (
        <CardFooter className="justify-between">
          <p className="text-xs text-muted-foreground">
            {page * PAGE_SIZE + 1}–
            {Math.min((page + 1) * PAGE_SIZE, sorted.length)} / {sorted.length}
            건
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
            >
              <HugeiconsIcon icon={ArrowLeft01Icon} data-icon="inline-start" />
              이전
            </Button>
            <span className="text-xs text-muted-foreground tabular-nums">
              {page + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= pageCount - 1}
              onClick={() => setPage((p) => p + 1)}
            >
              다음
              <HugeiconsIcon icon={ArrowRight01Icon} data-icon="inline-end" />
            </Button>
          </div>
        </CardFooter>
      ) : null}
    </Card>
  )
}
