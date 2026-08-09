# CLAUDE.md — Yielda TPO Demo (Primary Brain)

This file is Claude's primary reference for this repo. Read it before touching code.

---

## 1. What this repo is

Yieldus company demo: enter a 10-digit Korean business registration number (사업자등록번호) →
pipeline resolves the store (NTS → bizno → Kakao Local → trade area → Google Places →
web-search fallback → KMA weather → LLM scoring → E/T/M ambience fusion) → plays 10
matching tracks from a 620-track manifest (`data/demo_tracks.json`, audio on R2).

| Part | Path | Status |
|---|---|---|
| **API backend (canonical)** | `app/` — FastAPI, port 8077 | Working. 187 offline tests pass. `HANDOVER.md` is the authoritative doc |
| **Legacy demo UI** | `templates/demo.html` (vanilla JS, served at `/`) | Working; being replaced by `frontend/` |
| **New frontend (active work)** | `frontend/` — Vite + React 19 + TS + Tailwind v4 + shadcn | Scaffolded; pages to be built following the design system below |
| Node port | `backend/` | Low-fidelity stub — do NOT extend without explicit request |
| Design reference | `public/Spotify Web Onboarding 0–13.png` | 14 screens — source of truth for layout & UI blocks |

Run backend: `python -m uvicorn app.main:app --port 8077 --reload`
Run frontend: `cd frontend && npm run dev` · check: `npm run typecheck && npm run lint`

Key API: `POST /api/analyse {business_number, company_name?, address_hint?, place_id?}` →
`AnalyseResponse` (see `app/schemas.py`). `needs_input` in the response is a flow state
(user must pick a store / type a name), not an error.

---

## 2. Design system (learned from `public/` reference screens)

We reproduce the **exact UI blocks, layouts, and interaction patterns** of the reference
(Spotify web onboarding), but with **our own color tokens** (to be supplied — see §2.2).
Never copy Spotify's brand colors, logo, or name into product UI.

### 2.1 Foundations

- **Theme**: dark-first. Near-black page background; surfaces get *slightly* lighter as
  they elevate (page → card → hover). Borders are low-contrast white-alpha lines, not
  visible gray strokes.
- **One accent color** does all the talking (reference used green; ours comes from the
  token set). Everything else is monochrome. Accent is used ONLY for:
  primary CTA fill · progress-bar fill · selected radio/checkbox · valid-state checks ·
  inline text links in legal/footer copy · "now playing" highlight.
- **Typography**: bold geometric sans — primary font is **Paperlogy** (Korean, 9
  weights, self-hosted TTFs in `frontend/public/Paperlogy-1.001/`, `@font-face` in
  `frontend/src/index.css`; 400/700/800 preloaded in `index.html`), falling back to
  Outfit Variable. Scale observed:
  - Display: ~44–64px, weight 800–900, tight tracking (-0.02em), max 2 lines, centered
    ("Sign up to start listening")
  - Section title: ~24px / 700 ("Popular artists", "Featured Charts")
  - Step title: ~16px / 700; step counter above it ~16px / 400 muted
  - Field label: ~14px / 700; helper text under label ~14px / 400 muted
  - Body: ~14px; legal/footnote: ~12px muted, centered, links underlined
- **Radius language**: `rounded-full` (pill) for ALL buttons and chips; ~8px
  (`rounded-lg`) for inputs/selects; ~8–12px for cards and media tiles.
- **Onboarding column**: single centered column, **~410px wide** (`max-w-md`-ish),
  generous vertical rhythm: 24–32px between blocks, 8px label→input.
- **Buttons are 48px tall**, bold label, no size change between states.

### 2.2 Color tokens (values TBD — user will supply)

Components must reference **semantic tokens only** — never hardcoded hex/oklch values.
Token values live in ONE place: `frontend/src/index.css` (`:root` and `.dark`), already
mapped to Tailwind classes via `@theme inline`. When the user shares the palette, only
that file changes; zero component edits.

Semantic mapping used across all blocks:

| Token (shadcn var) | Role in the reference design |
|---|---|
| `--background` / `bg-background` | page (near-black) |
| `--card` / `bg-card` | elevated surface: sidebar cards, checkbox card, nav pills |
| `--muted` `--muted-foreground` | dimmed text: step counter, helpers, legal, "Artist" captions |
| `--border` `--input` | 1px field/divider lines (white-alpha) |
| `--primary` / `bg-primary` | **accent**: CTA fill, progress fill, selected controls, valid checks |
| `--primary-foreground` | text on accent (dark in reference) |
| `--secondary` | white/neutral pill buttons (Create playlist, Sign up free) |
| `--destructive` | error borders + unmet-rule text |
| `--ring` | focus rings |

Rule: `text-primary` for accent links, `bg-primary` for CTAs, `border-destructive` for
error inputs. If a needed token doesn't exist, add it to `index.css`, don't inline a color.

### 2.3 Layouts (3 shells)

**A. Onboarding / auth shell** (screens 1–12)
```
[centered brand logo, 40px, top ~32px]
[thin progress bar: 2px line spanning the column zone; accent fill = currentStep/total]
[step header: ‹ back chevron (ghost, 32px) | "Step N of 3" muted / "Title" bold]
[single centered column ~410px: fields / content]
[primary pill CTA, full column width]
[reCAPTCHA/legal footnote, centered, 12px muted, bottom of viewport]
[footer band: brand mark + wordmark left · attribution right]
```
- First screen (email) has no progress bar/step header — instead: logo, display heading
  (2 lines, centered), field, CTA, "or" divider (hairline—text—hairline), social buttons,
  hairline, "Already have an account? *Log in here*" (muted + underlined white link).

**B. App shell** (screens 0 & 13 — browse/home)
```
[top nav 64px: logo left · home icon-btn + search pill (~480px) center · actions right]
[left sidebar ~420px: "Your Library" header + promo cards (logged-out) / library list]
[main scroll area: chip filter row (logged-in) + content shelves]
[bottom fixed: gradient promo banner (logged-out) OR player bar (logged-in)]
[footer band]
```
- Search pill: leading search icon, placeholder "What do you want to play?", trailing
  divider + secondary icon. Nav actions: text link + white pill (logged out) /
  white "Explore Premium" pill + "Install App" + bell + 32px avatar circle (logged in).
- Shelf: section title left, "Show all" (14px bold muted, hover underline) right;
  horizontally scrolling row of media tiles.

**C. Wizard step content** (screens 3–10) — inside shell A:
one concern per step; fields stacked; CTA directly under the last field.

### 2.4 UI block inventory (reproduce these exactly)

1. **Primary button** — pill, `bg-primary text-primary-foreground`, 700 weight, 48px,
   full column width. Hover: brightness up + scale(1.02). **Loading state**: label
   replaced by 3 pulsing dots, fill dims (screen 11) — button size unchanged.
2. **Social/outline button** — pill, transparent bg, 1px `border`, white 700 label
   centered, brand icon absolutely placed left (~24px inset). Stack gap ~8px.
3. **Neutral pill button** — small white pill (`bg-secondary`), dark 700 label
   ("Create playlist", "Sign up free", "Explore Premium").
4. **Text input** — `rounded-lg`, transparent/dark bg, 1px `border-input`, white text,
   muted placeholder; focus: white 2px-ish border (or `ring`); **error: `border-destructive`**.
   Optional trailing icon button (password eye toggle). Label (bold 14px) above,
   optional helper (muted) between label and input.
5. **Select** — input look + trailing chevron ("Month").
6. **Composite DOB row** — `[select flex-1] [dd w-16] [yyyy w-24]`, 8px gaps.
7. **Radio** — 16px circle, 1px muted border; selected: accent ring + accent center dot.
   Gender layout: 2-col inline grid, 4 options.
8. **Requirement checklist** — bold 14px title ("Your password must contain at least"),
   rows of `[icon] [text 14px]`. States: idle = hollow muted circle; met = **accent
   filled circle + check**, text stays white; unmet-after-submit = hollow circle,
   **text turns destructive** (screens 3→4→5).
9. **Checkbox card** — `bg-card` rounded ~8px, p-4, square checkbox (accent fill +
   dark check when checked) + 14px label. Disabled variant dims whole card (screen 11).
10. **Progress bar** — 2px full-column line (`bg-border`), accent fill portion =
    step/total, animates on step change.
11. **Step header** — ghost back-chevron button + two-line text block (counter muted /
    title bold). Chevron dims while loading.
12. **Chip filters** — pill chips 32px ("All · Music · Podcasts · Audiobooks");
    active = white bg + dark text; inactive = `bg-card` white text.
13. **Media tile (circle)** — artist: circular image ~160px, name 16px/600 below,
    "Artist" muted 14px. Tile hover: subtle bg card + floating accent play button
    (bottom-right of artwork).
14. **Media tile (square)** — album/playlist: square rounded-lg artwork, title 16px/600,
    muted subtitle (artist / description, 2-line clamp).
15. **Shelf** — section title + "Show all"; 6-up row at desktop, horizontal overflow.
16. **Sidebar promo card** — `bg-card` rounded-lg p-5: bold 16px title, 14px body,
    neutral pill button. Stacked with 8px gap (screen 0).
17. **Sticky promo banner** — full-width gradient band (accent gradient), left: bold
    12px title + 16px body, right: large neutral pill CTA (screen 0, logged out).
18. **Player bar** — fixed bottom, 3 zones: track info left, transport center
    (shuffle · prev · **white 32px circular play/pause** · next · repeat, with thin
    progress line + mm:ss times below), utilities right (queue, device, volume slider).
19. **Top-nav icon button** — 40–48px circle, `bg-card`, white icon, hover brighten.
20. **Footer band** — slightly-elevated bg, brand logo + wordmark left, attribution right.
21. **Loaders** — inline (in-button) 3 dots; full-page centered 3 dots on dark
    (screen 12). No spinners.
22. **Inline text links** — accent + underlined inside legal copy; muted-white +
    underlined in secondary contexts.

### 2.5 Interaction & UX rules

- **Wizard**: validate on Next; on failure, input border + offending rules go
  destructive, met rules KEEP their accent checks. Back chevron always works.
  Progress bar reflects completed steps.
- **Loading**: swap CTA label for dot-loader, disable interactive elements (dim them),
  never resize the button; full-page dot-loader for page transitions.
- Autofocus the first field of each step; whole flow keyboard-completable; Enter submits.
- Radios/checkboxes flip instantly (no confirm buttons for selections).
- Media tiles and rows respond to hover with elevation, not borders.
- Respect `prefers-reduced-motion` (existing rule in legacy demo — keep it).

### 2.6 Yielda mapping (reference block → our product)

| Reference | Yielda usage |
|---|---|
| Email step + display heading | Business-number entry ("사업자번호 하나로 맞춤형 매장 음악 시작") |
| 3-step wizard + progress bar | Analysis flow: 번호 입력 → 매장 확인(후보 선택 = needs_input) → 결과 |
| Requirement checklist states | Pipeline check list (국세청 확인, Kakao 확정, …) — met = accent check |
| Checkbox/choice cards | Kakao place-candidate picker |
| Media tiles + shelves | Track recommendations, playlists by 업종군 |
| Player bar | Bottom fixed player (already exists in legacy demo — port it) |
| Chip filters | 업종군/시간대 filters |
| Loading dots | While `/api/analyse` runs (2–10s cold) |

---

## 3. Frontend conventions (`frontend/`)

- Stack: Vite · React 19 · TypeScript · Tailwind v4 (CSS-first, no config file) ·
  shadcn (style `radix-luma`, components in `src/components/ui/`) · HugeIcons ·
  `@fontsource-variable/outfit`.
- Add shadcn components with `npx shadcn add <name>` (run inside `frontend/`).
- Path alias `@/` → `src/`. Named exports; components in PascalCase files.
- **All colors via semantic Tailwind classes** (`bg-background`, `text-muted-foreground`,
  `bg-primary`…). Zero hex literals in TSX. Token values only in `src/index.css`.
- Dark mode: `.dark` class on root; this product is dark-first — build and test dark.
- API calls hit the FastAPI backend (`/api/analyse` etc.); dev requests proxy to
  `http://localhost:8077` (configured in `vite.config.ts` `server.proxy`).
- Routes (react-router-dom): `/` = analysis flow, **v2 light onboarding**
  (`src/pages/onboarding-v2-page.tsx`); `/onboarding-v1` = the parked dark
  version (`src/pages/onboarding-page.tsx`, desk photo + green gradient panel);
  `/stream` = playlist + player (`src/pages/stream-page.tsx`). Both onboarding
  pages share the flow state machine (`src/lib/use-analysis-flow.ts`) and the
  wizard bodies (`src/components/yielda/analysis-steps.tsx`) — put flow changes
  there, not in a page. v2 renders inside the `.theme-onboarding-v2` token scope
  (`src/index.css`): near-black page, deep-green form panel (`--panel` →
  `--primary-deep` sweep), raised green cards, bright accent green — same
  semantic token names, so shadcn blocks pick up the palette with no edits.
  Layout is v1 mirrored: form panel left (54%), hero right. Hero asset is
  `public/onboarding-3.png` (transparent, bottom-anchored — never mirror it,
  the phone screenshot would flip).
  The last successful
  `AnalyseResponse` lives in `src/lib/analysis-store.tsx` (context + sessionStorage);
  `/stream` redirects to `/` when it's empty. Playback uses the installed
  `src/components/ui/audio-player.tsx` provider. CAUTION: that provider syncs UI
  state via requestAnimationFrame, which freezes in background tabs — playback
  logic (auto-advance, shuffle order) must track the current index in refs, never
  from rAF-derived state (`stream-page.tsx` `currentIndexRef`).
- Shared Yielda blocks live in `src/components/yielda/` (brand, field, result-view);
  API types in `src/lib/api.ts` mirror `app/schemas.py`.
- Korean is the product language (UI copy in 한국어); code/comments in English.
- Formatting: Prettier (+ tailwind plugin) — `npm run format`; keep `typecheck` clean.

## 4. Backend guardrails (when touching `app/`)

- Secrets are query-params for data.go.kr/bizno — **never log or echo raw URLs or
  exception strings to responses**; `app/utils/logging.py` redaction depends on it.
- Kakao `x`=lng, `y`=lat — never swap (`_to_location` is the single conversion point).
- `needs_input` responses are flow states, not errors (`success: false` + payload).
- Caches are in-memory per-process (`app/utils/cache.py`); Places calls are capped
  daily (`places_daily_cap`) and must degrade, never fail the pipeline.
- Run `python -m pytest -q` (187 tests, offline) before calling backend work done.
