import { cn } from "@/lib/utils"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

// `strokeWidth` 는 제외한다: SVG 프롭 타입은 `string | number` 인데
// HugeiconsIcon 은 `number` 만 받아 그대로 스프레드하면 `tsc -b` 가 막는다.
// (레지스트리에서 받은 원본의 타입 오류 — 재설치 시 다시 확인할 것.)
type SpinnerProps = Omit<React.ComponentProps<"svg">, "strokeWidth">

function Spinner({ className, ...props }: SpinnerProps) {
  return (
    <HugeiconsIcon
      icon={Loading03Icon}
      strokeWidth={2}
      data-slot="spinner"
      role="status"
      aria-label="Loading"
      className={cn("size-4 animate-spin", className)}
      {...props}
    />
  )
}

export { Spinner }
