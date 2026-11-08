import { AudioLines } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { cn } from "@/lib/utils"

/** Yielda brand mark — white disc + waveform, Spotify-logo placement. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex size-10 items-center justify-center rounded-full bg-foreground text-background",
        className
      )}
    >
      <AudioLines className="size-5" strokeWidth={2.5} />
    </span>
  )
}

/** Text-only wordmark — font size inherits from `className` (default 18px). */
export function BrandWordmark({ className }: { className?: string }) {
  const navigate = useNavigate()
  return (
    <span
      onClick={() => navigate("/", { state: { restart: true } })}
      className={cn("text-lg font-extrabold tracking-[0.06em]", className)}
    >
      {/* Yield<span className="text-primary">a</span> */}
      <span className="text-white">Yielda</span>
    </span>
  )
}
