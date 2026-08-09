"""Pure-function unit tests for entity_validation_service.

No network. Tests cover:
- name normalisation + similarity
- address normalisation + similarity
- business-type family mapping
- the validate_google_place_identity decision matrix
- has_usable_review_text helper
"""
from __future__ import annotations

import pytest

from app.schemas import BusinessInfo, GooglePlaces, PlaceReview
from app.services import entity_validation_service as evs


# ---------------------------------------------------------------- name helpers

def test_normalize_company_name_strips_legal_prefix_and_branch():
    assert evs.normalize_company_name("(주) 샘플카페 강남점") == "샘플카페"
    assert evs.normalize_company_name("주식회사 옐다") == "옐다"
    assert evs.normalize_company_name("㈜ 알파베타 본점") == "알파베타"


def test_name_similarity_robust_to_branch_suffix():
    assert evs.name_similarity("(주) 샘플카페 강남점", "샘플카페") >= 90.0
    assert evs.name_similarity("스타벅스 강남R점", "스타벅스") >= 80.0
    assert evs.name_similarity("아주 다른 가게", "전혀 다른 매장") < 60.0


# ---------------------------------------------------------------- address helpers

def test_address_similarity_same_dong_high():
    sim = evs.address_similarity(
        "서울특별시 강남구 역삼동",
        "대한민국 서울특별시 강남구 역삼동 123-4",
    )
    assert sim >= 80.0


def test_address_similarity_different_sido_low():
    sim = evs.address_similarity(
        "서울특별시 강남구 역삼동",
        "부산광역시 해운대구 우동",
    )
    assert sim < 60.0


# ---------------------------------------------------------------- type families

@pytest.mark.parametrize("biz,family", [
    ("커피전문점", "food_and_beverage"),
    ("음악 및 기타 오디오물 출판업", "professional_services"),
    ("부동산 중개업", "real_estate"),
    ("미용실", "beauty"),
    ("PC방", "entertainment"),
    ("cafe", "food_and_beverage"),
    ("real_estate_agency", "real_estate"),
    ("", "other"),
])
def test_map_business_type_family(biz, family):
    assert evs.map_business_type_family(biz) == family


def test_is_business_type_compatible_with_google_types_list():
    assert evs.is_business_type_compatible("커피전문점", ["cafe", "food", "point_of_interest"]) is True
    assert evs.is_business_type_compatible("커피전문점", ["beauty_salon"]) is False
    # Only generic types -> treated as 'no signal' (compatible).
    assert evs.is_business_type_compatible("커피전문점", ["point_of_interest"]) is True


# ---------------------------------------------------------------- end-to-end validation

def _make_mp(name, biz_type, address):
    return BusinessInfo(company_name=name, business_type=biz_type, address=address)


def _make_gp(name, address, types):
    return GooglePlaces(place_name=name, formatted_address=address, place_types=types)


def test_validation_consistent_case():
    mp = _make_mp("(주) 샘플카페 강남점", "커피전문점", "서울특별시 강남구 역삼동")
    gp = _make_gp("샘플카페 강남점", "대한민국 서울특별시 강남구 역삼동 123", ["cafe", "food"])
    out = evs.validate_google_place_identity(mp, gp)
    assert out["is_consistent"] is True
    assert out["business_type_compatible"] is True
    assert out["score"] >= 0.55


def test_validation_rejects_wrong_entity_same_address():
    # A consumer cafe sharing the area with the legal entity but a totally different name & type.
    mp = _make_mp("옐다 음악 출판", "음악 및 기타 오디오물 출판업", "서울특별시 강남구 역삼동")
    gp = _make_gp("스타벅스 강남대로점", "서울특별시 강남구 역삼동 99", ["cafe", "food"])
    out = evs.validate_google_place_identity(mp, gp)
    assert out["is_consistent"] is False
    assert any("업종" in r or "상호명" in r or "종합 점수" in r for r in out["reasons"])


def test_validation_rejects_when_address_in_different_city():
    mp = _make_mp("샘플카페", "커피전문점", "서울특별시 강남구 역삼동")
    gp = _make_gp("샘플카페", "부산광역시 해운대구 우동", ["cafe"])
    out = evs.validate_google_place_identity(mp, gp)
    # Even with same name, a different 시/도 should not pass.
    assert out["address_similarity"] < 60.0
    assert out["is_consistent"] is False


def test_validation_handles_empty_google():
    mp = _make_mp("샘플카페", "커피전문점", "서울특별시 강남구 역삼동")
    out = evs.validate_google_place_identity(mp, GooglePlaces())
    assert out["is_consistent"] is False
    assert out["score"] == 0.0


# ---------------------------------------------------------------- review-text gate

def test_has_usable_review_text_thresholds():
    # too short
    assert evs.has_usable_review_text([PlaceReview(text="좋음")]) is False
    # only one usable -> default min_count=2 not satisfied
    assert evs.has_usable_review_text([PlaceReview(text="조용하고 좋아요 자주 갑니다")]) is False
    assert evs.has_usable_review_text([
        PlaceReview(text="조용하고 좋아요 자주 갑니다"),
        PlaceReview(text="점심에 회전 빠르고 친절합니다"),
    ]) is True
    assert evs.has_usable_review_text([]) is False
