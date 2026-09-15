"""LLM review scorer.

Sends each selected review to OpenAI with a strict JSON schema and returns
per-review {energy, tempo, mood, occasion_labels, keywords, evidence}.

Resilient to:
- missing OPENAI_API_KEY (auto-falls back to deterministic heuristic)
- LLM JSON parse failures (skips the review)
- transient network errors (retried)

Concurrency is capped by a semaphore to avoid burning quota.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import get_settings
from ..schemas import PlaceReview
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------- prompts

SYSTEM_PROMPT = (
    "You are an evaluator for Korean retail ambience profiling.\n"
    "You must score a single customer review for three latent atmosphere dimensions:\n"
    "1. Energy: lively, busy, stimulating, noisy, exciting vs quiet, calm, subdued\n"
    "2. Tempo: fast, rushed, efficient, quick-turnover, short-stay vs slow, relaxed, lingering\n"
    "3. Mood: cozy, pleasant, stylish, warm, comfortable, emotionally attractive vs dull, cold, stressful\n"
    "You must output valid JSON only."
)

# `evidence_lang_label` is always "Korean" (한국어 단일 서비스). 중국어 지원 제거됨.
# the model writes the human-facing `evidence` / `keywords` / `occasion_labels`
# fields in the language the UI is currently rendering. Numeric fields and the
# JSON schema itself are unaffected.
USER_TEMPLATE = (
    "Given the following review and shop context, return JSON with schema:\n"
    "{{\n"
    "  \"energy\": 0.0-1.0,\n"
    "  \"tempo\": 0.0-1.0,\n"
    "  \"mood\": 0.0-1.0,\n"
    "  \"occasion_labels\": [string in {evidence_lang_label}],\n"
    "  \"keywords\": [string in {evidence_lang_label}],\n"
    "  \"evidence\": \"short {evidence_lang_label} explanation\",\n"
    "  \"informativeness\": 0.0-1.0\n"
    "}}\n\n"
    "Shop context:\n"
    "- business_type: {business_type}\n"
    "- trade_area: {trade_area}\n"
    "- weather: {weather_summary}\n"
    "- business_hours: {business_hours}\n\n"
    "Review:\n{review_text}\n\n"
    "Scoring guidance:\n"
    "- Energy high if the review implies crowd, liveliness, stimulation, noise, excitement\n"
    "- Tempo high if the review implies hurry, short stay, quick service, fast turnover, lunch rush\n"
    "- Mood high if the review implies coziness, beauty, comfort, style, emotional positivity\n"
    "Output JSON only."
)


def _evidence_lang_label(lang: str = "ko") -> str:  # noqa: ARG001 — 한국어 고정
    return "Korean"


@dataclass
class ReviewScore:
    energy: float
    tempo: float
    mood: float
    informativeness: float
    occasion_labels: List[str]
    keywords: List[str]
    evidence: str
    weight: float = 1.0


# --------------------------------------------------------------------- helpers

def _parse_relative_weeks(text: Optional[str]) -> float:
    if not text:
        return 1.0
    m = re.search(r"(\d+)", text)
    if not m:
        return 1.0
    n = int(m.group(1))
    if "일" in text:
        return max(0.5, 1.0 - n / 60.0)
    if "주" in text:
        return max(0.5, 1.0 - n / 26.0)
    if "개월" in text or "달" in text:
        return max(0.4, 1.0 - n / 12.0)
    if "년" in text:
        return max(0.3, 1.0 - n / 5.0)
    return 1.0


def _length_weight(text: str) -> float:
    chars = len(text or "")
    if chars <= 20:
        return 0.4
    if chars <= 60:
        return 0.7
    if chars <= 160:
        return 1.0
    return 1.15


_RELEVANCE_TOKENS = [
    "분위기", "좌석", "자리", "공부", "작업", "미팅", "데이트", "가족",
    "친절", "빠른", "느린", "오래", "잠깐", "혼잡", "붐비", "조용",
    "커피", "음료", "디저트", "맛", "노이즈", "시끄럽", "편안", "아늑",
]


def _relevance_weight(text: str) -> float:
    if not text:
        return 0.6
    hits = sum(1 for kw in _RELEVANCE_TOKENS if kw in text)
    return 0.6 + min(hits, 4) * 0.12


def compute_weight(review: PlaceReview) -> float:
    w_recency = _parse_relative_weeks(review.relative_time)
    w_length = _length_weight(review.text)
    w_relevance = _relevance_weight(review.text)
    return float(w_recency * w_length * w_relevance)


# 무료 플랜(Groq 8000 TPM · OpenRouter 20 req/min)에서는 429 가 일상이다.
# 짧게 두 번만 더 시도한다 — 분석 1건이 30초를 넘기면 사용자가 떠난다.
LLM_MAX_ATTEMPTS = 3
LLM_RETRY_BASE_SEC = 1.5

_llm_client = None


def _is_rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429 or "429" in str(exc)


def _get_llm_client():
    """OpenAI 호환 클라이언트 하나를 만들어 재사용한다.

    ## 왜 base_url 을 명시하는가

    예전에는 `AsyncOpenAI(api_key=...)` 만 넘기고 base_url 은 OpenAI SDK 가
    `OPENAI_BASE_URL` 환경변수에서 알아서 집어가게 두었다. 동작은 했지만
    **코드 어디에도 어떤 제공자를 쓰는지 드러나지 않았다** — Groq 가 모델을
    폐기했을 때 원인 추적이 그만큼 느려졌다. 이제 설정에서 읽어 명시적으로 넘긴다.

    OpenAI / Groq / OpenRouter 모두 같은 스펙이므로 `OPENAI_BASE_URL` 과
    `OPENAI_MODEL` 두 줄만 바꾸면 제공자가 갈린다.
    """
    global _llm_client
    if _llm_client is not None:
        return _llm_client

    settings = get_settings()
    try:
        from openai import AsyncOpenAI
    except Exception:
        return None

    base_url = settings.openai_base_url or None
    headers = {}
    # OpenRouter 는 이 두 헤더로 순위 페이지에 앱을 노출한다. 선택 사항이다.
    if base_url and "openrouter.ai" in base_url:
        if settings.openrouter_site_url:
            headers["HTTP-Referer"] = settings.openrouter_site_url
        if settings.openrouter_app_name:
            headers["X-Title"] = settings.openrouter_app_name

    _llm_client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=base_url,
        default_headers=headers or None,
        max_retries=0,   # 재시도는 위에서 429 만 골라서 직접 한다
    )
    logger.info("LLM client: %s @ %s", settings.openai_model, base_url or "api.openai.com")
    return _llm_client


def reset_llm_client() -> None:
    """설정을 바꾼 뒤 클라이언트를 새로 만들게 한다 (테스트·핫리로드용)."""
    global _llm_client
    _llm_client = None


def _cache_key(model: str, review_text: str, context_fingerprint: str) -> str:
    digest = hashlib.sha1((model + "|" + context_fingerprint + "|" + review_text).encode("utf-8")).hexdigest()
    return f"rv:{digest}"


# ---------------------------------------------------------------- heuristic fallback

_POS_ENERGY = ["붐비", "활기", "시끄럽", "활발", "인파", "라인업", "대기", "피크", "사람 많", "에너지"]
_NEG_ENERGY = ["한산", "조용", "차분", "여유", "적막"]
_POS_TEMPO = ["빠른", "테이크아웃", "회전", "잠깐", "바쁜", "러시", "점심", "급한", "빨라"]
_NEG_TEMPO = ["오래", "여유", "머물", "느긋", "천천히", "쉬는"]
_POS_MOOD = ["아늑", "분위기", "예쁘", "감성", "편안", "좋아", "친절", "세련", "무드", "따뜻"]
_NEG_MOOD = ["별로", "실망", "불편", "짜증", "차가운", "딱딱"]


def _score_tokens(text: str, pos: List[str], neg: List[str], base: float = 0.5) -> float:
    if not text:
        return base
    score = base
    for tok in pos:
        if tok in text:
            score += 0.08
    for tok in neg:
        if tok in text:
            score -= 0.1
    return max(0.0, min(1.0, score))


def _heuristic_score(review: PlaceReview) -> ReviewScore:
    text = review.text or ""
    energy = _score_tokens(text, _POS_ENERGY, _NEG_ENERGY)
    tempo = _score_tokens(text, _POS_TEMPO, _NEG_TEMPO)
    mood = _score_tokens(text, _POS_MOOD, _NEG_MOOD)

    occasions: List[str] = []
    if any(k in text for k in ["점심", "런치"]):
        occasions.append("점심 커피")
    if any(k in text for k in ["테이크아웃", "회전", "빠른"]):
        occasions.append("테이크아웃")
    if any(k in text for k in ["미팅", "업무"]):
        occasions.append("업무 미팅")
    if any(k in text for k in ["공부", "작업", "콘센트"]):
        occasions.append("공부/작업")
    if any(k in text for k in ["데이트", "커플"]):
        occasions.append("데이트")
    if any(k in text for k in ["가족", "아이"]):
        occasions.append("가족 외식")
    if any(k in text for k in ["저녁", "야간", "밤"]):
        occasions.append("야간 모임")

    keywords = []
    for kw in _POS_ENERGY + _POS_TEMPO + _POS_MOOD:
        if kw in text and kw not in keywords:
            keywords.append(kw)

    info = min(1.0, 0.4 + len(text) / 240.0 + (0.15 if occasions else 0.0))
    return ReviewScore(
        energy=energy,
        tempo=tempo,
        mood=mood,
        informativeness=info,
        occasion_labels=occasions[:3],
        keywords=keywords[:5],
        evidence="휴리스틱 기반 키워드 점수",
    )


# ------------------------------------------------------------------- OpenAI call

async def _call_openai(
    text: str,
    *,
    business_type: str,
    trade_area: str,
    weather_summary: str,
    business_hours: str,
    lang: str = "ko",
) -> Optional[ReviewScore]:
    settings = get_settings()
    cache = get_cache("llm")
    # 한국어 단일 서비스 — lang 은 프롬프트 라벨용으로만 남아 있다
    # outputs that should not collide.
    context_fp = f"{business_type}|{trade_area}|{weather_summary}|{business_hours}"
    ck = _cache_key(settings.openai_model, text, context_fp)
    if ck in cache:
        return cache[ck]

    client = _get_llm_client()
    if client is None:
        return None
    prompt = USER_TEMPLATE.format(
        business_type=business_type or "",
        trade_area=trade_area or "",
        weather_summary=weather_summary or "",
        business_hours=business_hours or "",
        review_text=text,
        evidence_lang_label=_evidence_lang_label(lang),
    )

    resp = None
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                timeout=30,
            )
            break
        except Exception as exc:
            # 무료 플랜은 분당 한도가 낮아 동시 6건을 쏘면 429 가 섞여 나온다.
            # 예전에는 첫 실패에서 바로 휴리스틱으로 떨어졌고, 그 사실이 응답
            # 어디에도 남지 않아 점수가 조용히 나빠졌다. 429 만 짧게 재시도한다.
            if _is_rate_limited(exc) and attempt < LLM_MAX_ATTEMPTS - 1:
                delay = LLM_RETRY_BASE_SEC * (2 ** attempt)
                logger.warning("LLM rate-limited (%s) — %.1fs 후 재시도 %d/%d",
                               settings.openai_model, delay, attempt + 1, LLM_MAX_ATTEMPTS - 1)
                await asyncio.sleep(delay)
                continue
            logger.warning("LLM call failed (%s @ %s): %s", settings.openai_model,
                           settings.openai_base_url or "openai-default", exc)
            return None
    if resp is None:
        return None

    content = (resp.choices[0].message.content or "").strip()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON: %s", content[:200])
        return None

    score = ReviewScore(
        energy=float(payload.get("energy", 0.5)),
        tempo=float(payload.get("tempo", 0.5)),
        mood=float(payload.get("mood", 0.5)),
        informativeness=float(payload.get("informativeness", 0.7)),
        occasion_labels=[str(x) for x in payload.get("occasion_labels", []) if x][:5],
        keywords=[str(x) for x in payload.get("keywords", []) if x][:5],
        evidence=str(payload.get("evidence", ""))[:240],
    )
    cache[ck] = score
    return score


# --------------------------------------------------------------------- public API

async def score_reviews(
    reviews: List[PlaceReview],
    *,
    business_type: str,
    trade_area: str,
    weather_summary: str,
    business_hours: str,
    lang: str = "ko",
) -> List[ReviewScore]:
    settings = get_settings()
    cap = max(5, min(settings.llm_review_cap, 40))
    selected = [r for r in reviews if (r.text or "").strip()]
    selected.sort(key=lambda r: len(r.text or ""), reverse=True)
    selected = selected[:cap]
    if not selected:
        return []

    use_llm = not settings.effective_mock_mode() and bool(settings.openai_api_key)
    logger.info("score_reviews: n=%d use_llm=%s", len(selected), use_llm)

    sem = asyncio.Semaphore(6)
    results: List[Optional[ReviewScore]] = [None] * len(selected)

    async def _one(idx: int, review: PlaceReview):
        async with sem:
            if use_llm:
                score = await _call_openai(
                    review.text,
                    business_type=business_type,
                    trade_area=trade_area,
                    weather_summary=weather_summary,
                    business_hours=business_hours,
                    lang=lang,
                )
                if score is None:
                    score = _heuristic_score(review)
            else:
                score = _heuristic_score(review)
            score.weight = compute_weight(review)
            results[idx] = score

    await asyncio.gather(*[_one(i, r) for i, r in enumerate(selected)])

    return [r for r in results if r is not None]



def aggregate_text_scores(scores: List[ReviewScore]) -> Dict[str, float]:
    if not scores:
        return {"E_text": 0.5, "T_text": 0.5, "M_text": 0.5, "c_text": 0.0, "n": 0.0}
    tot_w = sum(s.weight for s in scores) or 1e-9
    E = sum(s.weight * s.energy for s in scores) / tot_w
    T = sum(s.weight * s.tempo for s in scores) / tot_w
    M = sum(s.weight * s.mood for s in scores) / tot_w
    q = sum(s.informativeness for s in scores) / len(scores)

    # consistency (d) via inverse of average std across 3 axes
    def _std(values: List[float]) -> float:
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        return math.sqrt(var)

    avg_std = (_std([s.energy for s in scores])
               + _std([s.tempo for s in scores])
               + _std([s.mood for s in scores])) / 3.0
    d = max(0.0, 1.0 - avg_std * 1.4)

    N = len(scores)
    c_text = min(1.0, 0.35 * math.log(1 + N) + 0.35 * q + 0.30 * d)

    return {"E_text": E, "T_text": T, "M_text": M, "c_text": c_text, "n": N, "q": q, "d": d}
