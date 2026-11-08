import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  BASE_CREDITS,
  CREDIT_PER_ANSWER,
  CREDIT_PER_CHECK,
  CREDIT_PER_NEWS,
  GRADES,
  NEWS,
  QUESTIONS,
  ROW_SWAP_MS,
  TODOS,
  type CareGrade,
} from "@/lib/care-data"

/** 챙김 화면의 모든 상태 — **메모리에만** 있다.
 *
 *  규칙 3(1)(2): API 호출 · DB · localStorage · sessionStorage · 쿠키 · 분석
 *  이벤트가 전부 금지다. 새로고침할 때와 화면을 **다시 열 때마다** 처음
 *  상태로 돌아간다. 그래서 이 훅은 저장소를 건드리지 않고, 오버레이가
 *  닫힐 때 언마운트되어 상태가 자연히 사라지도록 설계했다. */

export interface CareState {
  checked: readonly string[]
  answered: readonly string[]
  /** 건너뛴 문항 — 처리는 됐지만 크레딧은 없다. */
  skipped: readonly string[]
  read: readonly string[]
  /** 체크 직후 ROW_SWAP_MS 동안만 행에 남아 있는 id (되돌릴 수 있는 창). */
  pending: string | null
  totalCredits: number
  grade: CareGrade
  gradeIndex: number
  nextGrade: CareGrade | null
  /** 다음 등급까지 남은 크레딧. 다음 등급이 없으면 0. */
  remainingToNext: number
  toggleTodo: (id: string) => void
  answerQuestion: (id: string) => void
  skipQuestion: (id: string) => void
  markRead: (id: string) => void
}

/** 총 크레딧으로 현재 등급을 찾는다. 2-10 */
function gradeFor(total: number): number {
  let idx = 0
  for (let i = 0; i < GRADES.length; i += 1) {
    if (total >= GRADES[i].min) idx = i
  }
  return idx
}

export function useCareState(): CareState {
  const [checked, setChecked] = useState<string[]>([])
  const [answered, setAnswered] = useState<string[]>([])
  const [skipped, setSkipped] = useState<string[]>([])
  const [read, setRead] = useState<string[]>([])
  const [pending, setPending] = useState<string | null>(null)

  // 체크한 행이 다음 항목으로 바뀌기까지의 타이머. 언마운트 시 반드시 정리한다 —
  // 오버레이를 빨리 닫으면 사라진 컴포넌트에 setState 가 날아간다.
  const swapTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(
    () => () => {
      if (swapTimer.current) clearTimeout(swapTimer.current)
    },
    [],
  )

  const toggleTodo = useCallback((id: string) => {
    setChecked((prev) => {
      // ROW_SWAP_MS 안에 같은 행을 다시 누르면 체크가 풀린다. 크레딧도 함께
      // 줄어든다 — 총 크레딧이 체크 수에서 파생되므로(2-10) 자동으로 맞는다.
      if (prev.includes(id)) {
        if (swapTimer.current) clearTimeout(swapTimer.current)
        setPending(null)
        return prev.filter((x) => x !== id)
      }
      return [...prev, id]
    })

    setPending((cur) => {
      if (cur === id) return cur
      if (swapTimer.current) clearTimeout(swapTimer.current)
      swapTimer.current = setTimeout(() => setPending(null), ROW_SWAP_MS)
      return id
    })
  }, [])

  const answerQuestion = useCallback((id: string) => {
    setAnswered((prev) => (prev.includes(id) ? prev : [...prev, id]))
  }, [])

  const skipQuestion = useCallback((id: string) => {
    setSkipped((prev) => (prev.includes(id) ? prev : [...prev, id]))
  }, [])

  const markRead = useCallback((id: string) => {
    setRead((prev) => (prev.includes(id) ? prev : [...prev, id]))
  }, [])

  // 총 크레딧 = 1,180 + 10×체크 + 10×답(건너뛴 것 제외) + 2×읽은 소식. 2-10
  const totalCredits =
    BASE_CREDITS +
    CREDIT_PER_CHECK * checked.length +
    CREDIT_PER_ANSWER * answered.length +
    CREDIT_PER_NEWS * read.length

  const gradeIndex = gradeFor(totalCredits)
  const grade = GRADES[gradeIndex]
  const nextGrade = GRADES[gradeIndex + 1] ?? null

  return useMemo(
    () => ({
      checked,
      answered,
      skipped,
      read,
      pending,
      totalCredits,
      grade,
      gradeIndex,
      nextGrade,
      remainingToNext: nextGrade ? nextGrade.min - totalCredits : 0,
      toggleTodo,
      answerQuestion,
      skipQuestion,
      markRead,
    }),
    [
      checked,
      answered,
      skipped,
      read,
      pending,
      totalCredits,
      grade,
      gradeIndex,
      nextGrade,
      toggleTodo,
      answerQuestion,
      skipQuestion,
      markRead,
    ],
  )
}

/** 아직 체크하지 않은 항목 + 되돌림 창이 열려 있는 항목을 순서대로. 2-3 */
export function visibleTodos(state: CareState, count: number) {
  return TODOS.filter((t) => !state.checked.includes(t.id) || state.pending === t.id).slice(0, count)
}

/** 아직 처리(답변·건너뛰기)하지 않은 문항을 순서대로. 2-7 */
export function visibleQuestions(state: CareState, count: number) {
  return QUESTIONS.filter(
    (q) => !state.answered.includes(q.id) && !state.skipped.includes(q.id),
  ).slice(0, count)
}

export const ALL_TODOS_DONE = (s: CareState) => s.checked.length >= TODOS.length
export const ALL_QUESTIONS_DONE = (s: CareState) =>
  s.answered.length + s.skipped.length >= QUESTIONS.length
export const ALL_NEWS = NEWS
