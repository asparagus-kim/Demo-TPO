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
from dataclasses import dataclass, replace as dc_replace
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
    "You score EACH numbered customer review for three latent atmosphere dimensions:\n"
    "1. Energy: lively, busy, stimulating, noisy, exciting vs quiet, calm, subdued\n"
    "2. Tempo: fast, rushed, efficient, quick-turnover, short-stay vs slow, relaxed, lingering\n"
    "3. Mood: cozy, pleasant, stylish, warm, comfortable, emotionally attractive vs dull, cold, stressful\n"
    "You must output valid JSON only, with exactly one entry per review, in the given order."
)

# 리뷰 N건을 **요청 1번**에 묶는다. 예전에는 리뷰마다 1요청(동시 6)이었는데
# Groq 무료 등급의 실제 병목은 TPM 8000 이 아니라 **OTPM(출력 토큰/분) 1000** 이었다.
# 리뷰 1건 응답이 ~165 출력 토큰이라 5건이면 5번째부터 429 → 백오프 4.5초 → 결국
# 휴리스틱으로 떨어졌고, 그게 분석 시간의 51~72% 였다 (2026-09-15 실측).
# 묶으면 시스템 프롬프트를 한 번만 보내고, 출력도 건당 ~83 토큰으로 준다:
#   개별 5회: 출력 ~825 tok · 벽시계 ~6s   →   묶음 1회: 출력 ~382 tok · ~1.1s
#
# `evidence`(설명문) 는 하류 어디서도 읽지 않아 뺐다 — 출력 토큰의 절반이 여기 있었다.
# `occasion_labels` 는 derive_occasion 이 most_common(1) 만 보므로 2개면 충분하다.
# `informativeness` 는 aggregate_text_scores 의 품질 지표(q) 에 쓰이므로 남긴다.
USER_TEMPLATE = (
    "Score every review below. Return JSON with schema:\n"
    "{{\n"
    "  \"scores\": [\n"
    "    {{\"i\": <1-based review number>, \"energy\": 0.0-1.0, \"tempo\": 0.0-1.0, \"mood\": 0.0-1.0,\n"
    "     \"informativeness\": 0.0-1.0,\n"
    "     \"keywords\": [up to 3 short {evidence_lang_label} words],\n"
    "     \"occasion_labels\": [up to 2 short {evidence_lang_label} visit-occasion labels]}}\n"
    "  ]\n"
    "}}\n"
    "No other fields. Exactly one entry per review, in order.\n\n"
    "Shop context:\n"
    "- business_type: {business_type}\n"
    "- trade_area: {trade_area}\n"
    "- weather: {weather_summary}\n"
    "- business_hours: {business_hours}\n\n"
    "Reviews:\n{reviews_block}\n\n"
    "Scoring guidance:\n"
    "- Energy high if the review implies crowd, liveliness, stimulation, noise, excitement\n"
    "- Tempo high if the review implies hurry, short stay, quick service, fast turnover, lunch rush\n"
    "- Mood high if the review implies coziness, beauty, comfort, style, emotional positivity\n"
    "Output JSON only."
)

# 출력 토큰 예산. 실측 건당 ~83 → 여유를 두고 110. Groq 는 max_tokens 가 없으면
# '예상 출력' 을 크게 잡아 "Request too large" 로 요청 자체를 거절한다.
LLM_OUTPUT_TOKENS_PER_REVIEW = 110
LLM_OUTPUT_TOKENS_BASE = 64
# OTPM 1000 ÷ ~83 ≈ 12. 이 위로는 한 요청이 분당 한도를 혼자 다 쓴다.
LLM_BATCH_HARD_CAP = 12


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

def _score_from_payload(item: Dict[str, Any]) -> ReviewScore:
    return ReviewScore(
        energy=float(item.get("energy", 0.5)),
        tempo=float(item.get("tempo", 0.5)),
        mood=float(item.get("mood", 0.5)),
        informativeness=float(item.get("informativeness", 0.7)),
        occasion_labels=[str(x) for x in item.get("occasion_labels", []) if x][:2],
        keywords=[str(x) for x in item.get("keywords", []) if x][:3],
        evidence="",
    )


async def _score_batch(
    texts: List[str],
    *,
    business_type: str,
    trade_area: str,
    weather_summary: str,
    business_hours: str,
    lang: str = "ko",
) -> Optional[List[Optional[ReviewScore]]]:
    """리뷰 N건을 LLM 요청 1번으로 채점한다. `texts` 와 같은 순서·길이의 리스트를 돌려주고,
    모델이 빠뜨린 항목은 None 으로 남긴다(호출자가 휴리스틱으로 채운다).
    요청 자체가 실패하면 None."""
    if not texts:
        return []
    settings = get_settings()
    client = _get_llm_client()
    if client is None:
        return None

    reviews_block = "\n".join(f"{i + 1}. {t.strip()}" for i, t in enumerate(texts))
    prompt = USER_TEMPLATE.format(
        business_type=business_type or "",
        trade_area=trade_area or "",
        weather_summary=weather_summary or "",
        business_hours=business_hours or "",
        reviews_block=reviews_block,
        evidence_lang_label=_evidence_lang_label(lang),
    )
    max_tokens = LLM_OUTPUT_TOKENS_BASE + LLM_OUTPUT_TOKENS_PER_REVIEW * len(texts)

    resp = None
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            resp = await client.chat.completions.create(
                model=settings.openai_model,
                temperature=0.0,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                timeout=30,
            )
            break
        except Exception as exc:
            # 묶음이라 요청은 1번이지만, 직전 분석과 같은 분(minute) 안이면 OTPM 이 남아
            # 있지 않을 수 있다. 429 만 짧게 재시도하고, 그래도 안 되면 휴리스틱으로.
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

    items = payload.get("scores") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        logger.warning("LLM batch payload has no 'scores' list: %s", content[:200])
        return None

    out: List[Optional[ReviewScore]] = [None] * len(texts)
    for pos, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        # 모델이 준 번호(i, 1-based) 를 우선 믿고, 없거나 범위를 벗어나면 순서로 맞춘다.
        try:
            idx = int(item.get("i", pos + 1)) - 1
        except (TypeError, ValueError):
            idx = pos
        if not (0 <= idx < len(texts)):
            idx = pos
        if 0 <= idx < len(texts) and out[idx] is None:
            out[idx] = _score_from_payload(item)
    missing = sum(1 for x in out if x is None)
    if missing:
        logger.warning("LLM batch: %d/%d 건 누락 → 휴리스틱으로 보충", missing, len(texts))
    return out


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
    # 상한이 곧 묶음 크기다. 12 위로는 요청 1번이 OTPM(1000/분) 을 혼자 다 쓴다.
    cap = max(1, min(settings.llm_review_cap, LLM_BATCH_HARD_CAP))
    selected = [r for r in reviews if (r.text or "").strip()]
    selected.sort(key=lambda r: len(r.text or ""), reverse=True)
    selected = selected[:cap]
    if not selected:
        return []

    use_llm = not settings.effective_mock_mode() and bool(settings.openai_api_key)
    logger.info("score_reviews: n=%d use_llm=%s (batched)", len(selected), use_llm)

    results: List[Optional[ReviewScore]] = [None] * len(selected)

    if use_llm:
        cache = get_cache("llm")
        context_fp = f"{business_type}|{trade_area}|{weather_summary}|{business_hours}"
        keys = [_cache_key(settings.openai_model, r.text, context_fp) for r in selected]
        # 캐시는 리뷰 단위로 유지한다 — 같은 매장을 다시 분석하면 묶음 자체가 필요 없다.
        misses = [i for i, k in enumerate(keys) if k not in cache]
        for i, k in enumerate(keys):
            if k in cache:
                results[i] = cache[k]

        if misses:
            batch = await _score_batch(
                [selected[i].text for i in misses],
                business_type=business_type,
                trade_area=trade_area,
                weather_summary=weather_summary,
                business_hours=business_hours,
                lang=lang,
            )
            if batch:
                for j, i in enumerate(misses):
                    score = batch[j] if j < len(batch) else None
                    if score is not None:
                        results[i] = score
                        cache[keys[i]] = score

    out: List[ReviewScore] = []
    for i, review in enumerate(selected):
        score = results[i] or _heuristic_score(review)
        # 캐시된 객체를 직접 고치면 다른 분석의 가중치까지 바뀐다 — 복제해서 붙인다.
        out.append(dc_replace(score, weight=compute_weight(review)))
    return out



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
