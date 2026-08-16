"""Checksum validation for external security identifiers.

Providers occasionally serve malformed or transposed identifiers; validating checksums at
the boundary turns silent mis-mappings into loud errors. Each validator raises
``ValueError`` with a precise reason.
"""

import re

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_SEDOL_RE = re.compile(r"^[0-9BCDFGHJKLMNPQRSTVWXYZ]{6}[0-9]$")  # no vowels by definition
_CUSIP_RE = re.compile(r"^[A-Z0-9*@#]{8}[0-9]$")

_SEDOL_WEIGHTS = (1, 3, 1, 7, 3, 9, 1)


def validate_isin(value: str) -> None:
    """ISO 6166: 2-letter country prefix, 9-char body, Luhn check digit over base-36 digits."""
    if not _ISIN_RE.match(value):
        raise ValueError(f"ISIN {value!r}: malformed (expected 2 letters, 9 alnum, check digit)")
    digits = "".join(str(int(c, 36)) for c in value[:-1])
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    expected = (10 - total % 10) % 10
    if expected != int(value[-1]):
        raise ValueError(f"ISIN {value!r}: check digit {value[-1]} != expected {expected}")


def validate_sedol(value: str) -> None:
    """SEDOL: 7 chars, no vowels, weighted-sum check digit."""
    if not _SEDOL_RE.match(value):
        raise ValueError(f"SEDOL {value!r}: malformed (7 chars, no vowels, digit last)")
    total = sum(int(c, 36) * w for c, w in zip(value, _SEDOL_WEIGHTS, strict=True))
    if total % 10 != 0:
        raise ValueError(f"SEDOL {value!r}: checksum failure")


def validate_cusip(value: str) -> None:
    """CUSIP: 9 chars, modulus-10 double-add-double check digit."""
    if not _CUSIP_RE.match(value):
        raise ValueError(f"CUSIP {value!r}: malformed (9 chars, digit last)")
    total = 0
    for i, c in enumerate(value[:-1]):
        if c.isdigit():
            v = int(c)
        elif c.isalpha():
            v = int(c, 36)
        else:
            v = {"*": 36, "@": 37, "#": 38}[c]
        if i % 2 == 1:
            v *= 2
        total += v // 10 + v % 10
    expected = (10 - total % 10) % 10
    if expected != int(value[-1]):
        raise ValueError(f"CUSIP {value!r}: check digit {value[-1]} != expected {expected}")
