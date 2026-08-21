"""Per-security price-basis adjudications (QNT-098). Grows only by human review.

The QNT-098 market-cap harness flags implausible FTSE-member market caps; every flagged
security lands here with evidence, either as a CURRENCY override (the series is sane in
another quotation currency) or as a market-value EXCLUSION (the price basis is
unresolved and no market-value factor may be built on it). The exclusion list may only
shrink, and each entry names its evidence — the DEC-016 pattern.
"""

PRICE_CURRENCY_OVERRIDES: dict[str, tuple[str, str]] = {
    # Ferguson: EODHD serves the whole series dollar-quoted (~$82 in June 2020 vs
    # 6,590p on the LSE tape; dividends USD-labelled; USD dividend yield ~2.5% is sane;
    # USD reading puts the market cap at ~GBP 12bn, matching reality).
    "SEC-e9358707-dd8e-478b-b1e3-4c397410b732": ("USD", "USD-quoted series, div evidence"),
    # Metlen: LSE listing 2025; series is euro-quoted (~EUR 36 vs a 3,000p-scale tape);
    # EUR reading restores a ~GBP 10bn market cap.
    "SEC-796cc6e7-eb5d-4c8c-9cd8-ac21d996d5bb": ("EUR", "EUR-quoted series"),
}

MARKET_VALUE_EXCLUSIONS: dict[str, str] = {
    # Tullow: shares series is correct (326m -> 1.5bn) but 2010-2014 closes imply a
    # GBP 1tn market cap — a price basis no currency reading rescues. Unresolved.
    "SEC-90abc84f-1556-438a-939f-af4b2c5d932e": (
        "price basis implies GBP ~1tn market cap 2010-2014; unresolved"
    ),
    # Melrose: mixed-basis series; the DEC-020 whole-series x100 is right for the early
    # era but wrong post-2023 (implies GBP 711bn). Needs a segment-level re-adjudication.
    "SEC-fa995f37-4006-480f-b273-410aa6790c12": (
        "mixed GBP/GBX basis; x100 repair wrong post-2023 (implies GBP 711bn)"
    ),
    # Randgold: chaotic series (median 0.14 pre-repair; ~GBP 33m member market cap
    # post-repair against a real ~GBP 6bn). Vendor data unusable for market values.
    "SEC-e81b96d0-946a-4229-81a6-5ed7844b095f": (
        "series scale unresolvable (~200x off after every reading)"
    ),
    # Capita: basis inconsistent with both the historical tape and the 2023 15:1
    # consolidated basis in different eras; flagged months around 2016-2017.
    "SEC-9add5484-79f0-44fe-b6d5-3b67fd5f599b": (
        "era-dependent basis; neither raw nor consolidated reading fits 2016-2017"
    ),
}
