"""Kakao Local 매핑·후보 선택 단위 테스트. 네트워크 없음."""
from __future__ import annotations

import pytest

from app.schemas import PlaceCandidate
from app.services import kakao_local_service as K


def doc(name, *, x="127.0", y="37.5", cat="음식점 > 카페 > 커피전문점",
        group="CE7", road="서울 마포구 성미산로 128", addr="서울 마포구 성산동 1"):
    return {
        "id": "1", "place_name": name, "category_name": cat,
        "category_group_code": group, "phone": "02-0000-0000",
        "address_name": addr, "road_address_name": road,
        "x": x, "y": y, "place_url": "https://place.map.kakao.com/1",
    }


# ---------------------------------------------------------------- 좌표

def test_x_is_longitude_y_is_latitude():
    """뒤바꾸면 상권 매칭·날씨가 전부 틀리는데 조용히 실패한다 — 회귀 방지."""
    loc = K._to_location(doc("x", x="127.026874", y="37.498341"))
    assert loc == {"lat": 37.498341, "lng": 127.026874}
    assert loc["lat"] < loc["lng"], "한국에서 위도(33~39) < 경도(124~132)"


def test_to_location_handles_bad_values():
    assert K._to_location({"x": None, "y": None}) is None
    assert K._to_location({"x": "", "y": "abc"}) is None
    assert K._to_location({}) is None


# ---------------------------------------------------------------- 업종 추출

@pytest.mark.parametrize("cat,place,expected", [
    ("음식점 > 카페 > 커피전문점", "별빛카페 달빛차", "커피전문점"),
    ("음식점 > 카페", "카페민", "카페"),
    # 말단이 브랜드명이면(= 매장명에 그 토큰이 있으면) 그 앞 토큰을 쓴다
    ("음식점 > 카페 > 커피전문점 > 스타벅스", "스타벅스 강남R점", "커피전문점"),
    # 실측 회귀: '헬스클럽'을 브랜드로 오판해 '스포츠시설'을 뽑으면
    # 음원 업종군 매칭이 실패해 헬스장에 카페 곡이 추천된다.
    ("스포츠,레저 > 스포츠시설 > 헬스클럽", "아크로짐 홍대점24시휘트니스", "헬스클럽"),
    ("스포츠,레저 > 스포츠시설 > 헬스클럽", "어게인짐 건대입구역점", "헬스클럽"),
    ("", "", ""),
])
def test_business_type_from_category(cat, place, expected):
    assert K.business_type_from_category(cat, place) == expected


def test_business_type_two_level_not_collapsed_by_place_name():
    """'음식점 > 카페' + 매장명 '카페민' 이 '음식점'으로 올라가면 안 된다."""
    assert K.business_type_from_category("음식점 > 카페", "카페민") == "카페"


def test_fitness_category_maps_to_music_group():
    """업종군 판별까지 이어지는지 — 여기서 끊기면 카페 곡이 추천된다."""
    from app.services import ambience_service as A
    from app.services import music_service as M
    cat = "스포츠,레저 > 스포츠시설 > 헬스클럽"
    btype = K.business_type_from_category(cat, "아크로짐 홍대점24시휘트니스")
    canon = A.classify_business_type(btype)
    assert canon == "피트니스"
    assert M.detect_industry_group(canon, f"{btype} {cat}") == "fitness"


def test_category_tokens_includes_group_code():
    toks = K.category_tokens("음식점 > 카페 > 커피전문점", "CE7")
    assert "카페" in toks and "CE7" in toks


# ---------------------------------------------------------------- 점수 (핵심)

@pytest.mark.parametrize("query,place", [
    # 2026-08-05 실측 오탐 3종. partial_ratio/token_set_ratio 를 쓰면 전부 1.00 이 되어
    # 정답 매장이 동점에 묻혀 3위로 밀렸다.
    ("카페민", "마을카페민"),
    ("달달한카페", "달달한 오늘"),
    ("제이카페", "메리제이플라워카페"),
    ("송화의카페", "송화"),
])
def test_partial_match_must_not_score_full(query, place):
    exact = K.name_score(query, query)
    partial = K.name_score(query, place)
    assert exact == pytest.approx(1.0)
    assert partial < 0.95, f"{query} vs {place} = {partial} — 부분 일치가 만점을 받았다"
    assert partial < exact


def test_exact_and_whitespace_variants_score_full():
    assert K.name_score("헬카페스피리터스", "헬카페 스피리터스") == pytest.approx(1.0)
    assert K.name_score("별빛카페달빛차", "별빛카페 달빛차") == pytest.approx(1.0)


def test_type_affix_difference_still_matches():
    """bizno '더노라（The Nora）' vs Kakao '카페더노라' 처럼 업종 접두어만 다른 경우."""
    assert K.name_score("더노라", "카페더노라") >= 0.9


def test_word_order_difference_matches():
    assert K.name_score("별빛카페 달빛차", "달빛차 별빛카페") >= 0.9


def test_empty_names_score_zero():
    assert K.name_score("", "카페") == 0.0
    assert K.name_score("카페", "") == 0.0


# ---------------------------------------------------------------- 지점명 → 지역 힌트
#
# bizno 무료 플랜은 주소를 주지 않지만 상호명에 지점명이 들어 있는 경우가 많다.
# 그게 유일한 자동 지역 힌트다.

@pytest.mark.parametrize("name,expected", [
    ("아크로짐 홍대점 24시 휘트니스", "홍대"),
    ("어게인짐 건대입구역점", "건대입구역"),
    ("파리바게뜨 신촌지점", "신촌"),
    # 지역이 아닌 '점'은 제외한다
    ("투썸플레이스 본점", ""),
    ("메가커피 1호점", ""),
    # 지점명이 없으면 빈 문자열
    ("몸가짐휘트니스", ""),
    ("별빛카페달빛차", ""),
    ("", ""),
])
def test_extract_branch_hint(name, expected):
    assert K.extract_branch_hint(name) == expected


def test_branch_hint_boosts_same_region_candidate():
    """지점명이 있으면 그 지역 후보가 1위로 올라와야 한다."""
    c = K.score_candidates("어게인짐 건대입구역점", _cands([
        ("어게인짐", "부산 해운대구 센텀중앙로 55"),
        ("어게인짐 건대입구역점", "서울 광진구 아차산로 214"),
    ]), branch_hint="건대입구역")
    assert "광진구" in c[0].address


def test_branch_hint_discriminates_between_branches():
    """같은 브랜드의 다른 지점을 가릴 수 있어야 한다 — 이게 지점 힌트의 본래 용도다.

    주의: 지점명은 '건대입구역'·'홍대'처럼 통칭 지명이라 도로명 주소에는 나타나지
    않는다. 따라서 변별력은 후보 **매장명**에서 나온다.
    """
    c = K.score_candidates("아크로짐 홍대점", _cands([
        ("아크로짐 강남점", "서울 강남구 테헤란로 1"),
        ("아크로짐 홍대점", "서울 마포구 월드컵북로 30"),
    ]), branch_hint="홍대")
    assert c[0].place_name == "아크로짐 홍대점"
    assert c[0].score > c[1].score


# ---------------------------------------------------------------- 정렬·선택

def _cands(pairs):
    return [PlaceCandidate(place_name=n, address=a) for n, a in pairs]


def test_score_candidates_sorts_correct_one_first():
    c = K.score_candidates("달달한카페", _cands([
        ("달달한 오늘", "경기 화성시"), ("달달한카페", "서울 노원구"), ("달달한날", "경남 창원시"),
    ]))
    assert c[0].place_name == "달달한카페"


def test_address_hint_boosts_matching_region():
    c = K.score_candidates("카페민", _cands([
        ("카페민", "부산 금정구 장전로20번길 27"),
        ("카페민", "서울 노원구 동일로184길 6"),
    ]), address_hint="서울 노원구 동일로")
    assert "노원구" in c[0].address


def test_pick_best_auto_when_clear_winner():
    c = K.score_candidates("헬카페스피리터스", _cands([
        ("헬카페스피리터스", "서울 용산구"), ("헬카페", "서울 마포구"),
    ]))
    best, why = K.pick_best(c)
    assert why == "auto" and best.place_name == "헬카페스피리터스"


def test_pick_best_ambiguous_when_tied():
    """동명 매장이 여러 지역에 실존하면 자동 확정하지 않는다 (정보 부족)."""
    c = K.score_candidates("카페민", _cands([
        ("카페민", "서울 노원구"), ("카페민", "부산 금정구"), ("카페민", "인천 강화군"),
    ]))
    best, why = K.pick_best(c)
    assert best is None and why == "ambiguous"


def test_pick_best_single_hit_uses_lower_bar():
    c = K.score_candidates("카페더노라", _cands([("더노라", "서울 마포구")]))
    best, why = K.pick_best(c)
    assert why == "auto" and best is not None


def test_pick_best_rejects_low_score():
    c = K.score_candidates("별빛카페달빛차", _cands([("전혀다른이름", "서울 강남구")]))
    best, why = K.pick_best(c)
    assert best is None and why == "low_score"


def test_pick_best_empty():
    assert K.pick_best([]) == (None, "empty")


# ---------------------------------------------------------------- 문서 → 후보

def test_doc_to_candidate_maps_all_fields():
    c = K._doc_to_candidate(doc("별빛카페 달빛차"))
    assert c.place_name == "별빛카페 달빛차"
    assert c.business_type == "커피전문점"
    assert c.category_group_code == "CE7"
    assert c.address == "서울 마포구 성미산로 128"      # 도로명 우선
    assert c.location["lat"] == 37.5


def test_doc_to_candidate_falls_back_to_jibun_address():
    d = doc("x", road="")
    assert K._doc_to_candidate(d).address == "서울 마포구 성산동 1"


@pytest.mark.parametrize("addr,expected", [
    ("서울특별시 마포구 성미산로 128", "마포구"),
    ("서울 마포구 성미산로 128", "마포구"),
    ("경기도 성남시 분당구 황새울로", "성남시"),
    ("전북특별자치도 군산시 백토로 261", "군산시"),
])
def test_sigungu_extraction(addr, expected):
    assert K._sigungu(addr) == expected
