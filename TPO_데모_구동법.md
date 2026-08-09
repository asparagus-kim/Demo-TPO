# Yielda Ambience Profiling — 구동법 (이전 개발자 원본)

> ## ⚠ 경로·포트가 현재와 다릅니다
>
> **현재 구동법은 [`README.md`](README.md) "빠른 실행" 또는
> [`HANDOVER.md`](HANDOVER.md) Part I §6 을 보십시오.**
>
> | 이 문서 | 현재 |
> |---|---|
> | 폴더 `tpo_mvp_0` | `yielda_tpo_demo` |
> | 포트 8000 | **8077** |
> | `uvicorn app.main:app --reload` | `python -m uvicorn app.main:app --port 8077 --reload` |
> | 시연 번호 387-81-03198 | mock 모드 전용. 실제 시연은 642-07-00540(카페) / 871-76-00498(헬스장) |
> | 파이프라인에 moneypin | 삭제됨 — bizno + Kakao Local |
>
> **여기에만 있는 것: 강화학습 PPO 보정 명령어** (문서 하단). 단 이 코드는
> 프로덕션에서 호출되지 않습니다.

## =================================================
# Yielda Ambience Profiling — 데모

엔드투엔드 파이프라인: 사업자번호 → 국세청 → moneypin → 상권 → Google Places → 기상청 → LLM → TPO + 분위기(Ambience)

---

## ###############  방법-1 로컬 컴퓨터 구동 #################
1) "tpo_mvp_0\.env"에 API 키 입력

2) 컴퓨터 Terminal
```bash
uvicorn app.main:app --reload
```

3) 브라우저에 Copy and Paste: http://127.0.0.1:8000 
→ enter 387-81-03198 (그레이프스 사업자등록번호)

## ###############  방법-2 도커 이미지 구동 (Docker) #################

## Docker Desktop을 설치 합니다!!! 
1) Docker Desktop 열기

2) 프로젝트 루트의 `.env`에 API 키 입력

3) 컴퓨터 Terminal
```bash
cd C:\path\to\yielda_tpo_demo
docker compose up --build
```
4) 브라우저에 Copy and Paste:  http://localhost:8000

→ enter 387-81-03198 (그레이프스 사업자등록번호)

##  #############  강화학습 PPO 보정 구동방법  #################

```bash
# Stpe 1: 모델 트레이닝
python -m app.research.rl_calibration.run_calibration --name ambience_rl_summary

# Step 2: 계수조정
python -m app.research.rl_calibration.apply_to_production --from outputs/rl_calibration/learned_params/ambience_rl_summary.json
```

## #######################################################
