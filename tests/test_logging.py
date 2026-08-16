import logging

import pytest

from trp.logging import setup_logging


def test_setup_logging_emits_utc_single_handler(capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging("DEBUG")
    setup_logging("DEBUG")  # idempotent: no duplicate handlers
    root = logging.getLogger()
    assert len(root.handlers) == 1

    logging.getLogger("trp.test").info("hello")
    err = capsys.readouterr().err
    assert err.count("hello") == 1
    # ISO-ish UTC timestamp with explicit Z suffix.
    assert "Z INFO" in err


def test_httpx_request_urls_never_reach_logs(capsys: pytest.CaptureFixture[str]) -> None:
    # httpx logs full URLs at INFO; query-parameter API tokens must not be loggable.
    setup_logging("INFO")
    logging.getLogger("httpx").info("GET https://example.com/?api_token=SECRET")
    assert "SECRET" not in capsys.readouterr().err
