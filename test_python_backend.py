import asyncio
import json
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from app.schemas import AnalyseRequest
from app.routers.analyse import analyse

async def main():
    biz_no = sys.argv[1] if len(sys.argv) > 1 else "506-81-60897"
    print(f"==========================================================")
    print(f"Testing Python Backend Service for Business Number: {biz_no}")
    print(f"==========================================================\n")

    req = AnalyseRequest(business_number=biz_no)
    
    try:
        response = await analyse(req)
        print("Status Code / Success:", response.success)
        print("Business Number:", response.business_number)
        print("NTS Status:", response.nts_status)
        print("Error (if any):", response.error)
        print("Needs Input:", response.needs_input)
        print("\n--- Business Info ---")
        print(json.dumps(response.business_info.dict() if response.business_info else None, indent=2, ensure_ascii=False))
        print("\n--- Trade Area ---")
        print(json.dumps(response.trade_area.dict() if response.trade_area else None, indent=2, ensure_ascii=False))
        print("\n--- Google Places ---")
        print(json.dumps(response.google_places.dict() if response.google_places else None, indent=2, ensure_ascii=False))
        print("\n--- Weather ---")
        print(json.dumps(response.weather.dict() if response.weather else None, indent=2, ensure_ascii=False))
        print("\n--- TPO Profile ---")
        print(json.dumps(response.tpo_profile.dict() if response.tpo_profile else None, indent=2, ensure_ascii=False))
        print("\n--- Ambience Vector ---")
        print(json.dumps(response.ambience.dict() if response.ambience else None, indent=2, ensure_ascii=False))
        print("\n--- Entity Validation ---")
        print(json.dumps(response.entity_validation.dict() if response.entity_validation else None, indent=2, ensure_ascii=False))
        print("\n--- Recommended Music Playlist (10 Tracks) ---")
        if response.music:
            music_dict = response.music.dict()
            print("Playlist Label:", music_dict.get("playlist_label"))
            print("Pool Size:", music_dict.get("pool_size"))
            print("Recommended Tracks Count:", len(music_dict.get("tracks", [])))
            print("\nTop 3 Tracks:")
            for idx, tr in enumerate(music_dict.get("tracks", [])[:3], 1):
                print(f"  {idx}. {tr.get('title')} ({tr.get('genre_primary')}) - Score: {tr.get('score')} | Reason: {tr.get('reason')}")
        
    except Exception as exc:
        print("Error during Python backend execution:", exc)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
