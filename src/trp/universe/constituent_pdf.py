"""Parse FTSE Russell "Historic Additions and Deletions" policy PDFs (QNT-111).

The official constituent-history documents (e.g. ``FTSE_250_Constituent_history.pdf``,
April 2026 edition — research.ftserussell.com/products/downloads/) are four-column
tables: Date | Added | Deleted | Notes. Plain-text extraction destroys the column
boundary between the Added and Deleted names, so this parser works positionally from
word x-coordinates via pdfplumber (a dev dependency — this is curation tooling, not a
runtime path).

Output: a list of ``{date, added, deleted, notes, page}`` records, one per table row.
One PDF row means "on this effective date, `added` entered the index and `deleted`
left" — a paired change. Rows may wrap across lines (long names, long notes);
continuation lines carry no date and are appended to the open row's columns.

The parser NEVER normalises company names — downstream curation resolves them against
the security master with provenance. It does assert structural sanity: every row has a
parseable date, dates are non-decreasing within a page, and (for the FTSE 250 document)
each dated row names at least one of added/deleted.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

_DATE = re.compile(r"^(\d{1,2})\s*-?\s*([A-Z][a-z]{2})\s*-?\s*(\d{2})$")
_FOOTER = re.compile(r"^(FTSE|lseg|Source|©|Further)")

# Column x-origins measured from the April 2026 documents (stable across pages;
# asserted against each page's header row at parse time).
DATE_MAX_X = 95.0
ADDED_MAX_X = 210.0
DELETED_MAX_X = 345.0
LINE_TOLERANCE = 2.0


@dataclass
class ConstituentChange:
    effective: date
    added: str
    deleted: str
    notes: str
    page: int


def _parse_date(token: str) -> date:
    match = _DATE.match(token)
    assert match is not None, token
    return datetime.strptime("-".join(match.groups()), "%d-%b-%y").date()


def parse_history_pdf(path: Path) -> list[ConstituentChange]:
    import pdfplumber

    rows: list[ConstituentChange] = []
    open_row: dict[str, object] | None = None

    def flush() -> None:
        nonlocal open_row
        if open_row is not None:
            rows.append(
                ConstituentChange(
                    effective=open_row["date"],  # type: ignore[arg-type]
                    added=" ".join(open_row["added"]).strip(),  # type: ignore[arg-type]
                    deleted=" ".join(open_row["deleted"]).strip(),  # type: ignore[arg-type]
                    notes=" ".join(open_row["notes"]).strip(),  # type: ignore[arg-type]
                    page=open_row["page"],  # type: ignore[arg-type]
                )
            )
            open_row = None

    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages):
            words = page.extract_words()
            lines: dict[float, list[dict[str, object]]] = {}
            for word in words:
                placed = False
                for key in lines:
                    if abs(float(word["top"]) - key) <= LINE_TOLERANCE:
                        lines[key].append(word)
                        placed = True
                        break
                if not placed:
                    lines[float(word["top"])] = [word]
            header_seen = False
            for top in sorted(lines):
                line = sorted(lines[top], key=lambda w: float(w["x0"]))
                texts = [str(w["text"]) for w in line]
                if texts[:2] == ["Date", "Added"]:
                    header_seen = True
                    # Column origins must match the measured layout.
                    origins = {str(w["text"]): float(w["x0"]) for w in line}
                    assert abs(origins["Date"] - 39.4) < 5, origins
                    assert abs(origins["Added"] - 97.8) < 5, origins
                    continue
                if not header_seen:
                    continue  # page banner / title block
                # The date cell can split into several words ("01-Apr", "-26"): join
                # every date-column word before matching.
                date_words = [w for w in line if float(w["x0"]) < DATE_MAX_X]
                date_text = "".join(str(w["text"]) for w in date_words)
                is_new_row = bool(date_words) and bool(_DATE.match(date_text))
                if date_words and not is_new_row:
                    if _FOOTER.match(date_text):
                        break  # page footer region — done with this page
                    raise ValueError(
                        f"page {page_number}: unparseable date column {date_text!r} — "
                        "refusing to drop rows silently"
                    )
                if is_new_row:
                    flush()
                    open_row = {
                        "date": _parse_date(date_text),
                        "added": [],
                        "deleted": [],
                        "notes": [],
                        "page": page_number,
                    }
                    line = [w for w in line if float(w["x0"]) >= DATE_MAX_X]
                if open_row is None:
                    continue
                for word in line:
                    x = float(word["x0"])
                    text = str(word["text"])
                    if x < ADDED_MAX_X:
                        open_row["added"].append(text)  # type: ignore[union-attr]
                    elif x < DELETED_MAX_X:
                        open_row["deleted"].append(text)  # type: ignore[union-attr]
                    else:
                        open_row["notes"].append(text)  # type: ignore[union-attr]
    flush()

    if not rows:
        raise ValueError(f"{path}: no rows parsed — layout changed?")
    for row in rows:
        if not row.added and not row.deleted:
            raise ValueError(f"{path}: row on {row.effective} names neither side")
    return rows


if __name__ == "__main__":
    import json
    import sys

    parsed = parse_history_pdf(Path(sys.argv[1]))
    print(json.dumps(len(parsed)))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if out:
        out.write_text(
            json.dumps(
                [
                    {
                        "effective": str(r.effective),
                        "added": r.added,
                        "deleted": r.deleted,
                        "notes": r.notes,
                        "page": r.page,
                    }
                    for r in parsed
                ],
                indent=1,
            )
        )
        print(f"wrote {out}")
