import { HugeiconsIcon } from "@hugeicons/react"
import {
  Download01Icon,
  ReloadIcon,
  Search01Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { SidebarTrigger } from "@/components/ui/sidebar"
import { Spinner } from "@/components/ui/spinner"
import { RANGES, SECTION_TITLES, type Section } from "./dashboard-nav"

export function DashboardHeader({
  section,
  query,
  onQueryChange,
  range,
  onRangeChange,
  onRefresh,
  onExport,
  loading,
  exportDisabled,
}: {
  section: Section
  query: string
  onQueryChange: (next: string) => void
  range: string
  onRangeChange: (next: string) => void
  onRefresh: () => void
  onExport: () => void
  loading: boolean
  exportDisabled: boolean
}) {
  const { title, description } = SECTION_TITLES[section]

  return (
    <header className="sticky top-0 z-10 flex flex-col gap-3 border-b bg-background/95 px-4 py-3 backdrop-blur md:px-6">
      <div className="flex items-center gap-2">
        <SidebarTrigger />
        <Separator orientation="vertical" className="mr-1 h-5" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <h1 className="truncate text-base leading-none font-bold">{title}</h1>
          <p className="truncate text-xs text-muted-foreground">
            {description}
          </p>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Select value={range} onValueChange={onRangeChange}>
            <SelectTrigger size="sm" className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {RANGES.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={loading}
          >
            {loading ? (
              <Spinner data-icon="inline-start" />
            ) : (
              <HugeiconsIcon icon={ReloadIcon} data-icon="inline-start" />
            )}
            새로고침
          </Button>

          <Button size="sm" onClick={onExport} disabled={exportDisabled}>
            <HugeiconsIcon icon={Download01Icon} data-icon="inline-start" />
            CSV
          </Button>
        </div>
      </div>

      <div className="relative">
        <HugeiconsIcon
          icon={Search01Icon}
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="사업자번호 · 상호 · 업종 · 주소 · 상권으로 검색"
          className="pl-9"
        />
      </div>
    </header>
  )
}
