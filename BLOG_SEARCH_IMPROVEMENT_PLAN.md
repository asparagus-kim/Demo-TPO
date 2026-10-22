# Blog search relevance improvement plan

Date: 2026-10-21 (Asia/Seoul).
Proposal requested by the user; implementation has not started. The task status belongs in `TPO_시연페이지_구현계획.md`, under “Blog search relevance improvement”.

## Intended result

The result page should display distinct blog posts that plausibly describe the selected store. Business directories, unrelated branches, duplicate post URLs, and opening-hours-only pages must not inflate the review count or ambience scoring.

Precision takes priority over quantity. Zero accepted blogs is a valid result. Snippet matching is a heuristic, not proof of an authentic customer visit.

## Current implementation and observed gaps

- `app/routers/analyse.py` searches when usable Google reviews are unavailable or a consistently matched Google place has no hours. Preserve this trigger.
- `app/services/web_search_service.py` joins company name, industry, and address; Kakao Blog then tries shorter brand/branch/locality variants. Configured providers run in the order Kakao Blog, SerpAPI, Google CSE, DuckDuckGo.
- Only Kakao currently runs the storefront/spam/geographic filters in `app/services/blog_scoring_service.py`. Other providers can return business directories and unrelated pages.
- A nonempty response can end fallback before relevance has been established. Cached results can bypass later improvements.
- Mobile, desktop, and `PostView` URLs for the same Naver article can become separate cards and separate scoring inputs.
- Query locality extraction currently uses loose regexes over combined text; address fragments such as `구천면로` can be mistaken for administrative names. Extract from structured address tokens instead.
- The user-supplied case `309-30-71165` previously showed directory entries and two URL forms of the same Naver article. The redirect/link repair is already implemented and must be preserved.

## Scope and constraints

In scope: query construction, provider-independent blog acceptance, post deduplication, separate hours handling, cache correctness, and accurate existing evidence counts.

Out of scope: changing store resolution, always searching for blogs, adding providers/API keys/dependencies, downloading full posts, changing Google review scoring, redesigning the UI, deployment, or asserting legal/API-policy compliance.

Preserve pure-Python blog scoring, the existing result-card link safeguards, and the “show all remaining reviews” fix. Do not send blog snippets to an external LLM or add persistent snippet storage.

The backend checkout is on `feat/kakao-blog-storefront-scoring` at `7a6200c` plus uncommitted work. `frontend/` is a separate repository on `master` at `ddcf40c` plus uncommitted work. Recheck ownership, instructions, branches, worktrees, services, and diffs before edits; never replace this work with a clean checkout.

## Phase 1 — Establish the search context and regression fixtures

1. Read the callers and existing tests before editing. Record baseline results separately from changes introduced by this task.
2. Build a small internal search context containing the selected Kakao place ID, storefront name, branch, road address, administrative address, normalized locality tokens, and an optional validated registered-name alias.
3. Use a registered-name alias only when existing resolved store information supports it. A shared word in two names is insufficient. Blog results must never select or replace the canonical store.
4. If the store identity is contradictory or neither a branch nor reliable local address is available, return no blog reviews with a diagnostic reason. Do not invent locality or silently search a generic brand nationwide. Existing Google reviews and the rest of the analysis can continue.
5. Add synthetic fixtures for a correct post, another branch/city, corporate naming, directories, spam, duplicated Naver URL forms, and conflicting store identity. Keep provider HTML/JSON samples minimal and synthetic.

Acceptance: fixtures reproduce the current fallback contamination and duplicate-post behavior before the change; existing link tests still pass.

## Phase 2 — Build bounded, purposeful queries

Create at most **three distinct review-query templates** from the context. They are reused across providers, not regenerated recursively:

1. Canonical storefront name + explicit branch when present + strongest reliable locality.
2. Normalized brand + strongest locality + `후기`.
3. Validated registered-name alias + locality + `후기`; if there is no useful distinct alias, use a different reliable locality token, otherwise omit this template.

For example, with independently confirmed context `언니커피 / 강동구 / 암사동`, candidate strings could be `언니커피 암사동`, `언니커피 암사동 후기`, and `언니커피 강동구 후기`. This is an illustration, not a claim that the current place resolver has confirmed those fields for the user's case.

Kakao receives normal blog-search text. For general search providers, issue separate site-scoped searches for `site:blog.naver.com` and `site:tistory.com` as budget permits; each site query consumes its own request. Do not assume an engine honors a site restriction: validate every returned URL. Do not include business registration numbers in review queries.

Use one overall deadline from the existing `WEB_FALLBACK_BUDGET_SEC` setting (code default: 4 seconds); do not increase it. One shared counter allows at most **8 outbound search HTTP attempts**, including retries and redirect hops, across reviews and hours. The deadline can stop work earlier.

- When hours recovery is requested, reserve up to 2 of those attempts for hours; review search can use at most 6. If hours are already recovered from accepted evidence, no separate hours request is necessary.
- First pass: at most one most-specific review query per configured provider, in the existing order. If no provider has accepted results and budget remains, try later query templates in ordered passes. A site variant consumes a request in the same budget.
- Stop at the first provider batch containing accepted, deduplicated posts. A batch containing only rejected posts must continue fallback.
- Do not automatically retry before other configured providers have had their first opportunity. Optional retries consume the same remaining budget; they are never guaranteed.
- Bound each request by the remaining deadline. Count actual sends, including automatic redirects, or follow bounded redirects explicitly. Never forward an API credential to a different origin. Keep these changes local to search requests rather than altering all shared HTTP clients.
- Preserve completed accepted reviews if the later hours lookup times out. Cancel remaining search work and issue no new request after timeout/cap exhaustion.

Acceptance: captured requests prove correct query locality/site scope, deterministic ordering, no business number, no budget bypass through retries/redirects, and continuation after rejected-only responses.

## Phase 3 — Apply one acceptance pipeline to every provider

Every provider result, including cache reads, must pass the same review-specific checks:

1. Normalize the link while preserving destination query bytes. HTML-decode only HTML-origin hrefs; JSON API URLs are already URLs. Preserve the existing DuckDuckGo extraction and frontend normalization idempotence tests.
2. Require HTTP(S), an exact supported hostname, and a recognized post URL shape. Initial review platforms: `blog.naver.com`, `m.blog.naver.com`, and actual subdomains of `tistory.com`. Reject spoofed suffixes, profiles, category/search/list pages, directories, missing destinations, and unsafe schemes.
3. Reject listing/recruitment/franchise-sale content; require a meaningful complete brand or validated alias match plus reliable local/branch evidence. Do not accept a generic single brand token. An explicit conflicting branch must not pass merely because the target neighborhood is mentioned incidentally. Conflicting cities need reliable address evidence rather than substring guessing.
4. Require useful post text with contextual evidence of a visit or store experience; a page containing only company registration/address/hours metadata is insufficient. Avoid requiring the literal word `후기` in every accepted snippet. Centralize and test these deterministic heuristics; record uncertainty.
5. Deduplicate before truncation, counting, or scoring. For Naver, use `(blogId, logNo)` across mobile/desktop/`PostView.nhn`/`PostView.naver` forms. For Tistory, deduplicate equivalent host/post paths; do not assume a numeric path and an unrelated slug refer to the same article. Strip only known tracking data for identity comparison, never arbitrary query parameters from the link users open.
6. Retain the first accepted safe destination URL and use deterministic ranking: exact storefront/branch/locality before broader accepted matches. Return at most the existing `DEFAULT_MAX_RESULTS` (12), without padding.

Keep search-provider identity distinct from publisher identity in internal diagnostics. A Naver post discovered through DuckDuckGo is still a Naver post in the UI, while diagnostics can identify DuckDuckGo as the search provider.

Acceptance: all configured providers reject the same irrelevant fixtures; one Naver article produces one card and one blog score; safe query parameters remain unchanged through backend and frontend.

## Phase 4 — Keep hours separate and make caches coherent

- Maintain the current public response shape unless a necessary contract change is explicitly approved. Keep review candidates and hours-only candidates separate internally.
- A directory or other metadata page can help recover hours only after store/location verification. Its text must never enter `web_evidence`, review counts, keyword extraction, or blog scoring merely because it contains hours.
- If a snippet qualifies as a review and contains hours, it can serve both purposes. Keep existing hours provenance accurate; do not imply that a directory's hours are Google-provided.
- Version the search acceptance policy in search cache keys. Include canonical place/name/locality, purpose (`reviews` or `hours`), provider, query plan, and result limit so different stores/purposes cannot reuse incompatible results. Cache only accepted results and recheck them at the boundary.
- Version or otherwise invalidate the assembled analysis cache too. Preserve the `analyse:{digits}:` prefix or update `/api/reanalyse` invalidation and its tests together.
- Old browser `sessionStorage` analysis is not automatically reclassified by a server cache change. For this scope, require a fresh analysis of saved results and state that clearly; preserve the already-fixed saved-link handling. Do not add a browser data migration incidentally.
- Derive counts, text source, and scoring from accepted unique evidence only. Zero blogs must not produce a positive blog-review count or misleading “mixed” provenance. Short Google reviews follow the existing display/scoring rules.
- Expose only safe aggregate diagnostics through the existing debug structure: policy version, attempted/selected provider, candidate/accepted/duplicate counts, rejection reasons, elapsed time, and timeout/cap status. Do not expose keys, auth headers, provider URLs containing credentials, or raw response dumps.

Acceptance: review/hour cache entries cannot cross-contaminate; reanalysis refreshes the relevant assembled result; hours-only evidence creates zero blog cards/scores; existing frontend types continue to build.

## Phase 5 — Verify behavior and obtain independent review

Required offline cases:

- Right store; same brand in another city/branch; legal-name alias; missing/conflicting identity; road-name substrings mistaken for neighborhood names.
- Directory and spam rejection; blog homepage/list/category rejection; spoofed host and unsafe URL rejection; genuine visit text without the word `후기`.
- Naver mobile/desktop/`PostView` deduplication; destination query preservation and idempotence; duplicate elimination before result limits and scoring.
- Kakao empty/rejected-only/error followed by valid general-provider results; valid first provider stops fallback; configured-provider absence is skipped cleanly.
- Timeout, cancellation, redirect/retry accounting, request-cap exhaustion, and accepted review preservation when hours recovery times out. Use fake transport/time or controlled async fixtures rather than live API dependencies.
- Separate review/hour caches; canonical identity separation; policy version migration; `/api/reanalyse`; correct empty/mixed provenance and score counts.

Run the existing relevant tests plus new cases; do not replace old coverage. Baseline commands:

```bash
# Backend: use the verified project Python environment, not an arbitrary python3.
python -m pytest -q tests/test_web_search_links.py tests/test_web_fallback_budget.py tests/test_blog_scoring.py tests/test_hours_and_cap.py tests/test_pipeline_pure.py tests/test_schemas.py
# Also run every newly added query/provider/cache/integration test.

# From frontend/:
node --experimental-strip-types --test tests/review-links.test.mjs
npm run build
# Run focused ESLint on any touched frontend TS/TSX files.
```

Test the running UI with the supplied case `309-30-71165`, after fresh analysis, plus a synthetic wrong-branch scenario. Verify queries use the actual resolved context; every displayed blog card has an accepted unique post URL; counts match cards/scoring; the original article opens directly. Live availability may produce fewer or zero blogs: report the reason instead of promising a fixed count or changing filters to pass the example. Never silently fix an upstream store-identity mismatch under this task.

Request an independent review focused on false-positive matches, cache bypass, budget leaks, double decoding, and preservation of existing uncommitted work. Fix findings and rerun affected checks. Record exact commands/results; live behavior, tests, and review are separate evidence.

## Phase 6 — Handoff and rollback

Update the existing task record and root context with files changed, branches, test results, actual browser results, unresolved limits, and the next action. Report implementation, local verification, and review separately from merge/deployment.

Do not commit, push, merge, deploy, send messages, or stop another session's processes without the applicable authorization. For rollback, revert only this task's recorded patch; retain the earlier redirect fix, card expansion fix, and other user changes. Never use a checkout-wide reset or clear unrelated caches.
