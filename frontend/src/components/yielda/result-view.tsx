import { useLayoutEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Check, ChevronDown, ExternalLink } from "lucide-react"

import type { AnalyseResponse } from "@/lib/api"
import { buildEvidenceLines } from "@/lib/evidence-lines"
import { formatBno, scoreWord, summarizeHours } from "@/lib/format"
import { normalizeReviewUrl } from "@/lib/review-links"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ResultStoreHero } from "@/components/yielda/result-hero"
import { StoreMap } from "@/components/stream/store-map"

/** Post-analysis result — Spotify-style panel (gradient hero + track table +
 *  매장 분석 rail) followed by the evidence cards.
 *  `onRestart` wires the hero's "다시 분석하기" pill back to the flow's entry
 *  screen; pages that have no flow to reset simply omit it. */
export function ResultView({
  analysis,
  onRestart,
}: {
  analysis: AnalyseResponse
  onRestart?: () => void
}) {
  const navigate = useNavigate()
  const bi = analysis.business_info
  const ta = analysis.trade_area
  const gp = analysis.google_places
  const tpo = analysis.tpo_profile
  const prov = analysis.evidence_provenance
  const val = analysis.entity_validation
  const amb = analysis.ambience
  const music = analysis.music
  const dbg = analysis.debug as Record<
    string,
    string | number | boolean | undefined
  >

  const tracks = useMemo(() => music.tracks ?? [], [music.tracks])
  const region = (bi.address || "").split(/\s+/).slice(0, 2).join(" ")
  // 드로어·사이드바와 같은 우선순위 — Kakao 좌표가 canonical, 없으면 Google 좌표
  const place = analysis.resolved_place
  const mapLocation = place?.location ?? gp.location ?? null

  // Store hero (top) = identity + 양대 CTA (재분석 / 플레이리스트 재생).
  const storeMeta = [bi.business_type, ta.label, region]
    .filter(Boolean)
    .join(" · ")

  const goStream = (index = 0, autoplay = false) =>
    navigate("/stream", { state: { index, autoplay } })

  // 확인 절차 — real pipeline outcomes (demo.html render() 대응)
  const checkItems = [
    `국세청 상태 확인 (${analysis.nts_status || "-"})`,
    `상호명 조회 (${dbg.identity_source ?? "-"})`,
    `업종/주소/좌표 확인 (Kakao · 후보 ${dbg.kakao_candidates ?? "-"}건)`,
    dbg.google_available
      ? `리뷰 ${prov.google_review_count || 0}건 · 영업시간 수집 (Google)`
      : "리뷰·영업시간 — 웹 검색으로 대체",
    val.is_consistent
      ? `동일 업체 정합성 OK (점수 ${(val.score ?? 0).toFixed(2)})`
      : "동일 업체 불일치 — Google 데이터 제외",
    `상권/날씨 분석 (${ta.label || "-"})`,
    "TPO 프로파일 생성 완료",
    `음원 매칭 (${tracks.length}곡)`,
  ]

  const srcName: Record<string, string> = {
    google_reviews: "Google 리뷰",
    web_search: "웹 검색 텍스트",
    mixed: "Google 리뷰 + 웹 검색",
    none: "텍스트 근거 없음",
  }
  // 고정 10줄 템플릿: 리뷰 언급 빈도 + 상권 분석 수치 (PM 스펙).
  // 주변 분포 데이터가 없는 응답(엑셀 폴백·구버전 캐시)은 null → 기존 목록 폴백.
  const evidenceLines = useMemo(() => buildEvidenceLines(analysis), [analysis])
  const legacyEvidence = [
    ...(val.reasons || []).slice(0, 2),
    ...(prov.notes || []).slice(0, 2),
    "날씨는 분위기 점수에 반영되며, 곡 선택 기준으로는 사용하지 않습니다.",
  ]

  const reviewCards = useMemo(() => {
    const list: {
      id: string
      text: string
      cite: string
      url?: string | null
      sourceName: string
      sourceBadge: "naver" | "kakao" | "google" | "web"
    }[] = []

    // Blogs first: Korean store owners trust Naver blog posts over Google reviews.
    for (const [idx, w] of (analysis.web_evidence || []).entries()) {
      const text = (w.text || "").trim()
      if (text.length < 10) continue
      const url = normalizeReviewUrl(w.url)
      const hostname = url ? new URL(url).hostname : ""
      const isNaver =
        w.source === "naver_blog" ||
        hostname === "blog.naver.com" ||
        hostname === "m.blog.naver.com"
      const isKakao =
        w.source === "kakao_blog" ||
        ["tistory.com", "daum.net"].some(
          (domain) => hostname === domain || hostname.endsWith(`.${domain}`)
        )
      const sourceBadge = isNaver ? "naver" : isKakao ? "kakao" : "web"
      const sourceName = isNaver
        ? "네이버 블로그"
        : isKakao
          ? "다음·티스토리"
          : "웹 리뷰"
      list.push({
        id: `web-${idx}`,
        text,
        cite: w.title || sourceName,
        url,
        sourceName,
        sourceBadge,
      })
    }

    for (const [idx, r] of (gp.reviews || []).entries()) {
      const text = (r.text || "").trim()
      if (text.length < 10) continue
      list.push({
        id: `google-${idx}`,
        text,
        cite:
          [r.author, r.rating ? `★${r.rating}` : "", r.relative_time]
            .filter(Boolean)
            .join(" · ") || "Google 리뷰",
        url: null,
        sourceName: "Google 지도",
        sourceBadge: "google",
      })
    }
    return list
  }, [gp.reviews, analysis.web_evidence])

  const ratingText = gp.rating
    ? `★ ${gp.rating}${gp.review_count ? ` · 리뷰 ${gp.review_count}건` : ""}`
    : ""
  const facts: [string, string, string?][] = [
    ["업종", bi.business_type || "-"],
    ["주소", bi.address || "-"],
    ["상권", ta.label || "-", String(dbg.trade_area_reason ?? "")],
    ["영업시간", summarizeHours(gp.business_hours)],
    ["현재 날씨", analysis.weather.summary || "-"],
    ...(ratingText
      ? [["평점", ratingText, "Google 지도 기준"] as [string, string, string]]
      : []),
    [
      "사업자번호",
      formatBno(analysis.business_number || ""),
      val.is_consistent
        ? `동일 업체 확인 (정합성 ${(val.score ?? 0).toFixed(2)})`
        : "",
    ],
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* ── 매장 히어로: 상호명이 페이지 최상단에서 크게 보이도록 ── */}
      <section className="overflow-hidden rounded-lg bg-panel">
        <ResultStoreHero
          title={bi.company_name || "매장"}
          badge={analysis.nts_status || ""}
          badgeStatus={
            analysis.nts_status === "계속사업자"
              ? "ok"
              : analysis.nts_status === "조회실패"
                ? "warn"
                : "bad"
          }
          meta={storeMeta}
          onRestart={onRestart}
          canPlay={tracks.length > 0}
          onStream={() => goStream(0)}
        />
      </section>

      {/* ── 근거 2단: 좌 사실 / 우 해석 — 두 컬럼은 항상 같은 높이(stretch),
           우측은 지도가 남는 세로 공간을 흡수한다 ── */}
      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <CardContent className="flex flex-col gap-1">
            <h3 className="text-sm font-bold tracking-widest text-muted-foreground uppercase">
              내 매장 정보
            </h3>
            <dl className="mt-2">
              {facts.map(([k, v, sub]) => (
                <div
                  key={k}
                  className="flex items-baseline gap-3 border-b border-border py-3 text-base last:border-0"
                >
                  <dt className="w-20 shrink-0 text-sm text-muted-foreground">
                    {k}
                  </dt>
                  <dd className="min-w-0 flex-1 font-semibold wrap-break-word">
                    {v}
                    {sub ? (
                      <span className="mt-0.5 block text-sm font-normal text-muted-foreground">
                        {sub}
                      </span>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>

            {dbg.trade_area_evidence ? (
              <div className="mt-3 rounded-xl border border-border bg-secondary/40 p-4">
                <b className="block text-base">상권 판정 근거</b>
                <p className="mt-1 text-base leading-relaxed text-muted-foreground">
                  {String(dbg.trade_area_evidence)}
                </p>
              </div>
            ) : null}

            <Fold
              title={`분석 근거 · ${srcName[prov.text_source] || "—"}`}
              defaultOpen
            >
              {evidenceLines ? (
                <ol className="list-decimal space-y-2 pt-2 pl-5 text-base text-muted-foreground marker:text-sm marker:text-muted-foreground/70">
                  {evidenceLines.map((t) => (
                    <li key={t} className="pl-0.5 leading-relaxed">
                      {t}
                    </li>
                  ))}
                </ol>
              ) : (
                <ul className="list-disc space-y-2 pt-2 pl-4 text-base text-muted-foreground">
                  {legacyEvidence.map((t) => (
                    <li key={t}>{t}</li>
                  ))}
                </ul>
              )}
            </Fold>

            <Fold title={`${checkItems.length}개 항목 확인 완료`}>
              <ul className="flex flex-col gap-2 pt-2">
                {checkItems.map((t) => (
                  <li key={t} className="flex items-start gap-2.5 text-base">
                    <span className="mt-0.5 flex size-4.5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
                      <Check className="size-3" strokeWidth={3} />
                    </span>
                    {t}
                  </li>
                ))}
              </ul>
            </Fold>
          </CardContent>
        </Card>

        <div className="flex min-w-0 flex-col gap-4">
          <Card>
            <CardContent className="flex flex-col gap-4">
              <h3 className="text-xl font-bold">왜 이 음악인가</h3>

              <div className="overflow-hidden rounded-xl border border-border">
                {(
                  [
                    ["T", "TIME", tpo.time_label || "영업시간 정보 없음"],
                    ["P", "PLACE", tpo.place_label || "-"],
                    [
                      "O",
                      "OCCASION",
                      [
                        tpo.occasion_label,
                        (tpo.peak_slots || []).slice(0, 2).join(" / "),
                      ]
                        .filter(Boolean)
                        .join(" · ") || "-",
                    ],
                  ] as const
                ).map(([k, sub, v]) => (
                  <div
                    key={k}
                    className="flex border-b border-border last:border-0"
                  >
                    <div className="flex w-16 shrink-0 flex-col items-center justify-center bg-secondary py-3">
                      <b className="text-xl leading-none">{k}</b>
                      <span className="text-[10px] tracking-widest text-muted-foreground">
                        {sub}
                      </span>
                    </div>
                    <div className="flex min-w-0 flex-1 items-center px-4 py-3 text-base">
                      {v}
                    </div>
                  </div>
                ))}
              </div>

              {/* AI 분위기 벡터 — E/T/M bars with word + numeric badge */}
              <div className="flex flex-col gap-3">
                <h4 className="text-base font-bold">AI 분위기 벡터</h4>
                {(
                  [
                    ["에너지", amb.energy],
                    ["템포", amb.tempo],
                    ["무드", amb.mood],
                  ] as const
                ).map(([label, v]) => {
                  const value = Math.max(0, Math.min(100, v || 0))
                  return (
                    <div
                      key={label}
                      className="flex items-center gap-3 text-base"
                    >
                      <b className="w-14 shrink-0 font-semibold">{label}</b>
                      <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-secondary">
                        <i
                          className="block h-full rounded-full bg-primary"
                          style={{ width: `${value}%` }}
                        />
                      </span>
                      <span className="w-16 shrink-0 text-right text-sm text-muted-foreground">
                        {scoreWord(value)}
                      </span>
                      <span className="w-11 shrink-0 rounded-lg bg-foreground py-0.5 text-center text-sm font-bold text-background">
                        {value}
                      </span>
                    </div>
                  )
                })}
                {amb.explanations?.length > 0 && (
                  <ul className="flex flex-col gap-1.5">
                    {amb.explanations.slice(0, 3).map((t) => (
                      <li
                        key={t}
                        className="flex items-start gap-2.5 text-base"
                      >
                        <span className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />
                        <span className="leading-relaxed">{t}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              {reviewCards.length ? (
                <div className="flex flex-col gap-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold tracking-wider text-muted-foreground uppercase">
                      방문 리뷰 & 블로그 분석
                    </span>
                    <span className="text-xs text-muted-foreground">
                      총 {reviewCards.length}건
                    </span>
                  </div>

                  <div className="flex flex-col gap-2">
                    {reviewCards.slice(0, 2).map((item) => (
                      <BlogReviewCard key={item.id} item={item} />
                    ))}
                  </div>

                  {reviewCards.length > 2 && (
                    <Collapsible className="group/reviews">
                      <CollapsibleContent className="flex flex-col gap-2 pt-1">
                        {reviewCards.slice(2).map((item) => (
                          <BlogReviewCard key={item.id} item={item} />
                        ))}
                      </CollapsibleContent>
                      <CollapsibleTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="mt-0.5 h-8 w-full justify-between px-2 text-xs font-medium text-muted-foreground hover:bg-secondary hover:text-foreground"
                        >
                          <span className="group-data-[state=open]/reviews:hidden">
                            외 {reviewCards.length - 2}건의 리뷰 더 보기
                          </span>
                          <span className="hidden group-data-[state=open]/reviews:inline">
                            리뷰 접기
                          </span>
                          <ChevronDown className="size-3.5 transition-transform duration-200 group-data-[state=open]/reviews:rotate-180" />
                        </Button>
                      </CollapsibleTrigger>
                    </Collapsible>
                  )}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  리뷰 텍스트를 찾지 못해 상권·업종·영업시간·날씨만으로
                  분석했습니다.
                </div>
              )}
            </CardContent>
          </Card>

          {/* 좌측 카드가 길어 생기는 우측 하단 여백을 매장 위치 지도로 채운다 */}
          <StoreMap
            name={place?.place_name || bi.company_name || "매장"}
            address={place?.address || bi.address}
            placeUrl={place?.place_url || undefined}
            location={mapLocation}
            className="min-h-0 flex-1"
            mapClassName="min-h-56 flex-1"
          />
        </div>
      </div>
    </div>
  )
}

function BlogReviewCard({
  item,
}: {
  item: {
    id: string
    text: string
    cite: string
    url?: string | null
    sourceName: string
    sourceBadge: "naver" | "kakao" | "google" | "web"
  }
}) {
  const isClickable = Boolean(item.url)
  const Tag = isClickable ? "a" : "div"
  const textRef = useRef<HTMLParagraphElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [clamped, setClamped] = useState(false)

  // Google reviews have no source link, so a clamped one expands in place.
  // Measure the 2-line clamp; resizing the column can change it.
  useLayoutEffect(() => {
    const el = textRef.current
    if (!el || expanded) return
    const measure = () => setClamped(el.scrollHeight > el.clientHeight + 1)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [expanded, item.text])

  const expandable = !isClickable && (clamped || expanded)
  const toggle = () => setExpanded((open) => !open)

  const badgeConfig = {
    naver: {
      label: "네이버 블로그",
      bg: "bg-[#03C75A]/10 text-[#03C75A] border-[#03C75A]/30 dark:bg-[#03C75A]/20 dark:text-[#20db72]",
    },
    kakao: {
      label: "다음·티스토리",
      bg: "bg-[#FEE500]/20 text-[#3C1E1E] dark:text-[#FEE500] border-[#FEE500]/40",
    },
    google: {
      label: "Google 리뷰",
      bg: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/30",
    },
    web: {
      label: "웹 리뷰",
      bg: "bg-secondary text-muted-foreground border-border",
    },
  }[item.sourceBadge]

  return (
    <Tag
      {...(isClickable
        ? {
            href: item.url!,
            target: "_blank",
            rel: "noopener noreferrer",
          }
        : {})}
      {...(expandable
        ? {
            role: "button",
            tabIndex: 0,
            "aria-expanded": expanded,
            onClick: toggle,
            onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault()
                toggle()
              }
            },
          }
        : {})}
      className={cn(
        "group relative flex flex-col gap-1.5 rounded-xl border border-border bg-secondary/30 p-3 text-left transition-all",
        (isClickable || expandable) &&
          "cursor-pointer hover:border-primary/50 hover:bg-secondary/60 hover:shadow-sm",
        expandable &&
          "outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={cn(
              "inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-[11px] leading-none font-bold",
              badgeConfig.bg
            )}
          >
            {badgeConfig.label}
          </span>
          <span className="truncate text-xs font-medium text-muted-foreground">
            {item.cite}
          </span>
        </div>
        {isClickable && (
          <span className="flex shrink-0 items-center gap-0.5 text-[11px] font-medium text-muted-foreground transition-colors group-hover:text-primary">
            원문 보기
            <ExternalLink className="size-3 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
          </span>
        )}
        {expandable && (
          <span className="flex shrink-0 items-center gap-0.5 text-[11px] font-medium text-muted-foreground transition-colors group-hover:text-primary">
            {expanded ? "접기" : "전체 보기"}
            <ChevronDown
              className={cn(
                "size-3 transition-transform",
                expanded && "rotate-180"
              )}
            />
          </span>
        )}
      </div>

      <p
        ref={textRef}
        className={cn(
          "text-sm leading-relaxed text-foreground/90",
          !expanded && "line-clamp-2"
        )}
      >
        “{item.text}”
      </p>
    </Tag>
  )
}

function Fold({
  title,
  children,
  defaultOpen = false,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      className="mt-3 border-t border-border pt-3"
    >
      <CollapsibleTrigger className="group flex min-h-11 w-full items-center justify-between gap-2 rounded-lg px-2 text-base font-bold text-foreground transition-colors hover:bg-secondary hover:text-primary">
        {title}
        <span className="flex size-6 items-center justify-center rounded-full bg-secondary transition-transform group-data-[state=open]:rotate-180">
          <ChevronDown className="size-3.5" />
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  )
}
