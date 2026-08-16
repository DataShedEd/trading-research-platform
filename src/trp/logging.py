"""Logging setup: stdlib logging, UTC timestamps, one line per event.

Deliberately plain — no logging framework. Modules obtain loggers with
``logging.getLogger(__name__)``; applications and scripts call :func:`setup_logging` once.
"""

import logging
import time


def setup_logging(level: str = "INFO") -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # httpx/httpcore log full request URLs at INFO — for providers whose auth is a query
    # parameter (EODHD) that would print the API token. Secrets never appear in logs.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
