# Yielda Render Keep-Alive (Cloudflare Worker)

Prevents the Render free-tier backend (`https://yielda-tpo-api.onrender.com`) and its `yielda-insurance-db` Postgres connection pool from sleeping after 15 minutes of inactivity.

## How it works
- **Cron Trigger (`*/10 * * * *`)**: Every 10 minutes, Cloudflare's edge invokes `scheduled()` in `worker.js`.
- **Dual Warmup**:
  1. `GET /health` — keeps the FastAPI web service awake.
  2. `GET /api/insurance/estimate?name=warmup&gu=서울 광진구` — keeps the `asyncpg` connection pool to `yielda-insurance-db` warm so `/insurance.html` responds immediately.

## Deploy (Free Tier)

```bash
npx wrangler login
npx wrangler deploy --config scripts/cloudflare_keepalive/wrangler.toml
```
