# 교체 설계안 — ① 사업자번호→상호명 조회, ② Google Places → Kakao Local

> ## ⚠ 상태: **구현 완료** (작성 시점의 "미구현" 표기는 낡았습니다)
>
> **인수인계 정본은 [`HANDOVER.md`](HANDOVER.md) 입니다.** 충돌하면 그쪽이 맞습니다.
>
> 이 문서는 2026-08-04에 쓴 **설계안**이고, 설계대로 구현됐습니다.
> 구현 결과와 이후 변경은 `HANDOVER.md`와 `TPO_시연페이지_구현계획.md` 13장에 있습니다.
>
> ### 지금도 이 문서를 봐야 하는 이유는 하나입니다
>
> **7장 — 키 발급 절차.** 화면 단위로 적어 둔 곳이 여기뿐입니다.
> 키를 발급할 때 [7장](#7-키-발급-방법)으로 바로 가십시오.
>
> 나머지 장(모듈 구조·필드 매핑·검색 전략)은 `HANDOVER.md` Part I §3.1–3.2,
> Part II §2 §4 §5 에 **구현된 실제 값으로** 정리돼 있습니다. 설계 의도가 궁금할 때만
> 대조용으로 읽으십시오.
>
> ### 설계 대비 실제로 달라진 것
>
> | 설계안 | 구현 결과 |
> |---|---|
> | 상호명 조회에 **국민연금(NPS)** 활용 검토 | 활용신청을 하지 않아 **미사용**. bizno 단독 |
> | bizno 인증을 OAuth2로 추정한 초안 | 실제는 `key=` 쿼리 파라미터 (§1.3에 정정 반영됨) |
> | 상권은 기존 엑셀(행정동) 유지 | **주변 업종 집계 방식으로 교체** (엑셀은 폴백). 37% → 90% |
> | 후보 스코어링에 `partial_ratio` | 오탐이 심해 `ratio` + `token_sort_ratio` 로 교체 |

작성 2026-08-04. 대상: 당시 README "서비스 교체 계획" 1·2행.

---

## 0. 조사 결과 — 설계를 바꾸는 사실 3개

구현 전에 확인한 내용 중, README의 가정과 다른 것부터 적는다.

**(1) NPS(국민연금 가입 사업장) API는 소규모 매장을 거의 못 찾는다.**
- 수록 범위가 "가입자 3인 이상 법인사업장, 가입자 10인 이상 개인사업장(2025.7. 이후)"이다.
  이 데모의 타깃(동네 카페·음식점)은 대부분 미수록.
- 조회 파라미터 `bzowr_rgst_no`가 **사업자등록번호 앞 6자리**뿐이다. 10자리 정확 매칭이 불가능해
  후보가 여러 건 나오고, 그중 어느 것이 입력한 번호인지 **API만으로는 확정할 수 없다**.
- 결론: NPS를 1순위 소스로 두면 실패율·오매칭률이 모두 높다. → **후순위 + 사용자 확인 필수**로 격하.

**(2) bizno OPEN API가 사실상 moneypin의 공식 API다.** (docs.bizno.moneypin.biz)
- 크롤링이 아니라 정식 REST API. 무료 플랜 **1일 200건**, **1 req/sec** 제한.
- 응답에 상호명·업종·도로명/지번주소·위도·경도까지 포함 → 현재 크롤러가 주는 정보 + 좌표.
- 즉 "moneypin 크롤링 제거"라는 목표는 달성되지만 **벤더 의존은 그대로**다.
  → 이건 판단이 필요한 지점이라 5장 열린 결정사항에 올림.

**(3) 국세청 진위확인/상태조회 API로는 상호명을 얻을 수 없다.**
진위확인은 (사업자번호 + 개업일자 + 대표자명)을 받아 일치 여부만 01/02로 돌려준다.
상호명은 입력 항목이지 출력 항목이 아니다. → 사업자번호 단독으로 상호명을 얻는 **무료·공공** 경로는 없다.

**(4) Kakao Local은 리뷰·평점·영업시간을 주지 않는다.**
`keyword.json` 응답 필드는 `id, place_name, category_name, category_group_code, category_group_name,
phone, address_name, road_address_name, x, y, place_url, distance`뿐.
→ 텍스트 근거는 **기존 DuckDuckGo 웹검색 fallback이 상시 경로로 승격**된다.

---

## 1. 설계 ① 사업자번호 → 상호명 (`biz_lookup_service`)

### 1.1 모듈 구조

`app/services/moneypin_service.py` → `app/services/biz_lookup_service.py`로 교체.
Playwright 의존은 `requirements.txt`에서 제거.

analyse.py가 쓰는 진입점 하나만 노출한다.

```python
# app/services/biz_lookup_service.py

class BizCandidate(BaseModel):
    company_name: str
    address: str = ""
    business_type: str = ""
    source: str                       # "nps"
    hint: str = ""                    # 예: "가입자 12명 / 서울 강남구"

class BizIdentity(BaseModel):
    company_name: str = ""
    business_type: str = ""
    address: str = ""
    company_intro: str | None = None
    location: dict | None = None       # bizno가 좌표를 주면 채움 {"lat","lng"}
    source: str = "none"              # bizno | nps | user_input | mock | none
    confidence: float = 0.0
    candidates: list[BizCandidate] = []
    needs_user_input: bool = False
    message: str = ""

async def resolve_identity(
    digits: str,
    *,
    user_company_name: str | None = None,
    user_address: str | None = None,
    user_business_type: str | None = None,
) -> BizIdentity: ...
```

### 1.2 해결 체인

사용자 입력이 들어온 재요청이면 **체인을 타지 않고 즉시 확정**한다(0단계).

| 단계 | 소스 | 조건 | 성공 시 confidence | 실패 시 |
|---|---|---|---|---|
| 0 | `user_input` | 요청에 `company_name`이 있음 | 0.90 | — |
| 1 | `bizno` | `BIZNO_API_TOKEN` 존재 | 1.00 | 2로 |
| 2 | `nps` | `DATA_GO_KR_API_KEY` 존재 | 후보 1건 0.60 / 다건 0.0(선택 요청) | 3으로 |
| 3 | `none` | — | 0.0, `needs_user_input=True` | UI 입력 카드 |

**단계 1 — bizno** (2026-08-05 실호출로 계약 확정)

> **주의 — 이름이 비슷한 별개 제품 두 개가 있다.**
> `docs.bizno.moneypin.biz` + `api.moneypin.biz/bizno/v1/*` 는 moneypin이 운영하는
> **신규 BIZNO API**로 OAuth2 client-credentials(`grantType`/`clientId`/`clientSecret`) 방식이다.
> 이 프로젝트가 발급받은 것은 `bizno.net/openapi`의 **기존 OPEN API**이고 계약이 전혀 다르다.
> 초판은 전자의 문서를 보고 설계했는데 잘못이었다.

```
GET https://bizno.net/api/fapi?key={KEY}&q={사업자번호}&type=json
```

| 항목 | 값 |
|---|---|
| 키 파라미터 | **`key`** — `serviceKey`/`apikey`/`apiKey`/`token`/`authKey`는 전부 `-2 파라메터 오류` |
| 조회 파라미터 | `q` (사업자번호. **상호명 검색도 동작** — 유료 기능이라 안내된 것이지만 무료로 됨) |
| 출력 형식 | `type=json` 지원, 생략 시 XML |
| 성공 판정 | `resultCode == 0` / `resultMsg == "NORMAL SERVICE."` |
| 응답 필드 | `company`, `bno`, `cno`, `bsttcd`, `bstt`, `TaxTypeCd`, `taxtype`, `EndDt` |
| 제한 | 무료 200건/일 |

실제 응답 예 (`q=3878103198`):
`company="주식회사 그레이프스"`, `bstt="계속사업자"`, `taxtype="부가가치세 일반과세자"`,
`cno`·`TaxTypeCd`·`EndDt`는 빈 문자열.

**⚠ 무료 플랜에는 업종·주소·좌표가 없다.** `type`·`detail`·`gb`·`numOfRows` 등을 붙여도
응답 길이가 동일(522B)했다. 즉 bizno에서 얻는 것은 **상호명 + 사업 상태 + 과세유형**뿐이다.

**구현 함정**: `items` 배열에 `null` 패딩이 섞여 나온다(10슬롯 중 1개만 채워지고 나머지가 `null`).
파싱 시 반드시 필터링해야 한다.

### 1.2.1 주소가 없다는 사실이 설계를 바꾼다

| 항목 | 초판 계획 | 실제 |
|---|---|---|
| 상호명 | bizno | ✅ bizno |
| 등록 업종 | bizno → 업종 교차검증용 | ❌ 없음 → **업종 검증 불가** |
| 등록 주소 | bizno → 검색 힌트 + 주소 교차검증 | ❌ 없음 → **검색 힌트·주소 검증 불가** |
| 업종·주소·좌표 canonical | Kakao | ✅ Kakao (변경 없음) |

파생되는 문제와 대응:

**(1) 동명 매장을 좁힐 지역 힌트가 없다.** `스타벅스` 233건, `블루보틀` 27건인데 시군구를
붙일 수 없다. → **Kakao 후보가 1건이면 자동 확정, 2건 이상이면 후보 목록을 보여주고 사용자가
선택**하게 한다. 후보에 주소가 함께 뜨므로 점주는 자기 가게를 바로 알아본다.
상호명을 직접 입력받는 것보다 오히려 가벼운 UX다.

**(2) 검증 축이 이름 유사도 하나로 줄어든다.** 기존 `entity_validation`은 이름 60 + 주소 60 +
종합 0.55로 판정하는데, 주소가 없으면 `address_similarity`가 0이 되어 **정상 매장도 전부
불일치로 떨어진다**. → 주소가 없는 경우를 "신호 없음"으로 처리하고 이름 가중치를 올리는
분기가 필요하다(0으로 계산해 감점하면 안 됨). 4+5 작업의 필수 항목.

**(3) 데모 번호 387-81-03198은 카페가 아니다.** Kakao 조회 결과가
`그레이프스 / 서비스,산업 > 기업 / 서울 광진구 천호대로 579` — 법인 본사다.
mock이 이 번호를 "(주) 샘플카페 강남점"으로 위장해 왔을 뿐이다.
**시연 케이스 4건에는 실제 개인 카페·피트니스 사업자번호가 필요하다.**

**단계 2 — NPS**
`GET http://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2/getBassInfoSearchV2`
`?serviceKey=...&bzowr_rgst_no={digits[:6]}&numOfRows=100&pageNo=1`

> **V2 필수 (2026-08-04 실측 정정).** 초판에 적은 구 경로
> `NpsBplcInfoInqireService/getBassInfoSearch`는 **폐지**되어 유효한 키로도
> `NO_OPENAPI_SERVICE_ERROR`(400)가 납니다. 같은 가짜 키로 두 경로를 때려본 결과
> 구 경로는 400 `NO_OPENAPI_SERVICE_ERROR`, V2는 403 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`
> — 후자만 경로가 살아 있다는 뜻입니다.
> **V2의 파라미터·응답 필드명은 아직 미검증**입니다(실제 키가 없어 인증 단계를 못 넘김).
> 10번 작업 착수 시 실호출로 확정해야 합니다.

- 응답 0건 → 단계 3.
- 1건 → 자동 채택. 단 `confidence=0.60`, UI에 "6자리 부분일치로 추정" 배지 표시.
- 2건 이상 → **자동 채택 금지**. 상위 8건을 `candidates`에 담고 `needs_user_input=True`.
  정렬은 가입자수 내림차순(작은 사업장이 뒤로 가도록).
- 업종은 기본조회에 없다. 상세조회(`getDetailInfoSearch`, `seq`)의 업종코드는 별도 매핑표가 필요해
  **1차 구현에서는 업종을 공란**으로 두고, 5장 §2.4대로 **Kakao `category_name`으로 back-fill**한다.

**단계 3 — 사용자 입력 fallback**
`message`에 안내문("사업자번호로 상호명을 찾지 못했습니다. 상호명과 주소를 입력해 주세요."),
`needs_user_input=True`.

### 1.3 API 계약 — 2단계 요청 플로우

현재는 `POST /api/analyse {business_number, lang}` 단발이다. fallback에는 사용자 입력이 필요하므로
**엔드포인트를 늘리지 않고 같은 엔드포인트에 optional 필드를 추가**한다(파이프라인·캐시 구조 유지).

```python
class AnalyseRequest(BaseModel):
    business_number: str
    lang: str = "ko"
    # --- 아래 4개 신규(모두 optional) ---
    company_name: str | None = None      # 사용자 입력 fallback
    address: str | None = None
    business_type: str | None = None
    candidate_index: int | None = None   # NPS 후보 선택 시

class NeedsInput(BaseModel):
    reason: str                          # "lookup_failed" | "ambiguous"
    fields: list[str] = []               # ["company_name", "address"]
    candidates: list[BizCandidate] = []
    message: str = ""

class AnalyseResponse(BaseModel):
    ...
    needs_input: NeedsInput | None = None   # 신규
```

흐름:

```
1차: POST /api/analyse {business_number}
       ├─ bizno/NPS 단건 성공 → 기존과 동일한 전체 분석 응답
       └─ 실패/다건 → success=false + needs_input{...}   (error 배너 대신 입력 카드 렌더)
2차: POST /api/analyse {business_number, company_name, address}   ← 사용자 입력
  또는 POST /api/analyse {business_number, candidate_index: 2}    ← 후보 선택
       └─ 전체 분석 응답
```

UI(`templates/yiedla_ambience.html`)는 `needs_input`이 있으면 에러 배너 대신
① 후보 리스트(라디오) 또는 ② 상호명·주소 입력 폼을 렌더하고 같은 엔드포인트로 재요청한다.

**캐시 키 변경 필수.** 현재 `analyse:{digits}`는 같은 번호에 서로 다른 사용자 입력이 들어오면
첫 입력이 고착된다. → `analyse:{digits}:{sha1(company_name|address)[:8]}`
(사용자 입력이 없으면 해시부는 `-`).

### 1.4 provenance

`EvidenceProvenance`에 `identity_source: str`(bizno|nps|user_input|mock)와
`identity_confidence: float`를 추가한다. `source != "bizno"`면 UI 근거 패널에 한 줄 남긴다.
사용자 입력은 검증 수단이 없으므로 "사용자가 입력한 상호명 기준"이라고 **명시**한다.

---

## 2. 설계 ② Google Places → Kakao Local

### 2.1 모듈 구조 — 파사드 유지

`places_service.py`를 **얇은 파사드로 남기고** 실제 구현을 `kakao_local_service.py`로 뺀다.
`analyse.py`는 `places_service.lookup_place()` / `geocode()` 호출부를 그대로 유지 → diff 최소.

```
places_service.lookup_place(name, addr)
  └─ PLACES_PROVIDER=kakao  → kakao_local_service.lookup_place()   (기본값)
     PLACES_PROVIDER=google → 기존 구글 경로 (보존, 회귀 비교용)
     mock                   → 기존 _mock_place()
```

### 2.2 검색 전략 — 후보 15건 스코어링

현행은 `places[0]`을 그대로 믿는다. Kakao는 동명 매장이 많아 이걸 개선한다.

```
① query = "{상호명} {시군구}{동}"     size=15
② ①이 0건 → address.json으로 주소 지오코딩 → x,y,radius=2000 + query="{상호명}"
③ ②도 0건 → query = "{상호명}" 단독
→ 후보 전체를 기존 entity_validation_service.validate_google_place_identity()에 넣고
  score 최고값 1건 선택. 최고 score < COMBINED_SCORE_THRESHOLD(0.55)면 "매칭 없음" 처리.
```

`GET https://dapi.kakao.com/v2/local/search/keyword.json`,
헤더 `Authorization: KakaoAK {KAKAO_REST_API_KEY}`, `size` 최대 15 / `page` 최대 45.

### 2.3 필드 매핑

`GooglePlaces` 스키마는 **이름을 그대로 유지**한다. UI가 `data.google_places`를 참조하고 있어
리네이밍 이득보다 회귀 위험이 크다(내부 주석으로 "provider-agnostic" 명시).

| GooglePlaces | Kakao 소스 |
|---|---|
| `place_id` | `id` |
| `place_name` | `place_name` |
| `formatted_address` | `road_address_name` 우선, 없으면 `address_name` |
| `location` | `{"lat": float(y), "lng": float(x)}` ← **x가 경도, y가 위도** |
| `place_types` | `category_name.split(" > ")` + `[category_group_code]` |
| `business_hours` | `[]` (Kakao 미제공 → 웹검색 복구) |
| `rating` / `review_count` / `reviews` | `None` / `None` / `[]` |
| (신규) `place_url` / `phone` / `category_group_code` | 동명 필드 |

`geocode()`는 `GET /v2/local/search/address.json` → `documents[0].{x,y}`.
bizno가 좌표를 준 경우(§1.1 `BizIdentity.location`)는 지오코딩 자체를 생략한다.

### 2.4 entity_validation 영향 — 거의 손댈 게 없다

`_MP_FAMILY_RULES`가 이미 한글 키워드 매칭이라 Kakao `category_name`("음식점 > 카페 > 커피전문점")이
그대로 들어간다. 추가 작업은 두 개뿐:

- `category_group_code` 18종 매핑을 `_GP_TYPE_FAMILY`에 추가
  (`FD6`→food_and_beverage, `CE7`→food_and_beverage, `HP8`→health, `PM9`→health,
  `AD5`→lodging, `AC5`→education, `SC4`→education, `CS2`→retail, `MT1`→retail,
  `AG2`→real_estate, `OL7`→automotive, `BK9`/`PO3`→professional_services,
  `CT1`/`AT4`→entertainment, 나머지 other).
- **업종 비교의 자기참조 방지**: NPS/사용자입력 경로에서 업종이 공란이면
  `map_business_type_family("")` → `"other"` → `is_business_type_compatible()`가 True를 반환한다.
  이미 "신호 없음"으로 처리되므로 **코드 변경 불필요**. 대신 업종이 공란일 때
  Kakao `category_name`의 마지막 토큰을 `business_info.business_type`에 back-fill한다(analyse.py step 5 직후).

### 2.5 파이프라인(analyse.py) 정리

리뷰가 구조적으로 없으므로 5.6의 3분기가 2분기로 줄어든다.

- `has_google_reviews`는 **항상 False** → `review_corpus`는 `web_search` 또는 `none`뿐.
  `text_source`의 `"google_reviews"` / `"mixed"` 분기는 죽은 코드가 되므로 제거(또는
  `PLACES_PROVIDER=google` 경로 보존을 위해 남기되 주석 명시).
- `needs_hours_fallback`은 **항상 True** → 영업시간은 상시 웹검색 복구.
  이 때문에 요청당 웹검색이 최대 2회(일반 + 영업시간 타깃) 발생 → 캐시 TTL 확인 필요.
- provenance/UI 문구에서 "Google 리뷰"를 **"웹 텍스트 근거"**로 교체.
  `chkValFail` 문구는 "카카오 지도 결과가 사업자 정보와 일치하지 않아 제외했습니다"로.
- `EvidenceProvenance`에 `place_provider: str` 추가. `google_used`/`google_review_count`는
  하위호환으로 남기고 항상 false/0.

### 2.6 config 변경

```python
kakao_rest_api_key: str = os.getenv("KAKAO_REST_API_KEY", "")
places_provider: str    = os.getenv("PLACES_PROVIDER", "kakao")
bizno_api_token: str    = os.getenv("BIZNO_API_TOKEN", "")
bizno_api_base: str     = os.getenv("BIZNO_API_BASE", "https://api.bizno.net")
kakao_keyword_url: str  = ".../v2/local/search/keyword.json"
kakao_address_url: str  = ".../v2/local/search/address.json"
nps_bplc_url: str       = "http://apis.data.go.kr/B552015/NpsBplcInfoInqireService/getBassInfoSearch"
```

`effective_mock_mode()`의 게이트를 `google_maps_api_key` → `kakao_rest_api_key`로 교체.
(안 바꾸면 Kakao 키를 넣어도 계속 mock으로 떨어진다 — 첫 실행 시 반드시 걸리는 함정.)

---

## 3. 데이터 소스 요약 (교체 후)

| 정보 | 소스 | 비고 |
|---|---|---|
| 사업 상태(계속/휴업/폐업) | 국세청 상태조회 (기존) | 변경 없음 |
| 상호명 / 주소 | bizno → NPS → 사용자 입력 | 신뢰도 하락 시 UI 명시 |
| 업종 | bizno, 없으면 **Kakao category_name** | NPS 경로는 Kakao 의존 |
| 좌표 | bizno 또는 Kakao keyword/address | |
| 상권 라벨 | 기존 엑셀 매칭 | 변경 없음 |
| 영업시간 | **웹검색 복구 전용** | Kakao 미제공 |
| 리뷰/텍스트 근거 | **웹검색 전용** (DuckDuckGo) | Kakao 미제공 |
| 날씨 | 기상청 초단기실황 | 변경 없음 |
| 스코어링 | Groq (OpenAI 호환) | env만 |

**품질에 대한 정직한 평가**: 텍스트 근거가 Google 리뷰(수십 건, 리뷰 텍스트)에서
웹검색 스니펫(≤12건, 블로그 요약문)으로 내려간다. ambience 점수의 분산이 커지고
근거 없는 케이스(`text_source="none"`)가 늘어난다. 데모로는 성립하지만,
**"무료 조합으로 유료 품질을 낸다"가 아니라 "무료 조합으로 파이프라인 전체가 돈다"가 목표**임을
데모 시연 스크립트에 명시하는 게 좋다.

---

## 4. 테스트 계획

- `tests/test_kakao_mapping.py` — Kakao 응답 픽스처 → `GooglePlaces` 매핑, x/y 뒤바뀜 회귀 방지.
- `tests/test_entity_validation.py` 확장 — `category_name`/`category_group_code` 입력 케이스,
  업종 공란 시 `type_ok=True`.
- `tests/test_biz_lookup.py` — 체인 4단계 각각 + NPS 다건 → `needs_user_input`,
  사용자 입력 우선 확정.
- `tests/test_pipeline_pure.py` 확장 — `has_google_reviews=False` 전제에서
  `text_source`가 `web_search`/`none` 두 값만 나오는지.
- 실키 스모크(수동): 실제 사업자번호 3~5건(법인 1 / 개인 소규모 2 / 폐업 1 / 미등록 1).

---

## 5. 결정사항 (2026-08-04 확정)

1. **bizno API — 조건부 1순위로 확정.** ✅
   체인에 1순위로 넣되 `BIZNO_API_TOKEN`이 비어 있으면 **자동으로 NPS+사용자입력 체인으로 강등**된다.
   토큰 유무만으로 두 구성을 모두 시연할 수 있고, 벤더 의존을 나중에 걷어내기도 쉽다.
   → 구현 제약: bizno 호출은 반드시 `if not settings.bizno_api_token: skip` 가드 뒤에 둔다.
   bizno 경로를 전제하는 코드가 다른 곳에 새지 않게 할 것.

2. **NPS 경로 — 후순위로 확정.** ✅
   구현 8단계. 7단계(사용자 입력 fallback)를 먼저 완성한다. 조회 실패 시 데모가 멈추지 않는 것이
   NPS 적중률(3인↑ 법인 / 10인↑ 개인, 6자리 부분일치)보다 가치가 크다.
   → 8단계를 건너뛰어도 1~7단계만으로 데모가 완결되어야 한다.

3. **`GooglePlaces` 스키마명 — 유지로 확정.** ✅ (§2.3) 내부 주석으로 provider-agnostic 명시.

4. **웹검색 예비 provider — 미확정(운영 판단).** ⏳
   DuckDuckGo HTML 스크래핑은 차단·구조변경에 취약하다. `web_search_service.py`에 SerpAPI /
   Google CSE 경로가 **이미 구현되어 있어** env만 넣으면 우선 사용되므로, 코드 작업은 없고
   데모 당일 리스크를 얼마나 감수할지만 정하면 된다(§7-5).

---

## 6. 구현 순서 (세부 절차 — 전체 순서는 다른 문서 기준)

> **전체 프로젝트 순서는 `TPO_시연페이지_구현계획.md` §7이 단일 기준입니다.**
> 이 장은 그 표의 **4번(Kakao+Places)·5번(사업자조회 교체)** 을 어떤 절차로 쪼개 진행할지에 대한
> 세부 계획으로만 참조하세요. 두 문서의 번호는 대응하지 않습니다.

각 단계는 독립 커밋 단위이고, **끝날 때마다 앱이 동작하는 상태**를 유지한다.

| # | 작업 | 산출물 | 검증 |
|---|---|---|---|
| 1 | bizno 실호출 스모크 → 응답 필드명 확정 | 필드 매핑표(문서) | 실번호 1건 200 OK |
| 2 | config/env 확장 + `effective_mock_mode` 게이트 교체 + `.env.example` | `config.py` | `/health` missing_keys |
| 3 | `kakao_local_service` + `places_service` 파사드 + `geocode` | 신규 모듈 | 매핑 단위테스트 + 실키 1건 |
| 4 | 후보 15건 스코어링 + Kakao 카테고리 매핑 + 업종 back-fill | `entity_validation` 확장 | 확장 테스트 |
| 5 | `analyse.py` 분기 정리(리뷰 없음 전제) + provenance/UI 문구 | 파이프라인 | 전 구간 mock 통과 |
| 6 | `biz_lookup_service` (bizno 경로) + `moneypin_service` 제거 + Playwright 제거 | 신규 모듈 | 실번호 3건 |
| 7 | `needs_input` 2단계 플로우 + UI 입력 카드 + 캐시 키 변경 | 스키마+UI | 미등록 번호 시연 |
| 8 | NPS 경로 + 후보 선택 UI (선택) | 체인 2단계 | 법인 번호 1건 |
| 9 | Groq env 전환 확인 + 통합 스모크 + README 갱신 | 문서 | 5개 번호 E2E |

순서 근거: 3~5(Kakao)를 먼저 하는 이유는 불확실성이 가장 낮고, 업종·좌표 공급원이 되어
6~8(사업자 조회)의 공란 필드 문제를 미리 해소하기 때문이다. 7(사용자 입력)이 8(NPS)보다
앞서는 이유는 조회 실패 시 데모가 멈추지 않게 하는 것이 NPS 적중률보다 가치가 크기 때문이다.

---

## 7. 키 발급 방법

### 7-1. data.go.kr 인증키 — **하나로 3개 API 공용**

> README의 "NPS 키" 항목 정정: data.go.kr **일반 인증키는 계정당 1개**이고
> NTS(odcloud) · 기상청 · NPS 모두 같은 키를 쓴다. **다만 활용신청은 API별로 따로** 해야 한다.

1. https://www.data.go.kr 회원가입 · 로그인
2. 아래 3개를 각각 검색 → 상세 페이지 → **[활용신청]** (셋 다 자동승인)
   - `국세청_사업자등록정보 진위확인 및 상태조회`
   - `기상청_단기예보 조회서비스`
   - `국민연금공단_국민연금 가입 사업장 내역` (데이터 번호 3046071)
3. **마이페이지 → 데이터활용 → Open API → 인증키 발급현황**에서 키 확인
4. `.env`에 `DATA_GO_KR_API_KEY`, `KMA_API_KEY` 모두 **같은 값**을 넣는다

함정 두 개:
- 인증키가 **Encoding / Decoding 두 가지**로 표시된다. 현행 코드는 `httpx` params로 넘겨
  자동 URL 인코딩하므로 **Decoding 키**를 써야 한다. Encoding 키를 쓰면 `%`가 이중 인코딩돼
  `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`가 난다.
- 승인은 즉시지만 키 활성화까지 **최대 1시간** 걸린다. 신청 직후 401/403은 기다리면 해결된다.
- 개발계정 트래픽: API당 **10,000건/일**.

### 7-2. Kakao REST API 키

1. https://developers.kakao.com 카카오계정 로그인
2. **내 애플리케이션 → 애플리케이션 추가하기** (앱 이름·회사명 입력)
3. **앱 키** 탭 → **REST API 키** 복사 → `.env`의 `KAKAO_REST_API_KEY`
4. **제품 설정 → 카카오맵 → 사용 설정 ON** ← 이걸 빼먹으면 401이 난다
5. 카카오 로그인 설정·비즈앱 전환은 **불필요**

무료 쿼터: 키워드 검색 **100,000건/일**, 전체 합산 **월 300만건**.
주의: **계정의 첫 번째 앱만 무료 쿼터**를 받는다. 두 번째 앱부터는 Biz Wallet 연결이 필요하므로
기존 앱이 있으면 새로 만들지 말고 그 앱에 카카오맵을 켜서 쓰는 게 낫다.

### 7-3. Groq 키

1. https://console.groq.com 가입(구글 계정 가능)
2. **API Keys → Create API Key** → `gsk_...` 복사 (재확인 불가, 즉시 저장)
3. `.env` — 코드 수정 없이 OpenAI 호환 경로로 동작:
   ```
   OPENAI_API_KEY=gsk_...
   OPENAI_BASE_URL=https://api.groq.com/openai/v1
   OPENAI_MODEL=llama-3.3-70b-versatile
   ```
4. 무료 티어는 분당 요청수(RPM)·일일 토큰 제한이 있다. `LLM_REVIEW_CAP`을 낮게(≤15) 유지.

`llm_service.py`가 `OPENAI_BASE_URL`을 실제로 읽는지는 구현 2단계에서 확인 필요
(현행 `config.py`에 해당 필드가 없다 — SDK가 환경변수를 직접 읽는 구조라면 그대로 동작).

### 7-4. bizno API 토큰 (선택 — 열린 결정사항 1)

1. https://bizno.net 에서 웹 조회로 대상 번호가 실제로 검색되는지 먼저 확인
2. https://bizno.net/openapi → API 신청 (실제 가입·키 발급은 https://api.bizno.net)
3. 문서: https://docs.bizno.moneypin.biz/api
4. 무료 플랜 **1일 200건**, **1초당 1회** 제한 → 코드에 rate limiter 필수(§1.2)

### 7-5. 웹검색 예비 키 (선택)

DuckDuckGo는 키가 필요 없지만 차단 위험이 있다. 예비로 하나만:
- SerpAPI — https://serpapi.com 가입 → 무료 월 100건 → `.env`에 `SERPAPI_KEY`
- 또는 Google Custom Search JSON API — 무료 100건/일 → `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX`

두 경로 모두 `web_search_service.py`에 **이미 구현되어 있어** env만 넣으면 우선 사용된다.

### 7-6. 최종 `.env` 형태

```env
# data.go.kr — 아래 두 개는 같은 값 (Decoding 키)
DATA_GO_KR_API_KEY=발급받은_디코딩_키
KMA_API_KEY=발급받은_디코딩_키

# Kakao Local
KAKAO_REST_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
PLACES_PROVIDER=kakao

# Groq (OpenAI 호환)
OPENAI_API_KEY=gsk_...
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile

# 선택
BIZNO_API_TOKEN=
SERPAPI_KEY=

MOCK_MODE=0
LLM_REVIEW_CAP=15
LOG_LEVEL=INFO
```

`GOOGLE_MAPS_API_KEY`는 더 이상 필요 없다(회귀 비교용으로만 남김).
