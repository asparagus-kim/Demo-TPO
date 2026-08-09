"""발급한 API 키를 하나씩 실제 호출로 검증한다.

사용법:
    python scripts/check_keys.py            # .env 전체 검사
    python scripts/check_keys.py kakao      # 특정 항목만 (datago/kma/nps/kakao/groq/google/bizno)

각 항목은 독립적이다. 아직 발급하지 않은 키는 SKIP으로 넘어가므로
키를 하나 받을 때마다 돌려보면 된다. 종료 코드는 실패가 하나라도 있으면 1.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

# Windows 콘솔(cp949)에서도 한글이 깨지지 않게.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    import httpx
except ImportError:
    sys.exit("httpx가 없습니다. pip install -r requirements.txt 먼저 실행하세요.")

try:
    from dotenv import load_dotenv
except ImportError:
    sys.exit("python-dotenv가 없습니다. pip install -r requirements.txt 먼저 실행하세요.")

import os

# override=False로 app/config.py와 동일하게 맞춘다. 셸 환경변수가 .env보다 우선하므로
# 검증 결과와 실제 앱 동작이 어긋나지 않는다(키 하나만 임시로 시험할 때도 편하다).
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

TIMEOUT = 20.0
DEMO_BIZ_NO = "3878103198"          # 데모용 사업자번호 (README)
DEMO_BIZ_NO_PREFIX = DEMO_BIZ_NO[:6]

# data.go.kr 인증 실패 시 본문에 나타나는 문자열들.
DATAGO_AUTH_ERRORS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE ACCESS DENIED",
    "APPLICATION_ERROR",
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "UNKNOWN_ERROR",
)

results: list[tuple[str, str, str]] = []   # (status, 항목, 메시지)


def record(status: str, name: str, message: str) -> None:
    results.append((status, name, message))
    print(f"  [{status}] {message}")


def env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def looks_url_encoded(key: str) -> bool:
    """data.go.kr Encoding 키는 %2B / %3D 같은 이스케이프를 포함한다."""
    return "%" in key


# ---------------------------------------------------------------- data.go.kr 공통

def datago_key(name: str) -> str:
    """app/config.py 의 `_get_service_key()` 와 동일하게 동작해야 한다.

    Encoding 키가 들어오면 디코딩해서 검사한다. 그렇지 않으면 검증은 실패하는데
    앱은 성공하는(또는 그 반대의) 불일치가 생긴다.
    """
    raw = env(name)
    return unquote(raw) if "%" in raw else raw


def _datago_key_hint(key: str) -> str | None:
    if looks_url_encoded(key):
        return (
            "키에 '%'가 있습니다 — Encoding 키입니다. 앱과 이 스크립트가 자동으로 "
            "Decoding 키로 변환해 진행하지만, .env를 Decoding 키로 바꿔두는 편이 안전합니다."
        )
    return None


def check_datago_nts() -> None:
    """국세청 사업자등록 상태조회 (odcloud)."""
    print("\n[1/7] 국세청 상태조회 — DATA_GO_KR_API_KEY")
    key = datago_key("DATA_GO_KR_API_KEY")
    if not key or key.startswith("your_"):
        record("SKIP", "datago-nts", "DATA_GO_KR_API_KEY가 비어 있습니다.")
        return

    # 힌트 판정은 .env의 원문으로 해야 의미가 있다(디코딩 후에는 '%'가 사라진다).
    hint = _datago_key_hint(env("DATA_GO_KR_API_KEY"))
    if hint:
        record("WARN", "datago-nts", hint)

    url = "https://api.odcloud.kr/api/nts-businessman/v1/status"
    try:
        resp = httpx.post(
            url,
            params={"serviceKey": key, "returnType": "JSON"},
            json={"b_no": [DEMO_BIZ_NO]},
            headers={"Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "datago-nts", f"네트워크 오류: {exc}")
        return

    body = resp.text
    if resp.status_code == 200 and '"data"' in body:
        try:
            item = (resp.json() or {}).get("data", [{}])[0]
            status = item.get("b_stt") or "(상태 문자열 없음)"
        except Exception:
            status = "(파싱 실패)"
        record("OK", "datago-nts", f"인증 성공. {DEMO_BIZ_NO} 상태='{status}'")
        return

    if resp.status_code in (401, 403) or any(e in body for e in DATAGO_AUTH_ERRORS):
        record(
            "FAIL", "datago-nts",
            f"인증 실패 ({resp.status_code}). Decoding 키인지, '국세청_사업자등록정보 진위확인 및 "
            f"상태조회' 활용신청을 했는지 확인하세요. 신청 직후면 최대 1시간 대기가 필요합니다. "
            f"응답: {body[:160]}",
        )
        return

    record("FAIL", "datago-nts", f"예상치 못한 응답 {resp.status_code}: {body[:160]}")


def check_datago_kma() -> None:
    """기상청 초단기실황."""
    print("\n[2/7] 기상청 초단기실황 — KMA_API_KEY")
    key = datago_key("KMA_API_KEY")
    if not key or key.startswith("your_"):
        record("SKIP", "datago-kma", "KMA_API_KEY가 비어 있습니다.")
        return

    hint = _datago_key_hint(env("KMA_API_KEY"))
    if hint:
        record("WARN", "datago-kma", hint)

    # 초단기실황은 매시 정시 자료가 40분쯤 뒤에 열린다. 2시간 전으로 넉넉히 잡는다.
    base = datetime.now() - timedelta(hours=2)
    url = "http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"
    try:
        resp = httpx.get(
            url,
            params={
                "serviceKey": key,
                "pageNo": 1,
                "numOfRows": 10,
                "dataType": "JSON",
                "base_date": base.strftime("%Y%m%d"),
                "base_time": base.strftime("%H00"),
                "nx": 61,      # 서울 종로구
                "ny": 125,
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "datago-kma", f"네트워크 오류: {exc}")
        return

    body = resp.text
    if '"resultCode":"00"' in body.replace(" ", "") or "<resultCode>00</resultCode>" in body:
        record("OK", "datago-kma", f"인증 성공 (기준 {base:%Y-%m-%d %H}시 실황 조회됨)")
        return

    if any(e in body for e in DATAGO_AUTH_ERRORS):
        record(
            "FAIL", "datago-kma",
            f"인증 실패. '기상청_단기예보 조회서비스' 활용신청과 Decoding 키를 확인하세요. "
            f"응답: {body[:160]}",
        )
        return

    # NO_DATA는 키는 정상이고 시각/좌표만 안 맞는 경우다.
    if "NO_DATA" in body or "03" in body[:400]:
        record("WARN", "datago-kma", "키는 유효하나 해당 시각 자료가 없습니다(NO_DATA). 정상으로 봐도 됩니다.")
        return

    record("FAIL", "datago-kma", f"예상치 못한 응답 {resp.status_code}: {body[:160]}")


def check_datago_nps() -> None:
    """국민연금 가입 사업장 내역 (구현 8단계에서 사용)."""
    print("\n[3/7] 국민연금 사업장 — DATA_GO_KR_API_KEY 재사용 (선택)")
    key = datago_key("DATA_GO_KR_API_KEY")
    if not key or key.startswith("your_"):
        record("SKIP", "datago-nps", "DATA_GO_KR_API_KEY가 비어 있습니다.")
        return

    # V2 필수. 구 경로(NpsBplcInfoInqireService/getBassInfoSearch)는 폐지되어
    # 유효한 키를 넣어도 NO_OPENAPI_SERVICE_ERROR(400)가 난다. 2026-08-04 실측 확인.
    url = "http://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2/getBassInfoSearchV2"
    try:
        resp = httpx.get(
            url,
            params={
                "serviceKey": key,
                "bzowr_rgst_no": DEMO_BIZ_NO_PREFIX,
                "numOfRows": 5,
                "pageNo": 1,
            },
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "datago-nps", f"네트워크 오류: {exc}")
        return

    body = resp.text
    if "<resultCode>00</resultCode>" in body or '"resultCode":"00"' in body.replace(" ", ""):
        count = body.count("<item>")
        record(
            "OK", "datago-nps",
            f"인증 성공. 앞 6자리 '{DEMO_BIZ_NO_PREFIX}' 검색 결과 {count}건 "
            f"(0건은 정상 — 3인↑ 법인/10인↑ 개인만 수록)",
        )
        return

    if "NO_OPENAPI_SERVICE_ERROR" in body:
        record(
            "FAIL", "datago-nps",
            "엔드포인트 경로 오류 — 이 서비스는 V2만 살아 있습니다. "
            "NpsBplcInfoInqireServiceV2/getBassInfoSearchV2 를 쓰는지 확인하세요.",
        )
        return

    if any(e in body for e in DATAGO_AUTH_ERRORS):
        record(
            "FAIL", "datago-nps",
            f"인증 실패. '국민연금공단_국민연금 가입 사업장 내역'(데이터 3046071) 활용신청이 "
            f"별도로 필요합니다. 응답: {body[:160]}",
        )
        return

    record("WARN", "datago-nps", f"판정 불가 {resp.status_code}: {body[:160]}")


# ---------------------------------------------------------------- Kakao

def check_kakao() -> None:
    print("\n[4/7] Kakao Local — KAKAO_REST_API_KEY")
    key = env("KAKAO_REST_API_KEY")
    if not key or key.startswith("your_"):
        record("SKIP", "kakao", "KAKAO_REST_API_KEY가 비어 있습니다.")
        return

    try:
        resp = httpx.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": "강남역 스타벅스", "size": 1},
            headers={"Authorization": f"KakaoAK {key}"},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "kakao", f"네트워크 오류: {exc}")
        return

    if resp.status_code == 200:
        docs = (resp.json() or {}).get("documents") or []
        if not docs:
            record("WARN", "kakao", "인증은 됐지만 검색 결과가 0건입니다.")
            return
        d = docs[0]
        record(
            "OK", "kakao",
            f"인증 성공. '{d.get('place_name')}' / {d.get('category_name')} / "
            f"x={d.get('x')} y={d.get('y')}",
        )
        return

    body = resp.text
    if resp.status_code == 401:
        record("FAIL", "kakao", f"401 — REST API 키가 잘못됐습니다(JavaScript 키를 넣었을 수 있음). {body[:160]}")
        return
    if resp.status_code == 403:
        record(
            "FAIL", "kakao",
            "403 — 앱에서 [제품 설정 > 카카오맵]의 사용 설정이 OFF입니다. ON으로 바꾸세요. "
            f"{body[:160]}",
        )
        return
    record("FAIL", "kakao", f"예상치 못한 응답 {resp.status_code}: {body[:160]}")


# ---------------------------------------------------------------- Groq

def check_groq() -> None:
    print("\n[5/7] Groq (OpenAI 호환) — OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL")
    key = env("OPENAI_API_KEY")
    base = env("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    model = env("OPENAI_MODEL")

    if not key or key.startswith("your_"):
        record("SKIP", "groq", "OPENAI_API_KEY가 비어 있습니다.")
        return
    if key.startswith("gsk_") and "groq" not in base:
        record(
            "WARN", "groq",
            f"Groq 키(gsk_)인데 OPENAI_BASE_URL이 '{base}'입니다. "
            "https://api.groq.com/openai/v1 로 설정하세요.",
        )

    try:
        resp = httpx.get(
            f"{base.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "groq", f"네트워크 오류: {exc}")
        return

    if resp.status_code != 200:
        record("FAIL", "groq", f"인증 실패 {resp.status_code}: {resp.text[:160]}")
        return

    ids = [m.get("id") for m in (resp.json() or {}).get("data") or []]
    record("OK", "groq", f"인증 성공. 사용 가능 모델 {len(ids)}종")

    if not model:
        record("WARN", "groq", "OPENAI_MODEL이 비어 있습니다 (config 기본값 gpt-4o-mini는 Groq에 없습니다).")
    elif model in ids:
        record("OK", "groq-model", f"OPENAI_MODEL='{model}' 사용 가능")
    else:
        sample = ", ".join(i for i in ids[:8] if i)
        record(
            "FAIL", "groq-model",
            f"OPENAI_MODEL='{model}'이 목록에 없습니다. 사용 가능 예: {sample}",
        )


# ---------------------------------------------------------------- bizno

# ---------------------------------------------------------------- Google Places

# 앱의 필드 마스크와 동일하게 유지해야 한다. 필드를 늘리면 SKU 등급이 올라가
# 무료 한도(Enterprise 월 1,000건)가 깨진다 — 비용정리 §4.2 주의 2.
_PLACES_SEARCH_FIELDS = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.location", "places.types", "places.rating", "places.userRatingCount",
])


def check_google_places() -> None:
    print("\n[6/7] Google Places (New) + Geocoding — GOOGLE_MAPS_API_KEY")
    key = env("GOOGLE_MAPS_API_KEY")
    if not key or key.startswith("your_"):
        record("SKIP", "google-places",
                "GOOGLE_MAPS_API_KEY가 비어 있습니다 (미설정 시 Kakao+웹검색으로 degrade).")
        return

    # 1) Text Search — 리뷰 확보 경로의 1단계
    try:
        resp = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _PLACES_SEARCH_FIELDS,
            },
            json={"textQuery": "스타벅스 강남", "languageCode": "ko", "regionCode": "KR"},
            timeout=TIMEOUT,
        )
    except Exception as exc:
        record("FAIL", "google-places", f"네트워크 오류: {exc}")
        return

    body = resp.text
    if resp.status_code != 200:
        hint = ""
        if "SERVICE_DISABLED" in body or "has not been used in project" in body:
            hint = " → 'Places API (New)' 사용 설정이 안 됐습니다. 레거시 'Places API'와 다릅니다."
        elif "API_KEY_HTTP_REFERRER_BLOCKED" in body or "referer" in body.lower():
            hint = " → 키에 웹사이트(referrer) 제한이 걸려 있습니다. 서버 호출이라 전부 차단됩니다."
        elif "API_KEY_SERVICE_BLOCKED" in body:
            hint = " → 키의 API 제한에 Places API (New)가 빠져 있습니다."
        elif resp.status_code == 403:
            hint = " → 결제 계정 연결 또는 키 제한을 확인하세요."
        record("FAIL", "google-places", f"Text Search {resp.status_code}{hint} 응답: {body[:200]}")
        return

    places = (resp.json() or {}).get("places") or []
    if not places:
        record("WARN", "google-places", "인증은 됐지만 검색 결과가 0건입니다.")
        return
    top = places[0]
    name = (top.get("displayName") or {}).get("text") or "?"
    record("OK", "google-places",
            f"Text Search 성공. '{name}' / 평점 {top.get('rating')} / 리뷰수 {top.get('userRatingCount')}")

    # 2) Place Details — 리뷰 본문이 실제로 오는지 (분위기 분석의 입력)
    pid = top.get("id")
    if pid:
        try:
            r2 = httpx.get(
                f"https://places.googleapis.com/v1/places/{pid}",
                headers={"X-Goog-Api-Key": key,
                         "X-Goog-FieldMask": "id,displayName,reviews,regularOpeningHours"},
                params={"languageCode": "ko"}, timeout=TIMEOUT,
            )
            if r2.status_code == 200:
                d = r2.json() or {}
                nrev = len(d.get("reviews") or [])
                nhours = len((d.get("regularOpeningHours") or {}).get("weekdayDescriptions") or [])
                lvl = "OK" if nrev >= 2 else "WARN"
                record(lvl, "google-details",
                        f"Place Details 성공. 리뷰 본문 {nrev}건 / 영업시간 {nhours}일치"
                        + ("" if nrev >= 2 else " — 리뷰가 적어 분석이 뭉툭해질 수 있습니다."))
            else:
                record("WARN", "google-details",
                        f"Place Details {r2.status_code}: {r2.text[:160]}")
        except Exception as exc:
            record("WARN", "google-details", f"Place Details 네트워크 오류: {exc}")

    # 3) Geocoding — 좌표 폴백 경로
    try:
        r3 = httpx.get("https://maps.googleapis.com/maps/api/geocode/json",
                       params={"address": "서울특별시 강남구 역삼동", "key": key, "language": "ko"},
                       timeout=TIMEOUT)
        data = r3.json() or {}
        status = data.get("status")
        if status == "OK":
            record("OK", "google-geocode", "Geocoding 성공")
        elif status == "REQUEST_DENIED":
            record("FAIL", "google-geocode",
                    f"Geocoding 거부 — 'Geocoding API' 사용 설정 또는 키 API 제한을 확인하세요. "
                    f"{data.get('error_message','')[:120]}")
        else:
            record("WARN", "google-geocode", f"Geocoding status={status}")
    except Exception as exc:
        record("WARN", "google-geocode", f"Geocoding 네트워크 오류: {exc}")


def check_bizno() -> None:
    """bizno OPEN API — 사업자번호 → 상호명. 2026-08-05 실호출로 계약 확정."""
    print("\n[7/7] bizno OPEN API — BIZNO_API_KEY")
    key = env("BIZNO_API_KEY") or env("BIZNO_API_TOKEN")   # 구 변수명 호환
    if not key or key.startswith("your_"):
        record("SKIP", "bizno", "BIZNO_API_KEY가 비어 있습니다 (미설정 시 사용자 입력 체인으로 동작).")
        return

    url = env("BIZNO_API_URL") or "https://bizno.net/api/fapi"
    try:
        # 키 파라미터 이름은 `key`. serviceKey/apikey/token 등은 -2 파라메터 오류가 난다.
        resp = httpx.get(url, params={"key": key, "q": DEMO_BIZ_NO, "type": "json"}, timeout=TIMEOUT)
    except Exception as exc:
        record("FAIL", "bizno", f"네트워크 오류: {exc}")
        return

    if resp.status_code != 200:
        record("FAIL", "bizno", f"HTTP {resp.status_code}: {resp.text[:160]}")
        return
    try:
        data = resp.json() or {}
    except Exception:
        record("FAIL", "bizno", f"JSON 파싱 실패: {resp.text[:160]}")
        return

    if data.get("resultCode") != 0:
        record("FAIL", "bizno",
                f"조회 실패 (resultCode={data.get('resultCode')}): {data.get('resultMsg')}")
        return

    # items 배열에 null 패딩이 섞여 나온다 → 반드시 필터링
    items = [i for i in (data.get("items") or []) if i]
    if not items:
        record("WARN", "bizno", f"인증은 됐지만 {DEMO_BIZ_NO} 조회 결과가 0건입니다.")
        return
    it = items[0]
    record("OK", "bizno",
            f"인증 성공. {it.get('bno')} → 상호명='{it.get('company')}' / {it.get('bstt')}")
    # 무료 플랜에는 업종·주소가 없다. 있으면 유료 플랜이거나 스펙이 바뀐 것이므로 알린다.
    if any(k in it for k in ("addr", "address", "roadAddr", "upjong")):
        record("WARN", "bizno-fields",
                "응답에 주소/업종 필드가 보입니다 — 설계(무료 플랜은 상호명만) 재확인 필요.")


CHECKS = {
    "datago": check_datago_nts,
    "kma": check_datago_kma,
    "nps": check_datago_nps,
    "kakao": check_kakao,
    "groq": check_groq,
    "google": check_google_places,
    "bizno": check_bizno,
}


def main() -> int:
    if not (PROJECT_ROOT / ".env").exists():
        print("경고: .env 파일이 없습니다. .env.example을 복사해서 채우세요.\n")

    selected = sys.argv[1:]
    if selected:
        unknown = [s for s in selected if s not in CHECKS]
        if unknown:
            print(f"알 수 없는 항목: {', '.join(unknown)}")
            print(f"가능한 값: {', '.join(CHECKS)}")
            return 2
        todo = {k: CHECKS[k] for k in selected}
    else:
        todo = CHECKS

    print("=" * 66)
    print("API 키 검증")
    print("=" * 66)

    for fn in todo.values():
        fn()

    ok = sum(1 for s, _, _ in results if s == "OK")
    warn = sum(1 for s, _, _ in results if s == "WARN")
    fail = sum(1 for s, _, _ in results if s == "FAIL")
    skip = sum(1 for s, _, _ in results if s == "SKIP")

    print("\n" + "=" * 66)
    print(f"결과: OK {ok} / WARN {warn} / FAIL {fail} / SKIP {skip}")
    if fail:
        print("\nFAIL 항목:")
        for status, name, msg in results:
            if status == "FAIL":
                print(f"  - {name}: {msg}")
    print("=" * 66)
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
