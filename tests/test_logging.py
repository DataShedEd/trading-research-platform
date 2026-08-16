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
