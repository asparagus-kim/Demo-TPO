# Claude implementation prompt

Copy the text below into Claude in the Yieldus workspace. This is a prepared implementation request; no implementation was performed while writing it.

```text
Improve blog-search relevance in /Users/mac/Desktop/yieldus/yielda_tpo_demo.

Read /Users/mac/Desktop/yieldus/AGENTS.md and applicable local instructions, then:
- /Users/mac/Desktop/yieldus/context.md
- yielda_tpo_demo/BLOG_SEARCH_IMPROVEMENT_PLAN.md (the implementation plan)
- The “Review link repair” and “Blog search relevance improvement” sections in yielda_tpo_demo/TPO_시연페이지_구현계획.md.

First verify branch/status/worktrees, task ownership, services/ports, and current source. The backend is expected on feat/kakao-blog-storefront-scoring; frontend/ is an independent Git repository on master. Both contain substantial uncommitted work. Preserve it, including the DuckDuckGo direct-link fixes and the expanded review-card list. Do not switch/reset/stash either checkout or overwrite changes. Use an isolated worktree if ownership requires it, but preserve the actual uncommitted feature baseline rather than starting from the older commit alone.

Outcome: display and score distinct blog posts plausibly describing the selected store. Prefer zero verified matches to unrelated reviews. The supplied live case is 309-30-71165; do not hardcode its store details, results, or expected count.

Implement the referenced plan in phases, with test-first regression cases and a short progress update at meaningful checkpoints:
1. Build canonical store/branch/locality context and at most three review-query templates. Use validated registered-name aliases conservatively. Never invent locality or change the selected store based on blog results. Reject contradictory or insufficient identity for blog search.
2. Keep the existing conditional search trigger. Try configured Kakao Blog, SerpAPI, Google CSE, and DuckDuckGo in bounded ordered passes. General search queries must be blog-site scoped. Enforce the plan's shared existing deadline and 8-total-HTTP-attempt cap, including retries/redirects and hours recovery; no uncapped nested provider loop. A rejected-only batch must continue fallback.
3. Run every provider/cache result through the same review acceptance policy: safe direct post URL, supported exact host/post shape, brand plus locality/branch match, anti-spam checks, contextual review text, and canonical post deduplication. Count and score accepted unique items only. Preserve destination query parameters: HTML-decode HTML-origin hrefs only, never JSON URLs or an already-extracted destination. Preserve frontend normalization idempotence.
4. Keep hours-only evidence separate internally so directories may supply verified hours without becoming reviews or blog scores. Version search/assembled-analysis caches, preserve or correctly update /api/reanalyse invalidation, and keep current public response contracts. Existing browser-saved analysis requires fresh analysis for relevance changes; do not add an incidental data migration.
5. Preserve pure-Python blog scoring and current Google review behavior. No new provider, key, dependency, external LLM call on blog text, full-post crawler, persistent snippet store, or UI redesign. Keep safe aggregate diagnostics in existing debug data.

Read these implementation files and their callers:
- app/services/web_search_service.py
- app/services/blog_scoring_service.py
- app/routers/analyse.py
- app/schemas.py, app/config.py, app/utils/cache.py
- frontend/src/components/yielda/result-view.tsx
- frontend/src/lib/review-links.ts and frontend/src/lib/analysis-store.tsx
- tests/test_web_search_links.py, tests/test_web_fallback_budget.py,
  tests/test_blog_scoring.py, tests/test_hours_and_cap.py,
  tests/test_pipeline_pure.py, tests/test_schemas.py,
  frontend/tests/review-links.test.mjs

Verify wrong-city/branch rejection, conservative aliases, missing identity, correct locality extraction, directory/profile/spam rejection, mobile/desktop/PostView deduplication, safe query preservation, fallback after rejected results, timeout/cancellation/retry/redirect caps, hours-only isolation, versioned caches and reanalysis, counts/provenance/scoring, and the existing link fixes. Use synthetic offline fixtures and no secrets/raw private payloads in evidence.

Run the plan's backend/new regression tests, frontend link tests, build, and focused lint. Recheck the actual running app before claiming UI success; reuse authorized services rather than starting duplicates. Freshly analyze 309-30-71165, inspect accepted sources/counts, and click an accepted article if any. Zero accepted blogs is valid; explain it. Surface upstream store-resolution conflicts separately instead of repairing them in this scope.

Obtain independent review for false positives, cache bypass, deadline/request leaks, URL corruption, and preservation of existing work. Fix findings and rerun affected checks. If a required check is unavailable, keep it pending and report why.

Update the existing task record and root context. Summarize behavior changed, tests/browser evidence, review, and remaining limits in English. Do not claim deployed/merged status. No commit, push, merge, deployment, external message, or destructive cleanup without separate authorization. If the plan requires materially broader product behavior or a public contract change, present the concrete deviation for approval before doing it.
```
