"""AnalyseResponse contract checks for fields the frontend consumes directly."""
from app.schemas import AnalyseResponse, PlaceCandidate


def test_resolved_place_defaults_to_none():
    response = AnalyseResponse(business_number="123-45-67890")
    assert response.resolved_place is None
    # 직렬화에도 키 자체는 남아야 프론트 optional 필드가 안전하게 좁혀진다.
    assert "resolved_place" in response.model_dump()


def test_resolved_place_round_trips_map_fields():
    chosen = PlaceCandidate(
        place_id="26338954",
        place_name="테스트 카페",
        address="서울 중구 만리재로 193",
        region_address="서울 중구 만리동1가 62-1",
        place_url="http://place.map.kakao.com/26338954",
        location={"lat": 37.5563, "lng": 126.9723},
        score=0.92,
    )
    response = AnalyseResponse(business_number="123-45-67890", resolved_place=chosen)

    dumped = response.model_dump()["resolved_place"]
    # 지도 표시(location)와 카카오맵 딥링크(place_url·place_id)가 그대로 살아야 한다.
    assert dumped["location"] == {"lat": 37.5563, "lng": 126.9723}
    assert dumped["place_url"] == "http://place.map.kakao.com/26338954"
    assert dumped["place_id"] == "26338954"
