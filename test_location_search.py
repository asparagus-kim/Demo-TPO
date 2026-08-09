import asyncio
import json
import os, sys, urllib.parse
from dotenv import load_dotenv
import httpx

load_dotenv('.env')

sys.path.insert(0, os.path.dirname(__file__))

from app.services import kakao_local_service, places_service, weather_service, trade_area_service, llm_service, ambience_service, music_service, entity_validation_service

async def test_by_address():
    address = "서울 영등포구 영등포로 353"
    print(f"==========================================================")
    print(f"Searching Kakao Local API for Coffee Shop at: {address}")
    print(f"==========================================================\n")

    kakao_key = os.getenv("KAKAO_REST_API_KEY")
    if not kakao_key:
        print("KAKAO_REST_API_KEY missing in .env")
        return

    # Query Kakao Keyword / Address search
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {kakao_key}"}
    
    # Try searching "카페" near address or querying keyword "영등포로 353 카페"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params={"query": f"{address} 카페"}, headers=headers)
        data = resp.json()
        docs = data.get("documents", [])
        if not docs:
            # Fallback to general keyword "영등포로 353"
            resp = await client.get(url, params={"query": address}, headers=headers)
            data = resp.json()
            docs = data.get("documents", [])

    print(f"Found {len(docs)} places at/near address:")
    for idx, doc in enumerate(docs[:5], 1):
        print(f"  [{idx}] {doc.get('place_name')} | Category: {doc.get('category_name')} | Address: {doc.get('road_address_name') or doc.get('address_name')} | ID: {doc.get('id')}")

    if not docs:
        print("No places found for address.")
        return

    chosen = docs[0]
    company_name = chosen.get("place_name")
    category_name = chosen.get("category_name")
    road_address = chosen.get("road_address_name") or chosen.get("address_name")
    lat = float(chosen.get("y", 37.5147))
    lng = float(chosen.get("x", 126.9075))

    print(f"\n==========================================================")
    print(f"Selected Store: {company_name}")
    print(f"Category: {category_name}")
    print(f"Address: {road_address}")
    print(f"Coordinates: lat={lat}, lng={lng}")
    print(f"==========================================================\n")

    # Step 1: Surrounding places & Trade area
    surrounding = await kakao_local_service.count_surrounding_places(lat, lng)
    trade_area = trade_area_service.classify_by_surroundings(road_address, surrounding)
    print("--- Trade Area ---")
    print(f"Label: {trade_area.label} | Method: {trade_area.match_method} | Confidence: {trade_area.confidence}")

    # Step 2: Google Places (Reviews & Business Hours)
    places_data = await places_service.lookup_place_details(company_name, road_address)
    print("\n--- Google Places Details ---")
    print(f"Rating: {places_data.rating} | Reviews Count: {places_data.review_count}")
    print(f"Hours: {places_data.business_hours}")
    if places_data.reviews:
        print("Sample Review:", places_data.reviews[0].text[:120] if places_data.reviews[0].text else "(rating only)")

    # Step 3: Weather
    weather = await weather_service.get_weather(lat, lng)
    print("\n--- Weather ---")
    print(f"Summary: {weather.summary} | Condition: {weather.condition} | Temp: {weather.temperature_c}°C")

    # Step 4: LLM Ambience Scoring
    review_texts = [r.text for r in places_data.reviews if r.text]
    llm_score = await llm_service.score_reviews_with_llm(review_texts, company_name, category_name)
    print("\n--- LLM Ambience Scoring ---")
    print(f"Energy: {llm_score.energy} | Tempo: {llm_score.tempo} | Mood: {llm_score.mood}")
    print(f"Reason: {llm_score.reason}")

    # Step 5: Fusion & TPO Profile
    fusion = ambience_service.compute_ambience_and_tpo(llm_score, category_name, trade_area.label, weather)
    print("\n--- Ambience Vector Fusion ---")
    print(f"Final Energy: {fusion.ambience.energy} | Tempo: {fusion.ambience.tempo} | Mood: {fusion.ambience.mood}")
    print("TPO Profile:", fusion.tpo_profile.dict())

    # Step 6: Recommended Music Playlist
    industry_family = kakao_local_service.map_industry_family(category_name)
    music_res = music_service.recommend_tracks(industry_family, fusion.ambience, fusion.tpo_profile)
    print("\n==========================================================")
    print(f"Recommended Music Playlist (10 Tracks)")
    print(f"Playlist Label: {music_res.playlist_label}")
    print(f"Pool Size: {music_res.pool_size} tracks")
    print(f"==========================================================")
    for idx, tr in enumerate(music_res.tracks[:5], 1):
        print(f"  {idx}. {tr.title} ({tr.genre_primary}) - BPM: {tr.bpm} | Score: {tr.score} | Reason: {tr.reason}")

if __name__ == "__main__":
    asyncio.run(test_by_address())
