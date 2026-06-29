"""Presentation-only helpers for the Streamlit UI (no domain logic)."""
from __future__ import annotations

import datetime as _dt
import html
import re

_COLUMNS = ["Section", "Property Type", "PDF field", "PDF value",
            "docx field", "docx value"]

# Characters that are illegal in filenames on Windows/macOS/Linux.
_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Trailing '.docx'/'.doc' on the uploaded Word filename.
_DOC_EXT = re.compile(r"\.docx?$", re.IGNORECASE)


def _dashes_to_name(segment: str) -> str:
    """Turn a dash-encoded filename segment into a readable name.

    A double-dash ('--') is treated as a literal separator (' - '); single
    dashes become spaces. 'Sample-Holdings--Fund-IV' -> 'Sample Holdings - Fund IV'.
    """
    parts = [" ".join(p.replace("-", " ").split()) for p in segment.split("--")]
    return " - ".join(p for p in parts if p)


def client_name_from_filename(filename: str | None) -> str | None:
    """Derive the client name from the uploaded docx filename.

    Expected convention: '<date>__<Client-Name>__GRESB-Word-for-Diff.docx',
    where the client name uses dashes for spaces and '--' as a separator. The
    middle '__'-delimited segment is the client. If the name doesn't match the
    convention (no '__' delimiters / unexpected format), the whole filename
    (minus extension) is used as a fallback. Returns None for an empty name.
    """
    if not filename:
        return None
    stem = _DOC_EXT.sub("", filename)
    parts = stem.split("__")
    if len(parts) >= 3:  # date__client__suffix
        stem = "__".join(parts[1:-1])
    return _dashes_to_name(stem) or None


def clipboard_tsv(rows: list[dict]) -> str:
    lines = ["\t".join(_COLUMNS)]
    for r in rows:
        lines.append("\t".join(str(r.get(c, "")) for c in _COLUMNS))
    return "\n".join(lines)


def report_title(client_name: str | None, today: _dt.date | None = None) -> str:
    """Build the report title 'YYYY-MM-DD Client Name GRESB Diff Analysis'.

    `today` defaults to the local (computer) date. A missing/blank client name
    falls back to 'Client' so the title is always well-formed.
    """
    if today is None:
        today = _dt.date.today()
    name = " ".join((client_name or "").split()).strip() or "Client"
    return f"{today:%Y-%m-%d} {name} GRESB Diff Analysis"


def safe_filename(title: str) -> str:
    """Make `title` safe as a download filename (no extension added).

    Strips characters illegal across OSes and collapses whitespace; keeps
    commas/periods which are valid and common in fund names. A trailing period
    (e.g. 'L.P.') is preserved within the name but stripped if it is the very
    last character, which some systems dislike.
    """
    cleaned = _ILLEGAL_FILENAME.sub("", title)
    cleaned = " ".join(cleaned.split())
    return cleaned.rstrip(". ") or "report"


def printable_html(rows: list[dict], summary: str,
                   unlocated: list[str], title: str = "GRESB Diff Report") -> str:
    # `title` sets both the <title> (the default filename the browser proposes
    # when the user prints / saves the page as PDF) and the on-page <h1>.
    head = "".join(f"<th>{html.escape(c)}</th>" for c in _COLUMNS)
    body_rows = []
    for r in rows:
        cells = "".join(
            f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in _COLUMNS)
        body_rows.append(f"<tr>{cells}</tr>")
    unloc = ""
    if unlocated:
        items = "".join(f"<li>{html.escape(u)}</li>" for u in unlocated)
        unloc = (f"<h2>Could not locate on one side</h2><ul>{items}</ul>")
    esc_title = html.escape(title)
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{esc_title}</title>
<style>
 body{{font-family:Arial,Helvetica,sans-serif;margin:2rem;}}
 table{{border-collapse:collapse;width:100%;font-size:13px;}}
 th,td{{border:1px solid #999;padding:6px 8px;text-align:left;}}
 th{{background:#f0f0f0;}}
 button{{margin-bottom:1rem;}}
 @media print{{button{{display:none;}}}}
</style></head><body>
<button onclick="window.print()">Print / Save as PDF</button>
<h1>{esc_title}</h1>
<p>{html.escape(summary)}</p>
<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>
{unloc}
</body></html>"""
