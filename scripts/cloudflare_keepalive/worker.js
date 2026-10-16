// Cloudflare Worker Cron Keep-Alive for Yielda TPO API on Render.
//
// Runs every 10 minutes (`*/10 * * * *`) to prevent Render's free-tier web
// service (15-minute idle sleep) and its internal Postgres connection pool
// (`yielda-insurance-db`) from going cold.

const DEFAULT_API_BASE = "https://yielda-tpo-api.onrender.com"

async function pingBackend(env) {
  const base = (env && env.YIELDA_API_BASE) || DEFAULT_API_BASE
  const startedAt = Date.now()

  const endpoints = [
    `${base}/health`,
    // Also warm the insurance estimate DB pool with a lightweight district lookup
    `${base}/api/insurance/estimate?name=warmup&gu=${encodeURIComponent("서울 광진구")}`,
  ]

  const results = await Promise.allSettled(
    endpoints.map(async (url) => {
      const res = await fetch(url, {
        headers: { "User-Agent": "yielda-cloudflare-keepalive/1.0" },
      })
      return { url, status: res.status, ok: res.ok }
    })
  )

  return {
    ok: results.every((r) => r.status === "fulfilled" && r.value.ok),
    elapsedMs: Date.now() - startedAt,
    timestamp: new Date().toISOString(),
    results: results.map((r) =>
      r.status === "fulfilled"
        ? r.value
        : { error: String(r.reason || "fetch failed") }
    ),
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(pingBackend(env))
  },

  async fetch(request, env, ctx) {
    const report = await pingBackend(env)
    return new Response(JSON.stringify(report, null, 2), {
      status: report.ok ? 200 : 502,
      headers: { "content-type": "application/json; charset=utf-8" },
    })
  },
}
