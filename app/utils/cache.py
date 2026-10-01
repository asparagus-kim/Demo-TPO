"""In-memory TTL cache used across service modules."""
from __future__ import annotations

from typing import Any, Callable

from cachetools import TTLCache

_places_cache: TTLCache = TTLCache(maxsize=512, ttl=60 * 60 * 6)  # 6h
_weather_cache: TTLCache = TTLCache(maxsize=512, ttl=60 * 15)     # 15min
_llm_cache: TTLCache = TTLCache(maxsize=1024, ttl=60 * 60 * 24)   # 24h
_analysis_cache: TTLCache = TTLCache(maxsize=256, ttl=60 * 30)    # 30min
# Merchant-text translations (company_name, business_type) — long TTL because
# the source strings rarely change, and OpenAI calls dominate the budget.
_translate_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 60 * 24 * 7)  # 7d
# 사업자번호 → 상호명. 등록 상호는 거의 변하지 않고 bizno 무료 플랜이 200건/일이라
# TTL을 길게 잡아 쿼터를 아낀다.
_bizno_cache: TTLCache = TTLCache(maxsize=1024, ttl=60 * 60 * 24 * 3)      # 3d
# APICK 은 호출당 50포인트의 유료 API 다. 등록 주소·좌표는 거의 변하지 않으므로
# bizno 보다도 TTL 을 길게 잡아 중복 과금을 막는다.
_apick_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 60 * 24 * 7)      # 7d


def get_cache(name: str) -> TTLCache:
    mapping = {
        "places": _places_cache,
        "weather": _weather_cache,
        "llm": _llm_cache,
        "analysis": _analysis_cache,
        "translate": _translate_cache,
        "bizno": _bizno_cache,
        "apick": _apick_cache,
    }
    if name not in mapping:
        raise KeyError(f"Unknown cache: {name}")
    return mapping[name]


def memoize(cache_name: str, key_fn: Callable[..., str]):
    """Simple decorator: cache result of an async/sync callable by derived key."""
    cache = get_cache(cache_name)

    def _decorator(fn):
        if _is_coroutine(fn):
            async def _awrap(*args, **kwargs):
                key = key_fn(*args, **kwargs)
                if key in cache:
                    return cache[key]
                res = await fn(*args, **kwargs)
                cache[key] = res
                return res
            return _awrap

        def _wrap(*args, **kwargs):
            key = key_fn(*args, **kwargs)
            if key in cache:
                return cache[key]
            res = fn(*args, **kwargs)
            cache[key] = res
            return res
        return _wrap
    return _decorator


def _is_coroutine(fn: Any) -> bool:
    import inspect
    return inspect.iscoroutinefunction(fn)
