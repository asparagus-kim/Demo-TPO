"""Address and name keys for matching a shop against LOCALDATA licences.

Pure functions, no I/O. They MUST stay identical to the build that writes the
keys into the database (devFS/scripts/build_insurance_shards.py) — a key that
differs by one character silently turns a real match into "not found".

    split_region('서울 관악구 신림로67길 4')  -> ('서울 관악구', '신림로67길 4')
    road_key('신림로67길 4, 1층 (신림동)')     -> '신림로67길 4'
    lot_key('신림동 1422-5 2층')               -> '신림동 1422-5'
"""
from __future__ import annotations

import difflib
import re
import unicodedata

NAME_THRESHOLD = 0.60   # shun's gate — below it a candidate is never "matched"
TIE_MARGIN = 0.05       # two candidates this close are a human's call, not ours

# 시도 (province) long/old forms -> region label. Kakao prints short forms
# ('서울'); LOCALDATA prints long ones ('서울특별시'). Since 2026 LOCALDATA files
# 전남 (Jeonnam) and 광주 (Gwangju) under 전남광주통합특별시 (the merged
# Jeonnam-Gwangju special city); all forms share one label because their
# 시군구 (district) names never collide.
SIDO = {
    "서울특별시": "서울", "서울": "서울", "부산광역시": "부산", "부산": "부산",
    "대구광역시": "대구", "대구": "대구", "인천광역시": "인천", "인천": "인천",
    "대전광역시": "대전", "대전": "대전",
    "울산광역시": "울산", "울산": "울산", "세종특별자치시": "세종", "세종": "세종",
    "경기도": "경기", "경기": "경기", "강원특별자치도": "강원", "강원도": "강원", "강원": "강원",
    "충청북도": "충북", "충북": "충북", "충청남도": "충남", "충남": "충남",
    "전북특별자치도": "전북", "전라북도": "전북", "전북": "전북",
    "전남광주통합특별시": "전남광주", "전라남도": "전남광주", "전남": "전남광주",
    "광주광역시": "전남광주", "광주": "전남광주",
    "경상북도": "경북", "경북": "경북", "경상남도": "경남", "경남": "경남",
    "제주특별자치도": "제주", "제주도": "제주", "제주": "제주",
}

_ROAD = re.compile(r"([가-힣A-Za-z0-9]+(?:로|길))\s*(\d+(?:-\d+)?)")
_LOT = re.compile(r"^(.*?[동리가])(산?\d+(?:-\d+)?)(?![\d가])")
_FLOOR_TAIL = re.compile(r"\s*(?:지하)?\s*[\d*]+\s*층.*$|\s*[\d*]+\s*호.*$")
_CORP = re.compile(r"\(주\)|주식회사|㈜|\(유\)|유한회사|\(학\)|재단법인|사단법인")


# District reorganisations: Kakao may still print the old name while LOCALDATA
# already files the new one (verified 2026-10-01 in estimate.regions). 2026-07:
# Incheon 중구·동구 → 제물포구·영종구, 서구 → 서해구·검단구; 2023: 군위군 경북 → 대구;
# 2018: 인천 남구 → 미추홀구. Each label also queries its counterparts.
_ALIASES = {
    "인천 중구": ("인천 제물포구", "인천 영종구"), "인천 동구": ("인천 제물포구",),
    "인천 서구": ("인천 서해구", "인천 검단구"), "인천 남구": ("인천 미추홀구",),
    "인천 제물포구": ("인천 중구", "인천 동구"), "인천 영종구": ("인천 중구",),
    "인천 서해구": ("인천 서구",), "인천 검단구": ("인천 서구",), "인천 미추홀구": ("인천 남구",),
    "경북 군위군": ("대구 군위군",), "대구 군위군": ("경북 군위군",),
}


def region_aliases(label: str) -> list[str]:
    """The label plus its old/new counterparts, for `region = ANY(...)` queries."""
    return [label, *_ALIASES.get(label, ())]


def nfkc(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or ""))


def split_region(addr: str | None) -> tuple[str | None, str | None]:
    """(region label, rest of the address). 세종 has no 시군구 level."""
    tokens = nfkc(addr).split()
    if len(tokens) < 2 or tokens[0] not in SIDO:
        return None, None
    sido = SIDO[tokens[0]]
    if sido == "세종":
        return "세종", " ".join(tokens[1:])
    return f"{sido} {tokens[1]}", " ".join(tokens[2:])


def road_key(tail: str | None) -> str | None:
    """Road name + building number — the last such pair before the first comma.
    Road names are unique within a 시군구, and this survives 20682 injecting
    the 법정동 (legal dong) before the road."""
    if not tail:
        return None
    cleaned = re.sub(r"\([^)]*\)", " ", nfkc(tail)).split(",")[0]
    found = _ROAD.findall(cleaned)
    return f"{found[-1][0]} {found[-1][1]}" if found else None


def lot_key(tail: str | None) -> str | None:
    """Dong/ri + lot number. Keeps '양평동3가 12' whole and does not split on
    every '외' (that would empty 외동읍 addresses)."""
    if not tail:
        return None
    s = nfkc(tail).split("(")[0]
    s = re.sub(r"\s외\s*\d+\s*필지.*$", "", s)
    s = _FLOOR_TAIL.sub("", s, count=1)
    m = _LOT.match(re.sub(r"\s+", "", s))
    return f"{m.group(1)} {m.group(2)}" if m else None


def clean_name(name: str | None) -> str:
    """Corporate wrappers and punctuation out, NFKC first (bizno once returned
    a full-width bracket that broke naive comparison)."""
    s = _CORP.sub("", nfkc(name))
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s).lower()


def name_score(query: str | None, candidate: str | None) -> float:
    """difflib ratio on cleaned names, raised to 0.75 when one long name
    contains the other (franchise branches: '스타벅스' vs '스타벅스 신림역점')."""
    a, b = clean_name(query), clean_name(candidate)
    if not a or not b:
        return 0.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    # Both names must be >= 4 chars: a 1–3 char candidate ('무', '지니') inside a
    # long query must not jump to 0.75 and pass the gate (review 2026-10-01).
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        score = max(score, 0.75)
    return score


def owns_policy(shop: str | None, holder: str | None) -> bool:
    """Is a 20682 policy holder name this shop? Stricter than name_score: the
    containment boost needs BOTH names >= 4 chars, so a short building name
    ('초원' — an apartment complex) inside a shop name ('초원미용실' — a salon in
    its arcade) is not read as the salon's own contract."""
    a, b = clean_name(shop), clean_name(holder)
    if not a or not b:
        return False
    if min(len(a), len(b)) >= 4 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= NAME_THRESHOLD
