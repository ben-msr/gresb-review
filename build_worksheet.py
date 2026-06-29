"""Generate an editable crosswalk worksheet from a GRESB PDF + Measurabl docx.

One row per distinct field definition (property type collapsed). The reviewer
flips `compare` to true for the fields that matter, fixes pairings, and the
edited file becomes gresb_diff/mapping/gresb_2026.csv.
"""
from __future__ import annotations

import argparse
import csv

from gresb_diff.docx_parser import parse_docx
from gresb_diff.pdf_parser import parse_pdf

COLUMNS = ["canonical_id", "mode", "compare", "value_type", "section",
           "question", "docx_row", "docx_col", "pdf_row", "pdf_col",
           "display_pdf", "display_docx"]

_KEYED_QUESTIONS = {"R1", "RA2", "BC1.1", "BC1.2", "BC2"}


def _defs(records):
    """Distinct (question, row_label, col_label) with property type collapsed; value carries section."""
    seen = {}
    for r in records:
        key = (r.question, r.row_label, r.col_label)
        seen.setdefault(key, (r.section, r.question, r.row_label, r.col_label))
    return seen


def build_rows(pdf_records, docx_records) -> list[dict]:
    docx_defs = _defs(docx_records)
    pdf_defs = _defs(pdf_records)
    rows: list[dict] = []
    row_by_key = {}
    i = 0
    for key, (section, question, row, col) in sorted(docx_defs.items()):
        mode = "keyed" if question in _KEYED_QUESTIONS else "cell"
        i += 1
        r = {
            "canonical_id": f"{question.lower()}.{i}", "mode": mode,
            "compare": "false", "value_type": "decimal", "section": section,
            "question": question, "docx_row": row, "docx_col": col,
            "pdf_row": "", "pdf_col": "",
            "display_pdf": "", "display_docx": f"{question} {row} {col}".strip(),
        }
        rows.append(r)
        row_by_key[key] = r
    for key, (section, question, row, col) in sorted(pdf_defs.items()):
        if key in docx_defs:
            r = row_by_key[key]
            r["pdf_row"] = row
            r["pdf_col"] = col
            r["display_pdf"] = f"{question} {row} {col}".strip()
            continue
        i += 1
        rows.append({
            "canonical_id": f"{question.lower()}.pdf.{i}",
            "mode": "keyed" if question in _KEYED_QUESTIONS else "cell",
            "compare": "false", "value_type": "decimal", "section": section,
            "question": question, "docx_row": "", "docx_col": "",
            "pdf_row": row, "pdf_col": col,
            "display_pdf": f"{question} {row} {col}".strip(), "display_docx": "",
        })
    return rows


def write_worksheet(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="worksheet.csv")
    args = ap.parse_args()
    with open(args.pdf, "rb") as fh:
        pdf_records = parse_pdf(fh.read())
    with open(args.docx, "rb") as fh:
        docx_records = parse_docx(fh.read())
    write_worksheet(build_rows(pdf_records, docx_records), args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
