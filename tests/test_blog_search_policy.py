"""Deterministic storefront search policy; no live provider requests."""
from urllib.parse import quote

import pytest

from app.schemas import WebEvidenceItem
from app.services.blog_search_policy import (
    POLICY_VERSION, build_search_context, filter_evidence, normalize_url,
)


def context(**kwargs):
    return build_search_context("언니커피 암사점", "서울특별시 강동구 구천면로 251", "서울 강동구 암사동 100", **kwargs)


def item(url="https://blog.naver.com/author/222152065862", title="언니커피 암사점 방문", text="서울 강동구 암사동 언니커피에서 커피를 주문했어요. 좌석이 편하고 조용해서 오래 머물렀어요."):
    return WebEvidenceItem(url=url, title=title, text=text, source="duckduckgo")


def test_context_is_bounded_canonical_and_address_token_anchored():
    ctx = context(place_id="123", registered_name="(주) 언니커피 암사점")
    assert not ctx.reason
    assert len(ctx.review_queries) <= 3
    assert all("구천면 " not in q for q in ctx.review_queries)
    assert "구천면" not in ctx.locality_tokens
    assert "암사동" in ctx.review_queries[0]
    assert all("309-30" not in q for q in ctx.review_queries)
    assert ctx.cache_identity != context(place_id="456").cache_identity
    with pytest.raises(Exception):
        ctx.store_name = "changed"


@pytest.mark.parametrize("name,address,registered", [
    ("", "서울 강동구 암사동", ""),
    ("커피", "서울 강동구 암사동", ""),
    ("언니커피", "", ""),
    ("언니커피", "서울 강동구 암사동", "언니식당"),
    ("뽕쓰언니", "서울 강동구 천호동", "언니커피"),  # shared word only: upstream store conflict
])
def test_missing_or_conflicting_identity_abstains(name, address, registered):
    ctx = build_search_context(name, address, registered_name=registered)
    assert ctx.reason
    assert not ctx.review_queries and not ctx.hours_query
    assert not filter_evidence([item()], ctx)[0]


def test_corporate_alias_is_allowed_only_when_normalized_equal():
    ctx = build_search_context("언니 커피", "서울 강동구 암사동", registered_name="주식회사 언니커피")
    assert not ctx.reason
    accepted, _ = filter_evidence([item(title="언니커피 방문")], ctx)
    assert len(accepted) == 1


def test_genuine_experience_without_literal_review_word_is_accepted():
    accepted, diagnostics = filter_evidence([item()], context())
    assert len(accepted) == 1
    assert accepted[0].source == "naver_blog"
    assert diagnostics["accepted"] == 1


@pytest.mark.parametrize("candidate", [
    item(title="언니커피 부산점 방문", text="부산 해운대구 언니커피에서 커피를 마셨어요. 서울 암사동 친구와 방문했어요."),
    item(title="언니커피 천호점 방문", text="암사동 근처 천호점 언니커피에서 커피를 주문했어요."),
    item(title="언니커피 암사점 사업자 정보", text="서울 강동구 암사동 언니커피 사업자등록번호 주소 영업시간 09:00-22:00"),
    item(title="언니커피 암사점 창업비용", text="암사동 언니커피 매물 임대 안내. 커피를 마셨어요."),
    item(title="언니커피하우스 암사점", text="암사동 언니커피하우스에서 커피를 주문했어요."),
    item(url="https://directory.example/store/123"),
    item(url="https://blog.naver.com.evil.example/author/222152065862"),
    item(url="https://blog.naver.com/author"),
    item(url="https://blog.naver.com/PostList.naver?blogId=author"),
    item(url="https://author.tistory.com/category/cafe"),
    item(url="https://tistory.com/123"),
])
def test_rejects_unrelated_metadata_spam_and_nonpost_urls(candidate):
    accepted, diagnostics = filter_evidence([candidate], context())
    assert not accepted
    assert sum(diagnostics["rejected"].values()) == 1


def test_whole_brand_required_not_one_shared_word():
    ctx = build_search_context("심야식당 후타리", "서울 강동구 암사동")
    assert not filter_evidence([item(title="후타리 방문", text="암사동 후타리에서 맛있게 먹었어요.")], ctx)[0]


def test_naver_equivalent_posts_deduplicate_before_limit_keep_first_link():
    first = "https://m.blog.naver.com/author/222152065862?tracking=keep%26exact"
    urls = [first,
        "https://blog.naver.com/PostView.nhn?blogId=author&logNo=222152065862",
        "https://blog.naver.com/PostView.naver?logNo=222152065862&blogId=author",
        "https://blog.naver.com/other/222152065863",
    ]
    accepted, diagnostics = filter_evidence([item(url=u) for u in urls], context(), limit=2)
    assert len(accepted) == 2
    assert accepted[0].url == first
    assert diagnostics["duplicates"] == 2


def test_tistory_post_and_equivalent_path_identity():
    urls = ["https://writer.tistory.com/42?utm_source=a", "https://writer.tistory.com/42?utm_source=b", "https://writer.tistory.com/entry/cafe-story"]
    accepted, diagnostics = filter_evidence([item(url=u) for u in urls], context())
    assert len(accepted) == 2 and diagnostics["duplicates"] == 1
    assert accepted[0].source == "kakao_blog"


def test_hours_metadata_is_separate_and_store_verified():
    directory = item(url="https://directory.example/store/123", title="언니커피 암사점", text="서울 강동구 암사동 언니커피 영업시간 09:00-22:00")
    assert not filter_evidence([directory], context())[0]
    assert len(filter_evidence([directory], context(), purpose="hours")[0]) == 1
    wrong = directory.model_copy(update={"text": "부산 해운대구 언니커피 영업시간 09:00-22:00"})
    assert not filter_evidence([wrong], context(), purpose="hours")[0]


@pytest.mark.parametrize("url", [
    "https://example.com/review?currency=USD&notional=100",
    "https://example.com/review?x=1&amp;literal=2",
    "https://example.com/review?q=a%26b%2Bc&lang=ko#review",
])
def test_json_url_preserves_bytes_and_normalization_is_idempotent(url):
    assert normalize_url(url) == url
    assert normalize_url(normalize_url(url)) == url
    wrapped = f"https://duckduckgo.com/l/?uddg={quote(url, safe='')}&amp;rut=tracker"
    assert normalize_url(wrapped, html_origin=True) == url


def test_nested_ddg_html_url_unwraps_without_redecoding_destination():
    target = "https://blog.naver.com/PostView.nhn?blogId=sso_ii&logNo=222152065862"
    broken = f"https://duckduckgo.com/l/?uddg={quote(target, safe='')}&amp;rut=tracker"
    nested = f"https://duckduckgo.com/l/?uddg={quote(broken, safe='')}"
    assert normalize_url(nested, html_origin=True) == target
    assert normalize_url(target.replace("&", "&amp;"), html_origin=True) == target


@pytest.mark.parametrize("url", [None, "javascript:alert(1)", "https://[invalid", "https://user:pass@example.com/a", "https://duckduckgo.com/l/?rut=tracker", "https://duckduckgo.com/l/?uddg=%2Frelative", "https://example.com/\\evil", "https://example.com/a\nb"])
def test_unsafe_or_missing_destinations_are_rejected(url):
    assert normalize_url(url) is None


def test_other_municipal_address_overrides_incidental_target_locality():
    candidate = item(title="언니커피 방문", text="경기도 성남시 분당구 정자동 언니커피에서 커피를 주문했어요. 서울 암사동에서 온 친구와 방문했어요.")
    assert not filter_evidence([candidate], context())[0]


def test_branch_label_at_title_start_overrides_incidental_target_locality():
    candidate = item(title="천호점 언니커피 방문", text="서울 암사동 친구와 천호점 언니커피에서 커피를 주문했어요.")
    assert not filter_evidence([candidate], context())[0]


def test_structured_municipal_conflict_without_province_name():
    candidate = item(title="언니커피 방문", text="성남시 분당구 정자동 언니커피에서 커피를 주문했어요. 서울 암사동 친구도 함께 왔어요.")
    assert not filter_evidence([candidate], context())[0]


def test_same_municipality_local_address_passes():
    ctx = build_search_context("언니커피", "경기도 성남시 분당구 정자동 1")
    candidate = item(title="언니커피 방문", text="성남시 분당구 정자동 언니커피에서 커피를 주문했어요. 좌석이 편하고 조용했어요.")
    assert len(filter_evidence([candidate], ctx)[0]) == 1


def test_tistory_unknown_query_is_identity_relevant_and_opened_unchanged():
    urls = ["https://writer.tistory.com/42?lang=ko", "https://writer.tistory.com/42?lang=en"]
    accepted, diagnostics = filter_evidence([item(url=u) for u in urls], context())
    assert [i.url for i in accepted] == urls
    assert diagnostics["duplicates"] == 0


def test_registered_complete_brand_can_validate_selected_branch():
    ctx = build_search_context("별빛커피 역삼점", "서울 강남구 역삼동 123", registered_name="주식회사 별빛커피")
    assert not ctx.reason
    assert ctx.branch == "역삼점"
    assert ctx.review_queries[0].startswith("별빛커피 역삼점")
    conflicting = build_search_context("별빛커피 역삼점", "서울 강남구 역삼동 123", registered_name="별빛커피 서초점")
    assert conflicting.reason


def test_same_city_other_district_address_overrides_incidental_target():
    candidate = item(title="언니커피 방문", text="서울 송파구 방이동 언니커피에서 커피를 주문했어요. 강동구 암사동 친구와 함께 방문했어요.")
    assert not filter_evidence([candidate], context())[0]


def test_context_identity_changes_for_purpose_independent_canonical_fields():
    a = context(place_id="123")
    b = build_search_context("언니커피 암사점", "서울 강동구 구천면로 252", "서울 강동구 암사동 101", place_id="123")
    assert a.cache_identity != b.cache_identity
    assert POLICY_VERSION in a.cache_identity


@pytest.mark.parametrize("purpose", ["reviews", "hours"])
@pytest.mark.parametrize("incidental", ["", " 암사동 친구도 함께 왔어요."])
def test_explicit_other_neighborhood_cannot_pass_weaker_district_match(purpose, incidental):
    candidate = item(title="언니커피 방문", text="서울 강동구 천호동 언니커피에서 커피를 주문했어요. 좌석이 편하고 조용했어요." + incidental)
    accepted, diagnostics = filter_evidence([candidate], context(), purpose=purpose)
    assert not accepted
    assert diagnostics["rejected"] == {"locality_conflict": 1}


def test_gyeonggi_gwangju_is_municipality_not_other_metropolitan_city():
    ctx = build_search_context("언니커피", "경기도 광주시 경안동 1")
    assert not ctx.reason
    assert ctx.city == "경기"
    assert "광주시" in ctx.locality_tokens
    candidate = item(title="언니커피 방문", text="광주시 경안동 언니커피에서 커피를 주문했어요. 좌석이 편하고 조용했어요.")
    assert len(filter_evidence([candidate], ctx)[0]) == 1
    assert len(filter_evidence([candidate], ctx, purpose="hours")[0]) == 1
    wrong = item(title="언니커피 방문", text="광주광역시 동구 언니커피에서 커피를 주문했어요. 경안동 친구와 함께 왔어요.")
    assert not filter_evidence([wrong], ctx)[0]


@pytest.mark.parametrize("address,region", [
    ("경기도 광주시 경안동 1", "광주광역시 동구 충장동 1"),
    ("서울 강동구 암사동 1", "서울 송파구 방이동 1"),
    ("경기도 광주시 경안동 1", "경기도 성남시 정자동 1"),
    ("서울 강동구 암사동 1", "서울 강동구 천호동 1"),
])
def test_conflicting_structured_same_level_context_addresses_abstain(address, region):
    ctx = build_search_context("언니커피", address, region)
    assert ctx.reason == "conflicting_address_identity"
    assert not ctx.review_queries


def test_registered_name_containing_storefront_brand_is_compatible():
    # The branch's corporate case: legal name ⊇ storefront brand must still search.
    ctx = build_search_context("몸가짐휘트니스 구의점", "서울 광진구 아차산로 384", "서울 광진구 구의동 252-16",
                               registered_name="주식회사 몸가짐 휘트니스필라테스구의")
    assert not ctx.reason
    assert ctx.review_queries[0] == "몸가짐휘트니스 구의점 구의동"
    # The registered name is not a matching alias: a post naming only it is rejected.
    alias_only = item(title="몸가짐 휘트니스필라테스구의", text="구의동 몸가짐 휘트니스필라테스구의에서 운동했어요. 좌석이 편했어요.")
    assert not filter_evidence([alias_only], ctx)[0]


def test_apartment_building_label_is_not_a_locality():
    ctx = build_search_context("언니커피", "서울 강동구 암사동 100 101동 1203호")
    assert not ctx.reason
    assert "101동" not in ctx.locality_tokens and "암사동" in ctx.locality_tokens


def test_locality_and_branch_match_through_korean_particles():
    candidate = item(title="언니커피 방문", text="암사동에서 언니커피에 다녀왔어요. 커피가 고소하고 좌석이 편했어요.")
    assert len(filter_evidence([candidate], context())[0]) == 1
    branch_ctx = build_search_context("언니커피 암사점", "서울 강동구 구천면로 251")
    branch_post = item(title="언니커피 후기", text="언니커피 암사점에 다녀왔어요. 커피가 고소했어요.")
    assert len(filter_evidence([branch_post], branch_ctx)[0]) == 1


def test_third_query_broadens_to_district_before_road():
    ctx = build_search_context("언니커피", "서울특별시 강동구 구천면로 315", "서울 강동구 암사동 100")
    assert ctx.review_queries == ("언니커피 암사동", "언니커피 암사동 후기", "언니커피 강동구 후기")


def test_related_post_widget_mentioning_the_store_is_not_a_review():
    widget = item(title="강동구 카페 언니커피 암사점 모음",
                  text="양꼬치 맛집 방... blog.naver.com 강동구 암사동 언니커피 암사점 방문기 커피가 고소했어요 blog.naver.com 강동구 술집 추천...")
    accepted, diagnostics = filter_evidence([widget], context())
    assert not accepted and diagnostics["rejected"] == {"related_post_list": 1}


@pytest.mark.parametrize("text", [
    "언니커피 다녀왔어요 커피가 고소하고 분위기 좋아요 천호동 강동구",
    "언니커피 다녀왔어요 커피가 고소하고 분위기 좋아요 강동구",
])
def test_district_alone_cannot_place_post_when_store_neighborhood_is_known(text):
    accepted, _ = filter_evidence([item(title="언니커피 방문", text=text)], context())
    assert not accepted


def test_district_is_enough_only_when_no_finer_locality_is_known():
    ctx = build_search_context("언니커피", "서울 강동구")
    assert not ctx.reason
    candidate = item(title="언니커피 방문", text="강동구 언니커피에 다녀왔어요. 커피가 고소했어요.")
    assert len(filter_evidence([candidate], ctx)[0]) == 1


@pytest.mark.parametrize("host", ["www.tistory.com", "notice.tistory.com"])
def test_tistory_platform_subdomains_are_not_blog_posts(host):
    assert not filter_evidence([item(url=f"https://{host}/123")], context())[0]


def test_generic_registered_name_does_not_validate_storefront():
    ctx = build_search_context("스타벅스커피 암사점", "서울 강동구 암사동 1", registered_name="커피")
    assert ctx.reason == "registered_name_conflict"


@pytest.mark.parametrize("mentioned, ok", [
    ("원즈 커피 어린이대공원 본점", True),   # spaced label of the same 본점
    ("원즈커피 어린이대공원본점", True),
    ("원즈커피 건대점", False),
    ("원즈커피 본점", True),
])
def test_spaced_or_shortened_label_of_the_same_branch_is_not_a_conflict(mentioned, ok):
    ctx = build_search_context("원즈커피 어린이대공원본점", "서울 광진구 자양로32길 32", "서울 광진구 구의동 232-67")
    candidate = item(title=f"구의동 카페 {mentioned}", text="구의동 원즈커피에 다녀왔어요. 커피가 고소하고 분위기 좋아요.")
    assert bool(filter_evidence([candidate], ctx)[0]) is ok


def test_shortened_station_branch_matches_but_other_place_conflicts():
    ctx = build_search_context("별빛커피 구의역점", "서울 광진구 아차산로 1", "서울 광진구 구의동 1")
    same = item(title="별빛커피 구의점 방문", text="구의동 별빛커피에 다녀왔어요. 커피가 고소했어요.")
    other = item(title="별빛커피 중곡점 방문", text="구의동 별빛커피에 다녀왔어요. 커피가 고소했어요.")
    assert len(filter_evidence([same], ctx)[0]) == 1
    assert not filter_evidence([other], ctx)[0]


def test_store_used_only_as_a_landmark_is_not_a_review():
    ctx = build_search_context("빽다방 건대로데오점", "서울 광진구 아차산로 220", "서울 광진구 자양동 8-1")
    salon = item(title="자양동 속눈썹 찾는다면? 보리네눈썹가게 속눈썹펌 후기",
                 text="이번에 다녀온 곳은 자양동 속눈썹 가게예요. KT대리점· 빽 다방 있는 건물 3층! 빽 다방 건물 3층만 기억하세요.")
    landmark_title = item(title="자양동 빽다방 옆 네일샵 후기", text="자양동 빽다방 옆 네일샵에 다녀왔어요. 친절했어요.")
    accepted, diagnostics = filter_evidence([salon, landmark_title], ctx)
    assert not accepted
    assert diagnostics["rejected"] == {"brand_not_in_title": 1, "landmark_mention": 1}


def test_post_about_something_else_is_rejected_even_with_the_store_place_card():
    # Production report (579-13-01937): a friend's wedding post that stopped by the cafe.
    ctx = build_search_context("카페지니", "서울 광진구 면목로 18", "서울 광진구 군자동 49-11")
    wedding = item(title="<특별판> 나의 깜찍한 지니 의 결혼을 축하해 ♡",
                   text="카페 지니 군자 서울특별시 광진구 면목로 18 1층( 군자동 ) @ 카페 지니 자리 없어서 지나가다 본 카페로 갔다. 커피가 맛있었다.")
    review = item(title="카페 지니 군자 카공하기 좋은 카페", text="오늘 다녀온 카페는 카페 지니 군자 면목로 18 1층( 군자동 ). 조용해서 오래 앉아 있었어요.")
    accepted, diagnostics = filter_evidence([wedding, review], ctx)
    assert [a.title for a in accepted] == [review.title]
    assert diagnostics["rejected"] == {"brand_not_in_title": 1}
