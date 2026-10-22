"""Unit tests for pure-Python blog keyword scoring and storefront normalization."""
from __future__ import annotations

from app.schemas import WebEvidenceItem
from app.services import blog_scoring_service as B
from app.services.kakao_local_service import _expand_storefront_fallbacks


def test_positive_energy_scoring():
    item = WebEvidenceItem(
        title="성수동 핫플 카페",
        url="https://blog.naver.com/test/1",
        text="주말이라 손님이 북적거리고 신나는 힙한 분위기였어요. 웨이팅도 조금 있었습니다.",
        source="naver_blog",
    )
    score = B.score_blog_item(item)
    assert score.energy > 0.65
    assert any(k in score.keywords for k in ("신나", "웨이팅", "북적", "핫플", "힙한"))
    assert score.evidence == "pure_python_blog_keyword"


def test_negation_inverts_energy():
    # "시끄럽지 않고" should NOT increase energy; it should lower energy
    item = WebEvidenceItem(
        title="조용한 카페",
        url="https://blog.naver.com/test/2",
        text="사람이 많아도 전혀 시끄럽지 않고 조용해서 공부하기에 차분한 분위기입니다.",
        source="naver_blog",
    )
    score = B.score_blog_item(item)
    assert score.energy < 0.45
    assert "조용" in score.keywords or "차분" in score.keywords


def test_occasion_detection():
    gym_item = WebEvidenceItem(
        title="구의동 헬스장 후기",
        url="https://blog.naver.com/test/3",
        text="트레이너 선생님이 친절하게 PT 지도해주시고 기구도 다양해서 운동하기 최고입니다. 오운완!",
        source="naver_blog",
    )
    score = B.score_blog_item(gym_item)
    assert "운동/트레이닝" in score.occasion_labels

    pocha_item = WebEvidenceItem(
        title="새벽 포차 모임",
        url="https://blog.naver.com/test/4",
        text="2차로 간 심야 포차인데 안주가 맛있어서 친구들과 늦게까지 술자리 가졌습니다.",
        source="naver_blog",
    )
    pocha_score = B.score_blog_item(pocha_item)
    assert "야간 모임" in pocha_score.occasion_labels or "친구모임" in pocha_score.occasion_labels


def test_storefront_fallback_queries():
    queries = _expand_storefront_fallbacks("몸가짐 휘트니스필라테스구의", "서울특별시 광진구 자양로18길 33")
    assert any("몸가짐휘트니스" in q for q in queries)
    assert any("광진구" in q for q in queries)
    assert "몸가짐" in queries


def test_is_store_blog_match_valid():
    ok, reason = B.is_store_blog_match(
        title="[내돈내산] 광진구 자양동 수제 쿠키 딜란스쿠키 방문기",
        snippet="자양로 골목에 위치한 딜란스쿠키 다녀왔습니다. 쿠키가 달콤하고 맛있어요.",
        store_name="딜란스쿠키",
        address="서울 광진구 자양로28길 6",
        region_address="서울 광진구 자양동 629-12",
    )
    assert ok is True
    assert "local_geo_matched" in reason or "gu_geo_matched" in reason


def test_is_store_blog_match_rejects_spam():
    ok, reason = B.is_store_blog_match(
        title="광진구 자양동 원룸 오피스텔 분양 임대 매물",
        snippet="보증금 1000 월세 60 딜란스쿠키 인근 신축 원룸 임대합니다.",
        store_name="딜란스쿠키",
        address="서울 광진구 자양로28길 6",
    )
    assert ok is False
    assert reason.startswith("spam:")


def test_is_store_blog_match_rejects_unrelated_brand():
    # Literary essay about ancient Jongno "화신상회" should be rejected for "화신포차"
    ok, reason = B.is_store_blog_match(
        title="[문학기행] 종각 화신상회 터를 지나며",
        snippet="종로타워 자리의 화신상회와 제비다방을 걸었다.",
        store_name="화신포차",
        address="서울 광진구 자양로18길 37",
        region_address="서울 광진구 구의동 246-14",
    )
    assert ok is False
    assert reason.startswith("brand_not_found:")


def test_is_store_blog_match_rejects_conflicting_city():
    # Gwangju bar "술애화신" / "화신포차" should be rejected when target store is in Seoul
    ok, reason = B.is_store_blog_match(
        title="광주 수완지구 화신포차 안주 맛집",
        snippet="광주 광산구 수완동에 새로 오픈한 화신포차에 다녀왔습니다.",
        store_name="화신포차",
        address="서울 광진구 자양로18길 37",
        region_address="서울 광진구 구의동 246-14",
    )
    assert ok is False
    assert "conflicting_sido:광주" in reason


def test_is_store_blog_match_branch_filtering():
    # Blog for Junggok-dong branch should be rejected when target store is explicitly Guui branch
    ok_other_branch, reason_other = B.is_store_blog_match(
        title="중곡동 헬스장 몸가짐 휘트니스",
        snippet="중곡역 바로 앞에 있는 몸가짐 휘트니스 중곡점 시설입니다.",
        store_name="몸가짐휘트니스 구의점",
        address="서울 광진구 아차산로 384",
        region_address="서울 광진구 구의동 252-16",
    )
    assert ok_other_branch is False
    assert "branch_mismatch" in reason_other

    # Blog for Guui branch should be accepted
    ok_target_branch, reason_target = B.is_store_blog_match(
        title="구의역 헬스장 몸가짐 휘트니스 구의점 솔직후기",
        snippet="아차산로 구의동 헬스장 몸가짐 기구도 많고 샤워실도 깨끗해요.",
        store_name="몸가짐휘트니스 구의점",
        address="서울 광진구 아차산로 384",
        region_address="서울 광진구 구의동 252-16",
    )
    assert ok_target_branch is True
    assert reason_target in ("branch_matched", "local_geo_matched")


def test_filter_relevant_blogs():
    items = [
        WebEvidenceItem(title="구의동 화신포차 닭발 맛집", url="http://1", text="구의역 근처 화신포차 매콤한 안주 최고", source="naver_blog"),
        WebEvidenceItem(title="광주 화신포차 술자리", url="http://2", text="광주 수완동 화신포차", source="naver_blog"),
        WebEvidenceItem(title="오피스텔 원룸 임대", url="http://3", text="화신포차 근처 원룸 월세 분양", source="naver_blog"),
    ]
    filtered = B.filter_relevant_blogs(
        items,
        store_name="화신포차",
        address="서울 광진구 자양로18길 37",
        region_address="서울 광진구 구의동 246-14",
    )
    assert len(filtered) == 1
    assert filtered[0].title == "구의동 화신포차 닭발 맛집"

