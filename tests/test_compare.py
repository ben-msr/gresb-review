from gresb_diff.compare import (
    compare,
    compare_bc,
    compare_matrices,
    compare_renewables,
)


def _re(source, pt, row, metric, n):
    col = "Prior Year (MWh)" if metric == "prior" else "Reporting Year (MWh)"
    return FieldRecord("Energy", "EN1RE", pt, row, col, str(n), float(n), source)


def test_compare_renewables_matches_across_vocabularies():
    pt = "Industrial: Manufacturing | United States"
    docx = [_re("docx", pt, "Generated On-site by Third Party or Tenant", "prior", 1320.34),
            _re("docx", pt, "Generated On-site by Third Party or Tenant", "reporting", 586.67)]
    pdf = [_re("pdf", pt, "Generated and consumed by third-party (or tenant)", "prior", 1320.34),
           _re("pdf", pt, "Generated and consumed by third-party (or tenant)", "reporting", 586.67)]
    result = compare_renewables(docx, pdf)
    assert result.differences == [] and result.unlocated == []


def test_compare_renewables_flags_value_mismatch():
    pt = "Hotel | United States"
    docx = [_re("docx", pt, "Generated Off-site and Purchased by Landlord", "prior", 100.0)]
    pdf = [_re("pdf", pt, "Procured by Landlord", "prior", 250.0)]
    result = compare_renewables(docx, pdf)
    assert len(result.differences) == 1
    d = result.differences[0]
    assert d.pdf_value == "250.0" and d.docx_value == "100.0"
    assert d.canonical_id == "EN1RE.RE_OFF_LL.prior"
from gresb_diff.crosswalk import CrosswalkEntry
from gresb_diff.models import FieldRecord


def _mrec(source, row_label, col_label, num):
    return FieldRecord("Energy", "EN1", "Hotel | United States",
                       row_label, col_label, str(num), num, source)


_DOCX_ROW = "Common Area Electric"
_PDF_ROW = "Base Common Building Areas - | Landlord Controlled | Electricity"
_DOCX_COLS = {"prior": "Like-for-Like | Prior Year Usage (MWh)",
              "reporting": "Like-for-Like | Reporting Year Usage (MWh)",
              "coverage": "Like-for-Like | Data Coverage (ft²)"}
_PDF_COLS = {"prior": "Like-for-Like | 2024 Consumption (MWh)",
             "reporting": "Like-for-Like | 2025 Consumption (MWh)",
             "coverage": "Like-for-Like | Floor Area Covered (sq. ft.)"}


def _matrix_records(docx_vals, pdf_vals):
    docx = [_mrec("docx", _DOCX_ROW, _DOCX_COLS[k], v) for k, v in docx_vals.items()]
    pdf = [_mrec("pdf", _PDF_ROW, _PDF_COLS[k], v) for k, v in pdf_vals.items()]
    return docx, pdf


def test_one_sided_coverage_is_skipped():
    # One-sided coverage: PDF leaves the Like-for-Like coverage blank (0) while
    # the docx repeats the Absolute coverage. This is a representational
    # artifact, not a real difference — must not be flagged.
    docx, pdf = _matrix_records(
        {"prior": 0, "reporting": 0, "coverage": 99558.25},
        {"prior": 0, "reporting": 0, "coverage": 0})
    result = compare_matrices(docx, pdf, questions=("EN1",))
    assert result.differences == []
    assert result.unlocated == []


def test_both_sided_coverage_difference_flagged_even_without_usage():
    # Both documents report a (different) non-zero coverage/floor-area value
    # while usage is zero — e.g. Scope 3 Maximum Floor Area 3857261.8 vs
    # 4120649.3. This is a genuine difference and must be flagged (regression:
    # an earlier usage-based skip suppressed it).
    docx, pdf = _matrix_records(
        {"prior": 0, "reporting": 0, "coverage": 4120649.3},
        {"prior": 0, "reporting": 0, "coverage": 3857261.8})
    result = compare_matrices(docx, pdf, questions=("EN1",))
    fields = {d.pdf_field_name.split(" | ")[-1] for d in result.differences}
    assert fields == {"Floor Area Covered (sq. ft.)"}


def test_both_sided_coverage_compared_with_usage():
    # Both coverage values present and differing, with usage present too.
    docx, pdf = _matrix_records(
        {"prior": 343.33, "reporting": 306.86, "coverage": 627035.5},
        {"prior": 941.24, "reporting": 1062.35, "coverage": 653806.5})
    result = compare_matrices(docx, pdf, questions=("EN1",))
    fields = {d.pdf_field_name.split(" | ")[-1] for d in result.differences}
    assert fields == {"2024 Consumption (MWh)", "2025 Consumption (MWh)",
                      "Floor Area Covered (sq. ft.)"}


def _bc(source, pt, scheme, n):
    return FieldRecord("Building Certifications", "BC1.1", pt, scheme,
                       "Number of Assets", str(n), float(n), source)


def test_compare_bc_flags_scheme_missing_from_pdf():
    # docx has LEED Core & Shell for Medical Office; the PDF does not.
    pt = "Healthcare: Medical Office | United States"
    docx = [_bc("docx", pt, "LEED Core & Shell", 1),
            _bc("docx", pt, "LEED Building Design and Construction", 1)]
    pdf = [_bc("pdf", pt, "LEED/Building Design and Construction (BD+C) / Gold", 1)]
    result = compare_bc(docx, pdf, questions=("BC1.1",))
    # BD+C matches (1 == 1) -> no difference; Core & Shell is missing in PDF.
    assert result.differences == []
    assert len(result.unlocated) == 1
    u = result.unlocated[0]
    assert u.status == "missing_pdf"
    assert "Core & Shell" in u.docx_field_name and u.docx_value == "1"


def test_compare_bc_aggregates_pdf_levels_and_flags_count_mismatch():
    # PDF splits BD+C across levels (1 + 2 + 1 = 4); docx reports 2.
    pt = "Office: Corporate: High-Rise Office | United States"
    docx = [_bc("docx", pt, "LEED Building Design and Construction", 2)]
    pdf = [_bc("pdf", pt, "LEED/Building Design and Construction (BD+C) / Certified", 1),
           _bc("pdf", pt, "LEED/Building Design and Construction (BD+C) / Gold", 2),
           _bc("pdf", pt, "LEED/Building Design and Construction (BD+C) / Silver", 1)]
    result = compare_bc(docx, pdf, questions=("BC1.1",))
    assert result.unlocated == []
    assert len(result.differences) == 1
    d = result.differences[0]
    assert d.pdf_value == "4" and d.docx_value == "2"


def test_compare_bc_aggregated_levels_match_is_not_flagged():
    pt = "Office | United States"
    docx = [_bc("docx", pt, "LEED Building Operations and Maintenance", 3)]
    pdf = [_bc("pdf", pt, "LEED/Building Operations and Maintenance (O+M) / Gold", 1),
           _bc("pdf", pt, "LEED/Building Operations and Maintenance (O+M) / Silver", 2)]
    result = compare_bc(docx, pdf, questions=("BC1.1",))
    assert result.differences == [] and result.unlocated == []


def _entry(mode="cell", vt="decimal"):
    return CrosswalkEntry("c.id", mode, True, vt, "Energy", "EN1",
                          "dr", "dc", "pr", "pc", "PDF NAME", "DOCX NAME")


def _r(num=None, raw=None, src="pdf"):
    raw = raw if raw is not None else ("" if num is None else str(num))
    return FieldRecord("Energy", "EN1", "Hotel | United States", "rl", "cl",
                       raw, num, src)


def test_decimal_within_tolerance_is_not_flagged():
    pairs = [(_entry(vt="decimal"), "Hotel | United States",
              _r(87.9722, src="pdf"), _r(87.97, src="docx"), "")]
    result = compare(pairs)
    assert result.differences == []


def test_decimal_outside_tolerance_is_flagged():
    pairs = [(_entry(vt="decimal"), "Hotel | United States",
              _r(113.94, src="pdf"), _r(114.10, src="docx"), "")]
    result = compare(pairs)
    assert len(result.differences) == 1
    d = result.differences[0]
    assert d.pdf_field_name == "PDF NAME" and d.docx_field_name == "DOCX NAME"
    assert d.pdf_value == "113.94" and d.docx_value == "114.1"
    assert d.status == "value_mismatch"


def test_int_must_match_exactly():
    pairs = [(_entry(vt="int"), "Hotel | United States",
              _r(28.0, src="pdf"), _r(27.0, src="docx"), "")]
    assert len(compare(pairs).differences) == 1


def test_text_normalized_comparison():
    pairs = [(_entry(vt="text"), "Hotel | United States",
              _r(raw=" Energy  STAR ", src="pdf"),
              _r(raw="energy star", src="docx"), "")]
    assert compare(pairs).differences == []


def test_missing_side_goes_to_unlocated():
    pairs = [(_entry(), "Hotel | United States", None, _r(1.0, src="docx"), "")]
    result = compare(pairs)
    assert result.differences == []
    assert len(result.unlocated) == 1
    assert result.unlocated[0].status == "missing_pdf"


def test_numeric_with_none_value_falls_back_to_text():
    # value_type decimal but one side non-numeric -> compare raw text
    pairs = [(_entry(vt="decimal"), "Hotel | United States",
              _r(raw="N/A", src="pdf"), _r(12.0, src="docx"), "")]
    assert len(compare(pairs).differences) == 1


def test_missing_docx_side_goes_to_unlocated():
    pairs = [(_entry(), "Hotel | United States", _r(1.0, src="pdf"), None, "")]
    result = compare(pairs)
    assert result.differences == []
    assert len(result.unlocated) == 1
    assert result.unlocated[0].status == "missing_docx"


def test_keyed_entry_appends_key_to_field_names():
    pairs = [(_entry(vt="int"), "Hotel | United States",
              _r(2.0, src="pdf"), _r(1.0, src="docx"), "Energy Star Portfolio Manager")]
    d = compare(pairs).differences[0]
    assert d.pdf_field_name == "PDF NAME [Energy Star Portfolio Manager]"
    assert d.docx_field_name == "DOCX NAME [Energy Star Portfolio Manager]"


def test_both_sides_none_produces_unmapped_field_status():
    """A sentinel pair where both pdf_rec and docx_rec are None (produced when a
    crosswalk entry matches no records on either side) must land in unlocated
    with status 'unmapped_field' and produce no differences."""
    pairs = [(_entry(), "", None, None, "")]
    result = compare(pairs)
    assert result.differences == []
    assert len(result.unlocated) == 1
    u = result.unlocated[0]
    assert u.status == "unmapped_field"
