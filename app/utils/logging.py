"""Centralised logger setup, with secret redaction.

Uses a single stream handler configured at the INFO level by default. Every
service module calls `get_logger(__name__)` so the entire pipeline uses the
same format — and the same redaction.

## Why redaction lives here

Two of our upstreams authenticate with a **query parameter**, not a header:

    data.go.kr   ?serviceKey=<key>      (NTS status, KMA weather)
    bizno        ?key=<key>
    Google Geocode ?key=<key>

Anything that prints a URL therefore prints a credential. That has already
happened once — `httpx` logs every request at INFO including the full URL, so
successful NTS calls were writing the key to stdout in plaintext.

Silencing `httpx` fixes that one path, but relying on every future call site to
avoid logging a URL is not a control. The formatter below scrubs known secret
values out of **every** record — message, arguments and exception traceback —
so a new code path cannot reintroduce the leak.

> data.go.kr·bizno·Google Geocode 는 인증키를 **쿼리 파라미터**로 받습니다.
> URL을 찍는 모든 코드가 곧 키를 찍는 코드입니다. 호출부마다 조심하는 대신
> 포매터에서 일괄 제거합니다.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional, Tuple
from urllib.parse import quote, unquote

_CONFIGURED = False

REDACTED = "***REDACTED***"

# Environment variables whose values must never appear in a log line.
# URLs and model names are deliberately absent — they are not secrets.
SECRET_ENV_NAMES: Tuple[str, ...] = (
    "DATA_GO_KR_API_KEY",
    "KMA_API_KEY",
    "KAKAO_REST_API_KEY",
    "BIZNO_API_KEY",
    "APICK_API_KEY",
    "GOOGLE_MAPS_API_KEY",
    "OPENAI_API_KEY",
    # 이 둘은 '엔드포인트'처럼 보이지만 실제로는 자격증명이다. Apps Script 웹앱
    # exec URL 을 아는 사람은 누구나 수집 시트에 행을 쓸 수 있다.
    "SHEETS_WEBHOOK_URL",
    "SHEETS_WEBHOOK_TOKEN",
)

# Shortest value we will treat as a secret. Guards against blanking every "0"
# in the logs if someone sets an env var to a trivial placeholder.
_MIN_SECRET_LEN = 8

_secrets_cache: Tuple[str, ...] = ()
_secrets_resolved = False


def _known_secrets() -> Tuple[str, ...]:
    """Secret values to scrub, longest first.

    Resolved lazily and cached. It has to be lazy: `config.py` calls
    `get_logger()` at import time *before* `load_dotenv()` runs, so a snapshot
    taken during `configure_logging()` would be empty. We keep re-reading until
    we find something, then freeze.

    Each secret is registered in three forms because the value that reaches a
    log line is not always the value in `.env`:
      - as written,
      - URL-encoded (httpx encodes query params),
      - URL-decoded (`config._get_service_key()` decodes data.go.kr keys).
    """
    global _secrets_cache, _secrets_resolved
    if _secrets_resolved:
        return _secrets_cache

    found = set()
    for name in SECRET_ENV_NAMES:
        raw = (os.getenv(name) or "").strip()
        if len(raw) < _MIN_SECRET_LEN:
            continue
        for form in (raw, quote(raw, safe=""), unquote(raw)):
            if len(form) >= _MIN_SECRET_LEN:
                found.add(form)

    if found:
        # Longest first so a value that contains another is replaced whole.
        _secrets_cache = tuple(sorted(found, key=len, reverse=True))
        _secrets_resolved = True
    return _secrets_cache


def redact(text: str) -> str:
    """Replace every known secret value in `text` with a placeholder."""
    if not text:
        return text
    for secret in _known_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


class RedactingFormatter(logging.Formatter):
    """Formats as usual, then scrubs secrets from the finished line.

    Redacting after formatting (rather than in a `Filter`) is deliberate: this
    single hook also covers exception tracebacks, which a filter on
    `record.msg` would miss — and a traceback from an HTTP client is exactly
    where a credential-bearing URL shows up.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(level: Optional[str] = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(level or "INFO")

    # Windows 콘솔은 기본 코드페이지가 cp949라 한국어 로그와 em dash(—)가
    # UnicodeEncodeError로 터진다. 로그가 통째로 스택트레이스로 바뀌어 실제
    # 파이프라인 로그를 읽을 수 없게 되므로 스트림을 UTF-8로 고정한다.
    # (errors="replace": 그래도 못 쓰는 문자는 죽지 말고 대체한다)
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.handlers.clear()
    root.addHandler(handler)

    # First line of defence: httpx logs every request at INFO **including the
    # full URL**, so successful data.go.kr calls printed the key in plaintext.
    # The formatter above would scrub it anyway; keeping httpx at WARNING means
    # the credential is never even assembled into a log record.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
