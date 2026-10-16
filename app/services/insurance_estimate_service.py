"""Insurance ESTIMATE lookup — find the analysed shop's LOCALDATA licence.

Backs `GET /api/insurance/estimate`, which `frontend/public/insurance.html`
calls for business numbers that are not in the curated lead table. LOCALDATA
has no business number, so the match is by address + name, never by number:

  1. candidates = licences in the same district at the same 지번 (lot) or
     도로명 (road) key — lot first, it is the better-filled field
  2. one shop often holds several licences at one address (a café: 휴게음식점 +
     즉석판매제조가공업 + 통신판매업) — same cleaned name = one business; the page
     judges every licence of that business and keeps the strongest verdict
  3. the best business must clear NAME_THRESHOLD; a tie within TIE_MARGIN, or
     a building whose names all fail, is returned as candidates, never picked
  4. the Kakao storefront address first, then the registered (APICK) address —
     registered first when the two are in different districts
  5. nothing at any address -> exact cleaned-name hits in the district, flagged
     `addressMatched: false` (a same-name licence elsewhere is not confirmed)

The verdict is computed by the page (rules v2 + per-type rules); this service
only returns facts. Data: schema `estimate`, loaded by
devFS/scripts/load_insurance_estimate.py. Reference rows (regions, types) are
joined by label in every query — never cached by id — so a reload that
renumbers them cannot mislabel a running API's answers.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from ..config import get_settings
from ..utils.licence_keys import (
    NAME_THRESHOLD,
    TIE_MARGIN,
    clean_name,
    lot_key,
    name_score,
    owns_policy,
    region_aliases,
    road_key,
    split_region,
)
from ..utils.logging import get_logger

logger = get_logger(__name__)

_SELECT = (
    "SELECT l.name, l.road_tail, l.lot_tail, l.area, l.multi_use, l.type_id, l.class, l.licence_date, "
    "l.is_gym, l.basement, l.policy, l.lic_ins, l.road_key, l.lot_key, l.name_key, "
    "r.label AS region_label, t.slug, t.name_ko, t.name_en, t.family, t.rule, t.as_of "
    "FROM estimate.licences l "
    "JOIN estimate.regions r ON r.id = l.region_id "
    "JOIN estimate.types t ON t.id = l.type_id "
)


class EstimateUnavailable(RuntimeError):
    """The estimate database is not configured, unreachable or not loaded."""


def _db_errors() -> tuple[type[BaseException], ...]:
    try:
        import asyncpg

        return (OSError, asyncio.TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError)
    except ImportError:
        return (OSError, asyncio.TimeoutError)


class _Pool:
    """Lazily opened asyncpg pool, one per process."""

    def __init__(self) -> None:
        self._pool = None
        self._lock = asyncio.Lock()

    async def get(self):
        if self._pool is not None:
            return self._pool
        dsn = get_settings().insurance_database_url
        if not dsn:
            raise EstimateUnavailable("INSURANCE_DATABASE_URL is not set")
        async with self._lock:
            if self._pool is None:
                import asyncpg  # imported here so the music API boots without it

                try:
                    self._pool = await asyncpg.create_pool(dsn, min_size=0, max_size=4, command_timeout=10)
                except _db_errors() as exc:
                    raise EstimateUnavailable(type(exc).__name__) from exc
                logger.info("insurance estimate DB pool ready")
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


pool = _Pool()


def _type_of(rec) -> dict[str, Any]:
    return {
        "slug": rec["slug"], "ko": rec["name_ko"], "en": rec["name_en"], "family": rec["family"],
        "rule": json.loads(rec["rule"]) if rec["rule"] else None,
        "asOf": rec["as_of"].isoformat() if rec["as_of"] else None,
    }


def _policy(rec) -> list[Any] | None:
    """[own, holder, start, end, n_at_address]. `own` is re-decided here with the
    strict owns_policy() — the build's flag used the looser matching gate."""
    if not rec["policy"]:
        return None
    pol = json.loads(rec["policy"])
    pol[0] = 1 if owns_policy(rec["name"], pol[1]) else 0
    return pol


def _row(rec) -> list[Any]:
    """The page's v2 row: [name, roadTail, lotTail, area, multiUse, typeIdx, class,
    licenceDate, isGym, basement, policy20682, licenceInsurance]."""
    return [
        # `real` comes back as 69.36000061…; the licence value has two decimals.
        rec["name"], rec["road_tail"] or "", rec["lot_tail"] or "",
        round(rec["area"], 2) if rec["area"] is not None else None, 1 if rec["multi_use"] else 0,
        rec["type_id"], rec["class"] or "", rec["licence_date"].isoformat() if rec["licence_date"] else None,
        1 if rec["is_gym"] else 0, 1 if rec["basement"] else 0,
        _policy(rec),
        json.loads(rec["lic_ins"]) if rec["lic_ins"] else None,
    ]


def _type_rank(rec) -> int:
    """Server-side display order only — the page re-ranks by verdict strength."""
    if rec["family"] == "food":
        return 0
    if rec["family"] == "gym":
        return 1
    if rec["rule"]:
        return 2
    return 3 if rec["multi_use"] else 4


def pick(cands: list[tuple[str, Any]], names: list[str]) -> dict[str, Any]:
    """Name gate over address candidates. cands = [(method, record), ...]."""
    scored = sorted(
        ((max(name_score(n, rec["name"]) for n in names), method, rec) for method, rec in cands),
        key=lambda t: -t[0],
    )
    groups: dict[str, dict[str, Any]] = {}
    for score, method, rec in scored:
        g = groups.setdefault(clean_name(rec["name"]), {"score": score, "method": method, "recs": []})
        g["recs"].append(rec)
    ranked = list(groups.values())
    best = ranked[0]
    listing = [{"name": g["recs"][0]["name"], "score": round(g["score"], 2)} for g in ranked[:5]]
    if best["score"] < NAME_THRESHOLD:
        return {"status": "building_only", "candidates": listing}
    if len(ranked) > 1 and ranked[1]["score"] >= NAME_THRESHOLD and best["score"] - ranked[1]["score"] < TIE_MARGIN:
        return {"status": "ambiguous", "candidates": listing}
    return {"status": "matched", "method": best["method"], "score": round(best["score"], 2),
            "recs": sorted(best["recs"], key=_type_rank)}


def by_premises(recs: list[Any]) -> dict[str, Any]:
    """Name-only hits grouped by premises, so one shop's several licences count once."""
    premises: dict[str, list[Any]] = {}
    for i, rec in enumerate(recs):
        premises.setdefault(rec["road_key"] or rec["lot_key"] or f"#{i}", []).append(rec)
    if len(premises) == 1:
        return {"status": "matched", "method": "name", "score": 1.0,
                "recs": sorted(next(iter(premises.values())), key=_type_rank)}
    if premises:
        return {"status": "ambiguous", "method": "name", "candidates": [
            {"name": g[0]["name"], "addr": g[0]["road_tail"] or g[0]["lot_tail"]} for g in list(premises.values())[:5]]}
    return {"status": "unmatched"}


async def _match_at(conn, labels: list[str], lk: str | None, rk: str | None, names: list[str]) -> dict[str, Any]:
    """Address candidates (lot or road key) in the district(s), then the name gate."""
    if not (lk or rk):
        return {"status": "unmatched"}
    rows = await conn.fetch(
        _SELECT + "WHERE r.label = ANY($1::text[]) AND "
        "((l.lot_key = $2 AND $2 IS NOT NULL) OR (l.road_key = $3 AND $3 IS NOT NULL))",
        labels, lk, rk)
    if not rows:
        return {"status": "unmatched"}
    return pick([("lot" if lk and r["lot_key"] == lk else "road", r) for r in rows], names)


async def estimate(*, name: str = "", place: str = "", addr: str = "", jibun: str = "", gu: str = "",
                   reg: str = "") -> dict[str, Any]:
    """addr/jibun = the Kakao storefront the music analysis used; reg = the
    registered address (APICK). Raises EstimateUnavailable on any DB problem."""
    names = [n for n in (name, place) if n and clean_name(n)]
    if not names:
        return {"status": "unmatched", "reason": "no_name"}
    road_region, road_tail = split_region(addr)
    lot_region, lot_tail = split_region(jibun)
    gu_region, _ = split_region(f"{gu} _" if gu else "")
    reg_region, reg_tail = split_region(reg) if reg else (None, None)
    region = road_region or lot_region or gu_region or reg_region
    if not region:
        return {"status": "no_district"}

    kakao = (region, lot_key(lot_tail), road_key(road_tail), None)
    registered = (reg_region, lot_key(reg_tail), road_key(reg_tail), "registered")
    # Same district: the Kakao storefront first (the premises the owner picked).
    # Different district: the registered address first — it belongs to the
    # business number, and Kakao then picked a same-name shop elsewhere.
    order = [registered, kakao] if reg_region and reg_region != region else [kakao, registered]

    db = await pool.get()
    try:
        async with db.acquire(timeout=10) as conn:
            res: dict[str, Any] = {"status": "unmatched"}
            for label, lk, rk, how in order:
                if not label:
                    continue
                attempt = await _match_at(conn, region_aliases(label), lk, rk, names)
                if attempt["status"] == "matched":
                    res = {**attempt, "method": how or attempt["method"]}
                    break
                if res["status"] == "unmatched":
                    res = attempt          # keep the first informative failure (candidates)
            if res["status"] == "unmatched":
                hits = await conn.fetch(
                    _SELECT + "WHERE r.label = ANY($1::text[]) AND l.name_key = ANY($2::text[])",
                    region_aliases(region), list({clean_name(n) for n in names}))
                res = by_premises(list(hits))
                if res["status"] == "matched":
                    # Same name somewhere in the district, but not at the analysed
                    # address — the page must not present it as the same shop.
                    res["addressMatched"] = False
            meta = {r["key"]: r["value"] for r in await conn.fetch("SELECT key, value FROM estimate.meta")}
    except _db_errors() as exc:
        raise EstimateUnavailable(type(exc).__name__) from exc

    out = {k: v for k, v in res.items() if k != "recs"}
    types: dict[int, dict[str, Any]] = {}
    if res.get("recs"):
        recs = res["recs"]
        out["row"] = _row(recs[0])
        out["others"] = [_row(r) for r in recs[1:]]
        types = {r["type_id"]: _type_of(r) for r in recs}
        region = recs[0]["region_label"]
    out.update({
        "region": region,
        "asOf": {"localdata": meta.get("localdata_as_of"), "policy20682": meta.get("policy20682_as_of")},
        "types": types,
    })
    return out
