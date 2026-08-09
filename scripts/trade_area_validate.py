"""상권 판정 검증 — 주변 업종 집계 방식 vs 기존 엑셀.

목적: "Kakao 주변 업종 분포로 상권을 판정하는 방식이 기존 엑셀보다 정확한가"를
**숫자로** 확인한다. 확인되지 않으면 도입하지 않는다.

사용법:
    python scripts/trade_area_validate.py fetch      # 지표 수집 (Kakao 호출, 결과 캐시)
    python scripts/trade_area_validate.py report     # 캐시로 정확도 측정 (호출 없음)

`fetch` 는 결과를 `cache/trade_area_probe.json` 에 저장하므로 임계값을 바꿔가며
`report` 를 반복해도 추가 호출이 발생하지 않는다.

⚠ 기대 레이블은 작성자의 판단이다. 상권 분류에 객관적 정답은 없으므로
   `confidence` 열로 확신도를 구분해 두었다 — 낮은 항목은 정확도 계산에서 뺄 수 있다.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import httpx
from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")
KAKAO = (os.getenv("KAKAO_REST_API_KEY") or "").strip()
CACHE = PROJECT_ROOT / "cache" / "trade_area_probe.json"

# 집계할 카테고리. Kakao category_group_code 18종 중 판별력이 있는 것만.
# 오피스·의류점 카테고리가 없어서 오피스는 은행 비율로, 트렌드는 카페 비율로 간접 추론한다.
GROUPS = {
    "CE7": "카페", "FD6": "음식점", "AC5": "학원", "BK9": "은행",
    "AD5": "숙박", "AT4": "관광", "HP8": "병원", "CS2": "편의점",
}
RADII = [500, 1000]

# (검색어, 기대 레이블, 확신도)
#   확신도 high  = 널리 통용되는 성격
#   확신도 low   = 성격이 섞여 있어 판단이 갈릴 수 있음 → 정확도 계산에서 제외 가능
SPOTS: list[tuple[str, str, str]] = [
    # --- 주거 밀집
    ("서울 용산구 이촌로 248", "주거 밀집 상권", "high"),
    ("서울 강동구 상일로3길 8", "주거 밀집 상권", "high"),
    ("서울 노원구 상계로 118", "주거 밀집 상권", "high"),
    ("경기 고양시 일산동구 정발산로 24", "주거 밀집 상권", "mid"),
    ("경기 수원시 영통구 영통로 217", "주거 밀집 상권", "mid"),
    # --- 학원가
    ("서울 강남구 대치동 은마아파트", "학원가 특화 상권", "high"),
    ("서울 양천구 목동중앙본로 62", "학원가 특화 상권", "high"),
    ("서울 노원구 중계로 187", "학원가 특화 상권", "high"),
    ("경기 안양시 동안구 평촌대로 145", "학원가 특화 상권", "mid"),
    # --- 오피스 밀집
    ("서울 영등포구 여의대로 108", "오피스 밀집 상권", "high"),
    ("서울 강남구 테헤란로 152", "오피스 밀집 상권", "high"),
    ("서울 종로구 세종대로 175", "오피스 밀집 상권", "high"),
    ("경기 성남시 분당구 판교역로 235", "오피스 밀집 상권", "high"),
    ("서울 마포구 상암산로 34", "오피스 밀집 상권", "mid"),
    ("서울 금천구 가산디지털1로 168", "오피스 밀집 상권", "mid"),
    # --- 관광특구
    ("서울 중구 명동길 14", "관광특구 상권", "high"),
    ("서울 용산구 이태원로 177", "관광특구 상권", "high"),
    ("서울 종로구 인사동길 12", "관광특구 상권", "high"),
    ("전북 전주시 완산구 태조로 44", "관광특구 상권", "high"),
    ("강원 강릉시 창해로14번길 20", "관광특구 상권", "mid"),
    # --- 대학가/유흥
    ("서울 마포구 양화로 160", "대학가/유흥 상권", "high"),        # 홍대입구
    ("서울 서대문구 신촌로 83", "대학가/유흥 상권", "high"),
    ("서울 광진구 아차산로 200", "대학가/유흥 상권", "high"),      # 건대입구
    ("서울 종로구 대학로 104", "대학가/유흥 상권", "mid"),
    ("부산 남구 수영로 309", "대학가/유흥 상권", "mid"),           # 경성대·부경대
    # --- 카페·트렌드 (기존 '트렌드/패션' 대체 후보)
    ("서울 마포구 성미산로 128", "카페·트렌드 상권", "high"),      # 연남
    ("서울 성동구 연무장길 45", "카페·트렌드 상권", "high"),       # 성수
    ("서울 종로구 익선동 166", "카페·트렌드 상권", "high"),
    ("서울 마포구 망원로 8길 14", "카페·트렌드 상권", "mid"),
    ("서울 강남구 가로수길 43", "카페·트렌드 상권", "mid"),
    ("전북 군산시 백토로 261", "카페·트렌드 상권", "low"),         # 지방 밀도 확인용
    # --- 복합 / 애매 (중립 레이블 검증용)
    ("서울 강남구 압구정로 461", "복합 상권", "low"),              # 청담
    ("서울 송파구 올림픽로 240", "복합 상권", "low"),              # 잠실
    ("서울 동작구 사당로 300", "복합 상권", "low"),
    # --- 파일럿 거점 후보
    ("서울 마포구 월드컵북로 30", "대학가/유흥 상권", "mid"),      # 아크로짐(홍대)
    ("경기 김포시 김포한강2로 194", "주거 밀집 상권", "low"),
    ("경기 김포시 고촌읍 신곡리", "주거 밀집 상권", "low"),
    # --- 지방 소도시 (밀도 임계값이 서울 기준이면 여기서 깨진다)
    ("경남 창원시 성산구 중앙대로 105", "오피스 밀집 상권", "low"),
    ("충북 증평군 증평읍 송산로4길 21", "주거 밀집 상권", "mid"),
    ("전남 순천시 연향중앙상가길 30", "복합 상권", "low"),
]


def _get(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params,
                  headers={"Authorization": f"KakaoAK {KAKAO}"}, timeout=20)
    if r.status_code != 200:
        return {}
    return r.json() or {}


def resolve(query: str) -> tuple[float, float, str] | None:
    """주소/키워드 → (lat, lng, 확정된 표기). 주소 검색 실패 시 키워드 검색."""
    d = _get("https://dapi.kakao.com/v2/local/search/address.json",
             {"query": query, "size": 1})
    docs = d.get("documents") or []
    if not docs:
        d = _get("https://dapi.kakao.com/v2/local/search/keyword.json",
                 {"query": query, "size": 1})
        docs = d.get("documents") or []
    if not docs:
        return None
    doc = docs[0]
    try:
        return float(doc["y"]), float(doc["x"]), doc.get("address_name") or query
    except (KeyError, TypeError, ValueError):
        return None


def count(code: str, lat: float, lng: float, radius: int) -> int:
    d = _get("https://dapi.kakao.com/v2/local/search/category.json",
             {"category_group_code": code, "x": lng, "y": lat,
              "radius": radius, "size": 1})
    return int((d.get("meta") or {}).get("total_count") or 0)


def fetch() -> None:
    if not KAKAO:
        sys.exit("KAKAO_REST_API_KEY 가 없습니다.")
    out = []
    calls = 0
    print(f"{len(SPOTS)}곳 × {len(GROUPS)}카테고리 × 반경 {RADII} → 예상 호출 "
          f"{len(SPOTS) * (1 + len(GROUPS) * len(RADII))}건\n")
    for i, (query, expected, conf) in enumerate(SPOTS, 1):
        loc = resolve(query)
        calls += 1
        if not loc:
            print(f"[{i:2d}/{len(SPOTS)}] {query[:30]:<32} 좌표 확인 실패 — 건너뜀")
            continue
        lat, lng, resolved = loc
        rec = {"query": query, "resolved": resolved, "expected": expected,
               "confidence": conf, "lat": lat, "lng": lng, "counts": {}}
        for radius in RADII:
            with cf.ThreadPoolExecutor(max_workers=8) as ex:
                res = dict(zip(GROUPS, ex.map(
                    lambda c: count(c, lat, lng, radius), GROUPS)))
            calls += len(GROUPS)
            rec["counts"][str(radius)] = res
        out.append(rec)
        r500 = rec["counts"]["500"]
        print(f"[{i:2d}/{len(SPOTS)}] {query[:30]:<32} 총{sum(r500.values()):>5}  {expected}")

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n호출 {calls}건 · {len(out)}곳 저장 → {CACHE}")
    print("다음: python scripts/trade_area_validate.py report")


def report(include_low: bool = False) -> int:
    """캐시로 정확도를 재측정한다 (Kakao 호출 0건).

    판정은 **서비스 코드를 그대로 호출**한다 (`trade_area_service`). 여기에 규칙을
    복사해 두면 서비스와 검증이 서로 다른 답을 내고, 그 사실을 아무도 모르게 된다.
    """
    if not CACHE.exists():
        print(f"캐시가 없습니다: {CACHE}")
        print("먼저 `python scripts/trade_area_validate.py fetch` 를 실행하세요.")
        return 2

    from app.services import trade_area_service as TA

    rows = json.loads(CACHE.read_text(encoding="utf-8"))
    scored = [r for r in rows if include_low or r.get("confidence") != "low"]

    hit_new = hit_excel = 0
    misses: list[str] = []
    by_label: dict[str, list[int]] = {}

    for r in scored:
        counts = {k: v for k, v in (r["counts"].get("500") or {}).items() if k in TA.SURROUND_GROUPS}
        profile = TA.build_profile(counts, r.get("univ", 0))
        got, conf, why = TA.classify_by_surroundings(profile)
        expected = r["expected"]
        ok = (got == expected)
        hit_new += ok
        ex_ok = (r.get("excel_label") == expected)
        hit_excel += ex_ok
        by_label.setdefault(expected, []).append(1 if ok else 0)
        if not ok:
            misses.append(f"  {r['query'][:34]:<36} 기대 {expected:<14} 실제 {got:<14} "
                          f"({why}, conf {conf:.2f})")

    n = len(scored) or 1
    print("=" * 76)
    print(f"검증 대상 {len(scored)}곳 "
          f"(전체 {len(rows)}곳{'' if include_low else f', low 확신도 {len(rows)-len(scored)}곳 제외'})")
    print("-" * 76)
    print(f"  주변 업종 분포 판정 : {hit_new:>3}/{len(scored)}  ({hit_new/n*100:.0f}%)")
    print(f"  기존 엑셀(행정동)   : {hit_excel:>3}/{len(scored)}  ({hit_excel/n*100:.0f}%)")
    print("-" * 76)
    print("기대 레이블별:")
    for label, hits in sorted(by_label.items(), key=lambda kv: -len(kv[1])):
        print(f"  {label:<16} {sum(hits)}/{len(hits)}")
    if misses:
        print("-" * 76)
        print(f"불일치 {len(misses)}건:")
        for m in misses:
            print(m)
    print("=" * 76)
    print("⚠ 기대 레이블은 작성자의 판단입니다. 상권 분류에 객관적 정답은 없습니다.")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    if cmd == "fetch":
        fetch()
    elif cmd == "report":
        raise SystemExit(report(include_low="--all" in sys.argv))
    else:
        print(__doc__)
        raise SystemExit(2)
