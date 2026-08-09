"""End-to-end smoke test against a running server.

Run this on day one to confirm the whole pipeline works, and after any change to
`app/routers/analyse.py` or the services it calls. It exercises the real APIs
(NTS, bizno, Kakao, Google Places, KMA, Groq), so it costs live quota.

    python -m uvicorn app.main:app --port 8077 --reload    # in one terminal
    python scripts/smoke_all.py                            # in another

    python scripts/smoke_all.py --json                     # machine-readable
    python scripts/smoke_all.py --base http://host:port
    python scripts/smoke_all.py --quick                    # skip R2 audio sweep (620 HEADs)

Exit code 0 = every case matched its expectation. Non-zero = something regressed.

Why an HTTP smoke test on top of `pytest`
-----------------------------------------
`pytest` covers pure functions with no network. It cannot catch: a wrong API key,
a dead upstream endpoint, a response-shape change, a broken cache key, or a
regression in how the router wires the ten steps together. Those are exactly the
failures that have bitten this project, so they need a live check.

계획서(HANDOVER_PLAN.md) 5장 참조.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402

DEFAULT_BASE = "http://127.0.0.1:8077"
MANIFEST = PROJECT_ROOT / "data" / "demo_tracks.json"


# --------------------------------------------------------------------- cases
#
# Every business number below is a REAL, verified Korean business. They are the
# demo set the product owner signed off on (계획서 §14). Keep them in sync.
#
#   kind   = what we expect the API to return
#            "ok"    → success, full analysis
#            "need"  → needs_input (user must disambiguate or type the name)
#            "error" → success=false with a user-facing message
#            "http"  → non-2xx HTTP status (request validation)

CASES: List[Dict[str, Any]] = [
    # ---- happy path: auto-confirmed stores across 3 industries -------------
    dict(id="cafe-1", bno="642-07-00540", kind="ok",
         note="헬카페스피리터스 (Yongsan) — cafe, 5 reviews",
         expect=dict(group="cafe", area_method="surroundings")),
    dict(id="cafe-2", bno="160-04-00498", kind="ok",
         note="송화의카페 (Gangdong) — cafe, auto-confirmed from 5 candidates",
         expect=dict(group="cafe", area_method="surroundings")),
    dict(id="gym-1", bno="871-76-00498", kind="ok",
         note="어게인짐 건대입구역점 (Gwangjin) — 24h gym, branch name in title",
         expect=dict(group="fitness", area_method="surroundings", time_label="24시간 영업")),
    dict(id="gym-2", bno="785-17-02465", kind="ok",
         note="아크로짐 홍대점 (Mapo) — 24h gym, single candidate",
         expect=dict(group="fitness", area_method="surroundings", time_label="24시간 영업")),
    dict(id="salon-1", bno="413-02-93000", kind="ok",
         note="고아라헤어케어강남점 (Gangnam) — salon, non-pilot industry",
         expect=dict(group="beauty", area_method="surroundings")),

    # ---- candidate disambiguation (the free-tier consequence) --------------
    dict(id="need-corp", bno="406-81-65194", kind="need",
         note="몸가짐휘트니스 — one CORPORATE number, two branches (81 = 법인)",
         expect=dict(reason="place_choice", min_candidates=2)),
    dict(id="need-corp-pick", bno="406-81-65194", kind="ok", place_id="2706591",
         note="  └ user picks 구의점 → full analysis",
         expect=dict(group="fitness")),
    dict(id="need-same", bno="274-06-01000", kind="need",
         note="피트니스월드 — identical name owned by a DIFFERENT business",
         expect=dict(reason="place_choice", min_candidates=2)),
    dict(id="need-same-pick", bno="274-06-01000", kind="ok", place_id="52087507",
         note="  └ user picks 중구 → full analysis",
         expect=dict(group="fitness")),
    dict(id="need-common", bno="119-08-33908", kind="need",
         note="가은약국 — common name, pharmacy (no music group exists)",
         expect=dict(reason="place_choice", min_candidates=2)),

    # ---- rejections and fallbacks -----------------------------------------
    dict(id="closed", bno="119-10-71114", kind="error",
         note="24시편의점 — closed in 2018, must be refused before spending quota",
         expect=dict(nts="폐업자")),
    dict(id="unregistered", bno="105-90-91949", kind="need",
         note="not registered with NTS and unknown to bizno → ask user for the name",
         expect=dict(reason="company_name")),
    dict(id="user-typed", bno="105-90-91949", kind="ok",
         company_name="헬카페스피리터스",
         note="  └ user types the name → pipeline recovers",
         expect=dict(group="cafe")),

    # ---- request validation ------------------------------------------------
    dict(id="too-short", bno="123456789", kind="http",
         note="9 digits — must be rejected by the API, not by the browser only",
         expect=dict(status_min=400)),
]


# --------------------------------------------------------------------- checks

def check_ok(data: Dict[str, Any], expect: Dict[str, Any]) -> List[str]:
    """Field-completeness checks for a successful analysis."""
    bad: List[str] = []
    bi = data.get("business_info") or {}
    ta = data.get("trade_area") or {}
    am = data.get("ambience") or {}
    tpo = data.get("tpo_profile") or {}
    mu = data.get("music") or {}
    tracks = mu.get("tracks") or []

    if not bi.get("company_name"):
        bad.append("company_name empty")
    if not bi.get("business_type"):
        bad.append("business_type empty")
    if not bi.get("address"):
        bad.append("address empty")
    if not ta.get("label"):
        bad.append("trade_area.label empty")
    if not (am.get("energy") or 0):
        bad.append("ambience.energy == 0")
    if not tpo.get("time_label"):
        bad.append("tpo.time_label empty")
    # This is the exact bug that shipped twice: raw Google text leaking into the label.
    if "요일" in (tpo.get("time_label") or ""):
        bad.append(f"tpo.time_label leaks raw text: {tpo['time_label']!r}")
    if len(tracks) != 10:
        bad.append(f"track count {len(tracks)} != 10")
    for t in tracks:
        if not (t.get("audio_url") or "").startswith("https://"):
            bad.append(f"track {t.get('track_id')} has no audio_url")
            break
    for t in tracks:
        if not t.get("reason"):
            bad.append(f"track {t.get('track_id')} has no reason text")
            break
    if not mu.get("playlist_label"):
        bad.append("playlist_label empty")

    want_group = expect.get("group")
    got_group = ((mu.get("target") or {}).get("industry_group"))
    if want_group and got_group != want_group:
        bad.append(f"industry_group {got_group!r} != {want_group!r}")
    if want_group and not mu.get("industry_matched"):
        bad.append("industry_matched is False despite a known group")

    want_method = expect.get("area_method")
    if want_method and ta.get("match_method") != want_method:
        bad.append(f"trade_area.match_method {ta.get('match_method')!r} != {want_method!r}")

    want_time = expect.get("time_label")
    if want_time and tpo.get("time_label") != want_time:
        bad.append(f"time_label {tpo.get('time_label')!r} != {want_time!r}")
    return bad


def check_need(data: Dict[str, Any], expect: Dict[str, Any]) -> List[str]:
    bad: List[str] = []
    ni = data.get("needs_input") or {}
    want = expect.get("reason")
    if want and ni.get("reason") != want:
        bad.append(f"needs_input.reason {ni.get('reason')!r} != {want!r}")
    if not ni.get("message"):
        bad.append("needs_input.message empty (nothing to show the user)")
    if not ni.get("fields"):
        bad.append("needs_input.fields empty (UI cannot know what to ask)")
    lo = expect.get("min_candidates")
    if lo:
        cands = ni.get("place_candidates") or []
        if len(cands) < lo:
            bad.append(f"place_candidates {len(cands)} < {lo}")
        for c in cands:
            if not c.get("place_id") or not c.get("place_name"):
                bad.append("a candidate is missing place_id/place_name")
                break
    return bad


def check_error(data: Dict[str, Any], expect: Dict[str, Any]) -> List[str]:
    bad: List[str] = []
    if not data.get("error"):
        bad.append("error message empty")
    if data.get("needs_input"):
        bad.append("both error and needs_input set — UI cannot decide which screen to show")
    want_nts = expect.get("nts")
    if want_nts and data.get("nts_status") != want_nts:
        bad.append(f"nts_status {data.get('nts_status')!r} != {want_nts!r}")
    return bad


def classify(status: int, data: Dict[str, Any]) -> str:
    if status >= 400:
        return "http"
    if data.get("needs_input"):
        return "need"
    if data.get("success") is False or data.get("error"):
        return "error"
    return "ok"


# --------------------------------------------------------------------- runner

def run_cases(base: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with httpx.Client(base_url=base, timeout=180) as client:
        for case in CASES:
            body: Dict[str, Any] = {"business_number": case["bno"]}
            if case.get("place_id"):
                body["place_id"] = case["place_id"]
            if case.get("company_name"):
                body["company_name"] = case["company_name"]

            t0 = time.time()
            try:
                resp = client.post("/api/analyse", json=body)
                status = resp.status_code
                data = resp.json() if resp.content else {}
            except Exception as exc:                       # noqa: BLE001
                out.append(dict(case=case, ok=False, elapsed=time.time() - t0,
                                got="exception", problems=[f"request failed: {exc}"],
                                summary=""))
                continue
            elapsed = time.time() - t0

            got = classify(status, data)
            problems: List[str] = []
            skipped = False

            # The closed-business guard depends on a live NTS lookup. data.go.kr
            # returns 503 often enough that a run during an outage would otherwise
            # look like a regression in our code. Degrading past an unreachable NTS
            # is deliberate — an outage there must not block every analysis — so
            # report this as SKIP, not FAIL.
            if (case["kind"] == "error"
                    and (case.get("expect") or {}).get("nts")
                    and data.get("nts_status") == "조회실패"):
                skipped = True
                problems = []

            if skipped:
                pass
            elif got != case["kind"]:
                problems.append(f"expected {case['kind']}, got {got}")
            elif got == "ok":
                problems = check_ok(data, case.get("expect") or {})
            elif got == "need":
                problems = check_need(data, case.get("expect") or {})
            elif got == "error":
                problems = check_error(data, case.get("expect") or {})
            elif got == "http":
                lo = (case.get("expect") or {}).get("status_min", 400)
                if status < lo:
                    problems.append(f"HTTP {status} < {lo}")

            out.append(dict(case=case, ok=not problems, elapsed=elapsed, got=got,
                            status=status, problems=problems, skipped=skipped,
                            summary=("SKIP (NTS 조회 불가 — upstream outage) " + summarize(got, data))
                                    if skipped else summarize(got, data)))
    return out


def summarize(got: str, data: Dict[str, Any]) -> str:
    if got == "ok":
        bi = data.get("business_info") or {}
        ta = data.get("trade_area") or {}
        am = data.get("ambience") or {}
        mu = data.get("music") or {}
        tg = mu.get("target") or {}
        return (f"{bi.get('company_name')} · {bi.get('business_type')} · {ta.get('label')} · "
                f"E{am.get('energy')}/T{am.get('tempo')}/M{am.get('mood')} · "
                f"{tg.get('industry_group')} {mu.get('pool_size')}곡→{len(mu.get('tracks') or [])}")
    if got == "need":
        ni = data.get("needs_input") or {}
        return f"{ni.get('reason')} · 후보 {len(ni.get('place_candidates') or [])}건"
    if got == "error":
        return f"{data.get('nts_status')} · {(data.get('error') or '')[:44]}"
    return f"HTTP {data.get('detail') or ''}"[:60]


def check_cache(base: str) -> Dict[str, Any]:
    """Two DIFFERENT stores that need disambiguation must not share a cache entry.

    The cache key is (digits, company_name, place_id). If the user's choice were
    left out of the key, picking 구의점 and then 건대입구점 on the same business
    number would return the first store's analysis for both — silently wrong.
    Timing alone cannot catch that, so compare the payloads instead.
    """
    bno = "406-81-65194"            # one corporate number, two real branches
    picks = [("2706591", "구의"), ("1170483808", "건대입구")]
    problems: List[str] = []
    names: List[str] = []
    with httpx.Client(base_url=base, timeout=180) as client:
        for place_id, expect_in_name in picks:
            d = client.post("/api/analyse",
                            json={"business_number": bno, "place_id": place_id}).json()
            addr = ((d.get("google_places") or {}).get("formatted_address")
                    or (d.get("business_info") or {}).get("address") or "")
            ta = (d.get("trade_area") or {}).get("label") or ""
            names.append(f"{place_id}→{addr[:22]} / {ta}")
            if not addr:
                problems.append(f"{place_id}: no address in response")

        # 2nd identical request must be byte-stable (deterministic playlist).
        a = client.post("/api/analyse", json={"business_number": bno,
                                             "place_id": picks[0][0]}).json()
        b = client.post("/api/analyse", json={"business_number": bno,
                                             "place_id": picks[0][0]}).json()
    ids_a = [t["track_id"] for t in (a.get("music") or {}).get("tracks") or []]
    ids_b = [t["track_id"] for t in (b.get("music") or {}).get("tracks") or []]
    if ids_a != ids_b:
        problems.append("playlist is not deterministic across identical requests")
    if len(set(names)) < 2:
        problems.append(f"both picks returned the same store — cache key ignores place_id: {names}")
    return dict(name="cache-key", ok=not problems, problems=problems,
                detail=" | ".join(names))


def check_manifest() -> Dict[str, Any]:
    """The music manifest must cover every industry group and carry no seasonal tracks."""
    problems: List[str] = []
    if not MANIFEST.exists():
        return dict(name="manifest", ok=False, problems=[f"missing {MANIFEST}"], detail="")
    from app.services import music_service as MS

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tracks = [t for t in data.get("tracks") or [] if t.get("review") != "reject"]
    counts = {g: 0 for g in MS.INDUSTRY_TOKENS}
    for t in tracks:
        for g in MS.track_groups(t):
            counts[g] = counts.get(g, 0) + 1
    thin = {g: n for g, n in counts.items() if n < MS.MIN_POOL_SIZE}
    if thin:
        problems.append(f"industry groups with too few tracks: {thin}")
    seasonal = [t["track_id"] for t in tracks
                if MS.is_seasonal_only(t.get("suitable_industries") or [])]
    if seasonal:
        problems.append(f"seasonal-only tracks present: {seasonal[:3]}")
    mapped = {tok for toks in MS.INDUSTRY_TOKENS.values() for tok in toks}
    unmapped = {tok for t in tracks for tok in (t.get("suitable_industries") or [])
                } - mapped - set(MS.SEASONAL_TOKENS)
    if unmapped:
        problems.append(f"unmapped industry tokens: {sorted(unmapped)}")
    return dict(name="manifest", ok=not problems, problems=problems,
                detail=f"{len(tracks)}곡 · {len(counts)}업종군 · 최소 풀 {min(counts.values())}")


def check_audio() -> Dict[str, Any]:
    """Every track in the manifest must actually be downloadable from R2."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    base = (data.get("audio_base") or "").rstrip("/")
    ext = data.get("audio_ext") or ".mp3"
    tracks = [t for t in data.get("tracks") or [] if t.get("review") != "reject"]

    async def sweep() -> List[str]:
        sem = asyncio.Semaphore(16)
        bad: List[str] = []
        async with httpx.AsyncClient(timeout=30) as client:
            async def one(t: Dict[str, Any]) -> None:
                async with sem:
                    try:
                        r = await client.head(f"{base}/{t['track_id']}{ext}")
                        if r.status_code != 200:
                            bad.append(f"{t['track_id']} → {r.status_code}")
                    except Exception as exc:               # noqa: BLE001
                        bad.append(f"{t['track_id']} → {exc}")
            await asyncio.gather(*(one(t) for t in tracks))
        return bad

    bad = asyncio.run(sweep())
    return dict(name="audio(R2)", ok=not bad,
                problems=[f"{len(bad)} unplayable: {bad[:5]}"] if bad else [],
                detail=f"{len(tracks) - len(bad)}/{len(tracks)} playable")


# --------------------------------------------------------------------- output

def print_report(results: List[Dict[str, Any]], extras: List[Dict[str, Any]]) -> None:
    print("=" * 108)
    print(f"{'':3}{'id':<17}{'kind':<7}{'sec':>6}  summary")
    print("-" * 108)
    for r in results:
        mark = "-- " if r.get("skipped") else ("OK " if r["ok"] else "XX ")
        print(f"{mark}{r['case']['id']:<17}{r['got']:<7}{r['elapsed']:>6.1f}  {r['summary'][:70]}")
        print(f"{'':3}{r['case']['note']}")
        for p in r["problems"]:
            print(f"{'':3}  !! {p}")
    print("-" * 108)
    for e in extras:
        print(f"{'OK ' if e['ok'] else 'XX '}{e['name']:<17}{'':<7}{'':>6}  {e['detail']}")
        for p in e["problems"]:
            print(f"{'':3}  !! {p}")
    print("=" * 108)
    n_fail = sum(1 for r in results if not r["ok"]) + sum(1 for e in extras if not e["ok"])
    n_skip = sum(1 for r in results if r.get("skipped"))
    total = len(results) + len(extras)
    tail = f" ({n_skip} skipped — upstream unavailable)" if n_skip else ""
    if n_fail:
        print(f"FAIL — {n_fail}/{total} checks failed{tail}")
    else:
        print(f"PASS — all {total - n_skip}/{total} checks matched expectations{tail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=DEFAULT_BASE, help="server base URL")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--quick", action="store_true", help="skip the 620-file R2 sweep")
    args = ap.parse_args()

    try:
        httpx.get(f"{args.base}/health", timeout=5)
    except Exception as exc:                               # noqa: BLE001
        print(f"서버에 연결할 수 없습니다 / cannot reach server at {args.base}: {exc}")
        print("먼저 실행 / start it first:  python -m uvicorn app.main:app --port 8077 --reload")
        return 2

    results = run_cases(args.base)
    extras = [check_manifest(), check_cache(args.base)]
    if not args.quick:
        extras.append(check_audio())

    if args.json:
        print(json.dumps(dict(
            cases=[dict(id=r["case"]["id"], bno=r["case"]["bno"], note=r["case"]["note"],
                        expected=r["case"]["kind"], got=r["got"], ok=r["ok"],
                        elapsed=round(r["elapsed"], 2), summary=r["summary"],
                        skipped=r.get("skipped", False),
                        problems=r["problems"]) for r in results],
            extras=extras,
        ), ensure_ascii=False, indent=2))
    else:
        print_report(results, extras)

    failed = sum(1 for r in results if not r["ok"]) + sum(1 for e in extras if not e["ok"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
