# TPO demo - insurance consult "completed" screen

File: `insurance.html` (single file, no build step, no external deps). All links are site-root relative
(`/`, `/stream`, `/Paperlogy-1.001/*.ttf`) - opening the file locally shows them as C:\ paths; on the site they resolve normally.

Design = the analysis-result screen of yielda-tpo-demo reproduced from its live CSS/DOM.
If anything conflicts with the existing component system, unify with the existing design.

## IMPORTANT - deployed screen has NO scenario switcher
- On the site there is no pill / toggle UI. On every page load one of three outcome types is picked at random
  (대상·미가입 / 대상·만기 임박 / 비대상) and dummy values are rolled inside that type's range.
- The pill bar that appears when you open the file locally (file://) or add `?preview=1` is a PREVIEW aid only,
  so reviewers can see all three outcomes. It must not show on the deployed URL (it is hidden by default).

## Real values vs dummy values
REAL (must come from the current analyse response, never randomised):
  name <- store_name, bno <- biz_no, addr <- address, gu <- region_address, cat <- category, consistency <- consistency_score
  Inject via `window.__YIELDA_STORE__ = {name,bno,addr,gu,cat,consistency}` before the script, or query string
  `/insurance.html?name=..&bno=..&addr=..&gu=..&cat=..&consistency=..`.

DUMMY (random per page load): area, multi(다중이용업소), listed, insured/만기, open(개업일).
  Verdict text is computed by `judge()` (rules v2). "지하" in addr switches the threshold to 66 m2.
  Fixed dummies: applicant (홍길동 · 010-0000-0000 · 오후 2-5시 · 사업장 보험), progress bars; 신청 시각 = now.

## Wiring
1. Put the file in `public/` -> `/insurance.html`.
2. `/stream` left sidebar: add a card below "매장 분석 리포트" (same `rounded-lg bg-card p-5` pattern)
   title 사업장 보험 상담 / button **보험 상담 신청** (same variant as [리포트 보기]) -> navigate here with the
   analysed store's real values in the query string (plain navigation, not React Router).
3. [추천 플레이리스트 재생] -> `/stream`, [분석 결과로 돌아가기] -> `/`.

Demo only - legal review not applied.
