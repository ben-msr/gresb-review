"""Auto-pair matrix fields between the GRESB PDF and Measurabl docx by
value-anchoring, then write a crosswalk covering the reliably-parsed cells.

Strategy (conservative — no wrong pairings):
  * Column mapping is deterministic/semantic (Prior<->2024, Reporting<->2025,
    Absolute<->Absolute).
  * A docx matrix row is paired to a PDF row ONLY when their Absolute Prior and
    Absolute Reporting value vectors agree (within 0.05) across EVERY property
    type present, the match is unique, and at least one value is non-zero.
    Agreement across all property types proves both sides parsed that row
    correctly; rows that fail are excluded (all-zero, parse-unreliable, or a
    genuine difference that needs manual review) and reported, never guessed.

The keyed R1/RA2/BC rows are preserved from the existing mapping. Matrix
("cell") rows are regenerated. Run:
    python3 auto_pair.py <pdf> <docx> [-o gresb_diff/mapping/gresb_2026.csv]
"""
from __future__ import annotations

import argparse
import csv
import dataclasses

from gresb_diff.crosswalk import CrosswalkEntry
from gresb_diff.docx_parser import parse_docx
from gresb_diff.pdf_parser import parse_pdf

TOLERANCE = 0.05
MATRIX_QUESTIONS = {"EN1": "Energy", "GH1": "GHG", "WT1": "Water", "WS1": "Waste"}
COLUMNS = [f.name for f in dataclasses.fields(CrosswalkEntry)]


def classify_metric(label: str) -> str | None:
    low = label.lower()
    if "prior year" in low or "2024 consumption" in low:
        return "prior"
    if "reporting year" in low or "2025 consumption" in low:
        return "reporting"
    return None


def _is_absolute(label: str) -> bool:
    return label.startswith("Absolute")


def build_index(records, question):
    """(row, metric) -> {"vec": {pt: num}, "col": exact_col_string} for the
    Absolute Prior/Reporting columns, requiring a single consistent col label."""
    raw = {}
    for r in records:
        if r.question != question or not _is_absolute(r.col_label):
            continue
        metric = classify_metric(r.col_label)
        if metric is None:
            continue
        slot = raw.setdefault((r.row_label, metric), {"vec": {}, "cols": set()})
        slot["vec"][r.property_type] = r.value_num
        slot["cols"].add(r.col_label)
    index = {}
    for key, slot in raw.items():
        if len(slot["cols"]) == 1:  # consistent label across property types
            index[key] = {"vec": slot["vec"], "col": next(iter(slot["cols"]))}
    return index


def _vectors_agree(a: dict, b: dict) -> bool:
    if set(a) != set(b) or not a:
        return False
    # Both sides must carry a value above tolerance — otherwise a zero-padded
    # PDF "ghost" row could match tiny docx values and create a false pairing.
    if max((abs(a[p]) for p in a if a[p] is not None), default=0.0) <= TOLERANCE:
        return False
    if max((abs(b[p]) for p in b if b[p] is not None), default=0.0) <= TOLERANCE:
        return False
    return all(a[p] is not None and b[p] is not None
               and abs(a[p] - b[p]) <= TOLERANCE for p in a)


def pair_matrix(docx_records, pdf_records, question):
    """Return (paired, excluded). paired: list of dicts with row + col strings.
    excluded: list of (docx_row, reason)."""
    di = build_index(docx_records, question)
    pi = build_index(pdf_records, question)
    docx_rows = sorted({row for (row, _m) in di})
    pdf_rows = sorted({row for (row, _m) in pi})

    def _has_both(idx, row):
        return idx.get((row, "reporting")), idx.get((row, "prior"))

    d2p, p2d = {}, {}
    for drow in docx_rows:
        d_rep, d_pri = _has_both(di, drow)
        if not d_rep or not d_pri:
            continue
        for prow in pdf_rows:
            p_rep, p_pri = _has_both(pi, prow)
            if not p_rep or not p_pri:
                continue
            if (_vectors_agree(d_rep["vec"], p_rep["vec"])
                    and _vectors_agree(d_pri["vec"], p_pri["vec"])):
                d2p.setdefault(drow, []).append(prow)
                p2d.setdefault(prow, []).append(drow)

    paired, excluded = [], []
    for drow in docx_rows:
        d_rep, d_pri = _has_both(di, drow)
        if not d_rep or not d_pri:
            excluded.append((drow, "docx missing consistent prior/reporting cols"))
            continue
        cands = d2p.get(drow, [])
        if not cands:
            excluded.append((drow, "no value-matching pdf row "
                             "(all-zero, parse-unreliable, or genuine difference)"))
        elif len(cands) > 1:
            excluded.append((drow, f"ambiguous ({len(cands)} pdf matches)"))
        elif len(p2d.get(cands[0], [])) > 1:
            excluded.append((drow, f"pdf row claimed by {len(p2d[cands[0]])} docx rows"))
        else:
            prow = cands[0]
            paired.append({
                "docx_row": drow, "pdf_row": prow,
                "prior": (di[(drow, "prior")]["col"], pi[(prow, "prior")]["col"]),
                "reporting": (di[(drow, "reporting")]["col"], pi[(prow, "reporting")]["col"]),
            })
    return paired, excluded


def matrix_rows(paired, question, section):
    rows = []
    for pair in paired:
        for metric in ("prior", "reporting"):
            docx_col, pdf_col = pair[metric]
            rows.append({
                "canonical_id": f"{question.lower()}.{pair['docx_row']}.{metric}"
                .replace(" ", "_").replace(":", "_").replace("|", "").lower(),
                "mode": "cell", "compare": "true", "value_type": "decimal",
                "section": section, "question": question,
                "docx_row": pair["docx_row"], "docx_col": docx_col,
                "pdf_row": pair["pdf_row"], "pdf_col": pdf_col,
                "display_pdf": f"{pair['pdf_row']} | {pdf_col}",
                "display_docx": f"{pair['docx_row']} | {docx_col}",
            })
    return rows


def keyed_rows(existing_csv_path):
    """Preserve the keyed R1/RA2/BC rows from the existing mapping."""
    try:
        with open(existing_csv_path, newline="", encoding="utf-8") as fh:
            return [r for r in csv.DictReader(fh) if r.get("mode") == "keyed"]
    except FileNotFoundError:
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("docx")
    ap.add_argument("-o", "--out", default="gresb_diff/mapping/gresb_2026.csv")
    args = ap.parse_args()
    with open(args.pdf, "rb") as fh:
        pdf_records = parse_pdf(fh.read())
    with open(args.docx, "rb") as fh:
        docx_records = parse_docx(fh.read())

    out_rows = keyed_rows(args.out)
    print(f"Preserved {len(out_rows)} keyed rows (R1/RA2/BC).")
    for question, section in MATRIX_QUESTIONS.items():
        paired, excluded = pair_matrix(docx_records, pdf_records, question)
        out_rows.extend(matrix_rows(paired, question, section))
        print(f"\n{question}: {len(paired)} rows auto-paired, "
              f"{len(excluded)} excluded")
        for pair in paired:
            print(f"  PAIR  {pair['docx_row']}  <->  {pair['pdf_row']}")
        for drow, reason in excluded:
            print(f"  skip  {drow}: {reason}")

    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)
    print(f"\nWrote {args.out} ({len(out_rows)} compare rows).")


if __name__ == "__main__":
    main()
