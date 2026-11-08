import React from "react"

import { cn } from "@/lib/utils"

/** Animated dot-wave chevron — reads as a small equalizer/play glyph. */
const DoubleChevron = ({ index }: { index: number }) => {
  const base = index * 0.12
  const dots = [
    { cx: 2, cy: 2, d: 0 },
    { cx: 5, cy: 5, d: 0.05 },
    { cx: 8, cy: 8, d: 0.1 },
    { cx: 5, cy: 11, d: 0.15 },
    { cx: 2, cy: 14, d: 0.2 },
    { cx: 6, cy: 2, d: 0.05 },
    { cx: 9, cy: 5, d: 0.1 },
    { cx: 12, cy: 8, d: 0.15 },
    { cx: 9, cy: 11, d: 0.2 },
    { cx: 6, cy: 14, d: 0.25 },
  ]

  return (
    <svg
      width="14"
      height="16"
      viewBox="0 0 14 16"
      aria-hidden="true"
      focusable="false"
      className="shrink-0 overflow-visible"
    >
      <g className="fill-primary-foreground">
        {dots.map((p, i) => (
          <circle
            key={i}
            cx={p.cx}
            cy={p.cy}
            r="1"
            className="bd-dot"
            style={{ animationDelay: `${base + p.d}s` }}
          />
        ))}
      </g>
    </svg>
  )
}

export interface AntiMetalButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  label?: React.ReactNode
}

/** Accent CTA (adapted vendor "anti-metal" button) — white pill shell with a
 *  primary-green panel that sweeps across on hover, dot-wave animating like an
 *  equalizer. Keyframes (`bd-dot-wave`) live in src/index.css.
 *  Colors are theme tokens only; sized to the 48px pill button language. */
export const AntiMetalButton = React.forwardRef<
  HTMLButtonElement,
  AntiMetalButtonProps
>(({ className, children, label, ...props }, ref) => {
  return (
    <button
      ref={ref}
      className={cn(
        "group/btn relative inline-flex h-12 w-52 overflow-hidden rounded-full",
        "bg-foreground shadow-lg inset-shadow-2xs transition-transform",
        "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background focus-visible:outline-none",
        "active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50",
        className
      )}
      {...props}
    >
      <span className="absolute inset-y-0 right-5 flex items-center text-sm font-bold tracking-tight text-background">
        {label ?? children}
      </span>

      {/* accent panel — sweeps to full width on hover */}
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-1 bottom-1 left-1 z-10 flex w-10 items-center justify-start gap-2.5 overflow-hidden rounded-full pr-2.5 pl-3.5",
          "bg-linear-to-b from-primary to-primary-deep inset-shadow-2xs",
          "transition-[width,gap] duration-200 ease-[cubic-bezier(0.65,0,0.35,1)] group-hover/btn:w-[calc(100%-0.5rem)]"
        )}
      >
        <DoubleChevron index={0} />
        <DoubleChevron index={1} />
        <DoubleChevron index={2} />
        <DoubleChevron index={3} />
        <DoubleChevron index={4} />
      </span>
    </button>
  )
})

AntiMetalButton.displayName = "AntiMetalButton"
