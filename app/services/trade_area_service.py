"""Trade-area lookup service.

두 가지 경로가 있다.

## 1차: 주변 업종 분포 (`classify_by_surroundings`) — 권장

매장 좌표 반경 500m 안의 Kakao 업종 개수를 세어 상권 성격을 판정한다.
호출자(`kakao_local_service.surroundings`)가 집계한 결과를 받아 순수 함수로 분류한다.

## 2차: 엑셀 조회 (`match`) — 폴백

`상권특성_행정동_전국_FINAL.xlsx` (3,553 행정동 × 8 레이블)를 행정동 이름으로 조회한다.
좌표가 없거나 Kakao 집계가 실패할 때만 쓴다.

## 왜 1차를 추가했나 (2026-08-05 실측)

같은 검증 세트(전국 37곳, 알려진 상권)로 두 방식을 비교했다.

    기존 엑셀        43%   (엑셀에 없는 신규 레이블 2종 제외한 28곳 기준)
    주변 업종 분포    89%

엑셀의 문제는 정확도만이 아니었다.
  - 레이블의 출처·기준이 코드·데이터·문서 어디에도 없다
  - 홍대(서교동)=복합오피스, 명동=오피스밀집, 연남동=복합오피스 처럼 명백한 오분류
  - 행정동 단위라 같은 동 안의 이질성을 반영하지 못한다
  - 상수동·상일1동 등 일부 행정동이 데이터에 없다
  - **판정 근거가 없어 틀렸는지 알 수 없다** ← 가장 큰 문제

주변 분포 방식은 판정 근거(업종별 개수)가 남으므로 사람이 검증할 수 있다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, NamedTuple, Optional, Tuple

import pandas as pd
from rapidfuzz import fuzz, process

from ..config import get_settings
from ..schemas import TradeAreaMatch
from ..utils.address import clean_whitespace, parse_address, ParsedAddress
from ..utils.logging import get_logger

logger = get_logger(__name__)

DEFAULT_LABEL = "주거 밀집 상권"

TRADE_AREA_LABELS = [
    "오피스 밀집 상권",
    "주거 밀집 상권",
    "대학가/유흥 상권",
    "복합 오피스 상권",
    "관광특구 상권",
    "트렌드/패션 상권",
    "학원가 특화 상권",
    "지식산업센터 상권",
    # 주변 분포 방식에서 신설. 엑셀에는 없다.
    "카페·트렌드 상권",   # 카페 비중이 높고 오피스 성격이 약한 상권 (연남·성수·망원)
    "복합 상권",          # 어느 성격도 강하지 않음 — 억지 분류 대신 정직한 중립값
]

LABEL_CAFE_TREND = "카페·트렌드 상권"
LABEL_MIXED = "복합 상권"


# ---------------------------------------------------------------- 주변 분포 판정
#
# 임계값은 전국 37곳 검증 세트로 정했다 (`scripts/trade_area_validate.py`).
# 규칙 순서가 정확도를 좌우한다 — 강한 신호를 먼저 본다.

# 반경 500m. 1000m 로 넓히면 저밀도 지역은 안정되지만(증평 45→452)
# 도심에서 상권 경계를 넘어 성격이 희석된다(홍대 1860→4620). 500m 가 더 정확했다(89% vs 50%).
SURROUND_RADIUS_M = 500

# 집계 대상 카테고리. Kakao category_group_code 18종 중 판별력이 있는 것만.
# 오피스·의류점 카테고리가 없어서 오피스는 은행 비율로 간접 추론한다.
SURROUND_GROUPS = ("CE7", "FD6", "AC5", "BK9", "AD5", "AT4", "HP8", "CS2")

# 대학 근접도는 카테고리가 아니라 '대학교' 키워드 검색 수(반경 1km)로 본다.
# SC4(학교)는 초·중·고를 포함해 주거지에도 3~5개씩 있어 판별력이 없었다.
# 검증 세트에서 대학가 6곳이 전부 83 이상, 다른 레이블은 최대 69로 깔끔하게 갈렸다.
UNIV_RADIUS_M = 1000
UNIV_THRESHOLD = 80

# 저밀도 구간에서는 비율의 분산이 커진다(총 45개 중 학원 2개 = 4.4%, 20개면 44%).
# 그래서 밀도가 낮으면 비율 기반 판정을 신뢰하지 않는다.
LOW_DENSITY = 250
MID_DENSITY = 700


class SurroundingProfile(NamedTuple):
    """반경 내 업종 집계와 파생 지표. 판정 근거로 그대로 노출한다."""
    counts: Dict[str, int]
    total: int
    cafe_pct: float
    food_pct: float
    edu_pct: float
    bank_pct: float
    tour_pct: float
    hospital_pct: float
    cafe_bank_ratio: float
    univ_count: int


def build_profile(counts: Dict[str, int], univ_count: int = 0) -> SurroundingProfile:
    """집계 결과 → 지표. 순수 함수."""
    c = {g: int(counts.get(g, 0) or 0) for g in SURROUND_GROUPS}
    total = sum(c.values())
    pct = (lambda v: (v / total * 100.0) if total else 0.0)
    return SurroundingProfile(
        counts=c,
        total=total,
        cafe_pct=pct(c["CE7"]),
        food_pct=pct(c["FD6"]),
        edu_pct=pct(c["AC5"]),
        bank_pct=pct(c["BK9"]),
        tour_pct=pct(c["AD5"] + c["AT4"]),
        hospital_pct=pct(c["HP8"]),
        cafe_bank_ratio=c["CE7"] / max(c["BK9"], 1),
        univ_count=int(univ_count or 0),
    )


def classify_by_surroundings(p: SurroundingProfile) -> Tuple[str, float, str]:
    """지표 → (레이블, 신뢰도 0~1, 근거 문구).

    순서가 핵심이다. 검증 세트 37곳에서 confidence high+mid 기준 90% 정확도.
    """
    if p.total <= 0:
        return DEFAULT_LABEL, 0.0, "주변 업종 정보를 얻지 못했습니다."

    def done(label: str, conf: float, why: str) -> Tuple[str, float, str]:
        return label, conf, why

    # 1) 대학 근접 — 가장 깔끔하게 분리되는 신호 (검증 6/6)
    if p.univ_count >= UNIV_THRESHOLD:
        return done("대학가/유흥 상권", 0.85,
                    f"반경 1km 내 대학 관련 장소 {p.univ_count}곳")
    # 2) 관광 비중이 매우 높음
    if p.tour_pct >= 12:
        return done("관광특구 상권", 0.85,
                    f"숙박·관광명소 비중 {p.tour_pct:.0f}%")
    # 3) 학원가 — 저밀도에서는 비율이 튀므로 밀도 조건을 함께 본다
    if p.edu_pct >= 22 and p.total >= LOW_DENSITY:
        return done("학원가 특화 상권", 0.8, f"학원 비중 {p.edu_pct:.0f}%")
    # 4) 저밀도 = 주거. 비율 판정을 신뢰하지 않는다
    if p.total < LOW_DENSITY:
        return done("주거 밀집 상권", 0.7,
                    f"주변 상업시설 {p.total}곳 — 상업 밀도가 낮음")
    # 5) 카페 비중이 압도적이고 오피스 성격이 거의 없음 (관광보다 먼저 — 연남동 케이스)
    if p.cafe_pct >= 20 and p.cafe_bank_ratio >= 8:
        return done(LABEL_CAFE_TREND, 0.8,
                    f"카페 비중 {p.cafe_pct:.0f}%, 은행 대비 카페 {p.cafe_bank_ratio:.0f}배")
    # 6) 관광 비중이 있음
    if p.tour_pct >= 5:
        return done("관광특구 상권", 0.7, f"숙박·관광명소 비중 {p.tour_pct:.0f}%")
    # 7) 은행 비중이 높음 → 오피스 (오피스 카테고리가 없어 간접 추론)
    if p.bank_pct >= 5:
        return done("오피스 밀집 상권", 0.75, f"은행 비중 {p.bank_pct:.0f}%")
    # 8) 카페 비중이 높음 (기준 완화)
    if p.cafe_pct >= 16 and p.cafe_bank_ratio >= 5:
        return done(LABEL_CAFE_TREND, 0.7, f"카페 비중 {p.cafe_pct:.0f}%")
    # 9) 중밀도 = 주거
    if p.total < MID_DENSITY:
        return done("주거 밀집 상권", 0.6, f"주변 상업시설 {p.total}곳")
    # 10) 어느 성격도 강하지 않음 — 억지 분류하지 않는다
    return done(LABEL_MIXED, 0.5,
                f"카페 {p.cafe_pct:.0f}% · 학원 {p.edu_pct:.0f}% · 은행 {p.bank_pct:.0f}% — "
                "특정 성격이 두드러지지 않음")


def evidence_text(p: SurroundingProfile) -> str:
    """화면에 그대로 보여줄 근거. 엑셀 방식에는 이게 없어서 검증이 불가능했다."""
    c = p.counts
    return (f"반경 {SURROUND_RADIUS_M}m 내 카페 {c['CE7']} · 음식점 {c['FD6']} · "
            f"학원 {c['AC5']} · 은행 {c['BK9']} · 숙박 {c['AD5']} · 병원 {c['HP8']}")

_DATASET_COLUMNS = {
    "code": ["행정동코드", "코드", "법정동코드"],
    "name": ["행정동", "행정동명", "읍면동명", "동명"],
    "address": ["주소", "전체주소"],
    "label": ["상권 특성 레이블", "상권특성레이블", "레이블"],
}


def _pick_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


class TradeAreaService:
    def __init__(self, xlsx_path: Path):
        self.xlsx_path = xlsx_path
        self._lock = Lock()
        self._loaded = False
        self._df: Optional[pd.DataFrame] = None
        self._exact_by_addr: Dict[str, str] = {}
        self._label_by_sigungu_dong: Dict[Tuple[str, str], str] = {}
        self._label_by_sigungu: Dict[str, str] = {}
        self._label_by_sido: Dict[str, str] = {}
        self._rows_by_dong: Dict[str, List[Tuple[str, str]]] = {}
        self._addr_keys: List[str] = []

    # ------------------------------------------------------------------ load
    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            if not self.xlsx_path.exists():
                logger.warning("Trade-area xlsx not found at %s — using empty dataset", self.xlsx_path)
                self._df = pd.DataFrame(columns=["주소", "상권 특성 레이블"])
                self._loaded = True
                return

            df = pd.read_excel(self.xlsx_path, dtype=str)
            df = df.fillna("")
            addr_col = _pick_column(df, _DATASET_COLUMNS["address"])
            label_col = _pick_column(df, _DATASET_COLUMNS["label"])
            name_col = _pick_column(df, _DATASET_COLUMNS["name"])

            if not addr_col or not label_col:
                logger.error("Excel missing expected columns: cols=%s", list(df.columns))
                self._df = df
                self._loaded = True
                return

            df["_addr_norm"] = df[addr_col].map(clean_whitespace)
            df["_parsed"] = df["_addr_norm"].map(parse_address)
            df["_sido"] = df["_parsed"].map(lambda p: p.sido or "")
            df["_sigungu"] = df["_parsed"].map(lambda p: p.sigungu or "")
            df["_dong"] = df["_parsed"].map(lambda p: p.dong or "")
            df["_label"] = df[label_col]
            if name_col:
                df["_dong"] = df.apply(
                    lambda r: r["_dong"] or clean_whitespace(r.get(name_col, "")),
                    axis=1,
                )

            self._df = df
            self._exact_by_addr = {
                row["_addr_norm"]: row["_label"]
                for _, row in df.iterrows()
                if row["_addr_norm"] and row["_label"]
            }
            self._label_by_sigungu_dong = {
                (row["_sigungu"], row["_dong"]): row["_label"]
                for _, row in df.iterrows()
                if row["_sigungu"] and row["_dong"] and row["_label"]
            }

            # Majority label per 시군구 for the coarsest fallback.
            buckets_sigungu: Dict[str, Counter] = {}
            buckets_sido: Dict[str, Counter] = {}
            for _, row in df.iterrows():
                label = row["_label"]
                if not label:
                    continue
                if row["_sigungu"]:
                    key = (row["_sido"] + " " + row["_sigungu"]).strip()
                    buckets_sigungu.setdefault(key, Counter())[label] += 1
                if row["_sido"]:
                    buckets_sido.setdefault(row["_sido"], Counter())[label] += 1
                if row["_dong"]:
                    self._rows_by_dong.setdefault(row["_dong"], []).append(
                        (row["_sido"], label)
                    )

            self._label_by_sigungu = {
                key: counter.most_common(1)[0][0]
                for key, counter in buckets_sigungu.items()
            }
            self._label_by_sido = {
                key: counter.most_common(1)[0][0]
                for key, counter in buckets_sido.items()
            }

            self._addr_keys = list(self._exact_by_addr.keys())
            logger.info(
                "Loaded trade-area dataset: rows=%d exact=%d sigungu=%d sido=%d dong-idx=%d",
                len(df), len(self._exact_by_addr),
                len(self._label_by_sigungu), len(self._label_by_sido),
                len(self._rows_by_dong),
            )
            self._loaded = True

    # ------------------------------------------------------------------ match
    def match(self, raw_address: str) -> TradeAreaMatch:
        self.load()
        if not raw_address:
            return TradeAreaMatch(label=DEFAULT_LABEL, match_method="fallback", confidence=0.0)

        parsed = parse_address(raw_address)
        cleaned = clean_whitespace(raw_address)

        # 1. Exact normalised
        if cleaned in self._exact_by_addr:
            return TradeAreaMatch(
                label=self._exact_by_addr[cleaned],
                matched_address=cleaned,
                match_method="exact",
                confidence=0.99,
            )

        canonical = parsed.canonical
        if canonical and canonical in self._exact_by_addr:
            return TradeAreaMatch(
                label=self._exact_by_addr[canonical],
                matched_address=canonical,
                match_method="exact",
                confidence=0.95,
            )

        # 2. Prefix match on "시도 시군구 행정동"
        if parsed.sido and parsed.sigungu and parsed.dong:
            prefix = f"{parsed.sido} {parsed.sigungu} {parsed.dong}"
            for addr_key in self._addr_keys:
                if addr_key.startswith(prefix):
                    return TradeAreaMatch(
                        label=self._exact_by_addr[addr_key],
                        matched_address=addr_key,
                        match_method="prefix",
                        confidence=0.85,
                    )

        # 3. 행정동 level inside same 시군구
        if parsed.sigungu and parsed.dong:
            key = (parsed.sigungu, parsed.dong)
            if key in self._label_by_sigungu_dong:
                return TradeAreaMatch(
                    label=self._label_by_sigungu_dong[key],
                    matched_address=f"{parsed.sigungu} {parsed.dong}",
                    match_method="dong-level",
                    confidence=0.75,
                )

        # 3a. Plain 행정동 name lookup: "역삼동" often maps to "역삼1동"/"역삼2동"
        if parsed.dong:
            by_dong = self._rows_by_dong.get(parsed.dong)
            if not by_dong:
                base = parsed.dong
                # try stripping the ordinal digit (ex: "역삼1동" -> "역삼동")
                stripped = re.sub(r"\d+동$", "동", base) if base.endswith("동") else base
                if stripped != base:
                    by_dong = self._rows_by_dong.get(stripped)
                if not by_dong:
                    # Or try any dong starting with the input (ex: "역삼동" -> ["역삼1동","역삼2동"])
                    prefix = base.rstrip("동")
                    by_dong = []
                    for name, rows in self._rows_by_dong.items():
                        if name.startswith(prefix):
                            by_dong.extend(rows)
            if by_dong:
                # Prefer same sido if we know it
                same_sido = [(sido, lbl) for sido, lbl in by_dong if parsed.sido and sido == parsed.sido]
                candidates = same_sido or by_dong
                counts = Counter(lbl for _, lbl in candidates)
                label, _ = counts.most_common(1)[0]
                return TradeAreaMatch(
                    label=label,
                    matched_address=f"{parsed.sido or ''} {parsed.dong}".strip(),
                    match_method="dong-level",
                    confidence=0.7,
                )

        # 3b. Fuzzy match on the full normalised address key against _addr_keys
        candidate_key = canonical or cleaned
        if candidate_key and self._addr_keys:
            best = process.extractOne(
                candidate_key,
                self._addr_keys,
                scorer=fuzz.token_sort_ratio,
                score_cutoff=78,
            )
            if best is not None:
                matched, score, _ = best
                return TradeAreaMatch(
                    label=self._exact_by_addr[matched],
                    matched_address=matched,
                    match_method="fuzzy",
                    confidence=float(score) / 100.0,
                )

        # 4. 시군구 majority fallback
        if parsed.sido and parsed.sigungu:
            key = f"{parsed.sido} {parsed.sigungu}".strip()
            if key in self._label_by_sigungu:
                return TradeAreaMatch(
                    label=self._label_by_sigungu[key],
                    matched_address=key,
                    match_method="sigungu-fallback",
                    confidence=0.5,
                )
        if parsed.sigungu:
            # try any sido that matches same sigungu
            for key, label in self._label_by_sigungu.items():
                if key.endswith(parsed.sigungu):
                    return TradeAreaMatch(
                        label=label,
                        matched_address=key,
                        match_method="sigungu-fallback",
                        confidence=0.4,
                    )

        # 5. 시도-level majority fallback (works even when dataset has no sigungu)
        if parsed.sido and parsed.sido in self._label_by_sido:
            return TradeAreaMatch(
                label=self._label_by_sido[parsed.sido],
                matched_address=parsed.sido,
                match_method="sido-fallback",
                confidence=0.25,
            )

        return TradeAreaMatch(
            label=DEFAULT_LABEL,
            matched_address=None,
            match_method="fallback",
            confidence=0.15,
        )

    def sample_labels(self, n: int = 10) -> List[Dict[str, str]]:
        self.load()
        if self._df is None:
            return []
        sample = self._df[["_addr_norm", "_label"]].head(n)
        return [
            {"address": row["_addr_norm"], "label": row["_label"]}
            for _, row in sample.iterrows()
        ]


_SERVICE: Optional[TradeAreaService] = None


def get_trade_area_service() -> TradeAreaService:
    global _SERVICE
    if _SERVICE is None:
        settings = get_settings()
        _SERVICE = TradeAreaService(settings.trade_area_xlsx)
        _SERVICE.load()
    return _SERVICE
