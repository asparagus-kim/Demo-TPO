# Yielda Ambience Profiling (데모) — 이전 개발자 원본 설명서

> ## ⚠ 이 문서는 **변경 전 시스템**을 설명합니다
>
> **인수인계 정본은 [`HANDOVER.md`](HANDOVER.md) 입니다.**
>
> 이전 개발자가 작성한 원본 문서를 그대로 보존한 것입니다. 이후 구조가 바뀌어
> 아래 내용 상당수가 현재와 다릅니다.
>
> | 이 문서 | 현재 |
> |---|---|
> | ② **moneypin 크롤링** → 상호명·업종·소재지 | 삭제됨. **bizno API**(상호명) + **Kakao Local**(업종·주소·좌표) |
> | ④ Google Places → 영업시간·평점·리뷰 **및 장소 정보** | 리뷰·영업시간 **전용**으로 축소 |
> | ③ 상권 매칭 = **Excel(행정동) 조회** | **반경 500m 주변 업종 집계**로 교체 (엑셀은 폴백). 37% → 90% |
> | ⑥ OpenAI LLM | Groq (OpenAI 호환 경로) |
> | 포트 8000 · `tpo_mvp_0` 경로 | 포트 8077 · `yielda_tpo_demo` |
> | 파이프라인 7단계 | 10단계 + 음원 추천 |
>
> ### 여기에만 있는 것
>
> **7장 — 강화학습 PPO 보정 구동 방법.** `app/research/rl_calibration/`(2,235줄)의
> 사용법이 적힌 유일한 문서입니다. 단, 이 코드는 **프로덕션 요청 경로에서 호출되지
> 않으며 검토된 적이 없습니다** (`HANDOVER.md` Part I §5 참조).
>
> 나머지(프로젝트 구조·API 목록·스코어링 원리)는 `HANDOVER.md`에 현재 값으로 있습니다.

사업자등록번호 하나로 매장의 **TPO 프로파일**과 **에너지 / 템포 / 무드 (T/P/O)**
분위기 벡터를 자동 생성하는 FastAPI 백엔드 + 정적 HTML 프론트 데모입니다.

## 파이프라인 요약

```
사업자번호
  └─ ① 국세청(NTS) 상태조회       → 계속/휴업/폐업 판정
  └─ ② moneypin 크롤링            → 상호명 · 업종 · 소재지
  └─ ③ 상권 매칭 (Excel)          → 상권 특성 레이블 8개 중 1개
  └─ ④ Google Places (New)        → 영업시간 · 평점 · 리뷰
  └─ ⑤ KMA 기상청                 → 현재 날씨 / 온도 / 조건
  └─ ⑥ OpenAI LLM 리뷰 스코어링   → E/T/M 가중 평균 + 신뢰도
  └─ ⑦ TPO 프로파일 + 분위기 융합 → 최종 Energy / Tempo / Mood (0–100)
```

## 프로젝트 구조

```
project_root/
  app/
    main.py                # FastAPI 엔트리포인트
    config.py              # .env 로딩 / 설정
    schemas.py             # Pydantic 모델
    startup_calibration.py # uvicorn 부팅 시 RL 보정 자동 실행 (3장·7장 참고)
    routers/
      analyse.py           # /api/analyse, /api/reanalyse, 샘플 엔드포인트
      health.py            # /health
    services/
      nts_service.py       # 국세청 상태조회
      moneypin_service.py  # moneypin 크롤러 (Playwright sync API, async 래핑)
      trade_area_service.py# Excel 기반 상권 매칭
      places_service.py    # Google Places + Geocoding
      weather_service.py   # KMA 초단기실황
      llm_service.py       # OpenAI 리뷰 스코어링
      ambience_service.py  # 프라이어 + 퓨전 + TPO 프로파일
    utils/
      address.py           # 한국 주소 정규화
      cache.py             # TTL 인메모리 캐시
      logging.py           # 공용 로거
    research/
      rl_calibration/
        config.py             # 출력 경로 / PPO·환경 하이퍼파라미터 / 보상 가중치
        types.py              # 공통 데이터 타입 (Scenario, HiddenTruth, TextEvidence …)
        offsets.py            # 학습 대상 — prior 테이블에 더할 오프셋 파라미터
        scenario_generator.py # 합성 시나리오 (상권·업종·요일·시간·날씨) 생성
        synthetic_world.py    # 시나리오 → 숨은 진실 E/T/M 생성 시뮬레이션
        text_simulator.py     # 합성 리뷰 텍스트 / LLM 스코어 시뮬레이션
        synthetic_dump.py     # 학습 입력 샘플을 md/json/csv로 덤프
        constraints.py        # 학습 확률통계분포 함수
        fusion_bridge.py      # ambience_service의 prior 공식을 RL 환경에 노출
        reward.py             # fit + 제약 + 안정성 + 정규화 + 경계 페널티 합성
        environment.py        # gym 스타일 학습 환경 (reset / step / rollout)
        ppo_train.py          #  PPO 트레이너 
        baseline_search.py    # 비교용 random_search / hillclimb
        evaluate.py           # 학습된 오프셋의 MSE·제약·안정성 평가 + 보고서
        export_params.py      # 학습 결과 → JSON 직렬화 + 변경 diff 요약
        run_calibration.py    # 1~4단계 통합 실행 + Markdown 의사결정 보고서
        apply_to_production.py# ambience_service.py 자동 수정 / --restore 복원
  data/
    상권특성_행정동_전국_FINAL.xlsx
  templates/
    yiedla_ambience.html   # 업로드된 yielda-full-v2.html을 확장한 라이브 UI
  static/
  nts_api.py               # 업로드된 국세청 스크립트 (참조용)
  requirements.txt
  .env.example
  tests/
    test_pipeline_pure.py  # 순수 함수 단위 테스트
    sample_response.json   # 목 응답 샘플
```

## 1. 설치 및 환경 준비

```bash
conda activate tpo_etl
pip install -r requirements.txt
playwright install chromium
```

`.env` 파일에 API 인증키를 입력해야 합니다. 

```bash
cp .env.example .env
```

> **보안 주의** — 업로드 요청에 원본 API 키가 포함돼 있었지만,
> 본 프로젝트는 그 값을 **소스코드에 저장하지 않습니다**. `.env`만을 통해
> 로드되며 `.gitignore`에 제외돼 있습니다. **이미 노출된 키는 반드시 재발급
> (rotate) 하시기 바랍니다.**

필요한 환경변수:

| 변수 | 용도 | 없을 때 동작 |
|------|------|--------------|
| `DATA_GO_KR_API_KEY` | 국세청 상태조회 | mock 응답으로 진행 |
| `GOOGLE_MAPS_API_KEY` | Places + Geocoding | mock 응답 + 자동 mock 모드 |
| `OPENAI_API_KEY` | 리뷰 LLM 스코어링 | 휴리스틱 스코어로 대체 |
| `KMA_API_KEY` | 기상청 초단기실황 | mock 날씨 |

키가 하나라도 비어 있으면 `Settings.effective_mock_mode()`가 자동으로
`True`가 되어, 라이브 API 호출 없이도 전체 파이프라인이 끝까지 돌아갑니다.
명시적으로 `MOCK_MODE=1`을 줘도 같은 효과입니다.

## 2. 실행

```bash
uvicorn app.main:app --reload
```
- 브라우저에 Copy and Paste: http://127.0.0.1:8000 


사업자번호를 입력해 `분석 시작`을 누르면 `POST /api/analyse`가 호출되며,
체크리스트 진행과 최종 카드가 **실시간 API 응답**으로 채워집니다.

## 3. API

### `GET /health`
버전, 모의 모드 여부, 누락된 환경변수 이름을 반환합니다.

### `POST /api/analyse`

```json
{ "business_number": "387-81-03198" }
```

응답 스키마는 프로젝트 스펙 그대로입니다 (`app/schemas.py::AnalyseResponse`).

### `POST /api/reanalyse`
캐시를 무효화하고 재분석합니다.

### `GET /api/trade-area/test?address=서울특별시 광진구 자양동`
Excel 매칭 로직 확인용.

### `GET /api/sample/{biz_no}`
API 키와 무관하게 강제 목 모드로 전체 응답을 반환합니다.

## 4. 분위기 스코어링 원리

스펙의 수식을 그대로 구현했습니다. 요약:

```
E_raw = 0.50*E_text + 0.20*E_area + 0.15*E_type + 0.10*E_time + 0.05*E_weather
E     = c_text * E_raw + (1 - c_text) * (0.55*E_area + 0.45*E_type)
energy = round(100 * clamp(E, 0, 1))

c_text = min(1, 0.35 * log(1+N) + 0.35 * q + 0.30 * d)
```

- `N`: LLM이 실제로 채점한 리뷰 수 (기본 cap = 25)
- `q`: 리뷰 정보성 평균 (LLM이 `informativeness`로 반환)
- `d`: 리뷰 간 점수 분산의 역수

리뷰 가중치 `w_i = w_recency * w_length * w_relevance`는
`app/services/llm_service.py::compute_weight`를 참고하세요.

## 5. 상권 매칭 전략

`상권특성_행정동_전국_FINAL.xlsx`를 기동 시 1회 로드한 뒤 다음 순서로 매칭합니다.

1. 정규화된 주소 **정확 일치**
2. `시도 · 시군구 · 행정동` **prefix 일치**
3. 동일 시군구 내 **행정동명 일치**
4. `rapidfuzz`로 **fuzzy 매칭** (token_sort_ratio ≥ 78)
5. 시군구 내 **다수결 레이블** fallback
6. 모두 실패 시 기본값 `주거 밀집 상권`

각 매칭은 `match_method`와 `confidence`를 응답에 포함합니다.

지원하는 8개 상권 클래스:
`오피스 밀집 상권`, `주거 밀집 상권`, `대학가/유흥 상권`,
`복합 오피스 상권`, `관광특구 상권`, `트렌드/패션 상권`,
`학원가 특화 상권`, `지식산업센터 상권`.

## 6. 알려진 가정 / 한계

- 국세청 API 키가 없을 때는 `389810319X` 마지막 자리가 `0`인 번호만 `폐업자`
  모의 응답을 돌려줍니다 (UI의 폐업 분기 테스트용).
- moneypin 크롤러가 응답하지 않을 때는 샘플 카페 응답으로 degrade합니다.
- 리뷰 cap은 기본 25건. `LLM_REVIEW_CAP`으로 조절하세요.
- `KMA_ULTRA_NCST_URL`은 data.go.kr의 초단기실황 endpoint이며, 실제 운영
  시 키 등록이 필요합니다.
- LLM 호출은 동시 6개까지 실행됩니다 (`asyncio.Semaphore`). 필요 시
  `llm_service._one` 주변을 조정하세요.
- 브라우저 세션에서 업로드된 `yielda-full-v2.html`의 랜딩 ↔ 온보딩 ↔
  대시보드 스크린 전환을 그대로 유지합니다. 라이브 분석 결과는
  **온보딩 Step 4** 카드에 렌더링됩니다.

## 7. 강화학습 PPO 보정 구동방법

### 실제 적용
```bash
# 1단계: 학습 + 평가 
python -m app.research.rl_calibration.run_calibration --name ambience_rl_summary

# 2단계: 자동 보정
python -m app.research.rl_calibration.apply_to_production \
    --from outputs/rl_calibration/learned_params/ambience_rl_summary.json
```

