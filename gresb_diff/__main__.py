"""CLI: python -m gresb_diff <pdf> <docx> --mapping <csv>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_MAPPING = str(Path(__file__).resolve().parent / "mapping" / "gresb_2026.csv")

from .compare import (
    CompareResult,
    compare,
    compare_bc,
    compare_floor_areas,
    compare_matrices,
    compare_renewables,
)
from .crosswalk import align, load_crosswalk
from .docx_parser import parse_docx
from .pdf_parser import parse_pdf
from .report import order_differences, render_markdown

# Matrix sections are compared by canonical identity (see compare_matrices),
# not via the CSV crosswalk; keyed sections (R1/RA2/BC) come from the CSV.
_MATRIX_QUESTIONS = {"EN1", "GH1", "WT1", "WS1"}


def run(pdf_src, docx_src, mapping_path) -> CompareResult:
    entries = load_crosswalk(mapping_path)
    pdf_records = parse_pdf(pdf_src)
    docx_records = parse_docx(docx_src)
    # Keyed sections (R1/RA2/BC) via the CSV crosswalk; matrix entries in the
    # CSV are ignored here because canonical alignment handles them below.
    keyed = [e for e in entries if e.question not in _MATRIX_QUESTIONS]
    result = compare(align(keyed, pdf_records, docx_records))
    matrix = compare_matrices(docx_records, pdf_records)
    result.differences.extend(matrix.differences)
    result.unlocated.extend(matrix.unlocated)
    floor = compare_floor_areas(docx_records, pdf_records)
    result.differences.extend(floor.differences)
    result.unlocated.extend(floor.unlocated)
    renew = compare_renewables(docx_records, pdf_records)
    result.differences.extend(renew.differences)
    result.unlocated.extend(renew.unlocated)
    # BC1.1/BC1.2 green-building certs by canonical scheme (BC2 stays keyed/CSV).
    bc = compare_bc(docx_records, pdf_records)
    result.differences.extend(bc.differences)
    result.unlocated.extend(bc.unlocated)
    # Group Energy floor-area rows (appended last) with the Energy consumption
    # rows, floor area first per property type — mirroring the docx layout.
    result.differences = order_differences(result.differences)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gresb_diff")
    ap.add_argument("pdf")
    ap.add_argument("docx")
    ap.add_argument("--mapping", default=DEFAULT_MAPPING)
    args = ap.parse_args(argv)
    with open(args.pdf, "rb") as fh:
        pdf_bytes = fh.read()
    with open(args.docx, "rb") as fh:
        docx_bytes = fh.read()
    result = run(pdf_bytes, docx_bytes, args.mapping)
    print(render_markdown(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
