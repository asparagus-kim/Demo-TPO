import { M_FINANCIAL_AD as AD } from "@/lib/care-data"

/** 2-6 엠금융 배너 — 신규, **표시만**.
 *
 *  눌러도 아무 동작이 없다: 화면 이동 · 팝업 · 기록 전부 없음(기획 명시).
 *  그래서 button 이지만 disabled 가 아니라 onClick 이 없는 상태로 둔다 —
 *  시연에서 눌렀을 때 "죽은 버튼"처럼 보이지 않게 누름 효과만 남긴다.
 *
 *  색은 데모 토큰이 아니라 광고주(엠금융) 색이라 그대로 쓴다. 문구와 색은
 *  모두 `care-data.ts` 의 M_FINANCIAL_AD 한 곳에 있다 — 엠금융 검토 뒤
 *  바뀔 예정이라 기획이 모아 두라고 요청했다. */
export function MFinancialBanner() {
  return (
    <section
      className="relative isolate overflow-hidden rounded-xl"
      aria-label={`${AD.brand} ${AD.disclosure}`}
    >
      <img
        src={AD.image}
        alt=""
        aria-hidden="true"
        className="absolute inset-0 size-full object-cover"
      />
      <div
        className="absolute inset-0"
        style={{
          background: `linear-gradient(180deg, ${AD.gradientFrom} 30%, ${AD.gradientTo} 100%)`,
        }}
      />

      <div className="relative flex flex-col gap-3 p-5">
        <p className="flex flex-wrap items-center gap-2">
          <span
            className="rounded-full bg-white px-2.5 py-0.5 text-xs font-bold"
            style={{ color: AD.chipText }}
          >
            {AD.brand}
          </span>
          <span className="text-xs text-white/70">{AD.disclosure}</span>
        </p>

        <p className="text-[17px] leading-snug font-bold break-keep text-white">
          {AD.titleLines.map((line) => (
            <span key={line} className="block">
              {line}
            </span>
          ))}
        </p>

        <p className="text-sm break-keep text-white/80">{AD.subtitle}</p>

        {/* 오른쪽 열이 좁으므로 버튼은 글자 아래 한 줄로 둔다(기획 명시). */}
        <button
          type="button"
          className="min-h-10 w-full rounded-full bg-white px-4 py-2 text-sm font-bold transition-transform active:scale-[.98] motion-reduce:transition-none"
          style={{ color: AD.chipText }}
        >
          {AD.cta}
        </button>
      </div>
    </section>
  )
}
