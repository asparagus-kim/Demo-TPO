import { type ComponentProps } from "react"

import { cn } from "@/lib/utils"
import { Label } from "@/components/ui/label"

/** Reference-style form field: bold label, optional muted helper, bordered input. */

export function FieldInput({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      {...props}
      className={cn(
        "h-12 w-full rounded-lg border border-input bg-transparent px-4 text-base text-foreground",
        "placeholder:text-muted-foreground",
        "transition-colors outline-none focus:border-foreground",
        "aria-invalid:border-destructive",
        className
      )}
    />
  )
}

export function Field({
  label,
  helper,
  htmlFor,
  children,
  className,
}: {
  label?: string
  helper?: string
  /** id of the input inside — associates the label for a11y */
  htmlFor?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {label && (
        <Label htmlFor={htmlFor} className="text-sm font-bold">
          {label}
        </Label>
      )}
      {helper && (
        <p className="-mt-1 text-sm text-muted-foreground">{helper}</p>
      )}
      {children}
    </div>
  )
}

/** "or" divider from the sign-up screen: hairline — text — hairline. */
export function OrDivider({ text = "또는" }: { text?: string }) {
  return (
    <div className="flex items-center gap-4">
      <span className="h-px flex-1 bg-border" />
      <span className="text-sm text-muted-foreground">{text}</span>
      <span className="h-px flex-1 bg-border" />
    </div>
  )
}
