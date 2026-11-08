import { useRef } from "react"
import { useNavigate } from "react-router-dom"
import { Search } from "lucide-react"

import type { AnalyseResponse } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import { StoreDrawer } from "@/components/stream/store-drawer"

/** Streaming-shell top nav — brand · search-icon button + search pill · store identity. */
export function TopNav({
  analysis,
  query,
  onQueryChange,
  onOpenCare,
}: {
  analysis: AnalyseResponse
  query: string
  onQueryChange: (q: string) => void
  onOpenCare?: () => void
}) {
  const navigate = useNavigate()
  const searchRef = useRef<HTMLInputElement>(null)

  return (
    <header className="flex h-16 shrink-0 items-center gap-2 px-4">
      {/* left: brand */}
      <button
        type="button"
        onClick={() => navigate("/", { state: { restart: true } })}
        aria-label="분석 결과로 돌아가기"
        className="shrink-0"
      >
        <BrandWordmark />
      </button>

      {/* center: search-icon button (was home) + icon-less search pill */}
      <div className="flex min-w-0 flex-1 items-center justify-center gap-2">
        <Button
          variant="ghost"
          size="icon-lg"
          className="hidden size-12 shrink-0 rounded-full bg-panel hover:bg-secondary sm:inline-flex"
          aria-label="곡 검색"
          onClick={() => searchRef.current?.focus()}
        >
          <Search className="size-5" />
        </Button>
        <label className="flex h-12 w-full max-w-md items-center rounded-full bg-panel px-4 transition-colors focus-within:ring-2 focus-within:ring-ring hover:bg-secondary">
          <input
            ref={searchRef}
            type="search"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="무엇을 재생할까요?"
            aria-label="플레이리스트에서 곡 검색"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
        </label>
      </div>

      {/* right: 매장 아바타 + 상호 pill → 매장 정보 드로어 */}
      <div className="flex shrink-0 items-center">
        <StoreDrawer analysis={analysis} onOpenCare={onOpenCare} />
      </div>
    </header>
  )
}
