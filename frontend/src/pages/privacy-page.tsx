import { useEffect } from "react"

import { Button } from "@/components/ui/button"
import { BrandWordmark } from "@/components/yielda/brand"
import {
  PRIVACY_BODY_HTML,
  PRIVACY_META,
  PRIVACY_TOC,
} from "@/lib/privacy-content"

/** Privacy policy (/privacy) — public, no analysis session required.
 *
 *  The body is the generated HTML in `privacy-content.ts`, injected as-is so the
 *  page can never drift from the official policy text (edit the source, then
 *  regenerate — never hand-edit the HTML). Tag styles live in `.privacy-doc`
 *  in index.css. */
export function PrivacyPage() {
  useEffect(() => {
    const prev = document.title
    document.title = "개인정보 처리방침 — Yielda"
    return () => {
      document.title = prev
    }
  }, [])

  return (
    <div className="min-h-svh w-full bg-background px-4 pb-16 text-foreground">
      <div className="mx-auto w-full max-w-3xl">
        <header className="flex items-center justify-between gap-4 border-b border-border py-6">
          <BrandWordmark className="cursor-pointer text-2xl" />
          <Button asChild size="sm" className="rounded-full">
            <a href={PRIVACY_META.pdf} download>
              PDF 내려받기
            </a>
          </Button>
        </header>

        <main>
          <h1 className="mt-8 text-3xl leading-tight font-black tracking-tight break-keep sm:text-4xl">
            「일다」 개인정보 처리방침
          </h1>
          <p className="mt-2 mb-6 text-sm text-muted-foreground">
            버전 {PRIVACY_META.version} · 시행일 {PRIVACY_META.effective}
          </p>

          <nav aria-label="목차" className="rounded-xl bg-card p-5">
            <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground">
              목차
            </p>
            <ol className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              {PRIVACY_TOC.map(([id, title]) => (
                <li key={id}>
                  <a
                    href={`#${id}`}
                    className="text-foreground/90 transition-colors hover:text-accent-text hover:underline"
                  >
                    {title}
                  </a>
                </li>
              ))}
            </ol>
          </nav>

          <article
            className="privacy-doc mt-6"
            dangerouslySetInnerHTML={{ __html: PRIVACY_BODY_HTML }}
          />
        </main>

        <footer className="mt-12 border-t border-border pt-5 text-xs leading-relaxed text-muted-foreground">
          <p>{PRIVACY_META.company}</p>
          {PRIVACY_META.email && <p>문의: {PRIVACY_META.email}</p>}
        </footer>
      </div>
    </div>
  )
}
