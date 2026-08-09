# yielda_tpo_demo

사업자등록번호 10자리만 입력하면 그 매장에 맞는 음악을 골라 재생하는 시연용 데모.
소상공인 통합지원 파일럿(엠금융 협업)의 승인 자료 겸 D2D 세일즈 키트입니다.

Type a 10-digit Korean business registration number; the app works out the store's
industry, address, trade area, opening hours and current weather from free/public
APIs, scores its "ambience", and plays 10 matching tracks.

**미배포 상태입니다** — 배포는 대표자 결정 대기 중. / Not deployed yet.

---

## 👉 개발자는 여기부터 / Developers start here

### **[`HANDOVER.md`](HANDOVER.md)**

코드를 보기 전에 읽으십시오. **Part 0**은 소스 한 줄 없이 읽히고, 왜 이 구조인지를
설명합니다. 이 README에 없는 내용은 전부 거기 있습니다.

> Read it before opening the code. **Part 0** explains the constraints behind the
> design and needs no source file. Everything not in this README is in there.

한국어로 읽으시려면 [`HANDOVER_ko.md`](HANDOVER_ko.md) — 같은 내용의 한국어판입니다(두 판본이 어긋나면 영문판이 정본).

| | |
|---|---|
| **Part 0** | 목표와 제약, 방향이 바뀐 7개 지점, 어디에 투자할지 |
| **Part I** | 파이프라인 · 모듈 지도 · 로컬 실행 · 밟은 함정 20건 · **비밀값 취급** · 테스트 |
| **Part II** | API별 한계와 우회책, 유료 전환 시 삭제 가능한 코드 |
| **Part III** | 한국 도메인 사전 (사업자번호 구조, 법정동/행정동, data.go.kr …) |

---

## 빠른 실행 / Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # 키를 채워 넣습니다 / fill in your keys
python -m uvicorn app.main:app --port 8077 --reload
```

`http://localhost:8077` 을 엽니다. 화면의 예시 버튼 두 개(카페 · 헬스장)는 후보 선택
없이 한 번에 확정되는 매장이라 시연 중 흐름이 끊기지 않습니다.

**`--reload` 를 빼지 마십시오.** 코드 수정이 반영되지 않아 낡은 동작을 디버깅하게 됩니다.
키가 없으면 자동으로 mock 모드로 떨어집니다.

### 필요한 키 (전부 무료 티어)

| 변수 | 발급처 |
|---|---|
| `DATA_GO_KR_API_KEY` | data.go.kr — 국세청 사업자등록 상태조회 |
| `KMA_API_KEY` | data.go.kr — 기상청 초단기실황 (같은 키 사용 가능) |
| `KAKAO_REST_API_KEY` | developers.kakao.com — **카카오맵 사용설정 ON 필수** |
| `BIZNO_API_KEY` | bizno.net — 사업자번호 → 상호명 |
| `OPENAI_API_KEY` + `OPENAI_BASE_URL` | console.groq.com (OpenAI 호환) |
| `GOOGLE_MAPS_API_KEY` | GCP — Places API (New), 리뷰·영업시간 전용 |

data.go.kr은 **Decoding 키**를 쓰십시오. Encoding 키를 넣으면 401/403이 납니다
(`app/config.py`가 감지해 자동 보정하고 경고를 남깁니다). 이유는 `HANDOVER.md` Part III §4.2.

발급 절차는 [`TPO_교체설계_사업자조회_KakaoLocal.md`](TPO_교체설계_사업자조회_KakaoLocal.md) §7에
화면 단위로 있습니다.

---

## 검증 / Verify

```bash
python scripts/check_keys.py                    # 키 7종 점검
python -m pytest -q                             # 오프라인 테스트 187개
python scripts/smoke_all.py                     # 실제 API 대상 E2E 17개
python scripts/trade_area_validate.py report    # 상권 정확도 (API 호출 0)
```

2026-08-06 기준 기대값: `check_keys` OK 9 / WARN 2 / FAIL 1(NPS — 미사용),
`pytest` 187 통과, `smoke_all` 17/17 통과, 상권 27/30 (90%).

---

## 지금 상태 / Current state

| | |
|---|---|
| 동작 | 5개 업종 실측 검증 (카페 2 · 헬스 2 · 미용실) |
| 음원 | 620곡 · 11업종군 · R2 재생 620/620 |
| 상권 판정 | 30곳 벤치마크 90% (기존 엑셀 방식 37%) |
| 지연 | 2~10초 (콜드) · 캐시 히트 시 즉시 |
| 반응형 | 375 / 768 / 1440px |
| **UI** | **임의로 작성한 값 — 전체 디자인 변경 예정. 확정 사양이 아닙니다.** |
| 배포 | 미배포 |
| CI | 없음. git 커밋도 0개 |

---

## 문서 지도 / Documents

| 파일 | 성격 | 읽는 시점 |
|---|---|---|
| **[`HANDOVER.md`](HANDOVER.md)** | **인수인계 정본** (영문) | **처음이자 대부분** |
| [`HANDOVER_ko.md`](HANDOVER_ko.md) | 위 문서의 한국어판 — 기획·경영진 검토용 | 한국어로 내용을 파악할 때 |
| [`TPO_시연페이지_구현계획.md`](TPO_시연페이지_구현계획.md) | 작업 로그 — 구현 순서·실측 기록·날짜별 결정 | 특정 결정의 원래 근거를 파고들 때 |
| [`TPO_교체설계_사업자조회_KakaoLocal.md`](TPO_교체설계_사업자조회_KakaoLocal.md) | 설계 문서 — bizno·Kakao 교체 상세, **키 발급 절차** | 키를 발급할 때 |
| [`TPO_데모_설명서.md`](TPO_데모_설명서.md) | 이전 개발자 작성 원본 설명서 | 강화학습 PPO 실험을 볼 때 |
| [`TPO_데모_구동법.md`](TPO_데모_구동법.md) | 구동 절차 (요약본은 위 "빠른 실행") | — |
| [`HANDOVER_PLAN.md`](HANDOVER_PLAN.md) | 인수인계 문서 작성 계획·진행 상황 | 문서 작업을 이어받을 때 |

**충돌하면 `HANDOVER.md`가 정본입니다.** 나머지는 작성 시점의 기록이라 낡은 수치가
남아 있을 수 있습니다.

---

## 환경 주의 / Environment note

이 개발 PC는 Windows Smart App Control이 켜져 있어 pandas 최신 버전의 DLL 로드가
차단됩니다. `pandas==2.2.3`을 사용하십시오. 다른 환경에서는 해당 없습니다.

> Windows Smart App Control on the original dev machine blocks newer pandas DLLs.
> Pin `pandas==2.2.3` there; irrelevant elsewhere.
