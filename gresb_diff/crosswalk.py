"""Load the crosswalk CSV and align PDF/docx records into comparable pairs."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Optional, Tuple

from .canonical import normalize_pt
from .models import FieldRecord


@dataclass(frozen=True)
class CrosswalkEntry:
    canonical_id: str
    mode: str          # "cell" | "keyed"
    compare: bool
    value_type: str    # "decimal" | "int" | "text"
    section: str
    question: str
    docx_row: str
    docx_col: str
    pdf_row: str
    pdf_col: str
    display_pdf: str
    display_docx: str


# Pair = (entry, property_type, pdf_record_or_None, docx_record_or_None, key)
# typing.Tuple/Optional used (not `X | None`) so this alias is runtime-safe on 3.9.
Pair = Tuple[CrosswalkEntry, str, Optional[FieldRecord], Optional[FieldRecord], str]


def load_crosswalk(path: str) -> list[CrosswalkEntry]:
    entries: list[CrosswalkEntry] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            entries.append(CrosswalkEntry(
                canonical_id=row["canonical_id"].strip(),
                mode=row["mode"].strip(),
                compare=row["compare"].strip().lower() == "true",
                value_type=row["value_type"].strip(),
                section=row["section"].strip(),
                question=row["question"].strip(),
                docx_row=row["docx_row"].strip(),
                docx_col=row["docx_col"].strip(),
                pdf_row=row["pdf_row"].strip(),
                pdf_col=row["pdf_col"].strip(),
                display_pdf=row["display_pdf"].strip(),
                display_docx=row["display_docx"].strip(),
            ))
    return [e for e in entries if e.compare]


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def align(entries, pdf_records, docx_records) -> list[Pair]:
    pairs: list[Pair] = []
    for entry in entries:
        if entry.mode == "cell":
            new = _align_cell(entry, pdf_records, docx_records)
        elif entry.mode == "keyed":
            new = _align_keyed(entry, pdf_records, docx_records)
        else:
            new = []
        if not new:
            # A compare=true entry matching nothing on either side would
            # otherwise vanish silently. Surface it so mistyped/unmapped
            # crosswalk rows appear in the report instead of being skipped.
            new = [(entry, "", None, None, "")]
        pairs.extend(new)
    return pairs


# Property types are matched after normalization (parentheses/case/whitespace)
# so e.g. PDF "Parking (Indoors)" aligns with docx "Parking Indoors". The
# original (un-normalized) label is carried for display.
def _align_cell(entry, pdf_records, docx_records) -> list[Pair]:
    d_index = {
        normalize_pt(r.property_type): r for r in docx_records
        if r.question == entry.question and r.row_label == entry.docx_row
        and r.col_label == entry.docx_col
    }
    p_index = {
        normalize_pt(r.property_type): r for r in pdf_records
        if r.question == entry.question and r.row_label == entry.pdf_row
        and r.col_label == entry.pdf_col
    }
    pairs: list[Pair] = []
    for key in sorted(set(d_index) | set(p_index)):
        d, p = d_index.get(key), p_index.get(key)
        pairs.append((entry, (d or p).property_type, p, d, ""))
    return pairs


def _align_keyed(entry, pdf_records, docx_records) -> list[Pair]:
    d_index = {
        (normalize_pt(r.property_type), _norm(r.row_label)): r for r in docx_records
        if r.question == entry.question and r.col_label == entry.docx_col
    }
    p_index = {
        (normalize_pt(r.property_type), _norm(r.row_label)): r for r in pdf_records
        if r.question == entry.question and r.col_label == entry.pdf_col
    }
    pairs: list[Pair] = []
    for key in sorted(set(d_index) | set(p_index)):
        d = d_index.get(key)
        p = p_index.get(key)
        present = d or p
        pairs.append((entry, present.property_type, p, d, present.row_label))
    return pairs
