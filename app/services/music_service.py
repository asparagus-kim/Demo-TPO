"""분석 결과(Energy/Tempo/Mood + TPO) → 음원 추천.

입력은 `data/demo_tracks.json` 매니페스트 하나뿐이고 외부 API를 쓰지 않는다.
매니페스트는 `scripts/curate_demo_tracks.py`가 생성하며, 매칭에 필요한
메타데이터를 자체 포함한다(원본 tracks.json을 런타임에 참조하지 않음).

## 왜 "후보 풀 내 상대 정규화"인가

곡 메타데이터의 축과 매장 분석의 축은 서로 다른 스케일로 설계되었고,
실측 분포를 보면 절대 비교가 성립하지 않는다.

    valence        데모 세트 0.65~0.85  ← 폭이 좁아 절대 비교 시 Mood가 사실상 무시됨
    energy_level   피트니스 곡군이 한때 전부 8.0 ← 상수라 어떤 절대 스케일로도 변별 불가
    bpm            카페 60~129 / 피트니스 118~160 ← 업종에 따라 분포가 완전히 다름

그래서 각 축을 **후보 풀 내 min-max로 정규화**하고, 목표값(E/T/M ÷ 100)의
0~1 위치와 비교한다. 두 가지 이점이 있다.

    1) 절대 범위가 좁은 축도 변별력을 갖는다 (매장별로 다른 곡이 나온다)
    2) 값이 상수인 축은 자동으로 "정보 없음"이 되어 점수에 기여하지 않는다
       → 피트니스의 energy_level 상수 문제가 특별 처리 없이 해소된다

절대값은 `reason`과 `match_detail`에 그대로 노출해 표시의 정직성을 유지한다.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..config import get_settings
from ..schemas import (
    Ambience,
    MusicRecommendation,
    TpoProfile,
    TrackRecommendation,
    TradeAreaMatch,
)
from ..utils.logging import get_logger

logger = get_logger(__name__)

MANIFEST_FILENAME = "demo_tracks.json"

# 축이 상수일 때(폭이 이 값 미만) "정보 없음"으로 처리한다.
_FLAT_AXIS_EPS = 1e-6

# 점수 가중치. 합이 1.0이며 거리가 작을수록 좋다(0=완전 일치).
WEIGHTS = {
    "energy": 0.30,
    "tempo": 0.25,
    "mood": 0.20,
    "time": 0.15,
    "density": 0.10,
}
# 방문 목적(Occasion)이 곡의 purpose_tags와 겹칠 때 주는 보너스(거리에서 차감).
PURPOSE_BONUS = 0.05

# 같은 장르/무드가 결과를 독점하지 않게 하는 상한.
MAX_PER_GENRE = 3
MAX_PER_MOOD = 3


# --------------------------------------------------------------- 업종 매핑
#
# 두 방향의 매핑이 필요하고 서로 성질이 다르다.
#
#   ① 곡 → 업종군 : `INDUSTRY_TOKENS`. 곡 메타데이터의 `suitable_industries`는
#      **닫힌 어휘**다(원본 664곡 실측 32종). 그래서 부분 문자열이 아니라
#      **정확 일치**로 매핑한다. 부분 문자열을 쓰면 '카페'가 '키즈카페'까지
#      끌어와 유아용 곡이 일반 카페 풀에 섞인다.
#
#   ② 매장 → 업종군 : `_STORE_INDUSTRY_HINTS`. 입력이 Kakao category_name과
#      canonical 업종의 자유 조합이라 어휘가 열려 있다. 부분 문자열로 훑는다.

# 업종군 → 곡 메타데이터의 suitable_industries 토큰(정확 일치).
# `scripts/curate_demo_tracks.py`가 이 상수를 import해 매니페스트를 만든다
# (한 곳에서만 정의해 큐레이션과 추천이 어긋나지 않게 한다).
#
# 원본 664곡의 suitable_industries 32종 중 `12월 전 업종`을 뺀 31종을 모두 덮는다
# (2026-08-05 실측). 새 토큰이 생기면 `python scripts/curate_demo_tracks.py`가
# "미매핑 토큰" 경고로 알려준다.
INDUSTRY_TOKENS: Dict[str, List[str]] = {
    "cafe":        ["카페", "북카페", "브런치카페", "브런치", "스터디카페", "베이커리"],
    "fitness":     ["헬스장", "스피닝", "요가", "요가스튜디오"],
    "beauty":      ["미용실", "네일샵", "스파"],
    "retail":      ["리테일", "편집샵", "부티크", "스니커샵", "플라워샵", "플로리스트"],
    "dining":      ["레스토랑"],
    "bar":         ["바", "바이닐바", "클럽"],
    "lodging":     ["호텔", "호텔라운지"],
    "culture":     ["서점", "갤러리"],
    "kids":        ["키즈카페", "아동복매장"],
    "convenience": ["편의점"],
    "office":      ["오피스"],
}

# 업종이 아니라 **시기**를 뜻하는 토큰. 이 토큰만 달린 곡은 계절 한정(크리스마스)
# 이고 8월 시연에 나오면 오작동으로 보인다. 매니페스트 생성 단계에서 제외한다.
SEASONAL_TOKENS: Tuple[str, ...] = ("12월 전 업종",)

GROUP_LABELS_KO: Dict[str, str] = {
    "cafe": "카페·베이커리",
    "fitness": "피트니스·요가",
    "beauty": "미용·네일·스파",
    "retail": "리테일·편집샵",
    "dining": "레스토랑",
    "bar": "바·클럽",
    "lodging": "호텔·라운지",
    "culture": "서점·갤러리",
    "kids": "키즈",
    "convenience": "편의점",
    "office": "오피스",
}

# 토큰 → 업종군 역인덱스. 한 토큰이 여러 군에 속할 수 있게 리스트로 둔다.
_TOKEN_TO_GROUPS: Dict[str, List[str]] = {}
for _g, _tokens in INDUSTRY_TOKENS.items():
    for _t in _tokens:
        _TOKEN_TO_GROUPS.setdefault(_t, []).append(_g)


def groups_for_track(
    suitable: Sequence[str], unsuitable: Sequence[str] = (),
) -> Tuple[List[str], List[str]]:
    """곡의 적합/부적합 업종 토큰 → (적합 업종군, 부적합 업종군).

    부적합 토큰이 가리키는 군은 적합 목록에서 **빼고** 따로 돌려준다.
    실측 예: `헬스장`은 420곡에서 부적합으로 지정돼 있어 이 처리가 없으면
    피트니스 풀에 조용한 카페 곡이 대량으로 섞인다.
    """
    def _groups(tokens: Sequence[str]) -> set:
        out = set()
        for tok in tokens:
            out.update(_TOKEN_TO_GROUPS.get((tok or "").strip(), ()))
        return out

    bad = _groups(unsuitable)
    good = _groups(suitable) - bad
    order = list(INDUSTRY_TOKENS)
    return (sorted(good, key=order.index), sorted(bad, key=order.index))


def is_seasonal_only(suitable: Sequence[str]) -> bool:
    """적합 업종이 계절 토큰뿐인 곡인지 (예: 크리스마스 캐럴 31곡)."""
    tokens = {(t or "").strip() for t in suitable if (t or "").strip()}
    return bool(tokens) and tokens.issubset(set(SEASONAL_TOKENS))


# 매장 업종 문자열에서 업종군을 알아내기 위한 키워드(부분 문자열, **순서 우선**).
# classify_business_type()은 비F&B 업종을 원문 그대로 돌려주므로
# (예: "체력단련장 운영업") canonical/원문 양쪽을 모두 훑는다.
#
# 순서가 중요하다. Kakao category_name은 대분류를 포함한 경로 문자열이라
# 한 문장에 여러 군의 키워드가 동시에 들어온다.
#   "음식점 > 카페 > 커피전문점"   → cafe 가 dining 보다 먼저여야 한다
#   "음식점 > 술집 > 호프,요리주점" → bar 가 dining 보다 먼저여야 한다
#   "가정,생활 > 애견,애완 > 애견카페" 류도 있어 kids/cafe 순서를 앞에 둔다
_STORE_INDUSTRY_HINTS: List[Tuple[str, List[str]]] = [
    ("fitness", [
        # Kakao category_name 실측값: "스포츠,레저 > 스포츠시설 > 헬스클럽"
        "헬스", "헬스클럽", "스포츠시설", "스포츠,레저",
        "피트니스", "체력단련", "스포츠 센터", "스포츠센터", "짐", "gym",
        "필라테스", "요가", "스피닝", "크로스핏", "운동",
    ]),
    ("kids", [
        "키즈", "아동복", "유아", "어린이", "놀이방", "kids",
    ]),
    ("beauty", [
        # Kakao 실측: "생활,서비스 > 미용 > 미용실", "... > 네일샵", "... > 피부관리"
        "미용", "미용실", "헤어", "hair", "네일", "nail", "왁싱", "속눈썹",
        "피부관리", "에스테틱", "스파", "마사지", "테라피", "이용원", "바버",
    ]),
    ("cafe", [
        "카페", "커피", "coffee", "cafe", "베이커리", "빵", "제과", "디저트",
        "브런치", "북카페", "아이스크림", "도넛", "케이크", "차,음료", "티하우스",
    ]),
    ("bar", [
        # 한 글자 '바'는 오탐이 심해(예: 바베큐) 쓰지 않는다.
        "술집", "주점", "호프", "펍", "pub", " bar", "바(", "칵테일", "와인",
        "이자카야", "포차", "맥주", "막걸리", "클럽", "라운지바", "위스키",
    ]),
    ("culture", [
        "서점", "도서", "book", "북스", "갤러리", "화랑", "전시", "미술관",
        "문화,예술", "공방",
    ]),
    ("lodging", [
        "호텔", "hotel", "숙박", "리조트", "게스트하우스", "펜션", "모텔",
    ]),
    ("convenience", [
        "편의점", "convenience",
    ]),
    ("retail", [
        "의류", "패션", "잡화", "편집", "부티크", "신발", "슈즈", "안경",
        "화장품", "화장품판매", "꽃집", "플라워", "화원", "소품", "리빙",
        "쇼핑", "판매", "리테일", "select shop",
    ]),
    ("office", [
        "오피스", "office", "사무", "공유오피스", "코워킹", "스터디",
    ]),
    ("dining", [
        # 대분류 '음식점'은 마지막에 본다 — 위 군들이 모두 '음식점 > ...' 경로다.
        "레스토랑", "음식점", "식당", "한식", "일식", "양식", "중식", "분식",
        "패밀리레스토랑", "다이닝", "restaurant",
    ]),
]


def detect_industry_group(*business_types: Optional[str]) -> Optional[str]:
    """업종 문자열들에서 매니페스트 업종군을 추정한다. 못 찾으면 None."""
    joined = " ".join(t for t in business_types if t).lower()
    if not joined.strip():
        return None
    for group, keywords in _STORE_INDUSTRY_HINTS:
        for kw in keywords:
            if kw.lower() in joined:
                return group
    return None


# --------------------------------------------------------------- 시간대 매핑

# ambience_service.DAYPART_WINDOWS 의 daypart → 매니페스트 suitable_time_slots.
# brunch(약 10~12시)는 대응되는 daypart가 없어 early_morning/lunch에 걸쳐 배분한다.
TIME_SLOT_ORDER = ["morning", "brunch", "lunch", "afternoon", "evening", "late_night"]

DAYPART_TO_SLOT: Dict[str, Dict[str, float]] = {
    "early_morning": {"morning": 1.0, "brunch": 0.4},
    "lunch": {"lunch": 1.0, "brunch": 0.5},
    "afternoon": {"afternoon": 1.0},
    "dinner": {"evening": 1.0},
    "late_night": {"late_night": 1.0},
}


# --------------------------------------------------------------- Occasion 매핑

# TpoProfile.occasion_label은 LLM 자유 텍스트(한국어)라 키워드로 매핑한다.
_OCCASION_TO_PURPOSE: List[Tuple[List[str], List[str]]] = [
    (["운동", "workout", "헬스", "트레이닝"], ["workout", "energize"]),
    (["업무", "미팅", "작업", "공부", "노트북", "집중"], ["focus", "conversation"]),
    (["데이트", "친구", "수다", "모임", "대화"], ["conversation"]),
    (["야간", "파티", "축하", "기념"], ["celebration", "energize"]),
    (["테이크아웃", "포장", "간식", "대기"], ["waiting"]),
    (["식사", "점심", "저녁", "밥", "브런치"], ["meal", "conversation"]),
    (["쇼핑", "구경", "방문"], ["shopping"]),
    (["휴식", "쉬", "여유", "커피"], ["relax", "conversation"]),
    (["진료", "예약", "상담", "시술", "케어"], ["treatment", "waiting"]),
]


def purpose_tags_for_occasion(occasion_label: Optional[str]) -> List[str]:
    if not occasion_label:
        return []
    text = occasion_label.lower()
    out: List[str] = []
    for keywords, tags in _OCCASION_TO_PURPOSE:
        if any(kw.lower() in text for kw in keywords):
            for t in tags:
                if t not in out:
                    out.append(t)
    return out


# --------------------------------------------------------------- 매니페스트 로딩

@lru_cache(maxsize=4)
def load_manifest(path: Optional[str] = None) -> Dict[str, Any]:
    """매니페스트를 읽어 캐시한다. 없으면 빈 구조를 돌려준다(서비스가 죽지 않게)."""
    settings = get_settings()
    p = Path(path) if path else (settings.data_dir / MANIFEST_FILENAME)
    if not p.exists():
        logger.warning("음원 매니페스트가 없습니다: %s — 추천이 비활성화됩니다.", p)
        return {"tracks": [], "audio_base": "", "audio_ext": ".mp3"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("음원 매니페스트 파싱 실패 (%s): %s", p, exc)
        return {"tracks": [], "audio_base": "", "audio_ext": ".mp3"}
    tracks = [t for t in (data.get("tracks") or []) if t.get("review") != "reject"]
    data["tracks"] = tracks
    logger.info("음원 매니페스트 로드: %s (%d곡, reject 제외)", p, len(tracks))
    return data


def audio_url(manifest: Dict[str, Any], track_id: str) -> str:
    base = (manifest.get("audio_base") or "").rstrip("/")
    ext = manifest.get("audio_ext") or ".mp3"
    if not base:
        return ""
    return f"{base}/{track_id}{ext}"


# --------------------------------------------------------------- 축 계산

def _energy_feature(track: Dict[str, Any]) -> Optional[float]:
    """energy_level(1~10)과 arousal(0~1)을 합쳐 하나의 에너지 특징으로 만든다.

    두 축은 같은 방향이고 arousal 쪽이 결측이 없어 서로를 보완한다.
    한쪽만 있으면 있는 쪽을 그대로 쓴다.
    """
    parts: List[float] = []
    lvl = track.get("energy_level")
    if isinstance(lvl, (int, float)):
        parts.append(float(lvl) / 10.0)
    ar = track.get("arousal")
    if isinstance(ar, (int, float)):
        parts.append(float(ar))
    if not parts:
        return None
    return sum(parts) / len(parts)


def _tempo_feature(track: Dict[str, Any]) -> Optional[float]:
    bpm = track.get("bpm")
    return float(bpm) if isinstance(bpm, (int, float)) else None


def _mood_feature(track: Dict[str, Any]) -> Optional[float]:
    v = track.get("valence")
    return float(v) if isinstance(v, (int, float)) else None


_AXIS_FEATURES = {
    "energy": _energy_feature,
    "tempo": _tempo_feature,
    "mood": _mood_feature,
}


def _pool_ranges(pool: Sequence[Dict[str, Any]]) -> Dict[str, Optional[Tuple[float, float]]]:
    """후보 풀에서 축별 (min, max). 값이 없거나 상수면 None(정보 없음)."""
    ranges: Dict[str, Optional[Tuple[float, float]]] = {}
    for axis, fn in _AXIS_FEATURES.items():
        vals = [v for v in (fn(t) for t in pool) if v is not None]
        if not vals:
            ranges[axis] = None
            continue
        lo, hi = min(vals), max(vals)
        ranges[axis] = None if (hi - lo) < _FLAT_AXIS_EPS else (lo, hi)
    return ranges


def _normalized(axis: str, track: Dict[str, Any],
                ranges: Dict[str, Optional[Tuple[float, float]]]) -> Optional[float]:
    rng = ranges.get(axis)
    if rng is None:
        return None
    raw = _AXIS_FEATURES[axis](track)
    if raw is None:
        return None
    lo, hi = rng
    return (raw - lo) / (hi - lo)


# --------------------------------------------------------------- 시간대 / 혼잡도

def slot_weights_from_dayparts(daypart_weights: Optional[Dict[str, float]]) -> Dict[str, float]:
    """daypart 가중치를 매니페스트 시간대 슬롯 가중치로 변환(합=1). 신호 없으면 빈 dict."""
    if not daypart_weights:
        return {}
    total = sum(v for v in daypart_weights.values() if v and v > 0)
    if total < 1e-9:
        return {}
    out: Dict[str, float] = {}
    for daypart, w in daypart_weights.items():
        if not w or w <= 0:
            continue
        for slot, factor in DAYPART_TO_SLOT.get(daypart, {}).items():
            out[slot] = out.get(slot, 0.0) + (w / total) * factor
    s = sum(out.values())
    return {k: v / s for k, v in out.items()} if s > 0 else {}


def _time_distance(track: Dict[str, Any], slot_weights: Dict[str, float]) -> Optional[float]:
    """곡이 지원하는 슬롯이 매장 활동 시간대를 얼마나 덮는지. 0=완전 일치."""
    if not slot_weights:
        return None                      # 영업시간 미확인 → 페널티 없음
    slots = track.get("suitable_time_slots") or []
    if not slots:
        return None
    covered = sum(w for slot, w in slot_weights.items() if slot in slots)
    return max(0.0, 1.0 - covered)


_DENSITY_ORDER = ["quiet", "normal", "busy"]


def preferred_density(energy_0_100: float) -> str:
    if energy_0_100 >= 70:
        return "busy"
    if energy_0_100 >= 45:
        return "normal"
    return "quiet"


def _density_distance(track: Dict[str, Any], preferred: str) -> Optional[float]:
    fits = track.get("customer_density_fit") or []
    if not fits:
        return None
    if preferred in fits:
        return 0.0
    # 인접 단계(quiet↔normal, normal↔busy)는 절반만 벌점.
    pi = _DENSITY_ORDER.index(preferred)
    best = 1.0
    for f in fits:
        if f not in _DENSITY_ORDER:
            continue
        gap = abs(_DENSITY_ORDER.index(f) - pi)
        best = min(best, 0.5 if gap == 1 else 1.0)
    return best


# --------------------------------------------------------------- 후보 풀

MIN_POOL_SIZE = 5


def track_groups(t: Dict[str, Any]) -> List[str]:
    """매니페스트 항목의 적합 업종군. 구버전 `primary_group` 표기도 읽어준다."""
    groups = t.get("groups")
    if isinstance(groups, list):
        return [g for g in groups if g]
    single = t.get("primary_group")
    return [single] if single else []


def _build_pool(
    tracks: Sequence[Dict[str, Any]],
    industry_group: Optional[str],
    business_types: Sequence[Optional[str]],
) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """업종 기준 후보 풀. 부족하면 전체로 완화하고 그 사실을 notes로 알린다."""
    notes: List[str] = []
    joined = " ".join(t for t in business_types if t)

    # 하드 배제. 두 경로를 모두 본다.
    #   ① 업종군 기준 — 큐레이션 단계에서 계산해 둔 `unsuitable_groups`.
    #      canonical 업종("피트니스")과 곡 토큰("헬스장")처럼 표기가 달라도 걸린다.
    #   ② 원문 문자열 기준 — 업종군을 못 정한 경우에도 최소한의 안전장치.
    def excluded(t: Dict[str, Any]) -> bool:
        if industry_group and industry_group in (t.get("unsuitable_groups") or []):
            return True
        for bad in t.get("unsuitable_industries") or []:
            if bad and bad in joined:
                return True
        return False

    usable = [t for t in tracks if not excluded(t)]
    dropped = len(tracks) - len(usable)
    if dropped:
        notes.append(f"업종 부적합으로 {dropped}곡 제외")

    if industry_group:
        pool = [t for t in usable if industry_group in track_groups(t)]
        if len(pool) >= MIN_POOL_SIZE:
            return pool, True, notes
        label = GROUP_LABELS_KO.get(industry_group, industry_group)
        notes.append(
            f"'{label}' 전용 곡이 {len(pool)}곡뿐이어서 전체 후보로 확장했습니다."
        )
    else:
        notes.append("업종 전용 곡군을 특정하지 못해 분위기 기준으로만 추천합니다.")

    return usable, False, notes


# --------------------------------------------------------------- 설명 문구

def _slot_ko(slot: str) -> str:
    return {
        "morning": "아침", "brunch": "브런치", "lunch": "점심",
        "afternoon": "오후", "evening": "저녁", "late_night": "심야",
    }.get(slot, slot)


def _energy_word(level: Optional[float]) -> str:
    if not isinstance(level, (int, float)):
        return ""
    if level >= 7:
        return "강한"
    if level >= 5:
        return "적당한"
    if level >= 3:
        return "차분한"
    return "아주 조용한"


MAX_REASON_SLOTS = 2


def matched_slots(track: Dict[str, Any], slot_weights: Dict[str, float]) -> List[str]:
    """곡이 지원하는 시간대 ∩ 매장이 실제로 영업하는 시간대. 시간 순서로 반환.

    라벨과 곡 근거가 **같은 규칙**을 쓰도록 이 함수 하나로 모은다.
    (예전에는 라벨이 '최다 득표', 근거가 '매장 가중치 최대 + 동점 시 삽입 순서'라
    같은 곡을 두고 라벨은 "오후", 근거는 "점심"으로 갈리는 불일치가 있었다.)
    """
    slots = [s for s in (track.get("suitable_time_slots") or []) if s in TIME_SLOT_ORDER]
    if not slots:
        return []
    if slot_weights:
        slots = [s for s in slots if slot_weights.get(s, 0.0) > 0]
    return sorted(slots, key=TIME_SLOT_ORDER.index)


def _build_reason(track: Dict[str, Any], slot_weights: Dict[str, float]) -> str:
    bits: List[str] = []
    word = _energy_word(track.get("energy_level"))
    lvl = track.get("energy_level")
    if word and isinstance(lvl, (int, float)):
        bits.append(f"{word} 에너지 {lvl:.0f}/10")
    bpm = track.get("bpm")
    if isinstance(bpm, (int, float)):
        bits.append(f"{bpm:.0f}BPM")

    hits = matched_slots(track, slot_weights)
    if hits:
        shown = [_slot_ko(s) for s in hits[:MAX_REASON_SLOTS]]
        suffix = "" if len(hits) <= MAX_REASON_SLOTS else " 등"
        bits.append("·".join(shown) + suffix + " 시간대에 적합")

    if track.get("vocal_type") == "instrumental":
        bits.append("연주곡")
    return " · ".join(bits)


def _playlist_label(
    chosen: Sequence[Dict[str, Any]],
    business_type: Optional[str],
    slot_weights: Dict[str, float],
) -> str:
    """실제 선정된 곡들을 기준으로 라벨을 만든다.

    매장 점수(E)로 만들면 안 된다. 풀 내 상대 정규화를 쓰기 때문에 E=78은
    "카페 풀의 상단"을 뜻할 뿐 절대적으로 강한 음악이 아니고, 그렇게 만든
    라벨("강한")이 실제 선정곡("적당한 에너지 6/10")과 어긋난다.
    """
    levels = [t.get("energy_level") for t in chosen
              if isinstance(t.get("energy_level"), (int, float))]
    parts: List[str] = []
    if levels:
        parts.append(_energy_word(sum(levels) / len(levels)))

    # 시간대도 같은 이유로 선정곡에서 뽑는다. 매장 피크(slot_weights 최대)를 쓰면
    # 라벨이 "저녁 시간대"인데 상위 곡 근거는 "점심 시간대에 적합"으로 갈리는
    # 표시 불일치가 생긴다. 매장 활동 가중치는 후보 간 순위에만 쓰고,
    # 라벨은 곡 근거와 동일하게 matched_slots()로 계산한다.
    slot_votes: Dict[str, int] = {}
    for t in chosen:
        for slot in matched_slots(t, slot_weights):
            slot_votes[slot] = slot_votes.get(slot, 0) + 1
    if slot_votes:
        # 최다 득표, 동점이면 시간 순서상 앞선 슬롯.
        top = min(slot_votes.items(), key=lambda kv: (-kv[1], TIME_SLOT_ORDER.index(kv[0])))[0]
        parts.append(f"{_slot_ko(top)} 시간대")

    if business_type:
        parts.append(business_type)
    return " · ".join(p for p in parts if p)


# --------------------------------------------------------------- 다양성 제한

def _diversify(scored: List[Tuple[float, Dict[str, Any], Dict[str, float]]],
               limit: int) -> List[Tuple[float, Dict[str, Any], Dict[str, float]]]:
    """같은 장르/무드가 결과를 독점하지 않게 상한을 두고 뽑는다.

    상한 때문에 limit을 못 채우면, 마지막에 남은 후보로 채운다
    (다양성보다 개수를 우선 — 플레이리스트가 비는 것이 더 나쁘다).
    """
    picked: List[Tuple[float, Dict[str, Any], Dict[str, float]]] = []
    genre_count: Dict[str, int] = {}
    mood_count: Dict[str, int] = {}
    deferred: List[Tuple[float, Dict[str, Any], Dict[str, float]]] = []

    for item in scored:
        _, t, _ = item
        g = t.get("genre_primary") or "?"
        m = t.get("mood_primary") or "?"
        if genre_count.get(g, 0) >= MAX_PER_GENRE or mood_count.get(m, 0) >= MAX_PER_MOOD:
            deferred.append(item)
            continue
        picked.append(item)
        genre_count[g] = genre_count.get(g, 0) + 1
        mood_count[m] = mood_count.get(m, 0) + 1
        if len(picked) >= limit:
            return picked

    for item in deferred:
        if len(picked) >= limit:
            break
        picked.append(item)
    return picked


# --------------------------------------------------------------- 메인 API

def recommend(
    ambience: Ambience,
    tpo: Optional[TpoProfile] = None,
    *,
    business_type: Optional[str] = None,
    raw_business_type: Optional[str] = None,
    trade_area: Optional[TradeAreaMatch] = None,
    daypart_weights: Optional[Dict[str, float]] = None,
    limit: int = 10,
    manifest_path: Optional[str] = None,
) -> MusicRecommendation:
    """분석 결과로 플레이리스트를 만든다. 외부 호출 없음 · 결정적(deterministic)."""
    manifest = load_manifest(manifest_path)
    tracks = manifest.get("tracks") or []
    if not tracks:
        return MusicRecommendation(
            notes=["음원 매니페스트가 비어 있어 추천할 수 없습니다. "
                   "scripts/curate_demo_tracks.py 를 먼저 실행하세요."],
        )

    group = detect_industry_group(business_type, raw_business_type)
    pool, industry_matched, notes = _build_pool(
        tracks, group, [business_type, raw_business_type]
    )
    if not pool:
        return MusicRecommendation(notes=notes + ["조건에 맞는 곡이 없습니다."])

    ranges = _pool_ranges(pool)
    slot_weights = slot_weights_from_dayparts(daypart_weights)
    if not slot_weights:
        notes.append("영업시간 정보가 없어 시간대 가중치는 적용하지 않았습니다.")

    targets = {
        "energy": (ambience.energy or 0) / 100.0,
        "tempo": (ambience.tempo or 0) / 100.0,
        "mood": (ambience.mood or 0) / 100.0,
    }
    density_pref = preferred_density(float(ambience.energy or 0))
    wanted_purposes = purpose_tags_for_occasion(tpo.occasion_label if tpo else None)

    flat_axes = [a for a in _AXIS_FEATURES if ranges.get(a) is None]
    if flat_axes:
        notes.append(
            "후보 곡의 " + ", ".join(flat_axes) + " 값이 일정해 해당 축은 추천에 반영되지 않았습니다."
        )

    scored: List[Tuple[float, Dict[str, Any], Dict[str, float]]] = []
    for t in pool:
        detail: Dict[str, float] = {}
        weighted_sum = 0.0
        weight_used = 0.0

        for axis in ("energy", "tempo", "mood"):
            norm = _normalized(axis, t, ranges)
            if norm is None:
                continue
            d = abs(norm - targets[axis])
            detail[f"{axis}_distance"] = round(d, 4)
            detail[f"{axis}_norm"] = round(norm, 4)
            weighted_sum += WEIGHTS[axis] * d
            weight_used += WEIGHTS[axis]

        td = _time_distance(t, slot_weights)
        if td is not None:
            detail["time_distance"] = round(td, 4)
            weighted_sum += WEIGHTS["time"] * td
            weight_used += WEIGHTS["time"]

        dd = _density_distance(t, density_pref)
        if dd is not None:
            detail["density_distance"] = round(dd, 4)
            weighted_sum += WEIGHTS["density"] * dd
            weight_used += WEIGHTS["density"]

        # 사용된 가중치로만 나눠, 결측 축이 있는 곡이 부당하게 유리/불리해지지 않게 한다.
        distance = (weighted_sum / weight_used) if weight_used > 0 else 0.5

        if wanted_purposes:
            tags = t.get("purpose_tags") or []
            if set(tags) & set(wanted_purposes):
                distance = max(0.0, distance - PURPOSE_BONUS)
                detail["purpose_bonus"] = PURPOSE_BONUS

        detail["distance"] = round(distance, 4)
        scored.append((distance, t, detail))

    # 거리 오름차순. 동점은 track_id로 깨서 결과를 결정적으로 만든다.
    scored.sort(key=lambda x: (x[0], x[1]["track_id"]))
    chosen = _diversify(scored, limit)

    out_tracks: List[TrackRecommendation] = []
    for distance, t, detail in chosen:
        out_tracks.append(TrackRecommendation(
            track_id=t["track_id"],
            title=t.get("title") or "",
            title_ko=t.get("title_ko") or "",
            audio_url=audio_url(manifest, t["track_id"]),
            duration_sec=t.get("duration_sec"),
            bpm=t.get("bpm"),
            energy_level=t.get("energy_level"),
            valence=t.get("valence"),
            arousal=t.get("arousal"),
            genre_primary=t.get("genre_primary"),
            mood_primary=t.get("mood_primary"),
            vocal_type=t.get("vocal_type"),
            score=round(max(0.0, 1.0 - distance), 4),
            reason=_build_reason(t, slot_weights),
            match_detail=detail,
        ))

    logger.info(
        "music recommend: group=%s industry_matched=%s pool=%d → %d곡 (top score %.3f)",
        group, industry_matched, len(pool), len(out_tracks),
        out_tracks[0].score if out_tracks else 0.0,
    )

    return MusicRecommendation(
        tracks=out_tracks,
        playlist_label=_playlist_label([t for _, t, _ in chosen], business_type, slot_weights),
        target={
            "energy": ambience.energy,
            "tempo": ambience.tempo,
            "mood": ambience.mood,
            "density_preference": density_pref,
            "purpose_tags": wanted_purposes,
            "slot_weights": {k: round(v, 3) for k, v in slot_weights.items()},
            "industry_group": group,
            "industry_group_label": GROUP_LABELS_KO.get(group or "", ""),
        },
        industry_matched=industry_matched,
        pool_size=len(pool),
        notes=notes,
    )
