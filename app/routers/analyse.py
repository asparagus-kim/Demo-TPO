"""End-to-end analyse pipeline endpoint.

Order:
    1. validate + format business number
    2. NTS status lookup (reject 폐업자 / 휴업자 with friendly response)
    3. bizno 로 상호명 확보 (실패 시 needs_input 으로 사용자 입력 요청)
    4. Kakao Local 로 업종·주소·좌표 확정 (후보 다건이면 needs_input 으로 선택 요청)
    5. trade-area label from Excel  ← Kakao 주소 기준
    6. Google Places — 리뷰·영업시간만 (키 없음/일별 상한 시 degrade)
    6.1 동일 업체 검증 (Kakao 확정 정보 vs Google 후보)
        - if inconsistent: discard Google hours / reviews
    6.2 리뷰·영업시간 부족 시 웹검색 보강
        - Places API (New)는 리뷰를 매장당 5건만 주므로 상시 보강 경로다
    7. KMA weather — 좌표는 Kakao가 canonical
    8. LLM scoring of the chosen text corpus (Google / web / mixed / none)
    9. TPO profile + ambience fusion + provenance reporting
    10. 음원 추천 (로컬 매니페스트)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ..config import get_settings
from ..schemas import (
    AnalyseRequest,
    AnalyseResponse,
    BusinessInfo,
    EntityValidation,
    EvidenceProvenance,
    GooglePlaces,
    NeedsInput,
    PlaceCandidate,
    TpoProfile,
    TradeAreaMatch,
    Weather,
)
from ..services import (
    ambience_service,
    biz_lookup_service,
    entity_validation_service,
    kakao_local_service,
    llm_service,
    music_service,
    nts_service,
    places_service,
    sheets_logger,
    trade_area_service,
    weather_service,
    web_search_service,
)
from ..utils.cache import get_cache
from ..utils.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _cache_key(digits: str, *, company_name: str = "", place_id: str = "") -> str:
    """캐시 키에 사용자 선택을 포함한다.

    `analyse:{digits}` 만 쓰면 같은 사업자번호에 서로 다른 상호명·매장을 골라도
    **처음 결과가 고착**된다. 사용자 입력이 없으면 접미사는 '-'다.
    """
    extra = f"{company_name}|{place_id}".strip("|")
    if not extra:
        return f"analyse:{digits}:-"
    digest = hashlib.sha1(extra.encode("utf-8")).hexdigest()[:8]
    return f"analyse:{digits}:{digest}"


@router.post("/api/analyse", response_model=AnalyseResponse)
async def analyse(
    payload: AnalyseRequest,
    x_yielda_client: str = Header(default=""),
) -> AnalyseResponse:
    settings = get_settings()
    raw_value = payload.business_number
    started = time.perf_counter()

    def _collect(response: AnalyseResponse, outcome: str, *, cache_hit: bool = False) -> AnalyseResponse:
        """분석 수집 시트에 한 행 남기고 응답을 그대로 돌려준다 (fire-and-forget).

        모든 종료 지점을 이 함수로 감싼다. 실패해도 응답에는 영향이 없다.
        """
        sheets_logger.log_analysis(
            response,
            request=payload,
            outcome=outcome,
            client=x_yielda_client or "api",
            duration_ms=int((time.perf_counter() - started) * 1000),
            cache_hit=cache_hit,
        )
        return response

    # -------- Step 1: validate business number
    try:
        digits = nts_service.normalize_business_number(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"사업자번호 형식 오류: {exc}")

    formatted = nts_service.format_business_number(digits)
    logger.info("=== analyse start: %s (mock=%s) ===", formatted, settings.effective_mock_mode())

    cache = get_cache("analysis")
    ckey = _cache_key(digits,
                      company_name=payload.company_name or "",
                      place_id=payload.place_id or "")
    if ckey in cache:
        logger.info("analyse cache hit for %s", ckey)
        cached = cache[ckey]
        # 캐시 히트도 '사용자가 분석을 돌린' 사건이다 — 수집에서 빠지면 시트의
        # 실행 횟수가 실제보다 적게 보인다. cache_hit 열로 구분한다.
        return _collect(cached, "success" if cached.success else "error", cache_hit=True)

    # -------- Step 2: NTS
    nts = await nts_service.lookup_status(digits)
    status_label = nts.get("status_label") or nts_service.STATUS_LOOKUP_FAILED

    if status_label == nts_service.STATUS_CLOSED:
        return _collect(AnalyseResponse(
                success=False,
                business_number=formatted,
                nts_status=status_label,
                error="입력하신 사업자등록번호는 폐업 상태로 확인되어 분석을 진행할 수 없습니다.",
                debug={"nts": nts, "llm_prompt_version": settings.prompt_version, "reviews_used": 0},
            ), "closed")
    if status_label in (nts_service.STATUS_SUSPENDED,):
        return _collect(AnalyseResponse(
                success=False,
                business_number=formatted,
                nts_status=status_label,
                error="입력하신 사업자등록번호는 휴업 상태로 확인되어 분석을 진행할 수 없습니다.",
                debug={"nts": nts, "llm_prompt_version": settings.prompt_version, "reviews_used": 0},
            ), "suspended")
    if status_label != nts_service.STATUS_ACTIVE and not settings.effective_mock_mode():
        logger.warning("NTS status not active (%s) — continuing anyway with degraded confidence", status_label)

    # -------- Step 3: 상호명 및 상태 보강 (bizno → 사용자 입력)
    #
    # bizno 무료 플랜은 상호명과 사업 상태(bstt)를 준다 — 업종·주소·좌표는 Step 4에서 Kakao가 채운다.
    identity = await biz_lookup_service.resolve_identity(
        digits, user_company_name=payload.company_name, user_address=payload.address_hint,
    )

    # NTS API 503 장애로 status_label이 '조회실패'일 때, Bizno가 돌려준 사업 상태(예: '계속사업자')가 있으면 자동 복구한다
    if status_label == nts_service.STATUS_LOOKUP_FAILED and identity.registered_status:
        status_label = identity.registered_status
        logger.info("NTS status recovered via Bizno API: %s", status_label)

    if identity.needs_user_input or not identity.company_name:
        return _collect(AnalyseResponse(
                success=False,
                business_number=formatted,
                nts_status=status_label,
                error=identity.message or "상호명을 확인하지 못했습니다.",
                needs_input=NeedsInput(
                    reason="company_name",
                    message=identity.message or biz_lookup_service.MSG_NEED_NAME,
                    fields=["company_name", "address_hint"],
                    biz_candidates=identity.candidates,
                ),
                debug={"nts": nts, "identity_source": identity.source,
                       "llm_prompt_version": settings.prompt_version, "reviews_used": 0},
            ), "needs_input")

    # -------- Step 4: Kakao Local — 업종·주소·좌표 확정
    place_candidates = await kakao_local_service.search_candidates(
        identity.company_name, address_hint=payload.address_hint or identity.address,
    )

    chosen: Optional[PlaceCandidate] = None
    if payload.place_id:
        # 사용자가 후보를 고른 재요청. 목록에 없으면(캐시 만료 등) 그냥 자동 선택으로 넘어간다.
        chosen = next((c for c in place_candidates if c.place_id == payload.place_id), None)
    if chosen is None:
        chosen, pick_reason = kakao_local_service.pick_best(place_candidates)
    else:
        pick_reason = "user"

    if chosen is None:
        # 자동 확정 불가 → 사용자가 고르게 한다. 후보에 주소가 함께 뜨므로
        # 점주는 자기 가게를 바로 알아본다.
        msg = {
            "ambiguous": f"'{identity.company_name}' 로 검색된 매장이 여러 곳입니다. 내 매장을 선택해 주세요.",
            "low_score": f"'{identity.company_name}' 와 일치하는 매장을 찾지 못했습니다. 지역을 입력하거나 상호명을 확인해 주세요.",
            "empty": f"'{identity.company_name}' 로 검색된 매장이 없습니다. 상호명이나 지역을 입력해 주세요.",
        }.get(pick_reason, "매장을 선택해 주세요.")
        return _collect(AnalyseResponse(
                success=False,
                business_number=formatted,
                nts_status=status_label,
                business_info=BusinessInfo(company_name=identity.company_name),
                error=msg,
                needs_input=NeedsInput(
                    reason="place_choice" if place_candidates else "not_found",
                    message=msg,
                    # `company_name` 이 반드시 들어가야 한다. 프론트는 이 목록을 보고
                    # 상호명 입력칸을 그릴지 정하는데, 빠져 있으면 지역칸만 나온다.
                    # 그런데 여기까지 온 이유는 대부분 **bizno 상호명이 Kakao 에 없어서**다
                    # (법인명·협회명이 그대로 오는 경우). 지역만 바꿔 재요청하면 같은
                    # 상호명으로 다시 검색하므로 영원히 같은 화면으로 돌아온다.
                    fields=["place_id", "company_name", "address_hint"],
                    place_candidates=place_candidates,
                ),
                debug={"nts": nts, "identity_source": identity.source,
                       "kakao_candidates": len(place_candidates), "pick_reason": pick_reason,
                       "llm_prompt_version": settings.prompt_version, "reviews_used": 0},
            ), "needs_input")

    # 확정. 업종·주소는 Kakao가 canonical (등록 주소는 본점일 수 있어 상권 매칭에 못 쓴다).
    business_info = BusinessInfo(
        company_name=identity.company_name,
        business_type=chosen.business_type or identity.business_type,
        address=chosen.address,
        company_intro=identity.company_intro,
    )
    logger.info("매장 확정: '%s' / %s / %s (score=%.2f, %s)",
                chosen.place_name, chosen.business_type, chosen.address, chosen.score, pick_reason)

    # -------- Step 5: 상권 판정
    #
    # 1차: 매장 좌표 주변 업종 분포로 판정 (검증 세트 37곳에서 90%)
    # 2차: 실패 시 기존 엑셀 조회 (43%) — 좌표가 없거나 Kakao 집계 실패 시
    #
    # 엑셀 경로는 주소 종류에 따라 이렇게 갈린다:
    #   도로명('만리재로 193') → 동 정보 없음 / 지번('만리동1가') → **법정동**
    #   좌표→행정동('중림동')  → 정확히 매칭
    ta_service = trade_area_service.get_trade_area_service()

    # 상권 집계(Kakao 9건) · Places 조회(Google 2건) · 날씨(KMA 1건)는 서로를 필요로
    # 하지 않는다. 예전에는 순서대로 await 해서 세 왕복을 차례로 기다렸고 이 구간만
    # 3~4초였다. 동시에 띄우면 가장 느린 하나(상권 집계)만큼만 걸린다.
    #
    # 날씨는 좌표만 있으면 되고 좌표는 Kakao가 canonical이므로 보통 여기 포함된다.
    # `chosen.location` 이 없을 때만 Places 좌표에 의존하므로 그 경우는 뒤로 미룬다.
    #
    # These three stages are mutually independent; awaiting them in sequence cost
    # 3–4s. Weather joins the fan-out whenever Kakao gave us coordinates, and only
    # falls back to the Places coordinate (below) when it did not.
    _weather_first = chosen.location is not None
    _fanout = [
        kakao_local_service.surroundings(
            chosen.location, own_code=chosen.category_group_code
        ),
        places_service.lookup_place(business_info.company_name, business_info.address),
    ]
    if _weather_first:
        _fanout.append(weather_service.fetch_weather(chosen.location))

    _fanned = await asyncio.gather(*_fanout)
    surround, places_candidate = _fanned[0], _fanned[1]
    weather_early = _fanned[2] if _weather_first else None

    trade_area_evidence = ""

    if surround and sum(surround["counts"].values()) > 0:
        profile = trade_area_service.build_profile(surround["counts"], surround["univ"])
        label, ta_conf, why = trade_area_service.classify_by_surroundings(profile)
        trade_area_evidence = trade_area_service.evidence_text(profile)
        trade_area = TradeAreaMatch(
            label=label,
            matched_address=business_info.address,
            match_method="surroundings",
            confidence=round(ta_conf, 2),
            # '분석 근거' 10줄 템플릿용 원본 수치 + 판정 기준 트레이스.
            surroundings=trade_area_service.surroundings_payload(
                profile,
                own_code=str(surround.get("own_code") or chosen.category_group_code or ""),
                own_count=surround.get("own_count"),
            ),
            criteria=trade_area_service.criteria_trace(profile),
        )
        logger.info("상권 판정(주변분포): %s — %s | %s", label, why, trade_area_evidence)
    else:
        admin_dong = await kakao_local_service.region_from_coord(chosen.location)
        trade_area = ta_service.match(admin_dong or chosen.region_address or business_info.address)
        why = f"행정동 '{trade_area.matched_address or '-'}' 기준 (사전 분류표)"
        logger.info("상권 판정(엑셀 폴백): %s (%s)", trade_area.label, trade_area.match_method)
    trade_area_reason = why
    logger.info("trade_area: label=%s method=%s conf=%.2f", trade_area.label, trade_area.match_method, trade_area.confidence)

    # -------- Step 6: Google Places — 리뷰·영업시간만 (하이브리드 상위 경로)
    # `places_candidate` 는 위 fan-out 에서 이미 받아 두었다.
    google_ok, google_skip = places_service.availability()

    # -------- Step 6.1: 동일 업체 검증 (Kakao 확정 정보 vs Google 후보)
    validation_dict = entity_validation_service.validate_google_place_identity(
        business_info, places_candidate
    )
    validation = EntityValidation(**validation_dict)

    # Decide what we keep from Google. If the candidate refers to a different
    # entity, we discard EVERYTHING that could mislead the ambience pipeline:
    # business hours, place_types, reviews, rating. We still keep the
    # geocoded location only as a last-resort weather fallback.
    if validation.is_consistent:
        places = places_candidate
        google_metadata_used = True
    else:
        logger.info(
            "Google Places rejected by validation (score=%.2f reasons=%s)",
            validation.score, validation.reasons,
        )
        places = GooglePlaces(
            place_id=None,
            place_name=None,
            formatted_address=None,
            business_hours=[],
            rating=None,
            review_count=None,
            reviews=[],
            place_types=[],
            location=places_candidate.location,  # only the lat/lng survives, for weather
        )
        google_metadata_used = False

    # -------- Step 5.6: review-text / opening-hours availability + web-search fallback
    has_google_reviews = (
        validation.is_consistent
        and entity_validation_service.has_usable_review_text(places.reviews)
    )
    # Hours are often missing even when Google returned the right place
    # (small local merchants rarely configure hours on Google Business
    # Profile). Recover them from web snippets so the TPO time label,
    # daypart weights, and the UI's 영업시간 box stop saying "정보 없음".
    needs_hours_fallback = validation.is_consistent and not places.business_hours

    web_evidence: list = []
    recovered_hours: list = []
    if not has_google_reviews or needs_hours_fallback:
        # Three cases reach this branch:
        #   a) validation failed -> Google reviews already cleared above
        #   b) validation passed but reviews are absent / too short
        #   c) validation passed, reviews fine, but hours missing
        #
        # 근거 검색 → (영업시간 없으면) 영업시간 재검색을 **하나의 벽시계 예산** 안에서
        # 돈다. 예전에는 무제한이어서 DDG 가 Render IP 를 막았을 때 63초짜리 분석이
        # 나왔다(결과는 근거 0건). 예산을 넘기면 얻은 것만 쓰고 prior 로 계속 간다.
        web_evidence, recovered_hours = await web_search_service.collect_fallback_evidence(
            business_info.company_name,
            business_info.business_type,
            business_info.address,
            need_hours=needs_hours_fallback,
            budget_sec=settings.web_fallback_budget_sec,
        )
        logger.info("web_search fallback: %d evidence items, %d hour lines (budget %.1fs)",
                    len(web_evidence), len(recovered_hours), settings.web_fallback_budget_sec)

    # Google-sourced hours always win when present; web-recovered hours fill the gap.
    hours_source = "google" if places.business_hours else "none"
    if recovered_hours:
        places.business_hours = recovered_hours
        hours_source = "web"

    # Choose the text-evidence corpus the LLM will actually score.
    if has_google_reviews and web_evidence:
        review_corpus = list(places.reviews) + web_search_service.to_place_reviews(web_evidence)
        text_source = "mixed"
    elif has_google_reviews:
        review_corpus = list(places.reviews)
        text_source = "google_reviews"
    elif web_evidence:
        review_corpus = web_search_service.to_place_reviews(web_evidence)
        text_source = "web_search"
    else:
        review_corpus = []
        text_source = "none"

    # -------- Step 7: weather
    # 좌표는 Kakao가 canonical이다 (Google 후보가 다른 매장일 수 있으므로 먼저 쓰지 않는다).
    # Kakao 좌표가 있었다면 위 fan-out 에서 이미 조회했다.
    if weather_early is not None:
        location = chosen.location
        weather = weather_early
    else:
        location = (places.location
                    or (await kakao_local_service.geocode(business_info.address)))
        weather = await weather_service.fetch_weather(location)

    # -------- Step 7: LLM review scoring
    canonical_type = ambience_service.classify_business_type(business_info.business_type)
    hours_summary = ", ".join(places.business_hours[:3]) if places.business_hours else ""

    review_scores = await llm_service.score_reviews(
        review_corpus,
        business_type=canonical_type,
        trade_area=trade_area.label,
        weather_summary=weather.summary,
        business_hours=hours_summary,
    )
    text_scores = llm_service.aggregate_text_scores(review_scores)

    # -------- Step 8: TPO + ambience
    daypart_weights = ambience_service.compute_daypart_weights(
        ambience_service.parse_business_hours(places.business_hours)
    )
    tpo = ambience_service.build_tpo_profile(
        canonical_type, trade_area, places, review_corpus, review_scores
    )
    ambience, fusion_debug = ambience_service.fuse(
        text_scores=text_scores,
        trade_area=trade_area,
        business_type=canonical_type,
        daypart_weights=daypart_weights,
        weather=weather,
        # canonical만으로는 업종군을 못 잡는 경우가 있다(예: Kakao가 준
        # business_type이 "서비스,산업"). 원문 카테고리를 함께 넘겨 priors를 보정한다.
        raw_business_type=f"{business_info.business_type} {chosen.category_name}",
    )

    # -------- Step 9: 음원 추천 (외부 API 없음 · 로컬 매니페스트만 사용)
    music = music_service.recommend(
        ambience,
        tpo,
        business_type=canonical_type,
        # Kakao category_name 전체를 함께 넘긴다. 말단 토큰만으로는 업종군 판별이
        # 어긋난다 — '스포츠,레저 > 스포츠시설 > 헬스클럽'에서 '헬스'가 필요하다.
        raw_business_type=f"{business_info.business_type} {chosen.category_name}",
        trade_area=trade_area,
        daypart_weights=daypart_weights,
        limit=10,
    )

    # -------- Provenance bookkeeping
    provenance_notes: list = []
    if not validation.is_consistent:
        provenance_notes.append(
            "Google Places가 동일 업체로 판단되지 않아 Google의 업종·영업시간·리뷰는 제외했습니다."
        )
    if text_source == "web_search":
        provenance_notes.append("리뷰가 충분하지 않아 웹 검색 텍스트를 분석 근거로 사용했습니다.")
    elif text_source == "mixed":
        provenance_notes.append("Google 리뷰와 웹 검색 텍스트를 함께 분석 근거로 사용했습니다.")
    elif text_source == "google_reviews":
        provenance_notes.append("Google 리뷰를 분석 근거로 사용했습니다.")
    elif text_source == "none":
        provenance_notes.append(
            "사용 가능한 리뷰·웹 텍스트 근거가 없어 상권/업종 prior 위주로 추정했습니다."
        )
    if trade_area_evidence:
        provenance_notes.append(f"상권 판정 근거 — {trade_area_evidence}")
    # Google을 못 쓴 이유가 있으면(키 없음 / 일별 상한) 화면에 정직하게 남긴다.
    skip_text = places_service.SKIP_REASON_TEXT.get(google_skip, "") if not google_ok else ""
    if skip_text:
        provenance_notes.append(skip_text)
    if hours_source == "web":
        provenance_notes.append(
            f"Google이 영업시간을 제공하지 않아 웹 검색으로 {len(recovered_hours)}건을 보강했습니다."
        )

    # '분석 근거' 템플릿 슬롯 1-2: 리뷰 코퍼스에서 LLM이 뽑은 키워드의 언급 빈도.
    # 키워드는 리뷰당 최대 5개로 중복 제거되어 있으므로 count ≈ 언급 리뷰 수.
    keyword_counter = Counter(
        kw.strip()
        for rs in review_scores
        for kw in (rs.keywords or [])
        if kw and kw.strip()
    )
    review_keywords = [
        {"keyword": k, "count": n} for k, n in keyword_counter.most_common(5)
    ]

    provenance = EvidenceProvenance(
        text_source=text_source,
        google_used=text_source in {"google_reviews", "mixed"},
        google_metadata_used=google_metadata_used,
        web_search_used=bool(web_evidence) and text_source in {"web_search", "mixed"},
        google_review_count=len(places.reviews) if validation.is_consistent else 0,
        web_evidence_count=len(web_evidence),
        notes=provenance_notes,
        review_keywords=review_keywords,
        reviews_analyzed=len(review_scores),
    )

    # Append a short, user-facing line to the ambience explanation list so the
    # UI's existing explanation panel honestly reflects evidence provenance.
    if ambience.explanations is not None:
        if not validation.is_consistent:
            ambience.explanations.insert(
                0,
                f"⚠ Google Places 결과가 사업자 정보와 일치하지 않아 제외했습니다 "
                f"(검증 점수 {validation.score:.2f})."
            )
        if text_source == "web_search":
            ambience.explanations.insert(
                1 if not validation.is_consistent else 0,
                f"📚 분석 근거: 웹 검색 결과 {len(web_evidence)}건 (상호·업종·주소 키워드 사용)."
            )
        elif text_source == "mixed":
            ambience.explanations.insert(
                0,
                f"📚 분석 근거: Google 리뷰 {len(places.reviews)}건 + 웹 검색 {len(web_evidence)}건."
            )
        elif text_source == "none":
            ambience.explanations.insert(
                0,
                "📚 텍스트 근거가 부족하여 상권/업종 prior 기반으로 추정한 결과입니다."
            )

    response = AnalyseResponse(
        success=True,
        business_number=formatted,
        nts_status=status_label,
        business_info=business_info,
        trade_area=trade_area,
        google_places=places,
        weather=weather,
        tpo_profile=tpo,
        ambience=ambience,
        entity_validation=validation,
        evidence_provenance=provenance,
        web_evidence=web_evidence,
        music=music,
        resolved_place=chosen,
        debug={
            "identity_source": identity.source,
            "identity_confidence": identity.confidence,
            "kakao_candidates": len(place_candidates),
            "kakao_pick": pick_reason,
            "kakao_score": chosen.score,
            "google_available": google_ok,
            "google_skip_reason": None if google_ok else google_skip,
            "trade_area_method": trade_area.match_method,
            "trade_area_reason": trade_area_reason,
            "trade_area_evidence": trade_area_evidence,
            "places_calls_today": places_service.calls_today(),
            "places_daily_cap": settings.places_daily_cap,
            "music_pool_size": music.pool_size,
            "music_industry_matched": music.industry_matched,
            "music_track_count": len(music.tracks),
            "llm_prompt_version": settings.prompt_version,
            "reviews_used": len(review_scores),
            "google_review_count_raw": len(places_candidate.reviews or []),
            "web_evidence_count": len(web_evidence),
            "text_source": text_source,
            "entity_validation_score": validation.score,
            "entity_validation_consistent": validation.is_consistent,
            "text_scores": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in text_scores.items()},
            "canonical_business_type": canonical_type,
            "fusion": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in fusion_debug.items() if k != "daypart_weights"},
            "daypart_weights": {k: round(v, 3) for k, v in daypart_weights.items()},
            "hours_source": hours_source,
            "hours_recovered_count": len(recovered_hours),
            "mock_mode": settings.effective_mock_mode(),
        },
    )

    # 한국어 단일 서비스다. 응답을 그대로 캐시한다.
    cache[ckey] = response

    _persist_intermediate(digits, response)
    logger.info("=== analyse done: %s E=%d T=%d M=%d ===",
                formatted, ambience.energy, ambience.tempo, ambience.mood)
    return _collect(response, "success")


@router.post("/api/reanalyse", response_model=AnalyseResponse)
async def reanalyse(
    payload: AnalyseRequest,
    x_yielda_client: str = Header(default=""),
) -> AnalyseResponse:
    """Force-refresh the cached analysis for this business number."""
    digits = nts_service.normalize_business_number(payload.business_number)
    cache = get_cache("analysis")
    # 사용자 선택별로 키가 갈리므로 해당 번호의 모든 변형을 지운다.
    for k in [k for k in list(cache.keys()) if str(k).startswith(f"analyse:{digits}:")]:
        cache.pop(k, None)
    return await analyse(payload, x_yielda_client=x_yielda_client)


@router.get("/api/collection")
async def collection(limit: int = 200) -> dict:
    """수집 시트의 최근 행을 되읽어 준다 (기획·운영 대시보드용).

    프론트가 Apps Script 를 직접 부르지 않는 이유: 웹훅 URL·토큰이 번들에
    박히면 누구나 시트에 쓸 수 있고, Apps Script 는 CORS 프리플라이트를 받지
    않는다. 시트가 설정되지 않았으면 `available: false` + 빈 배열로 degrade 한다.
    """
    limit = max(1, min(limit, 2000))
    return await sheets_logger.fetch_rows(limit=limit)


@router.get("/api/trade-area/test")
def trade_area_test(address: str):
    service = trade_area_service.get_trade_area_service()
    result = service.match(address)
    return {"input": address, "match": result.model_dump()}


@router.get("/api/sample/{biz_no}")
async def sample_analysis(biz_no: str) -> AnalyseResponse:
    """Convenience route — returns the full mock pipeline even with keys present."""
    settings = get_settings()
    settings.mock_mode = True  # temporarily flip
    try:
        return await analyse(AnalyseRequest(business_number=biz_no))
    finally:
        settings.mock_mode = False


def _persist_intermediate(digits: str, response: AnalyseResponse) -> None:
    settings = get_settings()
    debug_dir: Path = settings.cache_dir / "analyse"
    debug_dir.mkdir(parents=True, exist_ok=True)
    try:
        (debug_dir / f"{digits}.json").write_text(
            json.dumps(response.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
