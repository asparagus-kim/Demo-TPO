"""음원 추천 로직 단위 테스트. 네트워크·외부 API 없음."""
from __future__ import annotations

import json

import pytest

from app.schemas import Ambience, TpoProfile
from app.services import music_service as ms


# --------------------------------------------------------------- 픽스처

def _track(tid, *, group="cafe", energy=4.0, bpm=90.0, valence=0.70, arousal=0.45,
           slots=("afternoon",), density=("normal",), purposes=("conversation",),
           genre="jazz_chill", mood="cozy", vocal="instrumental", unsuitable=()):
    return {
        "track_id": tid,
        "title": f"T-{tid}",
        "title_ko": "",
        "primary_group": group,
        "duration_sec": 180.0,
        "genre_primary": genre,
        "bpm": bpm,
        "energy_level": energy,
        "valence": valence,
        "arousal": arousal,
        "mood_primary": mood,
        "vocal_type": vocal,
        "suitable_industries": ["카페"] if group == "cafe" else ["헬스장"],
        "unsuitable_industries": list(unsuitable),
        "suitable_time_slots": list(slots),
        "customer_density_fit": list(density),
        "purpose_tags": list(purposes),
        "status": "draft",
        "review": "pending",
    }


def _write_manifest(tmp_path, tracks):
    p = tmp_path / "demo_tracks.json"
    p.write_text(json.dumps({
        "audio_base": "https://example.r2.dev",
        "audio_ext": ".mp3",
        "tracks": tracks,
    }, ensure_ascii=False), encoding="utf-8")
    ms.load_manifest.cache_clear()
    return str(p)


@pytest.fixture(autouse=True)
def _clear_cache():
    ms.load_manifest.cache_clear()
    yield
    ms.load_manifest.cache_clear()


# --------------------------------------------------------------- 업종 감지

@pytest.mark.parametrize("text,expected", [
    ("카페", "cafe"),
    ("커피전문점", "cafe"),
    ("베이커리 카페", "cafe"),
    ("체력단련장 운영업", "fitness"),
    ("헬스장", "fitness"),
    ("필라테스 스튜디오", "fitness"),
    ("음악 및 기타 오디오물 출판업", None),
    ("", None),
    (None, None),
])
def test_detect_industry_group(text, expected):
    assert ms.detect_industry_group(text) == expected


def test_detect_industry_group_uses_any_argument():
    # canonical이 비F&B 원문이어도 raw 쪽에서 힌트를 찾는다.
    assert ms.detect_industry_group("기타 스포츠시설", "헬스장 운영") == "fitness"


# --------------------------------------------------------------- Occasion 매핑

def test_purpose_tags_for_occasion():
    assert "workout" in ms.purpose_tags_for_occasion("운동 후 방문")
    assert "focus" in ms.purpose_tags_for_occasion("업무 미팅")
    assert ms.purpose_tags_for_occasion(None) == []
    assert ms.purpose_tags_for_occasion("알수없는라벨") == []


# --------------------------------------------------------------- 시간대 변환

def test_slot_weights_from_dayparts():
    w = ms.slot_weights_from_dayparts({"lunch": 1.0})
    assert w["lunch"] > w["brunch"] > 0
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_slot_weights_empty_when_no_signal():
    # compute_daypart_weights()는 영업시간이 없으면 전부 0을 돌려준다.
    assert ms.slot_weights_from_dayparts({k: 0.0 for k in ms.DAYPART_TO_SLOT}) == {}
    assert ms.slot_weights_from_dayparts(None) == {}


# --------------------------------------------------------------- 혼잡도

@pytest.mark.parametrize("energy,expected", [
    (85, "busy"), (70, "busy"), (55, "normal"), (45, "normal"), (30, "quiet"),
])
def test_preferred_density(energy, expected):
    assert ms.preferred_density(energy) == expected


# --------------------------------------------------------------- 핵심: 매장별 변별

def test_different_stores_get_different_top_track(tmp_path):
    """조용한 매장과 붐비는 매장이 서로 다른 곡을 1순위로 받아야 한다.

    이 데모의 핵심 증명(계획서 10.2.1) — 업종이 같아도 매장에 따라 달라진다.
    """
    tracks = [
        _track("LOW", energy=2.0, bpm=60.0, arousal=0.25, density=("quiet",)),
        _track("MID", energy=4.0, bpm=95.0, arousal=0.45, density=("normal",)),
        _track("HIGH", energy=6.0, bpm=129.0, arousal=0.65, density=("busy",)),
    ]
    path = _write_manifest(tmp_path, tracks)

    quiet = ms.recommend(
        Ambience(energy=20, tempo=15, mood=50),
        business_type="카페", limit=3, manifest_path=path,
    )
    busy = ms.recommend(
        Ambience(energy=95, tempo=95, mood=50),
        business_type="카페", limit=3, manifest_path=path,
    )

    assert quiet.tracks[0].track_id == "LOW"
    assert busy.tracks[0].track_id == "HIGH"
    assert quiet.tracks[0].score > 0.5


def test_flat_axis_is_ignored_not_crashed(tmp_path):
    """축이 상수면(피트니스 energy_level=8.0 전곡) 그 축은 점수에 기여하지 않는다."""
    tracks = [
        _track("A", group="fitness", energy=8.0, arousal=0.8, bpm=120.0, valence=0.75,
               slots=("evening",), density=("busy",)),
        _track("B", group="fitness", energy=8.0, arousal=0.8, bpm=160.0, valence=0.75,
               slots=("evening",), density=("busy",)),
    ]
    path = _write_manifest(tmp_path, tracks)

    rec = ms.recommend(
        Ambience(energy=80, tempo=10, mood=50),
        business_type="헬스장", limit=2, manifest_path=path,
    )
    # energy·mood는 상수라 무시되고, bpm만 변별 → 낮은 tempo 목표엔 120BPM이 1순위
    assert rec.tracks[0].track_id == "A"
    assert "energy" in " ".join(rec.notes)
    # 상수 축은 distance 항목 자체가 없어야 한다
    assert "energy_distance" not in rec.tracks[0].match_detail
    assert "tempo_distance" in rec.tracks[0].match_detail


def test_unsuitable_industry_is_hard_excluded(tmp_path):
    tracks = [
        _track("OK"),
        _track("BAD", unsuitable=("카페",)),
    ]
    path = _write_manifest(tmp_path, tracks)
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", limit=5, manifest_path=path)
    ids = [t.track_id for t in rec.tracks]
    assert "BAD" not in ids
    assert "OK" in ids


def test_industry_pool_relaxes_when_too_small(tmp_path):
    """전용 곡이 5곡 미만이면 전체로 확장하고 그 사실을 notes에 남긴다."""
    tracks = [_track("F1", group="fitness")] + [
        _track(f"C{i}", group="cafe") for i in range(6)
    ]
    path = _write_manifest(tmp_path, tracks)
    rec = ms.recommend(Ambience(energy=80, tempo=80, mood=60),
                       business_type="헬스장", limit=5, manifest_path=path)
    assert rec.industry_matched is False
    assert any("확장" in n for n in rec.notes)
    assert rec.pool_size == 7


def test_industry_pool_used_when_sufficient(tmp_path):
    tracks = [_track(f"F{i}", group="fitness") for i in range(6)] + [
        _track(f"C{i}", group="cafe") for i in range(6)
    ]
    path = _write_manifest(tmp_path, tracks)
    rec = ms.recommend(Ambience(energy=80, tempo=80, mood=60),
                       business_type="헬스장", limit=5, manifest_path=path)
    assert rec.industry_matched is True
    assert rec.pool_size == 6
    assert all(t.track_id.startswith("F") for t in rec.tracks)


def test_rejected_tracks_are_excluded(tmp_path):
    a, b = _track("KEEP"), _track("DROP")
    b["review"] = "reject"
    path = _write_manifest(tmp_path, [a, b])
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", limit=5, manifest_path=path)
    assert [t.track_id for t in rec.tracks] == ["KEEP"]


def test_genre_diversity_cap(tmp_path):
    """같은 장르가 결과를 독점하지 않는다 — 단, 개수는 채운다."""
    same = [_track(f"J{i}", genre="jazz_chill", mood=f"m{i}") for i in range(6)]
    other = [_track("E1", genre="edm_house", mood="driving")]
    path = _write_manifest(tmp_path, same + other)
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", limit=5, manifest_path=path)
    ids = [t.track_id for t in rec.tracks]
    assert len(ids) == 5                       # 상한 때문에 비지 않는다
    jazz = [i for i in ids if i.startswith("J")]
    assert len(jazz) >= ms.MAX_PER_GENRE       # 채우기 단계에서 초과 허용
    assert "E1" in ids                         # 다른 장르가 밀려나지 않는다


def test_deterministic_ordering(tmp_path):
    """동점이어도 순서가 고정 — 프리컴퓨트 시연 케이스의 재현성 전제."""
    tracks = [_track(f"T{i}") for i in range(5)]
    path = _write_manifest(tmp_path, tracks)
    kwargs = dict(business_type="카페", limit=5, manifest_path=path)
    first = ms.recommend(Ambience(energy=50, tempo=50, mood=50), **kwargs)
    second = ms.recommend(Ambience(energy=50, tempo=50, mood=50), **kwargs)
    assert [t.track_id for t in first.tracks] == [t.track_id for t in second.tracks]


def test_occasion_bonus_changes_ranking(tmp_path):
    """동일 스펙이면 Occasion과 맞는 purpose_tags를 가진 곡이 앞선다."""
    a = _track("PLAIN", purposes=("shopping",))
    b = _track("MATCH", purposes=("workout", "energize"))
    path = _write_manifest(tmp_path, [a, b])
    rec = ms.recommend(
        Ambience(energy=50, tempo=50, mood=50),
        TpoProfile(occasion_label="운동 후 방문"),
        business_type="카페", limit=2, manifest_path=path,
    )
    assert rec.tracks[0].track_id == "MATCH"
    assert rec.tracks[0].match_detail.get("purpose_bonus") == ms.PURPOSE_BONUS


def test_time_slot_affects_ranking(tmp_path):
    morning = _track("MORNING", slots=("morning",))
    evening = _track("EVENING", slots=("evening",))
    path = _write_manifest(tmp_path, [morning, evening])
    # 영업시간이 저녁에 몰린 매장
    rec = ms.recommend(
        Ambience(energy=50, tempo=50, mood=50),
        business_type="카페", limit=2, manifest_path=path,
        daypart_weights={"early_morning": 0.0, "lunch": 0.0, "afternoon": 0.0,
                         "dinner": 1.0, "late_night": 0.0},
    )
    assert rec.tracks[0].track_id == "EVENING"


def test_no_business_hours_means_no_time_penalty(tmp_path):
    tracks = [_track("A", slots=("morning",)), _track("B", slots=("late_night",))]
    path = _write_manifest(tmp_path, tracks)
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", limit=2, manifest_path=path,
                       daypart_weights=None)
    assert all("time_distance" not in t.match_detail for t in rec.tracks)
    assert any("영업시간" in n for n in rec.notes)


def test_missing_manifest_returns_empty_with_note(tmp_path):
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페",
                       manifest_path=str(tmp_path / "does_not_exist.json"))
    assert rec.tracks == []
    assert any("매니페스트" in n for n in rec.notes)


def test_audio_url_built_from_manifest(tmp_path):
    path = _write_manifest(tmp_path, [_track("YLD-1")])
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", manifest_path=path)
    assert rec.tracks[0].audio_url == "https://example.r2.dev/YLD-1.mp3"


# --------------------------------------------------------------- 표시 일관성

def test_matched_slots_filters_by_store_hours_and_orders_by_time():
    t = _track("X", slots=("evening", "lunch", "morning"))
    store = {"lunch": 0.5, "evening": 0.5}          # 아침엔 영업 안 함
    assert ms.matched_slots(t, store) == ["lunch", "evening"]
    # 매장 신호가 없으면 곡이 지원하는 전부를 시간 순서로
    assert ms.matched_slots(t, {}) == ["morning", "lunch", "evening"]


def test_playlist_label_slot_agrees_with_track_reasons(tmp_path):
    """라벨의 시간대가 상위 곡 근거에 반드시 등장해야 한다.

    회귀 방지: 라벨과 곡 근거가 서로 다른 규칙으로 대표 시간대를 뽑아
    라벨은 "오후", 근거는 "점심"으로 갈리는 버그가 두 차례 있었다.
    """
    tracks = [_track(f"T{i}", slots=("lunch", "afternoon")) for i in range(4)]
    tracks.append(_track("EVE", slots=("afternoon", "evening")))
    path = _write_manifest(tmp_path, tracks)
    rec = ms.recommend(
        Ambience(energy=50, tempo=50, mood=50),
        business_type="카페", limit=5, manifest_path=path,
        daypart_weights={"early_morning": 0.1, "lunch": 0.2, "afternoon": 0.2,
                         "dinner": 0.5, "late_night": 0.0},
    )
    label_slot = rec.playlist_label.split(" · ")[1].replace(" 시간대", "")
    assert label_slot in rec.tracks[0].reason, (
        f"라벨 시간대 '{label_slot}'가 1순위 곡 근거에 없음: {rec.tracks[0].reason}"
    )


def test_playlist_label_energy_word_matches_selected_tracks(tmp_path):
    """라벨의 에너지 표현은 매장 점수가 아니라 선정곡 평균에서 나와야 한다."""
    tracks = [_track(f"L{i}", energy=2.0, arousal=0.2, bpm=60.0) for i in range(3)]
    path = _write_manifest(tmp_path, tracks)
    # 매장 E는 매우 높지만 후보에는 조용한 곡만 있다 → 라벨이 "강한"이면 거짓
    rec = ms.recommend(Ambience(energy=95, tempo=95, mood=50),
                       business_type="카페", limit=3, manifest_path=path)
    assert rec.playlist_label.startswith("아주 조용한")


def test_reason_caps_slot_count(tmp_path):
    t = _track("MANY", slots=("morning", "brunch", "lunch", "afternoon"))
    path = _write_manifest(tmp_path, [t])
    rec = ms.recommend(Ambience(energy=50, tempo=50, mood=50),
                       business_type="카페", limit=1, manifest_path=path)
    # 2개까지만 보여주고 나머지는 '등'으로 축약
    assert "등 시간대에 적합" in rec.tracks[0].reason


# --------------------------------------------------------------- 실제 매니페스트

def test_real_manifest_end_to_end():
    """저장된 data/demo_tracks.json으로 카페·피트니스가 다른 곡군을 받는지."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다 (curate_demo_tracks.py 먼저 실행)")

    cafe = ms.recommend(
        Ambience(energy=45, tempo=40, mood=78),
        TpoProfile(occasion_label="점심 커피"),
        business_type="카페", limit=10,
        daypart_weights={"early_morning": 0.2, "lunch": 0.3, "afternoon": 0.3,
                         "dinner": 0.2, "late_night": 0.0},
    )
    fitness = ms.recommend(
        Ambience(energy=88, tempo=85, mood=60),
        TpoProfile(occasion_label="운동"),
        business_type="헬스장", limit=10,
        daypart_weights={"early_morning": 0.1, "lunch": 0.1, "afternoon": 0.3,
                         "dinner": 0.4, "late_night": 0.1},
    )

    assert len(cafe.tracks) == 10 and len(fitness.tracks) == 10
    assert cafe.industry_matched and fitness.industry_matched
    # 업종 간 대비가 실제로 나오는지 — 겹치는 곡이 없어야 한다
    assert not ({t.track_id for t in cafe.tracks} & {t.track_id for t in fitness.tracks})
    # 피트니스가 더 빠른 곡을 받아야 한다
    cafe_bpm = [t.bpm for t in cafe.tracks if t.bpm]
    fit_bpm = [t.bpm for t in fitness.tracks if t.bpm]
    assert sum(fit_bpm) / len(fit_bpm) > sum(cafe_bpm) / len(cafe_bpm)
    # 모든 곡이 재생 가능한 URL을 갖는다
    assert all(t.audio_url.startswith("https://") for t in cafe.tracks)
    assert all(t.reason for t in cafe.tracks)


# --------------------------------------------------------------- 업종군 확대 (11군)

def test_industry_tokens_cover_source_vocabulary():
    """곡 토큰 어휘가 닫혀 있다는 전제를 지킨다 — 미매핑 토큰이 생기면 실패."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다")
    mapped = {tok for toks in ms.INDUSTRY_TOKENS.values() for tok in toks}
    seen = {tok for t in manifest["tracks"] for tok in (t.get("suitable_industries") or [])}
    unmapped = seen - mapped - set(ms.SEASONAL_TOKENS)
    assert not unmapped, f"INDUSTRY_TOKENS에 없는 토큰: {sorted(unmapped)}"


def test_groups_for_track_is_exact_match_not_substring():
    """'카페'가 '키즈카페'까지 끌어오면 유아용 곡이 일반 카페 풀에 섞인다."""
    kids, _ = ms.groups_for_track(["키즈카페", "아동복매장"])
    assert kids == ["kids"]
    cafe, _ = ms.groups_for_track(["카페"])
    assert cafe == ["cafe"]


def test_groups_for_track_multi_group_and_unsuitable():
    good, bad = ms.groups_for_track(
        ["카페", "바", "서점"], ["헬스장", "스파"],
    )
    assert good == ["cafe", "bar", "culture"]
    # 부적합 토큰이 가리키는 군은 따로 잡아 둔다 (런타임 하드 배제에 쓴다).
    assert bad == ["fitness", "beauty"]


def test_groups_for_track_unsuitable_wins_over_suitable():
    good, bad = ms.groups_for_track(["카페", "헬스장"], ["헬스장"])
    assert good == ["cafe"] and bad == ["fitness"]


def test_is_seasonal_only():
    assert ms.is_seasonal_only(["12월 전 업종"])
    assert not ms.is_seasonal_only(["12월 전 업종", "카페"])
    assert not ms.is_seasonal_only([])


@pytest.mark.parametrize("text,expected", [
    # Kakao category_name 실측 형태 — 대분류가 섞여 있어도 세부 업종이 이겨야 한다.
    ("음식점 > 카페 > 커피전문점", "cafe"),
    ("음식점 > 술집 > 호프,요리주점", "bar"),
    ("음식점 > 한식 > 육류,고기", "dining"),
    ("생활,서비스 > 미용 > 미용실", "beauty"),
    ("생활,서비스 > 미용 > 네일샵", "beauty"),
    ("가정,생활 > 편의점", "convenience"),
    ("문화,예술 > 도서 > 서점", "culture"),
    ("여행 > 숙박 > 호텔", "lodging"),
    ("가정,생활 > 애견,애완 > 애견카페", "cafe"),
    ("서비스,산업 > 헤어케어", "beauty"),
    ("쇼핑,판매 > 의류 > 여성의류", "retail"),
    ("음식점 > 카페 > 키즈카페", "kids"),
    ("스포츠,레저 > 스포츠시설 > 헬스클럽", "fitness"),
])
def test_detect_industry_group_expanded(text, expected):
    assert ms.detect_industry_group(text) == expected


def test_unsuitable_groups_hard_excludes_across_naming(tmp_path):
    """canonical('피트니스')과 곡 토큰('헬스장')이 달라도 부적합이 걸려야 한다."""
    ok = _track("OK", group="fitness")
    ok["groups"] = ["fitness"]
    bad = _track("BAD", group="fitness")
    bad["groups"] = ["fitness"]
    bad["unsuitable_groups"] = ["fitness"]
    others = []
    for i in range(5):
        t = _track(f"F{i}", group="fitness")
        t["groups"] = ["fitness"]
        others.append(t)
    path = _write_manifest(tmp_path, [ok, bad] + others)
    rec = ms.recommend(Ambience(energy=80, tempo=80, mood=60),
                       business_type="피트니스", limit=10, manifest_path=path)
    ids = [t.track_id for t in rec.tracks]
    assert "BAD" not in ids and "OK" in ids


def test_track_groups_reads_legacy_primary_group():
    assert ms.track_groups({"primary_group": "cafe"}) == ["cafe"]
    assert ms.track_groups({"groups": ["cafe", "bar"]}) == ["cafe", "bar"]
    assert ms.track_groups({}) == []


def test_real_manifest_every_group_has_a_usable_pool():
    """11개 업종군 전부가 전용 풀로 추천될 만큼 곡을 갖고 있는지."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다")
    counts = {g: 0 for g in ms.INDUSTRY_TOKENS}
    for t in manifest["tracks"]:
        for g in ms.track_groups(t):
            counts[g] += 1
    thin = {g: n for g, n in counts.items() if n < ms.MIN_POOL_SIZE}
    assert not thin, f"전용 풀이 부족한 업종군: {thin}"


def test_real_manifest_has_no_seasonal_tracks():
    """크리스마스 곡이 8월 시연에 나오면 오작동으로 보인다."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다")
    seasonal = [t["track_id"] for t in manifest["tracks"]
                if ms.is_seasonal_only(t.get("suitable_industries") or [])]
    assert not seasonal, f"계절 한정 곡이 매니페스트에 있습니다: {seasonal[:5]}"


@pytest.mark.parametrize("business_type,raw", [
    ("미용실", "미용실 생활,서비스 > 미용 > 미용실"),
    ("서점", "서점 문화,예술 > 도서 > 서점"),
    ("주점/바", "호프 음식점 > 술집 > 호프,요리주점"),
    ("편의점", "편의점 가정,생활 > 편의점"),
])
def test_real_manifest_non_pilot_industries_get_own_pool(business_type, raw):
    """카페·피트니스 외 업종도 전용 곡군으로 추천되는지 (확대 전에는 전부 실패했다)."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다")
    rec = ms.recommend(
        Ambience(energy=50, tempo=48, mood=72),
        business_type=business_type, raw_business_type=raw, limit=10,
    )
    assert rec.industry_matched is True, rec.notes
    assert len(rec.tracks) == 10
    assert rec.target["industry_group_label"]


def test_real_manifest_industry_pools_differ():
    """서점(정숙)과 바(고에너지)가 같은 곡을 받으면 업종 분리가 무의미하다."""
    manifest = ms.load_manifest()
    if not manifest.get("tracks"):
        pytest.skip("data/demo_tracks.json 이 없습니다")
    books = ms.recommend(Ambience(energy=32, tempo=30, mood=62),
                         business_type="서점", limit=10)
    bar = ms.recommend(Ambience(energy=84, tempo=70, mood=72),
                       business_type="주점/바", limit=10)
    assert not ({t.track_id for t in books.tracks} & {t.track_id for t in bar.tracks})
    b_bpm = [t.bpm for t in bar.tracks if t.bpm]
    k_bpm = [t.bpm for t in books.tracks if t.bpm]
    assert sum(b_bpm) / len(b_bpm) > sum(k_bpm) / len(k_bpm)
