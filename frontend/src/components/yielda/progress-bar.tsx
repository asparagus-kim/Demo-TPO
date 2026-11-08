import { Orbit } from "ldrs/react"
import "ldrs/react/Orbit.css"

import { cn } from "@/lib/utils"

/** Bare orbiting two-dot loader. Colour follows `currentColor`, so callers
 *  tint it with a text-* class; carries no ARIA of its own (wrap it in a
 *  labelled container when it is the only progress signal on screen). */
export function OrbitLoader({
  size = 40,
  className,
}: {
  /** loader diameter in px */
  size?: number
  className?: string
}) {
  return (
    <span
      className={cn(
        "yielda-orbit inline-flex items-center justify-center",
        className
      )}
    >
      <Orbit size={size} speed={1.5} color="currentColor" />
    </span>
  )
}

/** Step dots — discrete step indicators with labels.
 *  Active step gets the accent fill; completed steps get a check; future = muted ring. */
export function StepIndicator({
  current,
  total,
  className,
}: {
  /** 0-indexed current step */
  current: number
  total: number
  className?: string
}) {
  return (
    <div className={cn("flex items-center gap-2", className)}>
      {Array.from({ length: total }, (_, i) => {
        const done = i < current
        const active = i === current
        return (
          <div key={i} className="flex items-center gap-2">
            <span
              className={cn(
                "flex size-2.5 rounded-full transition-all duration-300",
                done && "bg-primary",
                active && "scale-125 bg-primary",
                !done && !active && "bg-border"
              )}
            />
            {i < total - 1 && (
              <span
                className={cn(
                  "h-px w-6 transition-colors duration-300",
                  done ? "bg-primary" : "bg-border"
                )}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
