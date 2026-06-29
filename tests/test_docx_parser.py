from gresb_diff.docx_parser import parse_docx
from tests.conftest import make_docx


def _find(records, **kw):
    out = [r for r in records
           if all(getattr(r, k) == v for k, v in kw.items())]
    return out


def test_r1_emits_per_property_type_skipping_aggregate():
    recs = parse_docx(make_docx())
    assert not _find(recs, question="R1", property_type="All Use Types, All Countries")
    hotel = _find(recs, question="R1", property_type="Hotel | United States")
    cols = {r.col_label: r.value_num for r in hotel}
    assert cols["Number of Assets"] == 1.0
    assert cols["Floor Area (ft²)"] == 600.0
    assert cols["% of GAV"] == 60.0
    assert all(r.row_label == "" for r in hotel)


def test_ra2_keyed_by_topic_with_blank_property_type():
    recs = parse_docx(make_docx())
    energy = _find(recs, question="RA2", row_label="Energy", col_label="Number of Assets")
    assert len(energy) == 1
    assert energy[0].value_num == 3.0
    assert energy[0].property_type == ""


def test_energy_matrix_columns_are_group_qualified():
    recs = parse_docx(make_docx())
    rec = _find(recs, question="EN1", property_type="Hotel | United States",
                row_label="Whole Site: Indirect Fuel",
                col_label="Absolute | Reporting Year Usage (MWh)")
    assert len(rec) == 1
    assert rec[0].value_num == 1046.8


def test_renewables_table_parsed_as_en1re_with_all_five_rows():
    recs = parse_docx(make_docx())
    re_rows = _find(recs, question="EN1RE", property_type="Hotel | United States")
    labels = {r.row_label for r in re_rows}
    # The first data row was previously dropped by the two-header matrix logic.
    assert "Generated On-site and Consumed by Landlord" in labels
    assert len(labels) == 5
    tpt = _find(recs, question="EN1RE", property_type="Hotel | United States",
                row_label="Generated On-site by Third Party or Tenant",
                col_label="Prior Year (MWh)")
    assert len(tpt) == 1 and tpt[0].value_num == 12.5


def test_bc2_keyed_by_rating_name():
    recs = parse_docx(make_docx())
    bc = _find(recs, question="BC2", property_type="Hotel | United States",
               row_label="Energy Star Portfolio Manager",
               col_label="Number of Assets")
    assert len(bc) == 1
    assert bc[0].value_num == 1.0
