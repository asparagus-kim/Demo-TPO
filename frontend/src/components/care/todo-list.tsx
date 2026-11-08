import { HugeiconsIcon } from "@hugeicons/react"
import { Tick02Icon } from "@hugeicons/core-free-icons"

import { CHECK_FILL_MS, TODOS, TODO_VISIBLE } from "@/lib/care-data"
import { ALL_TODOS_DONE, visibleTodos, type CareState } from "@/lib/use-care-state"
import { cn } from "@/lib/utils"

/** 2-3 오늘 챙길 것 — 5개 중 3개씩.
 *
 *  누르면 체크 원이 채워지고(200ms), 0.7초 뒤 그 행이 다음 미체크 항목으로
 *  바뀐다. 0.7초 안에 같은 행을 다시 누르면 체크가 풀린다 — 그래서 체크된
 *  항목도 `pending` 인 동안에는 목록에 남는다(`visibleTodos`). */
export function TodoList({ state }: { state: CareState }) {
  const rows = visibleTodos(state, TODO_VISIBLE)
  const done = ALL_TODOS_DONE(state)

  return (
    <section className="flex flex-col gap-3" aria-label="오늘 챙길 것">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm text-muted-foreground">오늘 날씨 · 시간 · 상권 기준</p>
        <p className="text-sm font-bold text-accent-text">
          {state.checked.length}/{TODOS.length} 완료
        </p>
      </div>

      {done ? (
        <div className="rounded-xl border border-border bg-card px-5 py-8 text-center">
          <p className="text-lg font-bold">오늘도 일 다 하셨어요!</p>
          <p className="mt-1 text-sm text-muted-foreground">내일 새 챙길 것이 올라와요</p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {rows.map((todo) => {
            const isChecked = state.checked.includes(todo.id)
            return (
              <li key={todo.id}>
                <button
                  type="button"
                  aria-pressed={isChecked}
                  onClick={() => state.toggleTodo(todo.id)}
                  className="flex w-full min-h-10 items-start gap-3 rounded-xl border border-border bg-card px-4 py-3 text-left transition-[filter,transform] hover:brightness-110 active:scale-[.98] motion-reduce:transition-none"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors motion-reduce:transition-none",
                      isChecked
                        ? "border-primary bg-primary text-primary-foreground"
                        : "border-muted-foreground/50",
                    )}
                    style={{ transitionDuration: `${CHECK_FILL_MS}ms` }}
                  >
                    {isChecked && <HugeiconsIcon icon={Tick02Icon} size={14} strokeWidth={3} />}
                  </span>

                  <span className="min-w-0 flex-1">
                    <span className="block text-[17px] font-bold break-keep">{todo.title}</span>
                    <span className="mt-0.5 block text-sm break-keep">
                      <b className="font-bold text-accent-text">{todo.tag}</b>
                      <span className="text-muted-foreground"> · {todo.reason}</span>
                    </span>
                  </span>

                  <span className="shrink-0 text-sm font-bold text-accent-text">+10</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
