from gresb_diff.compare import CompareResult
from gresb_diff.models import Difference
from gresb_diff.report import (
    category_code,
    order_differences,
    readable_report,
    result_to_rows,
    render_markdown,
    section_label,
)


def test_readable_report_groups_and_formats():
    r = CompareResult()
    pt = "Industrial: Distribution Warehouse | United States"
    r.differences.append(Difference(
        "Energy", pt, "EN1.WB_TENANT|FUEL.L4L.fa_covered",
        "Whole Building | Tenant Controlled | Fuels | Like-for-Like | "
        "Floor Area Covered (sq. ft.)", "1322742",
        "Whole Site: Indirect Fuel | Like-for-Like | Data Coverage (ft²)",
        "344327", "value_mismatch"))
    r.differences.append(Difference(
        "Energy", pt, "EN1.WB_TENANT|FUEL.L4L.prior",
        "Whole Building | Tenant Controlled | Fuels | Like-for-Like | "
        "2024 Consumption (MWh)", "2572.18",
        "Whole Site: Indirect Fuel | Like-for-Like | Prior Year Usage (MWh)",
        "278.32", "value_mismatch"))
    out = readable_report(r)
    assert "**EN1 Energy - " + pt + "**" in out
    assert "- LFL Whole Site: Indirect Fuel" in out
    assert "Floor Area Covered: GRESB - 1322742 sq ft vs Word Dif - 344327 sq ft" in out
    assert "2024: GRESB - 2572.18 MWh vs Word Dif - 278.32 MWh" in out
    # both metrics nest under the one row bullet
    assert out.count("- LFL Whole Site: Indirect Fuel") == 1


def test_readable_report_empty_when_no_differences():
    assert readable_report(CompareResult()) == ""


def test_readable_report_ghg_unit_is_mtco2e():
    r = CompareResult()
    r.differences.append(Difference(
        "GHG", "Hotel | United States", "GH1.WB|SCOPE_3.L4L.prior",
        "Whole Building | Scope 3 | Like-for-Like | 2024 Consumption (tonnes)",
        "5024.47",
        "Scope 3 | Like-for-Like | Prior Year Emissions (MTCO2e)", "4069.12",
        "value_mismatch"))
    out = readable_report(r)
    assert "2024: GRESB - 5024.47 MTCO2e vs Word Dif - 4069.12 MTCO2e" in out
    assert "tonnes" not in out


def test_category_code_from_canonical_id():
    cases = {
        "EN1.SHARED|ELECTRIC.ABS.prior": "EN1",
        "EN1FA.FA_SHARED": "EN1",          # floor-area tag is part of EN1
        "GH1.WB|SCOPE_1.ABS.prior": "GH1",
        "WT1.WB_LANDLORD|WATER.ABS.prior": "WT1",
        "WS1.WS_DIVERTED.ABS.prior": "WS1",
        "ra2.assets": "RA2",
        "r1.gav": "R1",
        "bc2.assets": "BC2",
        "BC1.1 LEED Core & Shell": "BC1.1",
        "BC1.2 BOMA 360": "BC1.2",
        "mystery.thing": "",
    }
    for cid, code in cases.items():
        assert category_code(cid) == code, cid


def test_section_label_appends_code():
    d = Difference("Energy", "Hotel | United States", "EN1.X.ABS.prior",
                   "p", "1", "d", "2", "value_mismatch")
    assert section_label(d) == "Energy (EN1)"
    d2 = Difference("Building Certifications", "Hotel", "bc2.assets",
                    "p", "1", "d", "2", "value_mismatch")
    assert section_label(d2) == "Building Certifications (BC2)"


def _diff(section, ptype, cid):
    return Difference(section, ptype, cid, "P", "1", "D", "2", "value_mismatch")


def test_order_differences_floor_area_before_consumption_per_property_type():
    # Assembly order: consumption first, floor area appended last (as run() does).
    diffs = [
        _diff("Reporting Characteristics", "Office", "R1.gav"),
        _diff("Energy", "Retail: High Street", "EN1.WB_LANDLORD|ELECTRIC|reporting"),
        _diff("Energy", "Hotel", "EN1.WB_LANDLORD|ELECTRIC|reporting"),
        _diff("GHG", "Hotel", "GH1.WB|SCOPE_1|reporting"),
        _diff("Energy", "Retail: High Street", "EN1FA.FA_SHARED"),
        _diff("Energy", "Hotel", "EN1FA.FA_COMMON"),
    ]
    ordered = order_differences(diffs)
    cids = [d.canonical_id for d in ordered]
    # Non-Energy sections keep their relative order; Energy block is contiguous.
    assert cids[0] == "R1.gav"
    assert cids[-1] == "GH1.WB|SCOPE_1|reporting"
    # Within Energy, grouped by property type with floor area (EN1FA) first.
    energy = [d for d in ordered if d.section == "Energy"]
    assert [d.canonical_id for d in energy] == [
        "EN1FA.FA_COMMON",                       # Hotel floor area first
        "EN1.WB_LANDLORD|ELECTRIC|reporting",    # Hotel consumption
        "EN1FA.FA_SHARED",                       # Retail floor area first
        "EN1.WB_LANDLORD|ELECTRIC|reporting",    # Retail consumption
    ]


def _result():
    r = CompareResult()
    r.differences.append(Difference("Energy", "Hotel | United States", "en.x",
                                    "PDF F", "113.94", "DOCX F", "114.1",
                                    "value_mismatch"))
    r.unlocated.append(Difference("Building Certifications", "Hotel | United States",
                                  "bc2.assets", "P [LEED]", "", "D [LEED]", "1",
                                  "missing_pdf"))
    return r


def test_result_to_rows_shape():
    rows = result_to_rows(_result())
    assert rows[0] == {
        "Section": "Energy", "Property Type": "Hotel | United States",
        "PDF field": "PDF F", "PDF value": "113.94",
        "docx field": "DOCX F", "docx value": "114.1",
    }


def test_render_markdown_has_summary_and_groups():
    md = render_markdown(_result())
    assert "1 difference" in md
    assert "could not be located" in md
    assert "## Energy" in md
    assert "Hotel | United States" in md
    assert "113.94" in md and "114.1" in md


def test_render_markdown_escapes_pipe_in_cell_values():
    """A value containing a literal '|' must be rendered as '\\|' so it does
    not break the markdown table row."""
    r = CompareResult()
    r.differences.append(Difference(
        "Energy", "Office | United States", "en.x",
        "Whole Building | Fuels", "100.0",
        "Whole Site | Fuels", "101.0",
        "value_mismatch"))
    md = render_markdown(r)
    # The table data row must escape every pipe inside cell values
    assert "Whole Building \\| Fuels" in md
    assert "Whole Site \\| Fuels" in md
    # Sanity-check: the row should still be a valid pipe-delimited table row
    # (i.e., start and end with the structural '|' character)
    table_rows = [line for line in md.splitlines()
                  if line.startswith("| Whole Building")]
    assert len(table_rows) == 1


def test_render_markdown_unmapped_field_in_unlocated():
    """An unlocated entry with status 'unmapped_field' must render a message
    that mentions the canonical_id and 'check crosswalk labels', not 'missing in'."""
    r = CompareResult()
    r.unlocated.append(Difference(
        "Energy", "", "ghost.field", "P", "", "D", "", "unmapped_field"))
    md = render_markdown(r)
    assert "ghost.field" in md
    assert "check crosswalk labels" in md
    assert "missing in" not in md
