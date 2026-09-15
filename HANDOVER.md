# Handover / 인수인계 — Yielda TPO Demo

Everything an incoming developer needs, in one file.

Written 2026-08-06 by the product owner (윤시훈). The original implementation is by
**the previous developer**; this document distinguishes that work from later
changes throughout, and says *why* each direction changed.

**Start with Part 0.** It explains the constraints behind the design and can be
read without opening any source file.

### [Part 0: Why this looks the way it does](#part-0-why-this-looks-the-way-it-does)
**여기서 시작하십시오.** 코드 0줄로 읽힘 — 목표·제약·방향 전환의 이유. / **Start here.** No source needed.

- [0.1 The goal, and the constraint that is not the goal](#01-the-goal-and-the-constraint-that-is-not-the-goal)
- [0.2 Seven changes of direction](#02-seven-changes-of-direction)
- [0.3 Decisions the product owner made](#03-decisions-the-product-owner-made)
- [0.4 Reverse lookup: feature → cause → fate](#04-reverse-lookup-feature-cause-fate)
- [0.5 What to invest in — and what not to](#05-what-to-invest-in-and-what-not-to)

### [Part I: Orientation](#part-i-orientation)
첫날 1회 완독. 전체 지도. / Read once, front to back, on day one.

- [0. TL;DR](#0-tldr)
- [1. What this project is](#1-what-this-project-is)
- [2. System overview](#2-system-overview)
- [3. The previous implementation vs now](#3-the-previous-implementation-vs-now)
- [4. The one thing you must not misread](#4-the-one-thing-you-must-not-misread)
- [5. Module map](#5-module-map)
- [6. Running it locally](#6-running-it-locally)
- [7. Traps I fell into](#7-traps-i-fell-into)
- [8. Improvements, in priority order](#8-improvements-in-priority-order)
- [9. Tests, and what is not covered](#9-tests-and-what-is-not-covered)
- [10. If you change one of these, read the linked section first](#10-if-you-change-one-of-these-read-the-linked-section-first)

### [Part II: API constraints](#part-ii-api-constraints)
작업 중 수시 참조. / A working reference; keep it open while you code.

- [1. Field-by-field: who gives us what](#1-field-by-field-who-gives-us-what)
- [2. bizno free vs apick paid — the decision that shaped the codebase](#2-bizno-free-vs-apick-paid-the-decision-that-shaped-the-codebase)
- [3. Google Places API (New)](#3-google-places-api-new)
- [4. What deferring the paid API did to the architecture](#4-what-deferring-the-paid-api-did-to-the-architecture)
- [5. Kakao Local](#5-kakao-local)
- [6. data.go.kr (NTS status, KMA weather)](#6-datagokr-nts-status-kma-weather)
- [7. Groq (LLM review scoring)](#7-groq-llm-review-scoring)
- [8. Music library](#8-music-library)
- [9. Code you can delete when you switch to paid `apick`](#9-code-you-can-delete-when-you-switch-to-paid-apick)
- [10. Re-verifying all of this](#10-re-verifying-all-of-this)

### [Part III: Korea domain primer](#part-iii-korea-domain-primer)
막힐 때 찾아보는 사전. / A dictionary; consult it when something looks arbitrary.

- [1. Business Registration Number (사업자등록번호)](#1-business-registration-number-사업자등록번호)
- [2. 법정동 vs 행정동 — Legal vs Administrative *dong*](#2-법정동-vs-행정동-legal-vs-administrative-dong)
- [3. Registered name ≠ the name on the sign](#3-registered-name-the-name-on-the-sign)
- [4. data.go.kr — the public data portal](#4-datagokr-the-public-data-portal)
- [5. NTS business-status API — what it does and does not give](#5-nts-business-status-api-what-it-does-and-does-not-give)
- [6. Trade areas (상권) — the 8 categories and what replaced them](#6-trade-areas-상권-the-8-categories-and-what-replaced-them)
- [7. 통신판매업 신고 (E-commerce filing) — and the trap in that CSV](#7-통신판매업-신고-e-commerce-filing-and-the-trap-in-that-csv)
- [8. Weather — KMA 초단기실황 (ultra-short-term observation)](#8-weather-kma-초단기실황-ultra-short-term-observation)
- [9. Glossary / 용어집](#9-glossary-용어집)
- [10. Where each concept shows up in the code](#10-where-each-concept-shows-up-in-the-code)

### [Document history](#document-history)

---

## Part 0: Why this looks the way it does

> 코드를 보기 전에 읽으십시오. / Read this **before** opening the code.
> Everything here is readable without looking at a single line of source.

The code will show you *features*. It cannot show you the *constraints* that
produced them. Several things in this repository look like over-engineering until
you know what they are working around, and one of them — the two-step store
picker — is temporary scaffolding that a future budget decision will delete
entirely. Read this part first so you know **where to invest effort and where not
to**.

---

### 0.1 The goal, and the constraint that is not the goal

**What we set out to prove — one sentence:**

> A store owner types their 10-digit business registration number, and nothing
> else, and we play music that suits their store.

Why that matters commercially:

| Layer | |
|---|---|
| Business | Small merchants in Korea are hard to reach with financial products. Lead with something they actually want — good background music, chosen for *their* store — and the resulting conversation builds a consultation pipeline handed to our partner, 엠금융 (M Financial). |
| Music's role | It is the **hook**. The business is the financial consultation. |
| This demo's role | ① an approval piece for our CEO and the partner ② a door-to-door sales kit |

**Now the part that is easy to get wrong.** This system runs entirely on free and
public APIs. That was **not the goal.** It was the situation:

| | |
|---|---|
| Constraint at the time | No budget approved for paid APIs → build the demo on free/public ones |
| **Originally intended direction** | A **paid** business-lookup API returning **company name, address and industry together**, giving a far more precise picture of the store |

So the free-tier stack is a **deferred state, not a target.** Moving to the paid
API is a **return to the original plan**, not an enhancement someone thought of
later. Sections 0.2 ② and 0.5 explain exactly which code that removes.

> 무료 API 구성은 **목표가 아니라 유예된 상태**입니다. 당시 유료 API 예산이 승인되지
> 않아 무료·공공 API로 시연을 만들었습니다. 원래 지향점은 유료 API로 상호명·주소·업종을
> 한 번에 받아 사업장을 더 정밀하게 파악하는 것이었습니다. 따라서 유료 전환은 개선
> 아이디어가 아니라 **원래 계획의 복귀**입니다.

---

### 0.2 Seven changes of direction

In rough chronological order. Each one is *what changed → why → what it produced*.

Details per module are in **Part I §3**; this section is the story, that section is
the comparison table.

#### ① Crawling → official API — two answers to the same constraint

```
Previous developer:  paid API not adopted, so a commercial vendor's screen
                     (moneypin) was crawled — a temporary implementation
                     to get the demo working
Now:                 the official bizno REST API
```

**This was not a mistake.** It was the first answer to the same constraint —
no budget — and it did get a working demo.

Why it still had to change: a scraped screen breaks whenever the target page
changes, it needs a headless browser inside the container, and it is legally
uncomfortable in a product we intend to sell. `playwright` is gone from
`requirements.txt` and the image shrank accordingly.

**What did *not* change: the budget constraint.** We swapped an unofficial source
for an official one at the same price point — zero.

#### ② Which is why today's structure is also provisional

```
Originally intended:  paid API  →  name + address + industry, in one call
Today:                bizno free →  name only
                          │
                          ▼
                 we cannot add a region hint to the Kakao search
                          │
                          ▼
                 same-name stores become genuinely indistinguishable
                          │
                          ├──▶ ① scoring over up to 15 Kakao candidates
                          ├──▶ ② the needs_input two-step picker screen
                          ├──▶ ③ entity validation reworked to run without an address
                          └──▶ ④ region hint extracted from the branch name
```

The sentence to take away is not "free tiers cost you UX complexity". It is:

> **①–④ are temporary scaffolding.** They exist only because one field — the
> address — is missing. A paid lookup removes all four. Do not invest in
> polishing them.

That distinction matters practically. The first framing says *accept this*. The
second tells you *how much effort this deserves*, which is what you actually need.

Two real cases that look identical to a user but are different problems:

```
406-81-65194  몸가짐휘트니스   middle digits 81 = corporation
              → ONE company legitimately operating TWO branches

274-06-01000  피트니스월드     middle digits 06 = sole proprietor
              → a DIFFERENT owner happens to use the SAME store name
```

Measured on 10 real businesses: **5 auto-confirmed, 5 required the picker.** When
two candidates both score `1.00`, the names are *identical* — no algorithm can
separate them. Only an address can. Full thresholds and scores: **Part II §4**.

#### ③ Google Places → Kakao Local — the product owner's proposal

```
Previous developer:  Google Places supplied everything about the place
Now:                 industry / address / coordinates = Kakao Local
                     reviews / opening hours          = Google Places
```

**Proposed by the product owner (윤시훈)**, to work around free-tier limits and get
better coverage of Korean small merchants.

What we then confirmed by measurement:

| | |
|---|---|
| Quota | Kakao 100,000/day vs Google 1,000/month |
| Industry signal | Kakao's `음식점 > 카페 > 커피전문점` category path beats Google's `place_types` |
| Coverage | Kakao is the map Koreans actually use; small merchants are listed more completely |

**Why Google stayed:** Kakao Local exposes no reviews and no opening hours at all,
and review text carries 50% of the ambience score. Dropping it was not an option.
The two-map split is deliberate — see **Part I §3.2**.

#### ④ Trade area: spreadsheet lookup → count the neighbours

```
Previous developer:  parse a dong name out of the address, look it up in a
                     nationwide 행정동 spreadsheet
Now:                 count businesses in 8 Kakao categories within 500 m
                     (plus universities within 1 km) and classify by ratios
```

The spreadsheet path scored **37%** on a 30-location benchmark. Two separate bugs
were involved — road-name addresses contain no dong at all, and lot-number
addresses carry a *legal* dong while the spreadsheet is keyed by *administrative*
dong (**Part III §2**). **Fixing both left it at 37%**, because dong boundaries do
not follow commercial reality.

Counting neighbours scores **90%**, and because it uses only coordinates it
behaves identically for a pharmacy and a gym.

#### ⑤ Music recommendation: absent → the core of the demo

The earlier version computed the E/T/M ambience numbers and stopped. **The demo
ended on a chart.** The product promise is music, so the demo has to play music.
`music_service.py` was written from scratch.

#### ⑥ 2 industries → 11 — a scope decision, then a deliberate widening

```
2 groups (cafe · fitness):  the priority agreed with 엠금융 for the pilot
11 groups:                  widened deliberately, for extensibility
```

**This was scope, not an oversight.** The pilot targeted cafes and gyms because
that is what the partner prioritised, so the track manifest covered exactly those.

What prompted the widening: a salon came through the pipeline, matched no industry
group, and got a cafe jazz track. Looking at the source library, the tracks already
existed — 75 salon, 173 bar, 105 bookshop — and **604 of 664 tracks were unused.**
The manifest was the bottleneck, not the library. Widening cost nothing but
curation, so we took the extensibility.

#### ⑦ Ambience priors: F&B only → all industries

Same story. The prior tables covered cafe / restaurant / bar / fast food /
dessert, matching the 2-industry pilot. Salons, bookshops and convenience stores
all fell through to the neutral default and produced **identical E/T/M** — a salon
measured 48/51/64, exactly neutral. Widened alongside ⑥ so the 11 groups each get
their own priors.

---

### 0.3 Decisions the product owner made

Recorded separately because they are not the engineer's calls, and because if you
disagree with one, this is who to ask.

| Decision | Rationale |
|---|---|
| **Switch place data to Kakao Local** | Overcome free-tier limits; better Korean small-merchant coverage (0.2 ③) |
| **Do bizno before the Kakao work** | I proposed the reverse. The objection: search accuracy, validation thresholds and the query builder *all* depend on what bizno returns, so the name must come first. Correct — the two were merged into one work item. |
| **No precomputed results** | "It has to look like it is really running." Hence 2–10 s of real latency instead of instant canned answers. |
| **Ship the 620 un-QC'd tracks** | Industry coverage was judged more valuable than polish. Rejected tracks are filtered at load time, so QC can proceed incrementally. |

---

### 0.4 Reverse lookup: feature → cause → fate

You will meet the left column while reading code. This table gives you the middle
and right ones.

| What you see in the code | Why it exists | After the paid switch |
|---|---|---|
| Store-picker screen (`needs_input`) | bizno free has no address | **removed** |
| Candidate scoring · branch-name hint | same cause | **removed** |
| Address-free entity validation | same cause | **removed** |
| Two map APIs | Kakao has no reviews/hours; Google quota is 1,000/month | kept |
| App-level Places daily counter | console cannot lower the quota (`조정 가능 여부: 아니요`) | kept |
| Web-search supplement | reviews are capped at 5 per place — money cannot lift this | kept |
| Trade area from coordinates | dong boundaries ≠ commercial reality (37% → 90%) | kept |
| Pool-relative normalisation | track and store metrics are on incompatible scales | kept |
| Exact match for track tokens, substring for store text | track vocabulary is closed, store vocabulary is open | kept |
| 2–10 s latency | serial dependency chain + precompute deliberately rejected | shorter (fewer steps) |
| **The entire current UI** | **placeholder** | **being redesigned** |

---

### 0.5 What to invest in — and what not to

#### The UI is a placeholder. Do not preserve it.

Layout, colours, copy and information placement were all written provisionally.
**A full design change is expected.** Nothing about the current screen is a
specification.

What *is* worth preserving, because the redesign will need it:

| Keep | Why |
|---|---|
| The API response schema (`app/schemas.py`) | the contract a new front end builds against |
| The three response states | normal · `needs_input` · error — any UI must handle all three |
| `evidence_provenance` | records which source produced the text, so the UI can be honest about it |

> 현재 UI는 **임의로 작성한 값**입니다. 레이아웃·색상·문구·정보 배치 모두 전체 디자인
> 변경 예정이므로 확정 사양이 아닙니다. 보존해야 할 것은 화면이 아니라 **응답 스키마와
> 상태 분기**(정상 / `needs_input` / 오류)입니다.

#### Do not polish the scaffolding

These exist only to work around the missing address field, and a paid lookup
deletes them. Fix bugs in them if they block a demo; do not refactor or extend
them.

- candidate scoring and thresholds
- the store-picker flow
- branch-name region hints
- address-free validation reweighting

Exact list with line counts: **Part II §9**.

#### Do invest here

- **The paid-API switch itself.** This is the original plan resuming, waiting only
  on budget. Cost: 44 KRW/call, 55,000 KRW/month minimum. It deletes ~280 lines
  and removes a whole screen from the user's path.
- **Tests around `app/routers/analyse.py`.** The ten-step wiring is the most
  breakage-prone file in the repo and has no test of its own (**Part I §9**).
- **CI.** There is none, and the repository has no git history at all.
- **Music QC.** 620 tracks, none listened to. An unsuitable track during a sales
  call is expensive.

---

## Part I: Orientation

> 첫날 1회 완독. 전체 지도. / Read once, front to back, on day one.

### 0. TL;DR

1. A store owner types a **10-digit Korean business registration number**. Nothing else.
2. The app figures out the store's name, industry, address, trade area, opening
   hours and current weather from **free/public APIs**, scores the store's
   "ambience" as three numbers, and picks 10 tracks that fit.
3. It is a **demo**: an internal approval piece for a partner (엠금융) and a
   door-to-door sales kit. It is not a product. Not deployed anywhere yet.
4. **The free-tier choice is the design.** One vendor withholding the store's
   address is why there is a store-picker screen. Read **Part I §4** before changing it.
5. Everything is verifiable from the command line — see **Part I §6**. Today: 187 unit tests
   pass, 17 end-to-end checks pass, 620/620 audio files playable.

#### Works today

| | |
|---|---|
| Business-number → full analysis | 5 industries verified live (cafe ×2, gym ×2, salon) |
| Store disambiguation | picker screen when the name is ambiguous |
| Trade-area classification | 90% accurate on a 30-location benchmark |
| Music recommendation | 620 tracks, 11 industry groups |
| Responsive UI | 375 / 768 / 1440 px, no horizontal scroll |
| Graceful degradation | closed businesses refused; Google quota cap falls back to Kakao + web search |

#### Does not work / out of scope

| | |
|---|---|
| Deployment | Dockerfile and compose exist; **not deployed** — awaiting the CEO's decision |
| Music QC | all 620 tracks are `status: draft`; nobody has listened through them |
| Consultation form, admin, CRM | never in scope for the demo |
| AI music generation | out of scope — the library is pre-existing |
| Chinese localisation | existed in the earlier build; **removed** on request |
| Employee-count data (NPS) | API not applied for; not wired in |
| CI | none. No git history either — see **Part I §9** |

---

### 1. What this project is

#### 1.1 The business idea

Small-business owners in Korea are hard to reach for financial services. The idea
is to lead with something they actually want — **good background music for their
store, chosen for their specific store** — and use that conversation to build a
consultation pipeline that is handed to the partner, 엠금융 (M Financial).

Music is the hook. The financial consultation is the business.

#### 1.2 What this demo is for

| Audience | Purpose |
|---|---|
| Partner (엠금융) and our CEO | Prove the concept works with real data before funding a real build |
| D2D sales reps | Open a phone in front of a shop owner, type their number, play music |

Both audiences imply the same requirement: **it must look and behave like a real
running service**, not a mockup. That is why there are no hardcoded results and
why analyses take 2–10 seconds instead of being pre-computed.

#### 1.3 Explicitly out of scope

Do not build these; they were considered and excluded: AI music generation, the
consultation form and CRM handoff, an admin console, multi-language UI, user
accounts, payment.

---

### 2. System overview

#### 2.1 The pipeline

One POST to `/api/analyse` runs ten steps. Numbers in the source are slightly out
of order for historical reasons (`Step 5.6` sits after `Step 6.1`) — the list
below is the true execution order.

```
 1  Validate     10 digits, normalise            app/services/nts_service.py
 2  NTS status   active? closed? → refuse early  국세청 via data.go.kr
 3  Company name bizno → else ask the user       app/services/biz_lookup_service.py
 4  Store match  Kakao keyword search            → industry, address, coordinates
                 └─ ambiguous? → needs_input, stop and ask the user
 5  Trade area   count neighbours within 500 m   app/services/trade_area_service.py
 6  Reviews      Google Places (max 5)           app/services/places_service.py
 6.1 Validation  is the Google place the same store as the Kakao one?
 5.6 Fallback    no reviews / no hours → web search supplement
 7  Weather      KMA ultra-short-term observation, by grid coordinates
 8  LLM scoring  review text → Energy / Tempo / Mood signals (Groq)
 9  Fusion       LLM + trade-area + industry + time + weather priors → E/T/M
10  Music        local manifest, no API call     app/services/music_service.py
```

Router: `app/routers/analyse.py` (536 lines). This is the file to read first.

#### 2.2 The dependency chain is serial, and that is the latency

```
business number → company name → store match → coordinates → weather
                     (bizno)        (Kakao)                    (KMA)
```

Each arrow requires the previous result. You cannot parallelise the spine.
Reviews, trade area and weather *are* fetched concurrently once coordinates exist.

Measured latency: **2–10 s cold**, near-instant on cache hit. `송화의카페` at 10.1 s
is the worst case in the demo set.

#### 2.3 Which API owns which field

Summarised here; the full matrix with limitations is
**Part II §1**.

| Field | Owner |
|---|---|
| Trading status | NTS (free, public) |
| Company name | **bizno** (commercial, free tier) |
| Industry · address · coordinates | **Kakao Local** (because bizno's free tier withholds them) |
| Trade area | Kakao category counts |
| Reviews · opening hours · rating | Google Places |
| Weather | KMA |
| Ambience E/T/M | Groq LLM + priors |
| Playlist | local manifest |

---

### 3. The previous implementation vs now

Seven changes, module by module. **Part 0 §0.2** tells the same story as a
narrative; this section is the comparison table. For each: what it was, what it is,
and **why**.

#### 3.1 Company name: web scraping → bizno API

| | |
|---|---|
| **Before** | `moneypin_service.py` scraped the screen of a commercial vendor (moneypin) with Playwright — a **temporary implementation**, chosen because no paid API had been adopted and the demo had to work |
| **Now** | `biz_lookup_service.py` calls the official bizno REST API |
| **Why** | Not because the earlier choice was wrong — it was a reasonable answer to a zero-budget constraint. But a scraped screen breaks whenever the target page changes, needs a headless browser in the container, and is legally uncomfortable in a product we intend to sell. `playwright` is gone from `requirements.txt` and the Docker image shrank accordingly. |
| **What did not change** | The budget constraint. We swapped an unofficial source for an official one at the same price — zero. |
| **Cost** | bizno's free tier gives *only* the name — no address, no industry. That single missing field cascades into §4. |

#### 3.2 Industry / address / coordinates: Google Places → Kakao Local

| | |
|---|---|
| **Before** | Google Places supplied everything about the place |
| **Now** | Kakao Local supplies industry, address and coordinates; Google Places is used **only** for reviews and opening hours |
| **Proposed by** | the product owner (윤시훈) — to work around free-tier limits and get better coverage of Korean small merchants |
| **Why** | Three reasons, all confirmed by measurement afterwards. (a) Kakao's Korean coverage of small merchants is better — it is the map Koreans actually use. (b) Kakao's free quota is 100,000/day vs Google's 1,000/month. (c) Kakao's `category_name` (`음식점 > 카페 > 커피전문점`) is a far better industry signal than Google's `place_types`. |
| **Kept Google because** | Kakao Local exposes no reviews and no opening hours at all. Review text is 50% of the ambience score, so it cannot be dropped. |

This hybrid split is deliberate. If you see "why two map APIs?", that is the answer.

#### 3.3 Trade area: dong lookup in a spreadsheet → count the neighbours

| | |
|---|---|
| **Before** | Parse the address for a dong name, look it up in `상권특성_행정동_전국_FINAL.xlsx` |
| **Now** | Count businesses in 8 Kakao categories within 500 m (plus universities within 1 km) and classify by ratios |
| **Why** | The Excel path was **37% accurate** on a 30-location benchmark. Two separate bugs contributed (road addresses have no dong; lot-number addresses carry *legal* dong while the Excel is keyed by *administrative* dong — see **Part III §2**). Even after fixing both it stayed at 37%, because dong boundaries do not match commercial reality. |
| **Result** | **90%** on the same benchmark. Also industry-agnostic: it uses only coordinates, so it behaves identically for a pharmacy and a gym. |
| **Excel now** | fallback only, when the surroundings call returns nothing |

Reproduce: `python scripts/trade_area_validate.py report` (uses a cache, 0 API calls).

#### 3.4 Music recommendation: none → the core feature

| | |
|---|---|
| **Before** | Did not exist. The pipeline computed E/T/M and stopped. |
| **Now** | `music_service.py` (732 lines) matches E/T/M + TPO against a 620-track manifest |
| **Why** | The E/T/M numbers were the deliverable, which meant the demo ended on a chart. The product promise is *music*, so the demo has to play music. |

Design decision worth understanding — **pool-relative normalisation**. Track
metadata and store scores are on incompatible scales:

```
valence      spans only 0.65–0.85     → absolute comparison ignores Mood entirely
energy_level fitness tracks all 8.0   → constant; no absolute scale can separate them
bpm          cafe 60–129 / gym 118–160 → distributions barely overlap
```

So each axis is min-max normalised **within the candidate pool**, and the target
(E/T/M ÷ 100) is compared as a position in that range. Two benefits: narrow axes
regain discriminating power, and constant axes automatically become "no
information" and drop out of the score without special-casing.

Absolute values are still shown in the UI so the display stays honest.

#### 3.5 Industry coverage: 2 groups → 11

| | |
|---|---|
| **Before** | 60 tracks, `cafe` and `fitness` only |
| **Why only two** | **Scope, not an oversight.** Cafes and gyms were the priority agreed with 엠금융 for the pilot, so the manifest covered exactly those. |
| **Now** | 620 tracks, 11 groups — widened deliberately, for extensibility |
| **What prompted it** | A salon came through, matched no group, and got a cafe jazz track. The source library already had 75 salon tracks, 173 bar, 105 bookshop — the manifest was the bottleneck, not the library, and **604 of 664 tracks were unused**. Widening cost only curation time, so we took the extensibility. |

Group sizes: cafe 284, retail 246, bar 229, culture 104, lodging 101, beauty 100,
dining 67, fitness 62, office 38, convenience 36, kids 31.

Two mapping directions with deliberately different semantics:

- **track → group: exact token match.** The track vocabulary is closed (32 tokens
  measured). Substring matching would let `카페` pull in `키즈카페`, mixing
  children's music into the general cafe pool.
- **store → group: substring match, order-sensitive.** Store input is Kakao's
  `category_name`, an open vocabulary. `음식점 > 카페 > 커피전문점` contains both
  "카페" and "음식점", so `cafe` must be tested before `dining`.

#### 3.6 Ambience priors: F&B only → all industries

| | |
|---|---|
| **Before** | `BUSINESS_TYPE_PRIORS` covered cafe, restaurant, bar, fast food, dessert — matching the 2-industry pilot scope |
| **Now** | Three-level lookup: exact match → industry group → neutral. Widened alongside §3.5 so each of the 11 groups gets its own priors. |
| **Why** | `classify_business_type()` deliberately returns non-F&B industries verbatim (so a salon is not mislabelled "restaurant"). The side effect was that salons, bookshops and convenience stores all fell through to the neutral default and produced identical E/T/M. A salon measured 48/51/64 — exactly neutral. |
| **Now** | The *display* label stays verbatim; only the priors are corrected via the industry group. A bookshop gets E 0.32, a bar E 0.84. |

#### 3.7 Chinese localisation: removed

The module `app/utils/i18n.py` (deleted) and the request's `lang` field are gone,
on request. Scope was fixed to Korean for the pilot.

(The `language` field still on `PlaceReview` in `schemas.py` is unrelated — it is
Google's language code for a review, not a UI setting.)

---

### 4. The one thing you must not misread

**The free tier is not a cost detail, and it is not the destination either.** It is
a deferred state — the original plan was a paid lookup returning name, address and
industry together (**Part 0 §0.1**). Four structures exist only to compensate for
the one missing field, and a paid switch deletes all four.

If this does not land, you will read the two-step user
flow as accidental complexity and try to delete it.

```
bizno free tier = company name only. No address. No industry.
      │
      ▼
we cannot add a region hint to the Kakao search
      │
      ▼
stores with the same name become genuinely indistinguishable
      │
      ├──▶ ① score up to 15 Kakao candidates
      ├──▶ ② needs_input: stop and let the user pick   ← the architecture changed for this
      ├──▶ ③ entity validation reweighted to work without an address
      └──▶ ④ extract a region hint from the branch name as a substitute
      │
      ▼
paying for apick (44 KRW/call, 55,000 KRW/month min) removes ①②③④ entirely
```

Two real cases that look identical to the user but are different problems:

```
406-81-65194  몸가짐휘트니스   middle digits 81 = corporation
              → ONE company legitimately running TWO branches

274-06-01000  피트니스월드     middle digits 06 = sole proprietor
              → a DIFFERENT owner happens to have the SAME store name
```

Measured on 10 real businesses: **5 auto-confirmed, 5 needed the picker.**
Distinctive names and names containing a branch resolve automatically; common
names (pharmacies, convenience stores, clinics) do not. When two candidates score
`1.00` and `1.00`, the names are *identical* — no algorithm fixes that, only an
address does.

Full detail, thresholds and real scores: **Part II §4**.
Code you can delete after switching vendors: **Part II §9**.

---

### 5. Module map

```
app/
  main.py                    FastAPI app, CORS, startup
  config.py                  env → Settings; data.go.kr key auto-correction
  schemas.py                 Pydantic v2 request/response models
  routers/
    analyse.py               ★ the 10-step pipeline — read this first
  services/
    nts_service.py           business-number validation + NTS trading status
    biz_lookup_service.py    bizno client; name resolution chain
    kakao_local_service.py   ★ store matching, candidate scoring, surroundings
    places_service.py        Google Places (reviews + hours only); daily cap
    entity_validation_service.py   is the Google place the same store?
    trade_area_service.py    ★ surroundings-based trade-area classifier
    weather_service.py       KMA; lat/lng → grid conversion
    llm_service.py           Groq review scoring
    web_search_service.py    review/hours supplement when Google is thin
    ambience_service.py      ★ priors, opening-hours parsing, E/T/M fusion
    music_service.py         ★ track matching, industry groups
  utils/                     address normalisation, TTL cache, logging
  research/rl_calibration/   ⚠ see below
templates/demo.html          the entire front end, single file, 1,093 lines (547 of them JS)
scripts/                     key checks, curation, validation, smoke tests
data/demo_tracks.json        620-track manifest (generated)
tests/                       187 offline tests
```

★ = the five files that carry the most non-obvious logic.

#### ⚠ `app/research/rl_calibration/` — 2,235 lines, not in production

A reinforcement-learning experiment (PPO) that tries to learn better prior tables
for the ambience fusion. **Nothing in the request path imports it** — verified by
grep. It runs standalone via `python -m app.research.rl_calibration.run_calibration`.

I did not touch, run, or evaluate it. Treat it as an unreviewed research artefact.
Decide with the CEO whether to keep, finish, or delete it. Do not assume the prior
values currently in `ambience_service.py` came from it — they are hand-tuned.

---

### 6. Running it locally

#### 6.1 Keys

Copy `.env.example` → `.env` and fill in. Nothing is committed; `.env` is gitignored.

| Variable | Where to get it | Free? |
|---|---|---|
| `DATA_GO_KR_API_KEY` | data.go.kr → sign up → apply for the NTS business-status API | yes |
| `KMA_API_KEY` | data.go.kr → apply for 기상청 초단기실황 (can be the same key) | yes |
| `KAKAO_REST_API_KEY` | developers.kakao.com → create an app → REST API key → **turn Kakao Map ON** | yes |
| `BIZNO_API_KEY` | bizno.net → sign up | 200/day |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | console.groq.com (OpenAI-compatible) | yes |
| `GOOGLE_MAPS_API_KEY` | GCP → enable Places API (New) | 1,000/mo |

**Use the Decoding key** from data.go.kr, not the Encoding key. If you get it
wrong, `config.py` detects it, fixes it, and logs a warning — but fix your `.env`.
Why this happens: **Part III §4.2**.

Verify all seven at once:

```bash
python scripts/check_keys.py
```

Expected today: OK 9 / WARN 2 / FAIL 1. The FAIL is the National Pension API,
which we never applied for and do not use.

#### 6.2 Run

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8077 --reload
```

**Do not omit `--reload`.** Without it your code changes are not picked up and you
will debug stale behaviour. Even with it, the reloader occasionally misses a
change — if results contradict the source, restart the process before
investigating anything else. This cost me an hour twice.

Then open `http://localhost:8077`.

Without `KAKAO_REST_API_KEY` or `OPENAI_API_KEY` the app enters mock mode
automatically (`effective_mock_mode()`) and returns a fixed sample store.

#### 6.3 Verify

```bash
python -m pytest -q                             # 187 offline tests, ~2 s
python scripts/smoke_all.py                     # 17 end-to-end checks, real APIs
python scripts/trade_area_validate.py report    # trade-area accuracy, 0 API calls
python scripts/curate_demo_tracks.py            # regenerate the music manifest
```

`smoke_all.py` is the one to run after any pipeline change. It covers the happy
path across three industries, both disambiguation cases, closed-business refusal,
unregistered numbers, user-typed names, request validation, cache-key correctness,
manifest coverage, and a HEAD sweep of all 620 audio files. It exits non-zero on
any regression, so it can go straight into CI.

---

### 7. Traps I fell into

Every one of these cost real time. Several were silent — wrong output, no error.

#### Silent failures — the dangerous kind

| # | Trap | Symptom |
|---|---|---|
| 1 | Kakao `x`/`y` swapped | `x` is **longitude**, `y` is latitude. Swap them and trade area *and* weather are quietly wrong. Nothing throws. |
| 2 | `httpx` does not follow redirects by default | DuckDuckGo 302s to another host. We got a 138-byte redirect body, `status != 200`, and therefore **zero web evidence on every analysis** for weeks. One line: `follow_redirects=True`. |
| 3 | `fuzz.partial_ratio` for name matching | Scores 1.00 whenever one name contains the other: `카페민` vs `마을카페민`. The correct store sat at rank 3. Switched to `ratio` + `token_sort_ratio`. |
| 4 | Legal dong vs administrative dong | Trade area silently fell back to province level, so every store in Seoul got the same answer. **Part III §2** |
| 5 | Korean 12-hour opening hours | `오전 8:00 ~ 오후 9:00` did not match a 24-hour regex → all daypart weights 0 → the time axis dropped out of the recommendation, and the raw string leaked into the UI. |
| 6 | `24시간 영업` opening hours | Same class of bug, third occurrence. Google returns prose, not a time range, for 24-hour stores. |
| 7 | `"일" in line` to detect weekends | **`"월요일"` also contains `"일"`.** Every day was classified as a weekend, so the weekday/weekend split never once fired. A test with only Mon+Tue hid it for weeks. |
| 8 | `[hidden]` beaten on specificity | `#result{display:flex}` (id, 1-0-0) overrides the UA stylesheet's `[hidden]{display:none}` (0-1-0). The empty result panel showed on first load — but only ≥768 px, because that is where the rule lived. Fixed with `[hidden]{display:none !important}`. |
| 9 | `blockquote` default margin | Browsers ship `margin: 16px 40px`. Review quotes were indented 40 px out of alignment and wasted 64 px of height. |
| 10 | `.bar > i` with no `width` | `width: auto` filled the parent, so score bars rendered **full** while the number beside them read `0`. |

#### Loud failures — fast to diagnose once you know

| # | Trap | Symptom |
|---|---|---|
| 11 | data.go.kr **Encoding** key | 401/403. Double-encoded `%2B` → `%252B`. |
| 12 | NPS old endpoint path | `NO_OPENAPI_SERVICE_ERROR` — retired. V2 path is alive. |
| 13 | Kakao Map toggle off | 403 despite a valid key. |
| 14 | bizno `items` null padding | `items[0]` is `None`. Filter the array first. |
| 15 | `uvicorn` without `--reload` | Code changes ignored; you debug stale behaviour. |
| 16 | `tracks.json` (225) instead of `data.js` (664) | 439 tracks missing, silently. |
| 17 | Places quota cannot be lowered in the console | `조정 가능 여부: 아니요`. Enforce it in the app. |
| 18 | Stale state after an error | Entering a closed business number left the previous store's 10 tracks loaded in the player. The reset lived only in the `needs_input` path. |
| 19 | **`httpx` logs the full URL at INFO — including the API key** | data.go.kr takes its credential as a `serviceKey` **query parameter**, so every successful call printed the key in plaintext: `INFO httpx \| HTTP Request: POST https://api.odcloud.kr/...?serviceKey=X70Ep...`. Anywhere logs are shipped, the key leaks. Fixed by pinning the `httpx`/`httpcore` loggers to WARNING in `app/utils/logging.py`. **Check this whenever you add an API that authenticates via query string.** |
| 20 | data.go.kr returns `503` under load | Not our bug, but it makes the closed-business guard unavailable — see §7.1 below. |

#### And two mistakes about *method*, not code

- **I once sampled 8 tracks from R2, got 8× 404, and concluded "1 playable track".**
  The 8 happened to be exactly the tracks with no source audio. A full sweep showed
  651/664. **Sample size 8 out of 664 is not evidence.** This is why
  `smoke_all.py` HEADs all 620 rather than a sample.
- **I measured trade-area accuracy at 25%, then 43%, then 37%** as I fixed my own
  measurement harness. Only the last is comparable to the 90%. When you see a
  number in the older planning documents, prefer the one produced by
  `trade_area_validate.py report`.

---

#### 7.1 What happens when NTS is down

Observed 2026-08-06: `api.odcloud.kr` returned **`503 API 서버 오류가 발생하였습니다`**
for every business number for several minutes.

The pipeline **degrades rather than blocking**: status becomes `조회실패` and the
analysis continues. That is deliberate — an outage at the tax office must not stop
every user — but it has a consequence worth knowing:

> **While NTS is unreachable, closed businesses are not filtered out.** A shop that
> shut down in 2018 will analyse normally.

That trade-off is correct for a demo (better a slightly wrong result than a dead
screen), but if this ever becomes a real product handling real leads, decide
explicitly whether an unverifiable business should be allowed through.

`scripts/smoke_all.py` detects this case and reports the closed-business check as
**SKIP**, not FAIL, so an outage does not look like a regression in your code.

> 국세청 API가 죽어 있으면 폐업 매장이 걸러지지 않습니다. 데모에서는 화면이 죽는 것보다
> 낫다고 판단해 통과시키지만, 실제 제품에서는 명시적으로 결정해야 합니다.

#### 7.2 Secret handling — audited 2026-08-06

Three upstreams authenticate with a **query parameter**, not a header. Anything
that prints a URL therefore prints a credential.

| Upstream | Auth | Risk |
|---|---|---|
| data.go.kr (NTS, KMA) | `?serviceKey=` | **in URL** |
| bizno | `?key=` | **in URL** |
| Google Geocode | `?key=` | **in URL** |
| Kakao Local | `Authorization: KakaoAK` header | safe |
| Google Places | `X-Goog-Api-Key` header | safe |
| Groq / OpenAI | SDK, `Authorization` header | safe |

**What was actually leaking.** `httpx` logs every request at INFO *including the
full URL*, so every successful NTS call wrote the key to stdout in plaintext.

Three controls now, deliberately layered:

1. `httpx` / `httpcore` loggers pinned to WARNING — the credential is never even
   assembled into a log record.
2. `RedactingFormatter` (`app/utils/logging.py`) scrubs every known secret from
   the finished log line, **including exception tracebacks**. Redacting after
   formatting rather than in a `Filter` is deliberate: a filter on `record.msg`
   misses tracebacks, which is exactly where an HTTP client puts the URL. Each
   secret is registered in three forms — literal, URL-encoded, URL-decoded —
   because `config._get_service_key()` decodes data.go.kr keys before sending.
3. Exception text is never returned to the client. The global handler
   (`app/main.py`) and `nts_service`'s failure path both used to embed
   `str(exc)`; an httpx error there would have put the key in the browser.

Verified with `httpx` deliberately turned back to INFO — the worst case:

```
httpx | HTTP Request: POST https://api.odcloud.kr/...?serviceKey=***REDACTED***&returnType=JSON
httpx | HTTP Request: GET  https://bizno.net/api/fapi?key=***REDACTED***&q=...
```

Also checked and clean: all templates, static files, source, `cache/`, `data/`,
docs, `.env.example` (78 files); every API response including `/health`, `/`,
`/legacy`, error and `needs_input` paths; `.env` and `cache/` are gitignored and
untracked. Pinned by `tests/test_secret_redaction.py` (9 tests).

> **When you add an upstream, check how it authenticates.** If the credential
> goes in the query string, add its env var name to `SECRET_ENV_NAMES` in
> `app/utils/logging.py`. The redactor only knows what it is told.

---

### 8. Improvements, in priority order

#### Not an improvement — the original plan resuming

| Item | Status | Effect | Cost |
|---|---|---|---|
| **Switch to a paid business-lookup API (apick)** | **awaiting budget approval** | Picker screen disappears from the user's path; store identification becomes exact; ~280 lines deletable | 44 KRW/call, 55,000 KRW/month minimum |

This is listed separately on purpose. It is not an idea someone had later — it is
the direction the project started in, deferred when the budget was not approved
(**Part 0 §0.1**). Everything in the table below is a genuine improvement on top of
whatever vendor we use.

> 유료 API 전환은 개선 항목이 아니라 **원래 계획의 복귀**입니다. 예산 승인만 남았습니다.

#### Genuine improvements

| Priority | Item | Effect | Cost |
|---|---|---|---|
| **High** | Music QC — listen and mark `review: reject` | Prevents an embarrassing track during a sales call | human time, incremental |
| **High** | CI running `pytest` + `smoke_all.py` | There is none, and no git history either | half a day |
| Medium | Translate comments in the 5 core modules to English | 388 Korean lines sit in exactly the files carrying the *why* | ~1 day, **do not automate** |
| Medium | Redesign review evidence | 5 reviews carry 50% of the score. Make the web-search supplement unconditional rather than a fallback. | 1–2 days |
| Medium | Diversify fitness track metadata | Gym tracks are nearly all `energy_level: 8` EDM, so stores within the industry get near-identical playlists | needs the music team |
| Medium | Deduplicate `normalize_business_number` | Identical function in `nts_service.py` and `biz_lookup_service.py` | 10 minutes |
| Low | Decide on `app/research/rl_calibration/` | 2,235 unreviewed lines, not in production | a conversation |
| Low | Wire up NPS employee counts | Marginal signal; needs a usage application | low value |
| — | **Redesign the UI** | Current layout/colours/copy are placeholders, not a specification (**Part 0 §0.5**) | design-led, out of engineering scope |

On the comment translation: strings in these modules are a mix of code comments
(translate) and **user-facing Korean product copy** — log lines, UI note strings,
`evidence_text()` output, playlist labels (**do not translate**). A regex pass will
break the product. It has to be done by hand, file by file.

---

### 9. Tests, and what is not covered

`187 passed` in about 2 seconds. All offline — no network.

| File | Covers |
|---|---|
| `test_pipeline_pure.py` | business-type classification, opening hours, dayparts, fusion, priors |
| `test_music_service.py` | industry mapping, pool building, scoring, diversity caps, real manifest |
| `test_kakao_local.py` | category parsing, name scoring, branch hints, candidate selection |
| `test_entity_validation.py` | same-store validation, missing-address path |
| `test_hours_and_cap.py` | Korean 12-hour and 24-hour parsing, Places daily cap |
| `test_secret_redaction.py` | API keys never reach logs, tracebacks, or responses |

#### Real gaps

- **No test touches `app/routers/analyse.py`.** The ten-step wiring — the file
  most likely to break — is covered only by `smoke_all.py`, which needs live keys.
  A mocked-service integration test is the highest-value test to add.
- **No front-end tests.** `demo.html` holds 547 lines of JavaScript. Four of the
  bugs in §7 (#8, #9, #10, #18) were front-end and were caught by hand.
- **No CI.** Nothing runs automatically.
- **No git history.** The repository has **zero commits** — every file is
  untracked. There are no diffs to read, no blame, no bisect. `git status` shows
  23 untracked entries. **Making the first commit is your first task.** This
  document exists partly to substitute for the history that was never recorded.

---

### 10. If you change one of these, read the linked section first

| Tempted to… | Read | Because |
|---|---|---|
| Delete the store-picker flow | §4 | It is a consequence of the free tier, not sloppiness |
| Add fields to the Places field mask | **Part II §3.2** | The mask decides the billing SKU |
| Replace Kakao with Google for addresses | §3.2 | Coverage, quota, and industry signal all favour Kakao here |
| "Simplify" trade area back to the Excel | §3.3 | 37% vs 90% |
| Change music scoring to absolute thresholds | §3.4 | Track and store scales are incompatible |
| Substring-match track industry tokens | §3.5 | `카페` would pull in `키즈카페` |
| Translate module comments with a script | §8 | Product copy is mixed in with comments |
| Touch opening-hours parsing | §7 #5–7 | Three separate bugs live here; keep the regression tests |

---

## Part II: API constraints

> 작업 중 수시 참조. / A working reference; keep it open while you code.

### 1. Field-by-field: who gives us what

The single most useful table in this repo. Read it as: *for each field the UI
shows, which API is authoritative, what the free tier withholds, and what we do
about it.*

| Field shown in UI | Source now | Free-tier limitation | Our workaround | With paid `apick` |
|---|---|---|---|---|
| Trading status (계속/폐업) | NTS (data.go.kr) | none — fully free | — | same |
| **Company name (상호명)** | **bizno** | only field the free plan gives | — | same |
| **Address (주소)** | **Kakao Local** | bizno withholds it | search Kakao by name, then score candidates | **direct from apick** |
| **Industry (업종)** | **Kakao Local** | bizno withholds it | derive from Kakao `category_name` | **direct from apick** |
| **Coordinates** | **Kakao Local** | bizno withholds it | comes with the Kakao match | **direct from apick** |
| Trade area (상권) | Kakao category counts | — | count 8 categories within 500 m | unchanged |
| Reviews (리뷰) | Google Places | **max 5 per place, hard API cap** | web-search snippets as supplement | unchanged (API limit, not tier) |
| Opening hours | Google Places | often absent for small merchants | recover from web-search snippets | unchanged |
| Rating / review count | Google Places | — | — | unchanged |
| Weather | KMA (data.go.kr) | none — fully free | — | unchanged |
| Ambience E/T/M | Groq LLM + priors | free-tier RPM limits | cap reviews scored at 25 | unchanged |
| Playlist | local manifest | none — no API call | — | unchanged |

**Read the bold rows together.** Address, industry and coordinates are the three
fields that force the entire two-step architecture. Section 4 explains why.

---

### 2. bizno free vs apick paid — the decision that shaped the codebase

#### 2.1 What each actually returns

Measured 2026-07-28 across three vendors
(`yielda_with_mfinancial/benchmark_results.csv`), re-confirmed 2026-08-05.

| | bizno free | apick paid |
|---|---|---|
| Company name (상호명) | ✅ | ✅ |
| Trading status · tax type | ✅ | ✅ |
| **Address** (road + lot) | ❌ | ✅ |
| **Industry / business type** | ❌ | ✅ |
| **Latitude / longitude** | ❌ | ✅ |
| Representative name | ❌ | ✅ |
| Opening date | ❌ | ✅ |
| Phone | ❌ | ✅ |
| Employee count | ❌ | ✅ |
| Cost | **0 KRW** | **44 KRW/call**, 55,000 KRW/month minimum |
| Rate limit | 200 calls/day, 1 req/sec | higher |

There is **no free public path** from business number → company name. The
government API takes the name as an *input*, never returns it as an output
(see **Part III §5**). That is why a commercial vendor is
unavoidable, and why the choice is only *which* vendor.

#### 2.2 Contract details that bite

Endpoint: `https://bizno.net/api/fapi`

```
GET /api/fapi?key=<KEY>&q=<10-digit-number>&type=json
```

| Gotcha | Detail |
|---|---|
| It is **not** OAuth2 | No `grantType`/`clientId`/`clientSecret`. Just `key=`. |
| `items` is **null-padded** | The array contains `null` entries. `items[0]` is often `None`. Filter first. |
| Success flag | `resultCode == 0` (may arrive as int or string `"0"`). |
| 1 req/sec | Enforced with an `asyncio.Lock` + 0.4 s gap in `biz_lookup_service.py`. |

```python
# app/services/biz_lookup_service.py — parse_bizno_payload()
items = [i for i in (payload.get("items") or []) if i]   # null padding!
```

> 무료 플랜은 상호명·상태·과세유형만 줍니다. `type`·`detail`·`gb` 같은 파라미터를
> 붙여도 주소·업종은 나오지 않습니다 (실측 확인).

---

### 3. Google Places API (New)

We use it for **reviews and opening hours only**. Industry, address and
coordinates come from Kakao — see §5 for why.

#### 3.1 Reviews are capped at 5 per place — by the API, not by the tier

This is the constraint people assume money can fix. It cannot. The Places API
returns at most **5 reviews** per place regardless of plan.

```python
# app/services/places_service.py
def _review_limit(cap):
    return max(5, min(cap, 40))   # the API caps at 5 anyway
```

Consequence: the LLM scores ambience from at most 5 reviews. That is thin
evidence, which is exactly why the web-search supplement exists.

#### 3.2 The field mask decides your SKU — and your bill

Places API (New) prices by **which fields you request**. Adding one field can
promote the call to a more expensive SKU.

| Call | Field mask constant | SKU tier |
|---|---|---|
| Text Search | `_SEARCH_FIELDS` | Enterprise |
| Place Details | `_PLACE_DETAIL_FIELDS` | Enterprise + Atmosphere |

Free allowance: **1,000 calls/month per Enterprise SKU**.

> **Do not add fields to these two constants casually.** A field you add for a
> "small improvement" can move the call into a paid tier.
> `_SEARCH_FIELDS` / `_PLACE_DETAIL_FIELDS` in `app/services/places_service.py`.

#### 3.3 Quota cannot be lowered in the console — so we count in the app

The GCP console shows `조정 가능 여부: 아니요` (adjustable: no) for these quotas,
and budget alerts are retroactive. So we enforce a daily cap ourselves.

```python
# app/config.py
places_daily_cap: int = 40          # PLACES_DAILY_CAP env var
```

```python
# app/services/places_service.py
def availability() -> tuple[bool, str]:   # ("mock_mode"|"no_key"|"daily_cap"|"ok")
```

On hitting the cap the pipeline **degrades instead of failing**: Kakao supplies
industry/address/coordinates, web search supplies review text. The analysis still
completes; `evidence_provenance` records that Google was skipped.

Actual demo volume — a few live demos plus 100–200 D2D stores per month — is far
under 1,000, so Google Places is effectively free at this scale. The cap exists to
make an accident impossible, not because we expect to approach the limit.

---

### 4. What deferring the paid API did to the architecture

**If you read only one section of Part II, read this one.** Without it the two-step
user flow looks like accidental complexity and someone will try to delete it.

The narrative version is **Part 0 §0.2 ②**; this section carries the thresholds and
the measured scores.

```
bizno free  =  company name only, no address, no industry
      │
      ▼
we cannot add a region hint to the Kakao search
      │
      ▼
same-name stores become genuinely indistinguishable
   (피트니스월드: Jung-gu and Jongno-gu, different owners, identical name)
      │
      ├──▶ ① candidate scoring over up to 15 Kakao hits      (~90 lines)
      ├──▶ ② needs_input two-step user flow                  (router + UI)
      ├──▶ ③ entity validation redesigned to work name-only  (score reweighting)
      └──▶ ④ branch-name → region hint extraction            (~27 lines)
      │
      ▼
switching to apick makes ①②③④ unnecessary
```

Measured consequence, 10 real businesses:

| Store name character | Auto-confirmed? |
|---|---|
| Distinctive (헬카페스피리터스, 송화의카페) | yes |
| Branch name in title (어게인짐 건대입구역점) | yes |
| **Common name** (가은약국, 가온동물병원) | **no — picker screen** |
| Kakao lists a different name (VA미용실 → VA헤어메이크업) | **no — picker screen** |

**5 of 10 needed the picker.** Cafes and gyms tend to have distinctive names;
pharmacies, convenience stores and clinics do not. Expect the picker often in
those industries. This is a data limitation, not a bug.

#### 4.1 The two auto-confirm thresholds

```python
# app/services/kakao_local_service.py
AUTO_ACCEPT_SCORE  = 0.80   # top candidate must score at least this
AUTO_ACCEPT_MARGIN = 0.15   # and beat the runner-up by at least this
SINGLE_HIT_MIN_SCORE = 0.55 # relaxed rule when only one candidate exists
```

Failure reasons returned to the UI: `ambiguous` (several similar), `low_score`
(even the best is weak), `empty` (nothing found).

Real scores:

| Query | Top | 2nd | Margin | Verdict |
|---|---:|---:|---:|---|
| 헬카페스피리터스 | 1.00 | — | — | auto |
| 송화의카페 | 1.00 | 0.80 | 0.20 | auto |
| 고아라헤어케어강남점 | 0.92 | — | — | auto |
| 몸가짐휘트니스 | 0.88 | 0.78 | **0.10** | `ambiguous` |
| 피트니스월드 | 1.00 | **1.00** | **0.00** | `ambiguous` |
| VA미용실 | **0.31** | — | — | `low_score` |

A margin of `0.00` means the names are *identical*. No scoring function can fix
that; only an address can.

---

### 5. Kakao Local

Free quota: **100,000 keyword searches/day**, **3,000,000 calls/month** total.
At our volume this is not a constraint.

| Endpoint | Used for |
|---|---|
| `search/keyword.json` | find the store by name → industry, address, coordinates |
| `search/category.json` | count surrounding businesses (trade area) |
| `geo/coord2regioncode.json` | coordinates → administrative dong (fallback path) |
| `search/address.json` | geocoding when needed |

Traps:

| Trap | Detail |
|---|---|
| **`x` is longitude, `y` is latitude** | Swapping them silently corrupts trade area *and* weather. Nothing errors. |
| `size` max is 15 | Cannot page past 15 candidates in one call. |
| Only the **first app** on an account gets the free quota | A second app needs Biz Wallet. Reuse the existing app. |
| 카카오맵 must be switched ON per app | Otherwise `403` even with a valid key. |
| No reviews, no opening hours | Kakao Local does not expose them at all — hence Google Places. |

```python
# app/services/kakao_local_service.py
def _to_location(doc):
    """Kakao x/y → {"lat","lng"}. **x=longitude, y=latitude** — never swap."""
```

Trade-area calls are cached on a 500 m grid key, so stores in the same block reuse
one set of counts.

---

### 6. data.go.kr (NTS status, KMA weather)

Full explanation in **Part III §4**. Operational summary:

| Item | Value |
|---|---|
| Key | one per account, `DATA_GO_KR_API_KEY` / `KMA_API_KEY` |
| Per-API approval | 활용신청 required separately for each dataset |
| Key format | use the **Decoding** key; `app/config.py` auto-corrects and warns |
| Cost | free |
| NPS (employee counts) | path `NpsBplcInfoInqireServiceV2/getBassInfoSearchV2`; **not applied for**, so `check_keys.py` reports FAIL. Not used by the pipeline. |

Error-message decoder:

| Message | Means |
|---|---|
| `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` | path is alive, you have not applied |
| `NO_OPENAPI_SERVICE_ERROR` | path is retired — find the new version |
| `401` / `403` with a valid key | you used the Encoding key |

---

### 7. Groq (LLM review scoring)

Accessed through the OpenAI-compatible endpoint, so the OpenAI SDK works with
`OPENAI_BASE_URL` pointed at Groq.

| Item | Value |
|---|---|
| Free tier | requests-per-minute and daily-token limits |
| Guard | `LLM_REVIEW_CAP` — **6** (2026-09-15). This is now the *batch size*: all reviews go to the LLM in ONE request (`llm_service.score_reviews`). Groq free tier is bound by **OTPM = 1000 output tokens/min**, ~83 tok/review → 6 ≈ 500 tok leaves room for 2 analyses/min. Hard ceiling 12. **Do not raise to 25** — that re-creates the 429 → heuristic-fallback stall. |
| Model | `OPENAI_MODEL` — **`qwen/qwen3.8-27b`** on Groq (code default `gpt-4o-mini`). `llama-3.3-70b-versatile` was retired by Groq ~Aug 2026; the app silently ran on the keyword heuristic for a month because `score_reviews` degrades without surfacing it. `OPENAI_BASE_URL` is now read explicitly in `config.py`; startup logs `LLM client: <model> @ <base_url>`. |
| Base URL | the SDK reads `OPENAI_BASE_URL` from the environment; point it at Groq |
| Failure behaviour | scoring degrades to priors only; `c_text = 0` and the fusion falls back to the prior-only vector |

Note the two-level default: `app/config.py` ships OpenAI-flavoured defaults, and
`.env` overrides them to Groq. If you see `gpt-4o-mini` in the code, that is the
fallback, not what is running. Check `.env`.

Ambience weighting, for context on how much the LLM matters:

```
E = 0.50·text + 0.20·trade_area + 0.15·industry + 0.10·time + 0.05·weather
M = 0.50·text + 0.15·trade_area + 0.20·industry + …
```

Review text carries **half** the score. With reviews capped at 5 (§3.1), that half
rests on thin evidence — the main quality risk in the current design.

---

### 8. Music library

No API. One local manifest, `data/demo_tracks.json`, generated by
`scripts/curate_demo_tracks.py` from the player project's `data.js`.

| Item | Value |
|---|---|
| Source | `yieldus_player_founder/yieldus-player/data.js` — **664 tracks** (authoritative) |
| Do **not** use | `tracks.json` — 225 tracks, stale |
| Manifest | **620 tracks**, 11 industry groups |
| Excluded | 13 with no Drive link (no audio exists) + 31 Christmas-only tracks |
| Audio hosting | Cloudflare R2 public bucket, `{track_id}.mp3` |
| Playable | **620/620** verified by HEAD sweep |
| QC status | all 620 are `status: draft`; only 3 of the original 664 are `approved` |
| Vocals | 429 instrumental / 191 full vocal |

Known metadata weaknesses:

| Weakness | Effect |
|---|---|
| Fitness tracks are nearly all `energy_level: 8` EDM | Weak discrimination *within* the gym industry — raising target energy 60→75 changes only 2 of the top 10 |
| Only 104 of 664 tracks are tagged `lunch` | Some industry groups have no lunch-time coverage; adding tracks cannot fix it |
| `warmth`, `sophistication`, `quality_score` filled on almost no tracks | Excluded from matching entirely |
| `suitable_weather` is `any` on every track | Excluded — no discriminating power |

Human QC (listening and marking `review: reject`) is **not** a blocking step by
product-owner decision — coverage was prioritised over polish. Rejected tracks are
filtered at load time, so QC can proceed incrementally.

---

### 9. Code you can delete when you switch to paid `apick`

Ordered by size of the win. This is the concrete payoff of the 55,000 KRW/month —
and, since the paid lookup was the original direction (**Part 0 §0.1**), this table
is a roadmap rather than a wish list. Treat everything in it as scaffolding: fix
bugs that block a demo, but do not refactor or extend it.

| Remove | Where | Lines | Why it exists |
|---|---|---|---|
| Candidate scoring | `kakao_local_service.score_candidates`, `pick_best` | ~54 | no address to filter by |
| Branch-name hint extraction | `kakao_local_service.extract_branch_hint`, `_sigungu` | ~44 | infer region from the store name |
| Name-only validation reweighting | `entity_validation_service` — the `has_addresses` branch | ~15 | no address to compare |
| `needs_input` two-step flow | `analyse.py` Step 4 branch + `NeedsInput` schema + the picker UI in `demo.html` | ~120 | user must disambiguate |
| Fuzzy name matching hardening | `kakao_local_service.name_score`, `_strip_type_affix` | ~46 | registered name ≠ sign name |

Keep regardless of vendor:

- Kakao trade-area counting (apick has no trade-area data)
- Google Places reviews and hours (apick has neither)
- The web-search hours/review supplement
- The whole music matching layer

> apick으로 바꾸면 위 5개 블록(약 280줄)과 후보 선택 화면이 전부 불필요해집니다.
> 반대로 상권·리뷰·영업시간·음원 로직은 벤더와 무관하게 그대로 필요합니다.

---

### 10. Re-verifying all of this

```bash
python scripts/check_keys.py            # 7 credentials, cause-specific hints
python scripts/smoke_all.py             # 17 end-to-end checks against real APIs
python scripts/trade_area_validate.py report   # accuracy from cache, 0 API calls
python -m pytest -q                     # 187 offline unit/regression tests
```

Expected: `check_keys` OK 9 / WARN 2 / FAIL 1 (NPS, unused); `smoke_all` PASS 17/17;
trade area 27/30 (90%); pytest 187 passed.

If `smoke_all` reports `1 skipped — upstream unavailable`, data.go.kr is down. That
is not a regression; see **Part I §7.1**.

---

## Part III: Korea domain primer

> 막힐 때 찾아보는 사전. / A dictionary; consult it when something looks arbitrary.

### 1. Business Registration Number (사업자등록번호)

The only thing this product asks the user to type. 10 digits.

```
  6 4 2   -   0 7   -   0 0 5 4 0
  └─┬─┘       └┬┘       └──┬───┘
    │          │           └── serial number, assigned in order
    │          └────────────── entity type code  ← the interesting part
    └───────────────────────── issuing tax office
```

#### The middle two digits decide everything

| Middle 2 digits | Meaning | Consequence for us |
|---|---|---|
| `81`–`88` | Corporation (법인) | **One number can own many branches** |
| anything else | Sole proprietor (개인사업자) | Usually one storefront |

This is not trivia — it is the reason the app has a store-picker screen.

> 중간 2자리가 `81`~`88`이면 법인입니다. 법인은 사업자번호 하나로 여러 지점을
> 운영할 수 있어서, 번호만으로는 어느 지점인지 특정할 수 없습니다.

Measured example in our demo set:

```
406-81-65194  →  "몸가짐휘트니스"   (81 = corporation)
                 ├── 몸가짐휘트니스 구의점      (Guui branch)
                 └── 몸가짐휘트니스 건대입구점   (Konkuk Univ. Stn. branch)
                 → the user must tell us which one is theirs
```

Contrast with a case that *looks* the same but is not:

```
274-06-01000  →  "피트니스월드"   (06 = sole proprietor)
                 Jung-gu store    ← this one belongs to this number
                 Jongno-gu store  ← a DIFFERENT owner's store with the SAME name
                 → also ambiguous, but for the opposite reason
```

Both end up on the picker screen, and the developer should understand they are
different problems. See **Part II §4**.

Code: `normalize_business_number()` in `app/services/nts_service.py` (digit checks),
`resolve_identity()` in `app/services/biz_lookup_service.py` (name resolution).

---

### 2. 법정동 vs 행정동 — Legal vs Administrative *dong*

**This is the single most confusing concept in Korean addressing.** It silently
broke our trade-area classification and took two wrong fixes before we found it.

A *dong* (동) is a neighbourhood. Korea maintains **two parallel dong systems**:

| | 법정동 (legal dong) | 행정동 (administrative dong) |
|---|---|---|
| Purpose | Property/legal records | Local government service districts |
| Changes | Almost never | Redrawn as population shifts |
| Appears in | Lot-number addresses (지번 주소) | Government statistics, community centres |
| Example | `이촌동` | `이촌1동`, `이촌2동` |

One legal dong can map to several administrative dong, and the names differ.

#### Why it broke us

```
Korea's trade-area statistics Excel  →  keyed by 행정동  (administrative)
Kakao's lot-number address           →  contains 법정동  (legal)
                                         ↓
                                    never matched
                                         ↓
                            fell back to province level ("Seoul")
                                         ↓
                       every store in Seoul got the same trade area
```

Two failed attempts before the real fix:

1. Used the **road-name address** (도로명 주소) — road addresses contain no dong at all.
2. Used the **lot-number address** — closer, but that is 법정동, still no match.

The working fix: convert coordinates → administrative dong via Kakao's
`coord2regioncode` endpoint and read the entry where `region_type == "H"`
(`H` = 행정동, `B` = 법정동).

```python
# app/services/kakao_local_service.py  →  region_from_coord()
# region_type "H" is 행정동; "B" is 법정동. The Excel is keyed by 행정동.
```

> 상권 엑셀은 행정동 기준이고 Kakao 지번 주소는 법정동입니다. 그래서 문자열로는
> 절대 매칭되지 않습니다. 좌표 → `coord2regioncode` → `region_type=="H"` 로 풀었습니다.

**Note:** the dong lookup is now only a *fallback*. The primary trade-area method
counts surrounding businesses within 500 m, which needs no dong at all and scored
90% vs the Excel's 37%. See **Part I §3**.

---

### 3. Registered name ≠ the name on the sign

The name on a business registration is a legal record. The name customers see may
differ, and Kakao/Google index the *customer-facing* name.

| Source | Value |
|---|---|
| bizno (registration) | `고아라헤어케어강남점` |
| Kakao (map listing) | `고아라헤어케어 강남점` ← space added |
| bizno | `아크로짐 홍대점` |
| Kakao | `아크로짐 홍대점24시휘트니스` ← extra words |
| bizno | `VA미용실` |
| Kakao | `VA헤어메이크업` ← completely different |

Consequences baked into the code:

- **Korean spacing is unreliable.** `헬카페스피리터스` vs `헬카페 스피리터스` scores
  0.94 on plain string similarity. We add a space-removed comparison.
- **Do not use `fuzz.partial_ratio`.** It gives a perfect score whenever one name
  is a substring of the other: `카페민` vs `마을카페민` = 1.00. We use
  `fuzz.ratio` + `token_sort_ratio`, which are length-sensitive.
- **Branch names are a free location hint.** `아크로짐 홍대점` → extract `홍대`
  and append it to the Kakao query. This is a workaround for bizno not giving an
  address (§ **Part II §2**).

Code: `name_score()`, `extract_branch_hint()` in `app/services/kakao_local_service.py`.

> 등록 상호와 간판 상호가 다릅니다. 공백 유무·부가 문구·전혀 다른 이름까지 나옵니다.
> `partial_ratio`는 부분 일치를 만점으로 줘서 오탐이 심하므로 쓰지 않습니다.

---

### 4. data.go.kr — the public data portal

`data.go.kr` is the Korean government's open-data portal. It hosts the NTS
business-status API and the weather API we use. Three things surprise newcomers.

#### 4.1 One key, per-API approval

You get **one** service key per account, but each API needs its own
"활용신청" (usage application) before that key works on it.

```
account
  └── one service key (DATA_GO_KR_API_KEY)
        ├── NTS business status        ← 활용신청 approved  → works
        ├── KMA weather                ← 활용신청 approved  → works
        └── National Pension (NPS)     ← not applied        → 403
```

A `403` on one endpoint while another works with the same key means *approval*,
not a bad key. Most datasets auto-approve immediately; some take a business day.

> 인증키는 계정당 1개인데 API별로 **활용신청**을 따로 해야 합니다. 같은 키로 A는
> 되고 B는 403이면 키 문제가 아니라 신청 문제입니다.

#### 4.2 Encoding key vs Decoding key ← costs everyone an hour

The portal shows the same key twice:

| Shown as | Looks like | Use it when |
|---|---|---|
| **Decoding** key | `abc+def/ghi==` | Your HTTP client URL-encodes params for you |
| Encoding key | `abc%2Bdef%2Fghi%3D%3D` | You build the query string by hand |

We pass keys through `httpx`'s `params=`, which URL-encodes automatically.
So we need the **Decoding** key. Using the Encoding key double-encodes
(`%2B` → `%252B`) and returns 401/403.

Measured 2026-08-04: Encoding key → NTS `401`, KMA `403`. Decoding key → both `200`.

Because this is so easy to get wrong, `app/config.py` detects it and self-corrects:

```python
# data.go.kr keys are base64 (A–Z a–z 0–9 + / =) so a '%' cannot be part of one.
# A '%' therefore proves it is the Encoding key → decode it, and warn loudly.
```

#### 4.3 Endpoints get versioned without notice

The National Pension API's old path returns `NO_OPENAPI_SERVICE_ERROR` — it is
retired. The live path is `NpsBplcInfoInqireServiceV2/getBassInfoSearchV2`.

Diagnostic trick: `SERVICE_KEY_IS_NOT_REGISTERED_ERROR` means *the path is alive
but you have not applied* — which is good news. `NO_OPENAPI_SERVICE_ERROR` means
*the path is dead*.

---

### 5. NTS business-status API — what it does and does not give

`api.odcloud.kr/api/nts-businessman/v1/status` — free, no per-call cost.

| Gives | Does **not** give |
|---|---|
| Trading status: 계속사업자 / 휴업자 / 폐업자 | Company name |
| Tax type (과세유형) | Address |
| Closure date (폐업일) | Industry |

**This is the crux of the whole architecture.** The government will confirm a
number is valid and active, but will not tell you the name of the business.
Company name is an *input* to government lookups, never an *output*. There is no
free public path from business number → company name, which is why we depend on
the commercial `bizno` API. See **Part II §2**.

We call NTS **first** and refuse closed businesses before spending any paid or
rate-limited quota downstream.

```
119-10-71114  →  폐업자, closure date 2018-06-14  →  stop, show a message
342-74-00017  →  폐업자, closure date 2022-04-28  →  stop, show a message
```

> 국세청은 "이 번호가 살아있는지"는 알려주지만 **상호명은 알려주지 않습니다.**
> 상호명은 조회의 입력값이지 출력값이 아닙니다. 그래서 민간 API(bizno)가 필요합니다.

---

### 6. Trade areas (상권) — the 8 categories and what replaced them

Korean commercial districts are conventionally described with labels like these.
They are marketing vocabulary, not an official taxonomy.

| Korean | English | Character |
|---|---|---|
| 오피스 밀집 상권 | Office-dense | Weekday lunch peak, dead weekends |
| 주거 밀집 상권 | Residential | Evening/weekend, low density |
| 대학가/유흥 상권 | University / nightlife | High energy, late night |
| 복합 오피스 상권 | Mixed office | Office plus residential |
| 관광특구 상권 | Tourist zone | Hotels, attractions, visitors |
| 트렌드/패션 상권 | Trend / fashion | Boutiques, high foot traffic |
| 학원가 특화 상권 | Cram-school district | Students, after-school peak |
| 지식산업센터 상권 | Knowledge-industry complex | Office towers, quiet |
| 카페·트렌드 상권 * | Cafe / trend | Cafe-dense, long dwell time |
| 복합 상권 * | Mixed / undifferentiated | No dominant character |

`*` = added by us for the surroundings-based classifier.

These feed `TRADE_AREA_PRIORS` in `app/services/ambience_service.py`: the trade
area contributes 20% of the Energy and Tempo scores and 15% of Mood.

**How we classify now.** Not by looking a dong up in a spreadsheet, but by
counting what is physically around the store — 8 Kakao category groups within
500 m, plus universities within 1 km:

```
cafe · restaurant · cram school · bank · lodging · attraction · hospital · convenience store
```

Ratios between these decide the label. Example output shown in the UI:

```
반경 500m 내 카페 18 · 음식점 96 · 학원 38 · 은행 10 · 숙박 0 · 병원 34
(Within 500 m: 18 cafes, 96 restaurants, 38 cram schools, 10 banks, 0 lodgings, 34 clinics)
```

The decisive signal turned out to be the university count — a university district
looks like nothing else. Accuracy on a 30-location benchmark: **90%** vs the
Excel's **37%**. Reproduce with:

```bash
python scripts/trade_area_validate.py report
```

> 상권 판정은 엑셀 조회가 아니라 **주변 업종 개수 비율**로 합니다. 좌표만 쓰기 때문에
> 업종과 무관하게 모든 사업자에 동일하게 작동합니다.

---

### 7. 통신판매업 신고 (E-commerce filing) — and the trap in that CSV

The folder `쇼핑사업자 추출2_260410/` holds public filings of businesses that
registered to sell online. We used it only as a **source of real business numbers
for testing**.

Two traps:

1. **A filing is not proof of trading.** Many entries are long closed — that is
   how we found our 폐업 test cases. Always call NTS before trusting a row.
2. **The listed name is the registered name**, so it carries all the problems in
   §3 above.

Do not treat this CSV as a customer list.

---

### 8. Weather — KMA 초단기실황 (ultra-short-term observation)

`getUltraSrtNcst` returns *current observed* values (not a forecast) on a grid.

- It needs **grid coordinates (nx, ny)**, not latitude/longitude. Conversion is
  the Lambert Conformal Conic projection in `lat_lng_to_grid()`
  (`app/services/weather_service.py`).
- Observations publish at **:40 past each hour**. Asking for the current hour
  before :40 returns empty, so we step back an hour.
- Weather contributes only **5%** of the ambience score and is deliberately *not*
  used to select tracks. It is in the demo because store owners find "it knows
  today's weather" convincing.

---

### 9. Glossary / 용어집

| Korean | English | One line |
|---|---|---|
| 사업자등록번호 | Business registration number | 10 digits; the only user input |
| 법인 / 개인사업자 | Corporation / sole proprietor | Middle 2 digits `81`–`88` = corporation |
| 상호명 | Trade name | The business's registered name |
| 업종 | Industry / business category | e.g. cafe, gym, salon |
| 폐업자 / 휴업자 / 계속사업자 | Closed / suspended / active | NTS trading status |
| 과세유형 | Tax type | VAT-general vs simplified |
| 법정동 | Legal dong | Property records; stable |
| 행정동 | Administrative dong | Service districts; redrawn |
| 도로명 주소 | Road-name address | Modern format, no dong |
| 지번 주소 | Lot-number address | Legacy format, contains 법정동 |
| 시군구 | City / county / district | Second address level, e.g. 강남구 |
| 상권 | Trade area / commercial district | Neighbourhood commercial character |
| 활용신청 | Usage application | Per-API approval on data.go.kr |
| 국세청 (NTS) | National Tax Service | Provides trading status |
| 기상청 (KMA) | Korea Meteorological Administration | Provides weather |
| 국민연금 (NPS) | National Pension Service | Would give employee counts; not enabled |
| 통신판매업 신고 | E-commerce business filing | Public list we mined for test numbers |
| 소상공인 | Small business owner / micro-merchant | The end customer |
| D2D | Door-to-door | The sales motion this demo supports |

---

### 10. Where each concept shows up in the code

| Concept | File | Function |
|---|---|---|
| Business number validation | `app/services/nts_service.py` | `normalize_business_number` |
| NTS status gate | `app/routers/analyse.py` | Step 2 |
| Company-name resolution chain | `app/services/biz_lookup_service.py` | `resolve_identity` |
| Registered vs sign name | `app/services/kakao_local_service.py` | `name_score`, `_strip_type_affix` |
| Branch-name hint | `app/services/kakao_local_service.py` | `extract_branch_hint` |
| Legal → administrative dong | `app/services/kakao_local_service.py` | `region_from_coord` |
| Surroundings trade area | `app/services/trade_area_service.py` | `classify_by_surroundings` |
| Trade-area priors | `app/services/ambience_service.py` | `TRADE_AREA_PRIORS` |
| data.go.kr key handling | `app/config.py` | `_get_service_key` |
| KMA grid conversion | `app/services/weather_service.py` | `lat_lng_to_grid` |

Note: `normalize_business_number` exists in **both** `nts_service.py` and
`biz_lookup_service.py` with identical bodies. That duplication is real; see
the cleanup list in **Part I §8**.
---

## Document history

| Date | Change |
|---|---|
| 2026-08-05 | Plan agreed (`HANDOVER_PLAN.md`) — three separate documents |
| 2026-08-06 | Parts written; `scripts/smoke_all.py` added as the factual basis |
| 2026-08-06 | **Part 0 added.** The reader needs the goal, the constraints, and the
reason each direction changed *before* opening the code. Part I §3 kept as the
module-by-module comparison; Part 0 carries the narrative. |
| 2026-08-06 | Reframed three items the earlier draft had presented as mistakes: the
screen-scraping was a **temporary implementation** under the same zero-budget
constraint; the free lookup API is a **deferred state**, not the target; and the
2-industry music scope was the **priority agreed with 엠금융**, not an oversight.
The UI section was removed from the direction list and marked a **placeholder**. |
| 2026-08-06 | **Merged into this single file.** Three documents describing one system
would inevitably drift, and the reader benefits from one entry point. If Part II
(API constraints) later starts changing far more often than the rest, split it
back out then — not before. |

세 문서를 한 파일로 합친 이유: 한 시스템을 설명하는 문서를 나눠 두면 반드시 어긋나고,
인수받는 사람에게는 입구가 하나인 편이 낫습니다. Part II 만 자주 바뀌기 시작하면
그때 다시 분리하면 됩니다.
