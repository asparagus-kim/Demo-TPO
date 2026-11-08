# Yielda TPO Demo

Type a 10-digit Korean business registration number (사업자등록번호); the app identifies
the store from public data, scores its "ambience", and plays 10 matching tracks.

Built as the approval artefact for the 소상공인 통합지원 pilot (엠금융 협업) and as a D2D
sales kit.

| | |
|---|---|
| **Backend** | FastAPI · https://yielda-tpo-api.onrender.com · `/health` returns the version |
| **Frontend** | Vite + React 19 · https://yielda-tpo-demo.vercel.app |
| **Status** | Live. Demo-grade: no auth, no database, in-memory caches only |

---

## 1. How it works

One request (`POST /api/analyse`) runs the whole pipeline:

```
사업자등록번호 (10 digits)
   │
   ├─ 국세청 NTS ............ business status (계속/휴업/폐업)
   ├─ APICK ................. name + address + lat/lng          ← primary
   │    └─ bizno ............ name only                          ← fallback
   ├─ Kakao Local ........... resolve the actual store
   │    └─ by coordinates when APICK supplied them, else by name similarity
   ├─ Trade area ............ classify the 상권 from surrounding businesses
   ├─ Google Places ......... reviews + opening hours (daily-capped, degrades)
   ├─ Blog search ........... Naver/Kakao blog posts (display only)
   ├─ KMA ................... current weather
   ├─ LLM (Groq) ............ score review text
   └─ Ambience fusion ....... Energy / Tempo / Mood  →  10 tracks from 620
```

**Why APICK sits above bizno.** bizno's free plan returns a *name only*, and names are not
unique in Korea — two stores sharing one name both score `1.000` on name similarity, so the
gap is `0.000` and the store can never be auto-selected. The user then sees a 매장 선택
picker. APICK returns coordinates, which settle it. Measured on 49 real 광진구 stores:
**41% hit the picker without APICK, ~10% with it.**

`needs_input` in the response is a **flow state, not an error** (`success: false` plus a
payload). It means "ask the user to pick a store or type a name", and the UI is expected to
render it.

---

## 2. Repository layout

```
app/                FastAPI backend — the canonical implementation
  routers/          analyse · health · insurance
  services/         one module per upstream (apick, bizno, kakao, places, llm, …)
  utils/            http pool · TTL caches · log redaction
frontend/           Vite + React 19 + TS + Tailwind v4 + shadcn
  src/components/   care/ · stream/ · yielda/ · ui/
  src/lib/          api types, analysis store, flow state machines
  public/           fonts + images served as-is
data/               620-track manifest + 상권 reference xlsx
templates/          legacy vanilla-JS demo, served at /
tests/              262 test functions, fully offline
scripts/            key checks, smoke tests, data curation
```

`CLAUDE.md` is the working brief: design tokens, UI block inventory, and backend
guardrails. Read it before changing UI.

---

## 3. Running locally

### Backend

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in the keys below
python -m uvicorn app.main:app --port 8077 --reload
```

Open `http://localhost:8077` for the legacy demo UI.

Keep `--reload`. Without it you will debug stale code after every edit.
**With no keys the app silently falls back to mock mode** and serves fixture data for the
store `별빛카페 달빛차` — if you see that store, a key is missing.

### Frontend

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173, proxies /api → :8077
npm run typecheck && npm run lint
```

To run the frontend against **production** instead of a local backend (useful when you
don't want to set up Python):

```bash
VITE_API_BASE_URL=https://yielda-tpo-api.onrender.com npm run dev
```

Routes: `/` analysis flow · `/stream` player · `/collection` internal dashboard.
The Care screen (챙김) is an **overlay inside `/stream`**, not a route — see §6.

---

## 4. Environment variables

Required — the pipeline degrades or mocks without these:

| Variable | Where to get it | Notes |
|---|---|---|
| `KAKAO_REST_API_KEY` | developers.kakao.com | **카카오맵 사용설정 must be ON** |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | console.groq.com | OpenAI-compatible; base URL is required |
| `DATA_GO_KR_API_KEY` | data.go.kr | 국세청 business status |
| `KMA_API_KEY` | data.go.kr | 기상청; the same key works |
| `APICK_API_KEY` | apick.app | Paid, 50 points/call. Name + address + coordinates |
| `BIZNO_API_KEY` | bizno.net | Free, **200 lookups/day per key**. Fallback |
| `GOOGLE_MAPS_API_KEY` | GCP — Places API (New) | Reviews + hours only; degrades cleanly |

Optional: `SHEETS_WEBHOOK_URL` / `SHEETS_WEBHOOK_TOKEN` (analysis logging to a Google
Sheet), `MOCK_MODE`, `LLM_REVIEW_CAP`, `WEB_FALLBACK_BUDGET_SEC`, `LOG_LEVEL`.

> **data.go.kr keys:** use the **Decoding** key. The Encoding key double-escapes and
> returns 401/403. `app/config.py` detects this and corrects it with a warning.

Frontend build-time vars (set in Vercel, baked at build):
`VITE_API_BASE_URL`, `VITE_KAKAO_JS_KEY`.

---

## 5. Deployment — two independent pipelines

**This is the most common mistake.** The backend and frontend ship separately.

| | Backend | Frontend |
|---|---|---|
| Trigger | `git push origin main` → Render auto-deploys | `cd frontend && vercel deploy --prod` |
| Source | this git repo | direct upload from your machine |
| Verify | `/health` reports `version` — bump `app/__init__.py` so you can confirm | load the page |

**Pushing to `main` does not ship any frontend change.** If someone reports a UI fix that
"didn't deploy", this is almost always why.

Six secrets in `render.yaml` are `sync: false` — they live only in the Render Dashboard and
**no code push can carry them**. Setting one requires editing it there, which triggers a
redeploy.

Render's free plan spins down after ~15 minutes idle; the first request then pays a **~33s
cold start**. Before a demo, hit `/health` a minute ahead to wake it.

---

## 6. Testing

```bash
python -m pytest -q tests/        # 262 tests, fully offline — no network, no keys needed
python scripts/check_keys.py      # verifies every upstream key
python scripts/smoke_all.py       # end-to-end against the real APIs (costs quota)
```

`tests/` must stay offline. Several upstreams are paid or rate-limited, so a test that hits
the network will burn quota in CI.

Frontend: `npm run typecheck` is clean and should stay that way. `npm run lint` currently
reports **17 pre-existing errors in vendored shadcn files** (`components/ui/*`,
`components/tool-ui/*`, `hooks/use-mobile.ts`). `npm run build` does not run lint, so these
do not block a deploy — but the lint gate is effectively red, which will mask a real error.

---

## 7. Things that will bite you

**APICK reports failure as HTTP 200.** An expired key returns `401`, but *out of points*
returns `200` with `{"result":{"error":"사용 가능한 포인트이 부족합니다."}}`. Either way the
chain degrades silently to bizno and the 매장 선택 picker starts reappearing days later.
`apick_service.payload_error()` extracts the reason and logs it at ERROR. Error responses
are deliberately **never cached**, so topping up points takes effect immediately.
Diagnose with `debug.identity_source` — it should read `apick`, not `bizno`.

**bizno is 200 lookups/day per key.** When drained it returns `resultCode: -3`, and *every*
business number falls to "상호명을 입력해 주세요". Check `debug.biz_lookup_error`:
`quota_exceeded` means the service, `not_found` means the number.

**Kakao uses `x` = longitude, `y` = latitude.** Never swap them.
`kakao_local_service._to_location` is the single conversion point.

**Two files are stored with CRLF line endings** — `app/routers/analyse.py` and
`app/schemas.py`. Any tool that rewrites the whole file with `\n` normalises every line and
turns a 3-line edit into a ~1300-line diff. Compare `git diff --stat` against
`git diff --stat --ignore-all-space`; if they disagree wildly, the endings were normalised.

**Secrets are passed as query parameters** to data.go.kr and bizno. Never log a raw request
URL or echo an exception string into a response — `app/utils/logging.py` redaction depends
on this.

**Groq's free tier is bound by output tokens/minute (1000), not TPM.** Review scoring is
batched into one call for this reason; `LLM_REVIEW_CAP` is the batch size. Don't raise it
past ~12 on the free tier.

**DuckDuckGo blocks Render's egress IP.** The web-search fallback returns nothing from
production and is capped by `WEB_FALLBACK_BUDGET_SEC` (4s). Raising the budget won't help;
a real fix means a paid search API.

**Caches are per-process and in-memory** (`app/utils/cache.py`), and Render runs a single
worker deliberately. More workers would multiply paid API spend and fragment the cache.

---

## 8. Known gaps

- No authentication, no database, no CI.
- `entity_validation` can accept a Google Places match with `name_similarity = 0` when the
  address matches strongly — it has surfaced the wrong business in testing.
- The Care screen (챙김) is a **front-end-only mock**: no API calls, no storage, and its
  state resets every time it opens. It is demo content, not a feature.
- Three business numbers in the archived 광진구 49-store CSV point at entirely different
  businesses — that list was assembled from public listings and is not verified.
