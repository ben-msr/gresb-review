from build_worksheet import build_rows
from gresb_diff.models import FieldRecord


def _r(q, pt, row, col, src):
    return FieldRecord("Energy", q, pt, row, col, "1", 1.0, src)


def test_build_rows_collapses_property_type_and_defaults_ignore():
    docx = [
        _r("EN1", "Hotel | United States", "Whole Site: Indirect Fuel", "Absolute | Reporting Year Usage (MWh)", "docx"),
        _r("EN1", "Office | United States", "Whole Site: Indirect Fuel", "Absolute | Reporting Year Usage (MWh)", "docx"),
    ]
    pdf = [
        _r("EN1", "Hotel | United States", "Whole Building | Tenant Controlled | Fuels", "Absolute | 2025 Consumption (MWh)", "pdf"),
    ]
    rows = build_rows(pdf, docx)
    # one docx definition row (property type collapsed) + one pdf-only row
    assert len(rows) == 2
    docx_defs = [r for r in rows if r["docx_col"]]
    assert len(docx_defs) == 1
    assert all(r["compare"] == "false" for r in rows)
    assert docx_defs[0]["question"] == "EN1"
    assert docx_defs[0]["docx_row"] == "Whole Site: Indirect Fuel"


def test_build_rows_merges_matching_keys_into_one_paired_row():
    # Same (question,row,col) on both sides (e.g. keyed R1 'Number of Assets')
    # must collapse to ONE row with both sides filled, not two rows.
    docx = [_r("R1", "Hotel | United States", "", "Number of Assets", "docx")]
    pdf = [_r("R1", "Office | United States", "", "Number of Assets", "pdf")]
    rows = build_rows(pdf, docx)
    assert len(rows) == 1
    assert rows[0]["docx_col"] == "Number of Assets"
    assert rows[0]["pdf_col"] == "Number of Assets"
