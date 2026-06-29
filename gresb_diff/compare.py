"""Apply tolerance rules to aligned pairs and produce Differences."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Difference

TOLERANCE = 0.05


@dataclass
class CompareResult:
    differences: list[Difference] = field(default_factory=list)
    unlocated: list[Difference] = field(default_factory=list)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def _values_differ(value_type: str, pdf_rec, docx_rec) -> bool:
    if value_type == "text":
        return _norm(pdf_rec.value_raw) != _norm(docx_rec.value_raw)
    if pdf_rec.value_num is None or docx_rec.value_num is None:
        return _norm(pdf_rec.value_raw) != _norm(docx_rec.value_raw)
    if value_type == "int":
        return pdf_rec.value_num != docx_rec.value_num
    return abs(pdf_rec.value_num - docx_rec.value_num) > TOLERANCE


def _label(default, key):
    return f"{default} [{key}]" if key else default


_MATRIX_SECTION = {"EN1": "Energy", "GH1": "GHG", "WT1": "Water", "WS1": "Waste"}


def compare_matrices(docx_records, pdf_records,
                     questions=("EN1", "GH1", "WT1", "WS1")) -> CompareResult:
    """Compare matrix rows by CANONICAL identity (zone/scope × fuel), so every
    row is compared regardless of value agreement — this catches mismatches the
    value-anchored crosswalk could not. Property types are matched after
    normalisation (parentheses/case-insensitive). One-sided rows are reported
    only when the present value is non-zero (a zero row simply absent on the
    other side is not a meaningful mismatch).

    WS1 is excluded by default: the PDF exposes only an aggregate row.
    """
    from .canonical import (
        ROW_PRESENCE_METRICS,
        canonical_row,
        col_metric,
        normalize_pt,
    )

    result = CompareResult()

    def index(recs, source, question):
        idx = {}
        for r in recs:
            if r.question != question:
                continue
            ck = canonical_row(question, source, r.row_label)
            if ck is None:
                continue
            metric = col_metric(r.col_label)
            if metric is None:
                continue
            idx[(normalize_pt(r.property_type), ck, metric)] = r
        return idx

    for question in questions:
        section = _MATRIX_SECTION[question]
        d_index = index(docx_records, "docx", question)
        p_index = index(pdf_records, "pdf", question)
        for key in sorted(set(d_index) | set(p_index)):
            npt, ck, metric = key
            group, field = metric.split(".")
            is_coverage = field in ("fa_covered", "fa_max")
            d = d_index.get(key)
            p = p_index.get(key)
            present = d or p
            pt_disp = present.property_type
            canonical_id = f"{question}.{ck}.{metric}"
            pdf_name = f"{p.row_label} | {p.col_label}" if p else f"[{ck} {metric}]"
            docx_name = f"{d.row_label} | {d.col_label}" if d else f"[{ck} {metric}]"
            if d is None or p is None:
                # Only Absolute usage columns signal row presence. A one-sided
                # Like-for-Like/coverage column is structural (e.g. the GRESB
                # water/waste PDF omits them), not a missing row — skip it.
                if metric not in ROW_PRESENCE_METRICS:
                    continue
                if present.value_num in (None, 0, 0.0):
                    continue  # zero row absent on the other side: not meaningful
                status = "missing_pdf" if p is None else "missing_docx"
                result.unlocated.append(Difference(
                    section, pt_disp, canonical_id,
                    pdf_name, p.value_raw if p else "",
                    docx_name, d.value_raw if d else "", status))
                continue
            # Both sides effectively zero/blank (e.g. docx "-" vs PDF "0") is not
            # a real difference.
            if p.value_num in (None, 0, 0.0) and d.value_num in (None, 0, 0.0):
                continue
            # Coverage/floor-area columns: flag only when BOTH sides carry a
            # non-zero value. A one-sided coverage value (e.g. PDF leaves the
            # Like-for-Like coverage blank when there is no Like-for-Like usage,
            # while the docx repeats the Absolute coverage) is a representational
            # artifact, not a real difference. A genuine difference where both
            # documents report a value — e.g. Scope 3 Maximum Floor Area
            # 3857261.8 vs 4120649.3 — is still flagged.
            if is_coverage and (p.value_num in (None, 0, 0.0)
                                or d.value_num in (None, 0, 0.0)):
                continue
            if _values_differ("decimal", p, d):
                result.differences.append(Difference(
                    section, pt_disp, canonical_id,
                    pdf_name, p.value_raw, docx_name, d.value_raw,
                    "value_mismatch"))
    return result


def compare_floor_areas(docx_records, pdf_records) -> CompareResult:
    """Compare the EN1 'Floor Area by Type' values (records flagged EN1FA) by
    canonical zone. Separate from consumption: the PDF and docx each split EN1
    into a floor-area table and a consumption table."""
    from .canonical import canonical_floor_area, normalize_pt

    result = CompareResult()

    def index(recs):
        idx = {}
        for r in recs:
            if r.question != "EN1FA":
                continue
            ck = canonical_floor_area(r.row_label)
            if ck is not None:
                idx[(normalize_pt(r.property_type), ck)] = r
        return idx

    d_index, p_index = index(docx_records), index(pdf_records)
    for key in sorted(set(d_index) | set(p_index)):
        d, p = d_index.get(key), p_index.get(key)
        present = d or p
        cid = f"EN1FA.{key[1]}"
        pdf_name = f"{p.row_label} | Floor Area" if p else f"[{key[1]}]"
        docx_name = f"{d.row_label} | Floor Area" if d else f"[{key[1]}]"
        if d is None or p is None:
            if present.value_num in (None, 0, 0.0):
                continue
            status = "missing_pdf" if p is None else "missing_docx"
            result.unlocated.append(Difference(
                "Energy", present.property_type, cid,
                pdf_name, p.value_raw if p else "",
                docx_name, d.value_raw if d else "", status))
            continue
        if p.value_num in (None, 0, 0.0) and d.value_num in (None, 0, 0.0):
            continue
        if _values_differ("decimal", p, d):
            result.differences.append(Difference(
                "Energy", present.property_type, cid,
                pdf_name, p.value_raw, docx_name, d.value_raw, "value_mismatch"))
    return result


def compare_renewables(docx_records, pdf_records) -> CompareResult:
    """Compare the EN1 'Renewable Energy' values (records flagged EN1RE) by
    canonical row (on-site consumed/exported by landlord, by third party/tenant;
    off-site procured by landlord/tenant) and year (prior/reporting MWh). The
    PDF exposes these in a separate 'Renewable energy generated' table; the docx
    in its own EN1 renewables table."""
    from .canonical import canonical_renewable, normalize_pt

    result = CompareResult()

    def index(recs):
        idx = {}
        for r in recs:
            if r.question != "EN1RE":
                continue
            ck = canonical_renewable(r.row_label)
            if ck is None:
                continue
            metric = ("prior" if "prior" in r.col_label.lower()
                      else "reporting" if "reporting" in r.col_label.lower()
                      else None)
            if metric is not None:
                idx[(normalize_pt(r.property_type), ck, metric)] = r
        return idx

    d_index, p_index = index(docx_records), index(pdf_records)
    for key in sorted(set(d_index) | set(p_index)):
        d, p = d_index.get(key), p_index.get(key)
        present = d or p
        cid = f"EN1RE.{key[1]}.{key[2]}"
        pdf_name = f"{p.row_label} | {p.col_label}" if p else f"[{key[1]} {key[2]}]"
        docx_name = f"{d.row_label} | {d.col_label}" if d else f"[{key[1]} {key[2]}]"
        if d is None or p is None:
            if present.value_num in (None, 0, 0.0):
                continue
            status = "missing_pdf" if p is None else "missing_docx"
            result.unlocated.append(Difference(
                "Energy", present.property_type, cid,
                pdf_name, p.value_raw if p else "",
                docx_name, d.value_raw if d else "", status))
            continue
        if p.value_num in (None, 0, 0.0) and d.value_num in (None, 0, 0.0):
            continue
        if _values_differ("decimal", p, d):
            result.differences.append(Difference(
                "Energy", present.property_type, cid,
                pdf_name, p.value_raw, docx_name, d.value_raw, "value_mismatch"))
    return result


def _fmt_count(n) -> str:
    if n is None:
        return ""
    return str(int(n)) if float(n) == int(n) else str(n)


def compare_bc(docx_records, pdf_records,
               questions=("BC1.1", "BC1.2")) -> CompareResult:
    """Compare BC1.1/BC1.2 green-building certification asset counts by canonical
    scheme (PROGRAM|FAMILY). The docx reports one row per scheme family; the PDF
    splits each family into per-certification-level rows, so PDF rows are summed
    per (property type, scheme). A scheme present on only one side — e.g. docx
    'LEED Core & Shell' with no PDF counterpart — is reported as missing.

    BC2 is intentionally excluded: it is handled by the keyed CSV crosswalk
    (its 'Energy Star' scheme names already match across documents)."""
    from .canonical import canonical_bc_scheme, normalize_pt

    result = CompareResult()

    def index(recs, question):
        agg = {}  # (npt, scheme) -> [summed_assets, pt_display, sample_label]
        for r in recs:
            if r.question != question or r.col_label != "Number of Assets":
                continue
            ck = canonical_bc_scheme(r.row_label)
            if ck is None:
                continue
            key = (normalize_pt(r.property_type), ck)
            if key not in agg:
                agg[key] = [0.0, r.property_type, r.row_label]
            agg[key][0] += r.value_num or 0
        return agg

    for question in questions:
        d_index = index(docx_records, question)
        p_index = index(pdf_records, question)
        for key in sorted(set(d_index) | set(p_index)):
            d = d_index.get(key)
            p = p_index.get(key)
            present = d or p
            pt_disp = present[1]
            # canonical_id keeps the indicator (drives the section's code label);
            # the displayed field names use just the scheme, since the section
            # column already shows the BC indicator.
            cid = f"{question} {present[2]}"
            pdf_name = p[2] if p else f"[{key[1]}]"
            docx_name = d[2] if d else f"[{key[1]}]"
            if d is None or p is None:
                if present[0] in (None, 0, 0.0):
                    continue
                status = "missing_pdf" if p is None else "missing_docx"
                result.unlocated.append(Difference(
                    "Building Certifications", pt_disp, cid,
                    pdf_name, _fmt_count(p[0] if p else None),
                    docx_name, _fmt_count(d[0] if d else None), status))
                continue
            if int(p[0]) != int(d[0]):
                result.differences.append(Difference(
                    "Building Certifications", pt_disp, cid,
                    pdf_name, _fmt_count(p[0]),
                    docx_name, _fmt_count(d[0]), "value_mismatch"))
    return result


def compare(pairs) -> CompareResult:
    result = CompareResult()
    for entry, property_type, pdf_rec, docx_rec, key in pairs:
        pdf_name = _label(entry.display_pdf, key)
        docx_name = _label(entry.display_docx, key)
        if pdf_rec is None and docx_rec is None:
            result.unlocated.append(Difference(
                entry.section, property_type, entry.canonical_id,
                pdf_name, "", docx_name, "", "unmapped_field"))
            continue
        if pdf_rec is None or docx_rec is None:
            status = "missing_pdf" if pdf_rec is None else "missing_docx"
            result.unlocated.append(Difference(
                entry.section, property_type, entry.canonical_id,
                pdf_name, pdf_rec.value_raw if pdf_rec else "",
                docx_name, docx_rec.value_raw if docx_rec else "",
                status))
            continue
        if _values_differ(entry.value_type, pdf_rec, docx_rec):
            result.differences.append(Difference(
                entry.section, property_type, entry.canonical_id,
                pdf_name, pdf_rec.value_raw,
                docx_name, docx_rec.value_raw, "value_mismatch"))
    return result
