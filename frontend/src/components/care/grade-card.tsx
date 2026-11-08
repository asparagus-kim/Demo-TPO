import type { CareState } from "@/lib/use-care-state"

/** 2-5 등급 카드 — **표시만**.
 *
 *  기획이 명시적으로 "누를 수 없습니다. 화면 이동 없음, 마우스를 올려도 변화
 *  없음, 기본 커서"라고 못박았다. 그래서 button 이 아니라 div 이고 hover 효과도
 *  없다. 오른쪽 "›"는 장식이므로 aria-hidden 으로 보조기기에서 숨긴다 —
 *  읽히면 이동할 수 있는 것처럼 들린다. */
export function GradeCard({ state }: { state: CareState }) {
  const { grade, nextGrade, remainingToNext } = state

  return (
    <section className="flex items-center gap-4 rounded-xl bg-primary-deep p-5 text-white">
      <img
        src={grade.image}
        alt=""
        aria-hidden="true"
        className="size-16 shrink-0 object-contain"
      />
      <div className="min-w-0 flex-1">
        <p className="text-lg font-bold break-keep">{grade.name}</p>
        {nextGrade && (
          <p className="mt-0.5 text-sm break-keep text-white/75">
            {nextGrade.name}까지 {remainingToNext.toLocaleString("ko-KR")}
          </p>
        )}
      </div>
      <span aria-hidden="true" className="shrink-0 text-white/60">
        ›
      </span>
    </section>
  )
}
