"""API 키가 로그·응답에 새지 않는지 고정하는 회귀 테스트.

배경: data.go.kr(NTS·기상청) · bizno · Google Geocode 는 인증키를 **쿼리 파라미터**로
받는다. 따라서 URL을 찍는 모든 코드가 곧 키를 찍는 코드다. 실제로 `httpx` 의 INFO
로그가 성공한 NTS 호출마다 키를 평문으로 출력하고 있었다 (2026-08-06 발견).

Three upstreams authenticate via query parameter, so anything printing a URL prints a
credential. `httpx` was doing exactly that at INFO level. These tests pin the fixes.
"""
from __future__ import annotations

import io
import logging
from urllib.parse import quote, unquote

import pytest

from app.utils import logging as applog


FAKE_KEY = "Zm9vYmFyc2VjcmV0S0VZ+abc/def=="


@pytest.fixture
def secret_env(monkeypatch):
    """알려진 비밀값 캐시를 비우고 가짜 키를 심는다."""
    monkeypatch.setenv("DATA_GO_KR_API_KEY", FAKE_KEY)
    monkeypatch.setattr(applog, "_secrets_cache", ())
    monkeypatch.setattr(applog, "_secrets_resolved", False)
    yield FAKE_KEY
    monkeypatch.setattr(applog, "_secrets_cache", ())
    monkeypatch.setattr(applog, "_secrets_resolved", False)


def _capture(logger_name: str):
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(applog.RedactingFormatter("%(message)s"))
    lg = logging.getLogger(logger_name)
    lg.handlers = [handler]
    lg.propagate = False
    lg.setLevel(logging.DEBUG)
    return lg, buf


# ------------------------------------------------------------------ redact()

def test_redact_plain_value(secret_env):
    out = applog.redact(f"GET https://api.odcloud.kr/x?serviceKey={secret_env}")
    assert secret_env not in out
    assert applog.REDACTED in out


def test_redact_url_encoded_form(secret_env):
    """httpx 는 쿼리 파라미터를 URL 인코딩해서 보낸다 — 그 형태도 잡아야 한다."""
    encoded = quote(secret_env, safe="")
    assert encoded != secret_env, "테스트 키에 인코딩 대상 문자가 있어야 의미가 있다"
    out = applog.redact(f"?serviceKey={encoded}")
    assert encoded not in out and applog.REDACTED in out


def test_redact_url_decoded_form(monkeypatch):
    """config._get_service_key() 가 Encoding 키를 디코딩해 전송하므로 그 형태도 잡아야 한다.

    .env 에는 `%2B` 형태로 들어 있고 실제 전송값은 `+` 형태다. 둘 다 등록되지 않으면
    로그에 찍히는 쪽(전송값)이 그대로 남는다.
    """
    encoded_key = "abc%2Bdef%2Fghi%3D%3D"          # .env 에 들어 있는 Encoding 키 형태
    decoded_key = unquote(encoded_key)             # config 가 실제로 전송하는 값
    assert decoded_key != encoded_key

    monkeypatch.setenv("DATA_GO_KR_API_KEY", encoded_key)
    monkeypatch.setattr(applog, "_secrets_cache", ())
    monkeypatch.setattr(applog, "_secrets_resolved", False)

    out = applog.redact(f"?serviceKey={decoded_key}")
    assert decoded_key not in out and applog.REDACTED in out


def test_redact_leaves_normal_text_alone(secret_env):
    msg = "상권 판정(주변분포): 대학가/유흥 상권 — 반경 500m 내 카페 18"
    assert applog.redact(msg) == msg


def test_short_values_are_not_treated_as_secrets(monkeypatch):
    """짧은 플레이스홀더까지 마스킹하면 로그가 통째로 뭉개진다."""
    monkeypatch.setenv("BIZNO_API_KEY", "x")
    monkeypatch.setattr(applog, "_secrets_cache", ())
    monkeypatch.setattr(applog, "_secrets_resolved", False)
    assert applog.redact("axbxc") == "axbxc"


# ------------------------------------------------------- formatter integration

def test_formatter_redacts_log_message(secret_env):
    lg, buf = _capture("redaction-msg")
    lg.info("calling %s", f"https://api.odcloud.kr/x?serviceKey={secret_env}")
    assert secret_env not in buf.getvalue()
    assert applog.REDACTED in buf.getvalue()


def test_formatter_redacts_exception_traceback(secret_env):
    """트레이스백은 record.msg 가 아니라 포매터가 만든다.

    Filter 로 record.msg 만 손보면 이 경로가 뚫린다 — httpx 예외 메시지에
    요청 URL이 들어가므로 실제로 가장 위험한 경로다.
    """
    lg, buf = _capture("redaction-exc")
    try:
        raise RuntimeError(f"Server error for url 'https://x/y?serviceKey={secret_env}'")
    except RuntimeError:
        lg.exception("upstream failed")
    assert secret_env not in buf.getvalue()
    assert applog.REDACTED in buf.getvalue()


# ------------------------------------------------------------- noisy loggers

def test_httpx_logger_is_not_at_info():
    """httpx 의 INFO 로그가 전체 URL(= 키)을 찍는다. WARNING 이상으로 묶여 있어야 한다."""
    applog.configure_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


# ------------------------------------------------ 응답에 예외 문자열을 싣지 않는다

def test_nts_failure_message_has_no_exception_text(monkeypatch):
    """debug.nts.message 는 브라우저까지 간다 — 예외 문자열이 들어가면 안 된다."""
    import asyncio

    from app.services import nts_service

    monkeypatch.setenv("DATA_GO_KR_API_KEY", FAKE_KEY)

    async def boom(*args, **kwargs):
        raise RuntimeError(f"Server error for url 'https://x?serviceKey={FAKE_KEY}'")

    monkeypatch.setattr(nts_service, "_post_batch", boom)
    monkeypatch.setattr(nts_service.get_settings(), "data_go_kr_api_key", FAKE_KEY, raising=False)
    monkeypatch.setattr(nts_service.get_settings(), "mock_mode", False, raising=False)

    result = asyncio.run(nts_service.lookup_status("642-07-00540"))
    assert result["status_label"] == nts_service.STATUS_LOOKUP_FAILED
    assert FAKE_KEY not in result["message"]
    assert "serviceKey" not in result["message"]
    assert "Server error" not in result["message"]
