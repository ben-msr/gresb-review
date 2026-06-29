"""Common data shapes shared by parsers, crosswalk, comparator, and reporter."""
from __future__ import annotations

from dataclasses import dataclass

_BLANKS = {"", "-", "n/a", "na"}


@dataclass(frozen=True)
class FieldRecord:
    section: str
    question: str
    property_type: str
    row_label: str
    col_label: str
    value_raw: str
    value_num: float | None
    source: str  # "pdf" or "docx"


@dataclass(frozen=True)
class Difference:
    section: str
    property_type: str
    canonical_id: str
    pdf_field_name: str
    pdf_value: str
    docx_field_name: str
    docx_value: str
    status: str  # "value_mismatch" | "missing_pdf" | "missing_docx"


def parse_value(raw: str) -> tuple[str, float | None]:
    """Return (trimmed_original_string, numeric_value_or_None)."""
    raw = "" if raw is None else str(raw)
    stripped = raw.strip()
    if stripped.lower() in _BLANKS:
        return stripped, None
    cleaned = stripped.replace(",", "").rstrip("%").strip()
    try:
        return stripped, float(cleaned)
    except ValueError:
        return stripped, None
