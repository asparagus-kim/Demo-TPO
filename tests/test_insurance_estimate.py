"""Insurance estimate lookup — pure logic + estimate() against a fake database."""
from __future__ import annotations

import asyncio

import pytest

from app.services import insurance_estimate_service as svc
from app.services.insurance_estimate_service import by_premises, pick
from app.utils.licence_keys import (
    clean_name,
    lot_key,
    name_score,
    owns_policy,
    region_aliases,
    road_key,
    split_region,
)


@pytest.mark.parametrize("addr, region, tail", [
    ("서울 관악구 신림로67길 4", "서울 관악구", "신림로67길 4"),
    ("서울특별시 관악구 신림로67길 4, 1층 (신림동)", "서울 관악구", "신림로67길 4, 1층 (신림동)"),
    ("전남광주통합특별시 목포시 석현로25번길 20-9", "전남광주 목포시", "석현로25번길 20-9"),
    ("광주 광산구 첨단중앙로 1", "전남광주 광산구", "첨단중앙로 1"),
    ("세종특별자치시 한누리대로 2130", "세종", "한누리대로 2130"),
    ("Seoul Gwanak-gu", None, None),
    ("", None, None),
])
def test_split_region(addr, region, tail):
    assert split_region(addr) == (region, tail)


@pytest.mark.parametrize("tail, key", [
    ("신림로67길 4, 1층 (신림동)", "신림로67길 4"),
    ("홍성읍 남장리 남장중로 10", "남장중로 10"),       # 20682 injects the 법정동
    ("와우산로29가길 13-1 (서교동)", "와우산로29가길 13-1"),
    ("능동", None),
])
def test_road_key(tail, key):
    assert road_key(tail) == key


@pytest.mark.parametrize("tail, key", [
    ("신림동 1422-5 2층", "신림동 1422-5"),
    ("양평동3가 12", "양평동3가 12"),                  # not ('양평동', '3')
    ("외동읍 입실리 123", "외동읍입실리 123"),          # '외' must not empty the address
    ("통진읍 마송리 산 12 외 2필지", "통진읍마송리 산12"),
])
def test_lot_key(tail, key):
    assert lot_key(tail) == key


def test_name_score_franchise_containment_needs_two_long_names():
    assert clean_name("㈜스타벅스 (신림역점)") == "스타벅스신림역점"
    assert name_score("스타벅스", "스타벅스 신림역점") >= 0.75
    assert name_score("우지커피", "전봇대포장마차") < 0.60
    assert name_score("카페지니무", "무") < 0.60          # 1-char placeholder gets no boost


def test_owns_policy_rejects_short_building_names():
    assert owns_policy("초원미용실", "초원") is False            # apartment arcade, not the salon
    assert owns_policy("가나모텔", "가나모텔") is True
    assert owns_policy("다수제과", "(주)다수제과 본점") is True


def test_region_aliases_cover_2026_incheon_and_gunwi():
    assert region_aliases("인천 서구") == ["인천 서구", "인천 서해구", "인천 검단구"]
    assert "대구 군위군" in region_aliases("경북 군위군")
    assert region_aliases("서울 마포구") == ["서울 마포구"]


def _rec(name, family="other", multi_use=False, road_key=None, lot_key=None, rule=None):
    return {"name": name, "family": family, "rule": rule, "multi_use": multi_use,
            "road_key": road_key, "lot_key": lot_key, "road_tail": road_key, "lot_tail": lot_key}


def test_pick_groups_one_shops_licences():
    cands = [("road", _rec("카페지니")), ("road", _rec("카페지니", family="food")), ("road", _rec("옆집미용실"))]
    res = pick(cands, ["카페 지니"])
    assert res["status"] == "matched"
    assert [r["family"] for r in res["recs"]] == ["food", "other"]      # both licences kept


def test_pick_never_auto_picks_a_tie_or_a_failed_gate():
    tie = [("lot", _rec("우지커피 1호점")), ("lot", _rec("우지커피 2호점"))]
    assert pick(tie, ["우지커피"])["status"] == "ambiguous"
    clear = [("lot", _rec("우지커피 군자점")), ("lot", _rec("우지커피 군자역점"))]
    assert pick(clear, ["우지커피 군자"])["status"] == "matched"   # 0.92 vs 0.86
    assert pick([("road", _rec("전봇대포장마차"))], ["우지커피"])["status"] == "building_only"
    assert pick([("road", _rec("지니"))], ["카페지니"])["status"] == "matched"   # 0.67 ratio, no boost


def test_name_only_hits_group_by_premises():
    same = [_rec("카페지니", road_key="능동로 1"), _rec("카페지니", road_key="능동로 1")]
    assert by_premises(same)["status"] == "matched"
    two = [_rec("카페지니", road_key="능동로 1"), _rec("카페지니", road_key="자양로 9")]
    assert by_premises(two)["status"] == "ambiguous"
    assert by_premises([])["status"] == "unmatched"


# ── estimate() against a fake database ────────────────────────────────────────
def _db_rec(name, road_key, region="서울 광진구", **kw):
    base = {"name": name, "road_tail": road_key, "lot_tail": "", "area": 40.0, "multi_use": False,
            "type_id": 0, "class": "커피숍", "licence_date": None, "is_gym": False, "basement": False,
            "policy": None, "lic_ins": None, "road_key": road_key, "lot_key": None, "name_key": clean_name(name),
            "region_label": region, "slug": "rest_cafes", "name_ko": "휴게음식점", "name_en": "Rest cafés",
            "family": "food", "rule": None, "as_of": None}
    return {**base, **kw}


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, sql, *args):
        if "estimate.meta" in sql:
            return [{"key": "localdata_as_of", "value": "2026-09-22"}]
        labels = args[0]
        rows = [r for r in self.rows if r["region_label"] in labels]
        if "name_key = ANY" in sql:
            return [r for r in rows if r["name_key"] in args[1]]
        lk, rk = args[1], args[2]
        return [r for r in rows if (lk and r["lot_key"] == lk) or (rk and r["road_key"] == rk)]


class _FakePool:
    def __init__(self, rows):
        self.conn = _FakeConn(rows)

    def acquire(self, timeout=None):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


def _run(monkeypatch, rows, **q):
    async def fake_get():
        return _FakePool(rows)
    monkeypatch.setattr(svc.pool, "get", fake_get)
    return asyncio.run(svc.estimate(**q))


def test_estimate_no_district_without_any_address(monkeypatch):
    assert _run(monkeypatch, [], name="카페지니")["status"] == "no_district"


def test_estimate_registered_address_wins_across_districts(monkeypatch):
    rows = [_db_rec("전봇대포장마차", "신림로67길 4", region="서울 관악구"),
            _db_rec("전봇대포장마차", "능동로36길 29")]
    out = _run(monkeypatch, rows, name="전봇대포장마차", addr="서울 관악구 신림로67길 4",
               reg="서울특별시 광진구 능동로36길 29")
    assert (out["status"], out["method"], out["region"]) == ("matched", "registered", "서울 광진구")


def test_estimate_name_only_hit_is_flagged_as_unconfirmed_address(monkeypatch):
    rows = [_db_rec("카페지니", "자양로 9")]
    out = _run(monkeypatch, rows, name="카페지니", addr="서울 광진구 능동로 1")
    assert out["status"] == "matched" and out["addressMatched"] is False


def test_estimate_maps_db_errors_to_unavailable(monkeypatch):
    class _Boom:
        def acquire(self, timeout=None):
            raise OSError("connection refused")

    async def fake_get():
        return _Boom()
    monkeypatch.setattr(svc.pool, "get", fake_get)
    with pytest.raises(svc.EstimateUnavailable):
        asyncio.run(svc.estimate(name="카페지니", addr="서울 광진구 능동로 1"))


def test_masking_keeps_only_safe_parts():
    from app.utils.masking import mask_name, mask_phone
    assert mask_name("김민수") == "김**"
    assert mask_name("") == ""
    assert mask_phone("010-1234-5678") == "010-****-5678"
    assert mask_phone("02-123-4567") == "02-****-4567"
    assert mask_phone("1588") == ""            # not a phone number — dropped, not echoed
