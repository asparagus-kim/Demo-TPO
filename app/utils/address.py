"""Korean address normalisation helpers.

The Excel trade-area dataset stores addresses as `시/도 시군구 행정동` (e.g.
"서울특별시 광진구 자양동"), while the moneypin crawler may return short
forms such as "서울특별시 광진구" or Google Places may return long forms
with building names. These helpers convert both into a canonical tokenised
form that can be prefix-matched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# ----------------------------------------------------------------------------
# Sido (시/도) canonicalisation
# ----------------------------------------------------------------------------
SIDO_ALIASES = {
    "서울": "서울특별시",
    "서울시": "서울특별시",
    "서울특별시": "서울특별시",
    "부산": "부산광역시",
    "부산시": "부산광역시",
    "부산광역시": "부산광역시",
    "대구": "대구광역시",
    "대구시": "대구광역시",
    "대구광역시": "대구광역시",
    "인천": "인천광역시",
    "인천시": "인천광역시",
    "인천광역시": "인천광역시",
    "광주": "광주광역시",
    "광주광역시": "광주광역시",
    "대전": "대전광역시",
    "대전시": "대전광역시",
    "대전광역시": "대전광역시",
    "울산": "울산광역시",
    "울산시": "울산광역시",
    "울산광역시": "울산광역시",
    "세종": "세종특별자치시",
    "세종시": "세종특별자치시",
    "세종특별자치시": "세종특별자치시",
    "경기": "경기도",
    "경기도": "경기도",
    "강원": "강원특별자치도",
    "강원도": "강원특별자치도",
    "강원특별자치도": "강원특별자치도",
    "충북": "충청북도",
    "충청북도": "충청북도",
    "충남": "충청남도",
    "충청남도": "충청남도",
    "전북": "전북특별자치도",
    "전라북도": "전북특별자치도",
    "전북특별자치도": "전북특별자치도",
    "전남": "전라남도",
    "전라남도": "전라남도",
    "경북": "경상북도",
    "경상북도": "경상북도",
    "경남": "경상남도",
    "경상남도": "경상남도",
    "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
    "제주특별자치도": "제주특별자치도",
}

_SIDO_PREFIX_SORTED = sorted(SIDO_ALIASES.keys(), key=len, reverse=True)

# Matches Korean administrative tokens (roughly). We keep 읍/면/동/가/로/길 so
# downstream logic can decide whether to strip them.
_DONG_SUFFIXES = ("읍", "면", "동", "가", "로", "길")
_GU_SUFFIXES = ("구", "군", "시")


@dataclass
class ParsedAddress:
    raw: str
    sido: Optional[str]
    sigungu: Optional[str]
    dong: Optional[str]
    tokens: List[str]

    @property
    def canonical(self) -> str:
        return " ".join(t for t in (self.sido, self.sigungu, self.dong) if t)


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _strip_floor_room(token: str) -> str:
    # Remove trailing "XX층", "XX호" patterns that contaminate sigungu matches.
    return re.sub(r"\d+(층|호|번지|번길)$", "", token)


def _normalise_sido(token: str) -> Optional[str]:
    for prefix in _SIDO_PREFIX_SORTED:
        if token.startswith(prefix):
            return SIDO_ALIASES[prefix]
    return None


def _looks_like_sigungu(token: str) -> bool:
    return token.endswith(_GU_SUFFIXES) and len(token) >= 2


def _looks_like_dong(token: str) -> bool:
    if not token:
        return False
    stripped = re.sub(r"\d+(가|동|로|길)$", lambda m: m.group(1), token)
    return stripped.endswith(_DONG_SUFFIXES)


def parse_address(raw: str) -> ParsedAddress:
    """Parse a Korean address into (sido, sigungu, dong) if possible.

    Robust to:
    - leading/trailing whitespace
    - "서울시 광진구" (short sido)
    - "서울특별시 광진구 자양동 123-4 5층" (long with detail)
    - Google Places "대한민국 서울특별시 ..." prefix
    """
    cleaned = clean_whitespace(raw)
    # Strip "대한민국 " / "South Korea, " prefix
    cleaned = re.sub(r"^(대한민국|South Korea|Republic of Korea)[,\s]+", "", cleaned, flags=re.I)

    tokens = cleaned.split()
    tokens = [_strip_floor_room(t) for t in tokens if t]

    sido = None
    sigungu = None
    dong = None

    idx = 0
    if tokens:
        candidate = _normalise_sido(tokens[0])
        if candidate:
            sido = candidate
            idx = 1

    # Allow compound "시" inside a province, e.g. "경기도 성남시 분당구"
    while idx < len(tokens):
        token = tokens[idx]
        if sigungu is None and _looks_like_sigungu(token):
            sigungu = token
            idx += 1
            # "성남시 분당구" style — pick the 구 if the next token is also sigungu
            if idx < len(tokens) and _looks_like_sigungu(tokens[idx]) and tokens[idx].endswith("구"):
                sigungu = f"{sigungu} {tokens[idx]}"
                idx += 1
            continue
        # dong after sigungu (normal case) OR dong directly after sido
        # (some datasets collapse 시군구, e.g. "서울특별시 청운효자동").
        if dong is None and _looks_like_dong(token) and (sigungu or sido):
            dong = token
            idx += 1
            continue
        idx += 1

    return ParsedAddress(raw=cleaned, sido=sido, sigungu=sigungu, dong=dong, tokens=tokens)


def normalize_address(raw: str) -> str:
    """Return canonical "시/도 시군구 행정동" form if possible, else cleaned raw."""
    parsed = parse_address(raw)
    canon = parsed.canonical
    return canon if canon else clean_whitespace(raw)


def address_prefix_key(raw: str) -> str:
    """Key used for prefix matching against the Excel `주소` column.

    Drops sub-dong details so "서울특별시 광진구 자양동 123" and
    "서울특별시 광진구 자양동" match.
    """
    parsed = parse_address(raw)
    if parsed.sido and parsed.sigungu and parsed.dong:
        return f"{parsed.sido} {parsed.sigungu} {parsed.dong}"
    if parsed.sido and parsed.sigungu:
        return f"{parsed.sido} {parsed.sigungu}"
    return normalize_address(raw)
