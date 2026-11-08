/** Resolve old saved search redirects as well as fresh API evidence links. */
export function normalizeReviewUrl(link?: string | null): string | null {
  link = link?.trim()
  for (let depth = 0; depth < 4; depth++) {
    if (!link) return null
    if (link.startsWith("//")) link = `https:${link}`
    try {
      const url: URL = new URL(link)
      if (url.protocol !== "https:" && url.protocol !== "http:") return null
      if (
        [
          "duckduckgo.com",
          "www.duckduckgo.com",
          "html.duckduckgo.com",
        ].includes(url.hostname) &&
        url.pathname.replace(/\/$/, "") === "/l"
      ) {
        // Old search wrappers contain HTML separators. Direct API destinations
        // are already normalized and must remain unchanged, including literal &amp;.
        const wrapper: URL = new URL(link.replace(/&(?:amp|#0*38|#x0*26);/gi, "&"))
        link = wrapper.searchParams.get("uddg")
        continue
      }
      return link
    } catch {
      return null
    }
  }
  return null
}
