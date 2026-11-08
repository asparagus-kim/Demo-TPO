/* insurance-estimate.js — ESTIMATE lookup for business numbers that are not in
 * insurance-leads.json: GET {API}/api/insurance/estimate matches the analysed
 * shop against nationwide LOCALDATA licences (address + name, never number).
 *
 * The key functions mirror app/utils/licence_keys.py (the page uses them to
 * flag an analysis address that differs from the licensed premises); the
 * lookup itself calls the TPO API, which matches server-side. */
;(function (root) {
  "use strict"


  // 시도 (province) forms -> shard label. Same table as build_insurance_shards.py SIDO.
  const SIDO = {
    서울특별시: "서울",
    서울: "서울",
    부산광역시: "부산",
    부산: "부산",
    대구광역시: "대구",
    대구: "대구",
    인천광역시: "인천",
    인천: "인천",
    대전광역시: "대전",
    대전: "대전",
    울산광역시: "울산",
    울산: "울산",
    세종특별자치시: "세종",
    세종: "세종",
    경기도: "경기",
    경기: "경기",
    강원특별자치도: "강원",
    강원도: "강원",
    강원: "강원",
    충청북도: "충북",
    충북: "충북",
    충청남도: "충남",
    충남: "충남",
    전북특별자치도: "전북",
    전라북도: "전북",
    전북: "전북",
    전남광주통합특별시: "전남광주",
    전라남도: "전남광주",
    전남: "전남광주",
    광주광역시: "전남광주",
    광주: "전남광주",
    // 내부 라벨 자체 (화면에 다시 들어온 주소) — 지역 비교가 조용히 실패하지 않게.
    전남광주: "전남광주",
    경상북도: "경북",
    경북: "경북",
    경상남도: "경남",
    경남: "경남",
    제주특별자치도: "제주",
    제주도: "제주",
    제주: "제주",
  }

  const nfkc = (s) => String(s == null ? "" : s).normalize("NFKC")

  /** [region, tail] — '서울 관악구' + '신림로67길 4, 1층' — or [null, null]. */
  function splitRegion(addr) {
    const t = nfkc(addr).trim().split(/\s+/)
    if (t.length < 2 || !SIDO[t[0]]) return [null, null]
    const sido = SIDO[t[0]]
    if (sido === "세종") return ["세종", t.slice(1).join(" ")]
    return [`${sido} ${t[1]}`, t.slice(2).join(" ")]
  }

  /** Last road+number pair before the first comma, parentheses removed. */
  function roadKey(tail) {
    if (!tail) return null
    const cleaned = nfkc(tail)
      .replace(/\([^)]*\)/g, " ")
      .split(",")[0]
    const found = [
      ...cleaned.matchAll(/([가-힣A-Za-z0-9]+(?:로|길))\s*(\d+(?:-\d+)?)/g),
    ]
    if (!found.length) return null
    const last = found[found.length - 1]
    return `${last[1]} ${last[2]}`
  }

  /* ── API ──────────────────────────────────────────────────────────── */
  // Matching runs server-side (TPO API, app/services/insurance_estimate_service.py)
  // against the nationwide LOCALDATA Postgres. A local API may be used only when
  // the page itself is served from localhost — a public link cannot redirect it.
  const LOCAL = /^(localhost|127\.0\.0\.1)$/.test(
    (typeof location !== "undefined" && location.hostname) || ""
  )
  const API_BASE =
    (LOCAL && new URLSearchParams(location.search).get("api")) ||
    "https://yielda-tpo-api.onrender.com"

  const CACHE_PREFIX = "yielda:ins-est:"
  const _inflight = new Map()

  function buildParams(q) {
    const params = new URLSearchParams()
    if (!q) return params
    for (const k of ["name", "place", "addr", "jibun", "gu", "reg"])
      if (q[k]) params.set(k, String(q[k]).slice(0, 200))
    return params
  }

  function cacheKey(q) {
    return CACHE_PREFIX + buildParams(q).toString()
  }

  /** Synchronously read a pre-fetched / cached estimate from sessionStorage (null if absent or error). */
  function peek(q) {
    try {
      if (typeof sessionStorage === "undefined") return null
      const raw = sessionStorage.getItem(cacheKey(q))
      if (!raw) return null
      const parsed = JSON.parse(raw)
      return parsed && parsed.status && parsed.status !== "error" ? parsed : null
    } catch (e) {
      return null
    }
  }

  function writeCache(key, data) {
    try {
      if (
        typeof sessionStorage !== "undefined" &&
        data &&
        data.status &&
        data.status !== "error"
      ) {
        sessionStorage.setItem(key, JSON.stringify(data))
      }
    } catch (e) {
      // sessionStorage unavailable or quota exceeded
    }
  }

  /**
   * q = {name, place, addr (road), jibun (lot), gu, reg (registered address)}. Resolves to
   * {status: matched|ambiguous|building_only|unmatched|no_district|error,
   *  row?, others?, candidates?, region, asOf, types}. Never throws.
   */
  async function estimate(q) {
    const cached = peek(q)
    if (cached) return cached

    const params = buildParams(q)
    const key = CACHE_PREFIX + params.toString()
    if (_inflight.has(key)) return _inflight.get(key)

    const p = (async () => {
      const ctl = typeof AbortController !== "undefined" ? new AbortController() : null
      // Render's free tier sleeps; the first call after idle can take ~50 s.
      const timer = ctl && setTimeout(() => ctl.abort(), 70000)
      try {
        const res = await fetch(`${API_BASE}/api/insurance/estimate?${params}`, {
          signal: ctl ? ctl.signal : undefined,
        })
        if (!res.ok) return { status: "error", http: res.status }
        const data = await res.json()
        writeCache(key, data)
        return data
      } catch (e) {
        return { status: "error" }
      } finally {
        if (timer) clearTimeout(timer)
        _inflight.delete(key)
      }
    })()

    _inflight.set(key, p)
    return p
  }

  const api = {
    estimate,
    peek,
    cacheKey,
    API_BASE,
    splitRegion,
    roadKey,
    SIDO,
  }
  root.YieldaEstimate = api
  if (typeof module !== "undefined" && module.exports) module.exports = api
})(typeof window !== "undefined" ? window : globalThis)
