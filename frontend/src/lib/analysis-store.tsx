/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import type { AnalyseResponse } from "@/lib/api"
import { prefetchInsuranceEstimate } from "@/lib/insurance-link"

/** Holds the last successful analysis so /stream can read it (survives refresh via sessionStorage). */

const STORAGE_KEY = "yielda:analysis"

interface AnalysisStore {
  analysis: AnalyseResponse | null
  setAnalysis: (a: AnalyseResponse | null) => void
}

const AnalysisContext = createContext<AnalysisStore | null>(null)

function readStored(): AnalyseResponse | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as AnalyseResponse) : null
  } catch {
    return null
  }
}

export function AnalysisProvider({ children }: { children: ReactNode }) {
  const [analysis, setAnalysisState] = useState<AnalyseResponse | null>(
    readStored
  )

  useEffect(() => {
    if (analysis) {
      prefetchInsuranceEstimate(analysis)
    }
  }, [analysis])

  const value = useMemo<AnalysisStore>(
    () => ({
      analysis,
      setAnalysis: (a) => {
        setAnalysisState(a)
        try {
          if (a) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(a))
          else sessionStorage.removeItem(STORAGE_KEY)
        } catch {
          // sessionStorage full/unavailable — in-memory state still works
        }
      },
    }),
    [analysis]
  )

  return (
    <AnalysisContext.Provider value={value}>
      {children}
    </AnalysisContext.Provider>
  )
}

export function useAnalysis(): AnalysisStore {
  const ctx = useContext(AnalysisContext)
  if (!ctx) throw new Error("useAnalysis must be used within AnalysisProvider")
  return ctx
}
