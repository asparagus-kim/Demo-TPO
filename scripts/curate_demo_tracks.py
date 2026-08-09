"""시연용 음원 매니페스트를 생성한다.

결과는 data/demo_tracks.json 하나로, 매칭에 필요한 메타데이터를 자체 포함한다
(런타임에 원본 폴더를 참조하지 않음).

기본 동작은 **재생 가능한 전곡 수록**이다. 처음에는 파일럿 2업종(카페·피트니스)
40~60곡만 뽑았는데, D2D 현장에서 미용실·서점·바 같은 업종이 들어오면 업종군을
못 정해 카페 곡이 추천되는 문제가 있었다 (2026-08-05 실측: 헤어케어 매장 →
`industry_group=None`, 1위 곡이 카페용 재즈). 원본에는 미용실 75곡·바 173곡처럼
해당 업종 곡이 이미 있었고 매니페스트가 좁은 것이 유일한 원인이었다.

제외 기준은 두 개뿐이다.
    · Drive 링크 없음      → R2에 음원이 없어 재생 불가
    · 계절 한정(12월) 단독  → 크리스마스 곡이 8월 시연에 나오면 오작동으로 보인다

사용법:
    python scripts/curate_demo_tracks.py                    # 전곡
    python scripts/curate_demo_tracks.py --limit 60         # 업종군 균형 서브셋
    python scripts/curate_demo_tracks.py --tracks <경로>     # 원본 위치 지정

계획서 10.2 참조. 사람 검수(10.3)는 review 필드로 별도 관리한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ⚠ `tracks.json`이 아니라 `data.js`가 정본이다.
#   tracks.json = 225곡 (구버전, README상 "참고용")
#   data.js     = 664곡 (플레이어가 실제로 읽는 인라인 데이터, 배포본과 동일)
#   차이는 20260617(208곡) + 20260618(231곡) 배치. 2026-08-05 실측 확인.
DEFAULT_TRACKS = (
    PROJECT_ROOT.parent / "yieldus_player_founder" / "yieldus-player" / "data.js"
)
OUT_PATH = PROJECT_ROOT / "data" / "demo_tracks.json"

# 업종군 매핑은 추천 서비스와 **같은 상수**를 쓴다. 그래야 큐레이션(매니페스트에
# 넣는 groups)과 추천(후보 풀 필터)이 어긋나지 않는다.
from app.services.music_service import (  # noqa: E402
    GROUP_LABELS_KO,
    INDUSTRY_TOKENS as INDUSTRY_GROUPS,
    groups_for_track,
    is_seasonal_only,
)

TIME_SLOTS = ["morning", "brunch", "lunch", "afternoon", "evening", "late_night"]
DENSITIES = ["quiet", "normal", "busy"]

# 업종군별로 "덮여 있어야 정상"인 시간대. 심야 영업이 드문 업종(카페·헬스장)에
# late_night 곡이 0인 것은 메타데이터가 합리적으로 붙은 결과이므로 결함이 아니다.
EXPECTED_SLOTS = {
    "cafe":        ["morning", "brunch", "lunch", "afternoon", "evening"],
    "fitness":     ["morning", "afternoon", "evening"],
    "beauty":      ["morning", "afternoon", "evening"],
    "retail":      ["lunch", "afternoon", "evening"],
    "dining":      ["lunch", "afternoon", "evening"],
    "bar":         ["evening", "late_night"],
    "lodging":     ["morning", "afternoon", "evening", "late_night"],
    "culture":     ["afternoon", "evening"],
    "kids":        ["brunch", "lunch", "afternoon"],
    "convenience": ["morning", "afternoon", "evening"],
    "office":      ["morning", "lunch", "afternoon"],
}

# --- 아래는 `--limit` 을 준 서브셋 모드에서만 쓴다 (기본은 전곡 수록) ---

# 선정 목표 비율. 지정하지 않은 군은 남은 몫을 균등 분배받는다.
GROUP_QUOTA = {"cafe": 0.25, "fitness": 0.20}

# 업종별로 무게를 두는 에너지 구간.
ENERGY_BANDS = {"low": (2.0, 4.0), "mid": (4.01, 6.0), "high": (6.01, 10.0)}
_DEFAULT_BAND_WEIGHT = {"low": 1.0, "mid": 1.0, "high": 1.0}
GROUP_BAND_WEIGHT = {
    "cafe":    {"low": 1.0, "mid": 1.0, "high": 0.4},
    "fitness": {"low": 0.3, "mid": 1.0, "high": 1.0},
    "bar":     {"low": 0.4, "mid": 1.0, "high": 1.0},
    "culture": {"low": 1.0, "mid": 0.8, "high": 0.3},
    "beauty":  {"low": 0.8, "mid": 1.0, "high": 0.6},
    "lodging": {"low": 1.0, "mid": 0.9, "high": 0.4},
}

DRIVE_ID_RE = re.compile(r"/file/d/([A-Za-z0-9_-]+)")


def split_field(value) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def drive_file_id(path: str | None) -> str | None:
    if not path or "drive.google" not in path:
        return None
    m = DRIVE_ID_RE.search(path)
    return m.group(1) if m else None


TRACKS_JS_RE = re.compile(r"window\.TRACKS\s*=\s*(\[.*?\]);", re.S)


def load_tracks(path: Path) -> list[dict]:
    """`data.js`(window.TRACKS = [...]) 또는 `tracks.json` 둘 다 읽는다."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return json.loads(text)
    m = TRACKS_JS_RE.search(text)
    if not m:
        raise ValueError(f"{path} 에서 window.TRACKS 배열을 찾지 못했습니다.")
    return json.loads(m.group(1))


def energy_band(level) -> str | None:
    if not isinstance(level, (int, float)):
        return None
    for name, (lo, hi) in ENERGY_BANDS.items():
        if lo <= level <= hi:
            return name
    return None


def industry_groups(track: dict) -> tuple[list[str], list[str]]:
    """곡의 (적합 업종군, 부적합 업종군). 매핑 자체는 music_service가 정본이다."""
    return groups_for_track(
        split_field(track.get("suitable_industries")),
        split_field(track.get("unsuitable_industries")),
    )


def track_score(track: dict, group: str) -> float:
    """같은 셀 안에서 어느 곡을 먼저 뽑을지 정하는 점수 (높을수록 우선)."""
    score = 0.0
    band = energy_band(track.get("energy_level"))
    if band:
        weights = GROUP_BAND_WEIGHT.get(group, _DEFAULT_BAND_WEIGHT)
        score += weights.get(band, 0.5) * 2.0
    # 매장 BGM은 가사가 튀지 않는 연주곡이 안전하다 (full_vocal 203곡이라 희소 가치).
    if track.get("vocal_type") == "instrumental":
        score += 1.5
    if track.get("status") == "approved":
        score += 1.0
    q = track.get("quality_score")
    if isinstance(q, (int, float)):
        score += q / 10.0
    # 메타가 촘촘한 곡을 선호 — 추천 근거 문구를 만들 재료가 많다.
    for f in ("mood_primary", "purpose_tags", "customer_density_fit", "bpm"):
        if track.get(f):
            score += 0.2
    return score


def build_pool(tracks: list[dict]) -> tuple[list[tuple], Counter, Counter]:
    """매니페스트 후보. 재생 불가 곡과 계절 한정 곡만 걸러낸다."""
    pool: list[tuple] = []
    skipped: Counter = Counter()
    unmapped: Counter = Counter()
    mapped_tokens = {tok for toks in INDUSTRY_GROUPS.values() for tok in toks}
    for t in tracks:
        fid = drive_file_id(t.get("audio_file_path"))
        if not fid:
            # Drive 링크가 없으면 R2에도 음원이 없다 (2026-08-05 실측 13곡).
            skipped["재생불가_drive_link_없음"] += 1
            continue
        suitable = split_field(t.get("suitable_industries"))
        if is_seasonal_only(suitable):
            skipped["계절한정_12월_전용"] += 1
            continue
        for tok in suitable:
            if tok not in mapped_tokens:
                unmapped[tok] += 1
        groups, bad_groups = industry_groups(t)
        if not groups:
            skipped["업종군_미매핑"] += 1
            continue
        pool.append((t, fid, groups, bad_groups))
    return pool, skipped, unmapped


def curate_all(pool: list[tuple]) -> tuple[list[dict], dict]:
    """전곡 수록. 곡마다 소속 업종군 전체를 담는다."""
    selected = [_manifest_entry(t, fid, groups, bad) for t, fid, groups, bad in pool]
    return selected, {"mode": "all"}


def curate_subset(pool: list[tuple], limit: int) -> tuple[list[dict], dict]:
    """업종군 쿼터 × (시간대, 에너지구간) 라운드로빈으로 균형 서브셋을 뽑는다.

    업종군별 풀 크기 차이(cafe 284 vs kids 31)가 선정 비율을 지배하지 않게
    하는 것이 목적이다. 전곡 수록이 기본이므로 `--limit` 을 줄 때만 쓴다.
    """
    cells: dict[str, dict[tuple, list]] = {g: defaultdict(list) for g in INDUSTRY_GROUPS}
    entry_of: dict[str, tuple] = {}
    for t, fid, groups, bad in pool:
        entry_of[t["track_id"]] = (t, fid, groups, bad)
        slots = [s for s in split_field(t.get("suitable_time_slots")) if s in TIME_SLOTS]
        if not slots:
            slots = ["afternoon"]
        band = energy_band(t.get("energy_level")) or "unknown"
        for g in groups:
            for s in slots:
                cells[g][(s, band)].append((track_score(t, g), t, fid))

    for g in cells:
        for key in cells[g]:
            cells[g][key].sort(key=lambda x: -x[0])

    # 그룹별 목표치. 풀이 쿼터보다 작으면 그만큼만 뽑고 남은 몫은 다른 그룹에 넘긴다.
    group_pool_size = {g: len({t["track_id"] for _, t, _ in
                               [x for b in cells[g].values() for x in b]})
                       for g in cells}
    # GROUP_QUOTA에 없는 군은 남은 비율을 균등 분배받는다 (한 군도 빠지지 않게).
    rest = [g for g in INDUSTRY_GROUPS if g not in GROUP_QUOTA]
    share = max(0.0, 1.0 - sum(GROUP_QUOTA.values())) / len(rest) if rest else 0.0
    ratios = {**GROUP_QUOTA, **{g: share for g in rest}}
    targets: dict[str, int] = {}
    for g, ratio in ratios.items():
        targets[g] = min(int(round(limit * ratio)), group_pool_size.get(g, 0))
    leftover = limit - sum(targets.values())
    if leftover > 0:
        for g in sorted(targets, key=lambda x: -(group_pool_size.get(x, 0) - targets[x])):
            room = group_pool_size.get(g, 0) - targets[g]
            take = min(room, leftover)
            targets[g] += take
            leftover -= take
            if leftover <= 0:
                break

    chosen: dict[str, dict] = {}
    per_group: dict[str, int] = {g: 0 for g in cells}

    for g in cells:
        ordered = sorted(
            cells[g].keys(),
            key=lambda k: (TIME_SLOTS.index(k[0]), k[1]),
        )
        round_no = 0
        while per_group[g] < targets.get(g, 0):
            added = 0
            for key in ordered:
                if per_group[g] >= targets.get(g, 0):
                    break
                bucket = cells[g][key]
                if round_no >= len(bucket):
                    continue
                _, t, fid = bucket[round_no]
                tid = t["track_id"]
                if tid in chosen:
                    continue
                _, _, groups, bad = entry_of[tid]
                chosen[tid] = _manifest_entry(t, fid, groups, bad)
                per_group[g] += 1
                added += 1
            if added == 0:
                break
            round_no += 1

    stats = {
        "mode": f"subset(limit={limit})",
        "group_pool_size": group_pool_size,
        "targets": targets,
        "cells": sum(len(v) for v in cells.values()),
    }
    return list(chosen.values()), stats


def _manifest_entry(t: dict, drive_id: str, groups: list[str], bad_groups: list[str]) -> dict:
    """매칭에 실제로 쓰는 필드만 남긴다.

    warmth / sophistication / quality_score 는 극소수 곡만 채워져 있어
    매칭 축으로 쓸 수 없으므로 매니페스트에 넣지 않는다 (계획서 5.2).
    suitable_weather 도 전곡이 'any' 라 변별력이 없어 제외한다.

    `groups`는 곡이 속한 업종군 **전체**다. 한 곡이 카페와 바에 모두 맞을 수
    있으므로 단일 `primary_group`으로는 표현할 수 없다.
    """
    return {
        "track_id": t["track_id"],
        "title": t.get("title") or "",
        "title_ko": t.get("title_ko") or "",
        "drive_file_id": drive_id,
        "groups": groups,
        "unsuitable_groups": bad_groups,
        "duration_sec": t.get("duration_sec"),
        "genre_primary": t.get("genre_primary"),
        "genre_secondary": t.get("genre_secondary"),
        "bpm": t.get("bpm"),
        "energy_level": t.get("energy_level"),
        "valence": t.get("valence"),
        "arousal": t.get("arousal"),
        "mood_primary": t.get("mood_primary"),
        "mood_secondary": t.get("mood_secondary"),
        "vocal_type": t.get("vocal_type"),
        "suitable_industries": split_field(t.get("suitable_industries")),
        "unsuitable_industries": split_field(t.get("unsuitable_industries")),
        "suitable_time_slots": split_field(t.get("suitable_time_slots")),
        "customer_density_fit": split_field(t.get("customer_density_fit")),
        "purpose_tags": split_field(t.get("purpose_tags")),
        "status": t.get("status"),
        "rights_status": t.get("rights_status"),
        "review": "pending",   # 10.3 사람 검수 상태: pending | ok | reject
    }


def report(selected: list[dict], stats: dict) -> None:
    print("=" * 72)
    print(f"모드 {stats['mode']} / 후보 풀 {stats['pool']}곡 → 수록 {len(selected)}곡")
    if stats["skipped"]:
        print("제외:")
        for k, v in stats["skipped"].items():
            print(f"  {v:4d}  {k}")
    if stats["unmapped"]:
        print("경고: INDUSTRY_TOKENS에 없는 적합업종 토큰이 있습니다 — 매핑을 추가하세요.")
        for k, v in stats["unmapped"].items():
            print(f"  {v:4d}  {k!r}")
    print("=" * 72)

    gaps: list[str] = []
    print(f"\n{'업종군':<14}{'곡수':>5}  {'시간대 미커버':<22}{'에너지 low/mid/high':<22}보컬(inst)")
    print("-" * 72)
    for g in INDUSTRY_GROUPS:
        rows = [t for t in selected if g in t["groups"]]
        if not rows:
            print(f"{g:<14}{0:>5}  (수록 곡 없음)")
            continue
        slot_count: Counter = Counter()
        for t in rows:
            for s in t["suitable_time_slots"]:
                if s in TIME_SLOTS:
                    slot_count[s] += 1
        missing = [s for s in EXPECTED_SLOTS.get(g, []) if not slot_count[s]]
        gaps += [f"{g}/{s}" for s in missing]

        band_count = Counter(energy_band(t.get("energy_level")) for t in rows)
        bands = "/".join(str(band_count[b]) for b in ("low", "mid", "high"))
        inst = sum(1 for t in rows if t["vocal_type"] == "instrumental")
        label = GROUP_LABELS_KO.get(g, g)
        print(f"{g:<14}{len(rows):>5}  {(','.join(missing) or '-'):<22}{bands:<22}"
              f"{inst}/{len(rows)}   {label}")

    print("-" * 72)
    dens: Counter = Counter()
    for t in selected:
        for d in t["customer_density_fit"]:
            dens[d] += 1
    print("혼잡도 커버: " + " / ".join(f"{d} {dens[d]}곡" for d in DENSITIES))
    multi = sum(1 for t in selected if len(t["groups"]) > 1)
    print(f"복수 업종군 소속: {multi}곡 / 단일 {len(selected) - multi}곡")

    if gaps:
        # 전곡 수록 모드에서 남는 미커버는 **원본 라이브러리의 커버리지 한계**다
        # (예: 전체 664곡 중 lunch 태그가 104곡뿐). 곡을 더 넣어 해결할 수 없고,
        # 시간 축 가중치가 0.15라 추천이 실패하지도 않는다. 참고 정보로만 남긴다.
        print(f"\n참고: 원본 라이브러리에 없어 미커버인 (업종군/시간대) — {gaps}")
    else:
        print("\n모든 업종군의 기대 시간대가 커버되었습니다.")
    print("review=pending 은 사람 검수 전입니다 — 부적합 곡은 review=reject 로 바꾸면 "
          "런타임에서 자동 제외됩니다 (계획서 10.3).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracks", type=Path, default=DEFAULT_TRACKS)
    ap.add_argument("--limit", type=int, default=0,
                    help="0(기본)이면 재생 가능한 전곡 수록. 양수면 업종군 균형 서브셋.")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    if not args.tracks.exists():
        print(f"원본 트랙 파일을 찾을 수 없습니다: {args.tracks}")
        print("--tracks 로 경로를 지정하세요.")
        return 2

    tracks = load_tracks(args.tracks)
    print(f"원본 {len(tracks)}곡 로드: {args.tracks.name}")

    pool, skipped, unmapped = build_pool(tracks)
    if not pool:
        print("후보가 없습니다. 필터 조건을 확인하세요.")
        return 1

    if args.limit and args.limit > 0:
        selected, stats = curate_subset(pool, args.limit)
    else:
        selected, stats = curate_all(pool)
    stats.update(pool=len(pool), skipped=dict(skipped), unmapped=dict(unmapped))

    report(selected, stats)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_from": str(args.tracks),
        "source_track_count": len(tracks),
        "audio_base": "https://pub-166e7759980e41b59821fcd472181ea7.r2.dev",
        "audio_ext": ".mp3",
        "note": "review=pending 인 곡은 사람 검수 전입니다 (계획서 10.3).",
        "tracks": selected,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n매니페스트 저장: {args.out}  ({len(selected)}곡)")
    print("다음: scripts/fetch_demo_audio.py 로 Drive→R2 이전")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
