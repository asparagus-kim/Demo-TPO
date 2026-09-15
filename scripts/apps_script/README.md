# 분석 수집 (Analysis Data Collection) — 설치

분석이 끝날 때마다 **입력값 + 분석 결과 전체**가 Google Sheet 한 행으로 쌓인다.
서버도 DB도 추가하지 않는다: FastAPI → Apps Script 웹앱 → 시트.

```
POST /api/analyse ──► 분석 파이프라인 ──► 응답(사용자)
                              └────────► sheets_logger (fire-and-forget)
                                              └──► Apps Script doPost ──► 시트 append

GET /api/collection ──► sheets_logger.fetch_rows ──► Apps Script doGet ──► 최근 N행
```

수집 실패는 **절대 분석을 실패시키지 않는다**. 시트가 죽어도 사용자는 정상 응답을 받는다.

---

## 1. 시트 + 스크립트 만들기

1. 새 Google Sheet 를 만든다 (예: `Yielda — 분석 수집`). 탭 이름은 건드리지 않아도 된다 —
   스크립트가 `analyses` 탭을 자동으로 만들고 헤더도 자동으로 채운다.
2. **확장 프로그램 → Apps Script** 를 연다.
3. `Code.gs` 내용을 이 폴더의 [Code.gs](./Code.gs) 로 통째로 교체한다.
4. **프로젝트 설정(⚙) → 스크립트 속성** 에서 속성 하나를 추가한다:

   | 이름 | 값 |
   |---|---|
   | `TOKEN` | 아무 랜덤 문자열 (예: `openssl rand -hex 24` 결과) |

   비워 두면 토큰 검사를 건너뛴다. URL 만 알면 누구나 쓸 수 있게 되므로 넣는 쪽을 권한다.

## 2. 웹앱으로 배포

**배포 → 새 배포 → 유형: 웹 앱**

| 항목 | 값 |
|---|---|
| 실행 계정 | **나** (Me) |
| 액세스 권한 | **모든 사용자** (Anyone) |

→ 발급되는 `https://script.google.com/macros/s/****/exec` URL 을 복사한다.

> 「모든 사용자」로 두는 이유: FastAPI 서버가 Google 계정 없이 호출해야 하기 때문.
> 실제 접근 통제는 위의 `TOKEN` 이 담당한다.

> 코드를 고친 뒤에는 **새 배포**(또는 기존 배포의 새 버전)를 만들어야 반영된다.
> 배포 URL 은 유지된다.

## 3. 백엔드 연결

`.env` 에 추가:

```bash
SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/****/exec
SHEETS_WEBHOOK_TOKEN=위에서_넣은_토큰
```

`SHEETS_WEBHOOK_URL` 이 비어 있으면 수집 기능 전체가 조용히 꺼진다(기본 상태).

선택 설정:

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `SHEETS_LOGGING_ENABLED` | `1` | 전체 on/off |
| `SHEETS_LOG_CACHE_HITS` | `1` | 캐시 히트도 기록 (`cache_hit` 열로 구분) |
| `SHEETS_LOG_NEEDS_INPUT` | `0` | 매장 선택 등 중간 단계도 기록 (분석 1건이 2행 이상이 된다) |
| `SHEETS_TIMEOUT_SEC` | `10` | 웹훅 타임아웃 |

**URL 자체가 자격증명이다.** 아는 사람은 누구나 시트에 행을 쓸 수 있으므로
프론트 번들에 넣지 않는다 — 대시보드는 백엔드의 `GET /api/collection` 을 경유한다.
`app/utils/logging.py` 가 이 두 값을 로그에서 자동으로 스크럽한다.

## 4. 확인

```bash
# 서버 재시작 후 분석 한 건 실행
curl -s -X POST localhost:8077/api/analyse \
  -H 'content-type: application/json' -H 'x-yielda-client: curl' \
  -d '{"business_number":"117-12-23963"}' > /dev/null

# 시트에 행이 늘었는지 백엔드를 통해 확인
curl -s 'localhost:8077/api/collection?limit=5' | head -c 400
```

시트에도 새 행이 보이면 끝이다.

---

## 시트에서 데이터 관리하기

스크립트를 붙이면 시트 상단에 **`Yielda 수집`** 메뉴가 생긴다 (메뉴가 안 보이면
시트를 새로고침). 세 가지를 할 수 있다.

| 메뉴 | 하는 일 |
|---|---|
| **표 서식 다시 적용** | 1행 고정 · 앞 4열 고정 · 전체 필터 · 열 너비 · 숫자 서식 · 줄무늬 · 결과별 색 |
| **요약 탭 만들기 / 새로고침** | `요약` 탭 생성. QUERY 수식이라 원본이 늘면 **자동 갱신** |
| **빈 탭·레거시 탭 정리** | `Sheet1` 같은 구버전 탭을 확인 후 삭제 |

서식은 열이 새로 생길 때 자동으로 한 번 적용된다. 나중에 손으로 흐트러뜨렸으면
메뉴에서 다시 적용하면 된다.

몇 가지 의도적인 선택:

- **`timestamp` 는 텍스트(`@`)로 고정한다.** Date 로 바꾸면 `+09:00` 이 사라지고
  로케일에 따라 `11/08` 이 8월 11일로도 11월 8일로도 읽힌다. ISO8601 문자열이라
  사전순 정렬이 곧 시간순 정렬이므로 정렬·필터는 그대로 동작한다.
- **1행(헤더)에는 경고 보호가 걸린다.** 열 이름이 백엔드 `COLUMNS` 와 어긋나면
  매핑이 깨지기 때문. 잠금이 아니라 경고라 필요하면 넘어갈 수 있다.
- **행 색**: `needs_input` 은 회색(오류가 아니라 중간 상태), `closed`·`suspended`·
  `error` 는 붉은색, 동일업체 검증 실패(`consistency = FALSE`)는 주황색 —
  Google 데이터가 버려진 행이라 근거가 약하다는 표시다.

시트가 아주 커지면 `analyses` 를 월별 탭으로 나누고 옛 탭을 보관하는 편이 낫다.
지금 구조에서는 `SHEET_NAME` 만 바꾸면 새 탭에 쌓이기 시작한다.

## 열(컬럼) 바꾸기

열의 정본은 **`app/services/sheets_logger.py` 의 `COLUMNS` 튜플**이다.
스크립트는 헤더를 스스로 맞춘다:

- 시트가 비어 있으면 → 받은 열 목록을 그대로 헤더로 쓴다
- 새 열이 생기면 → 헤더 **오른쪽 끝에 덧붙인다** (기존 데이터 정렬이 깨지지 않는다)
- 열이 빠지면 → 헤더에 남고 이후 행에서는 빈 셀이 된다

즉 기획이 열을 확정하면 `COLUMNS` 와 `build_row()` 만 고치면 되고, 시트나 스크립트는
손대지 않아도 된다. 열 순서를 시트에서 예쁘게 다시 정렬하고 싶으면 스크립트가 아니라
시트에서 직접 열을 옮기면 된다 (스크립트는 헤더 **이름**으로 값을 맞춘다).
