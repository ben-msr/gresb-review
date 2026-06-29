from gresb_diff.crosswalk import load_crosswalk, align
from gresb_diff.models import FieldRecord


def _docx(q, pt, row, col, num):
    return FieldRecord("S", q, pt, row, col, str(num), float(num), "docx")


def _pdf(q, pt, row, col, num):
    return FieldRecord("S", q, pt, row, col, str(num), float(num), "pdf")


def test_load_crosswalk_only_returns_rows(tmp_path):
    entries = load_crosswalk("gresb_diff/mapping/gresb_2026.csv")
    ids = {e.canonical_id for e in entries}
    assert "ra2.assets" in ids
    assert all(e.compare for e in entries)


def test_align_keyed_matches_by_row_label_per_property_type(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text(
        "canonical_id,mode,compare,value_type,section,question,docx_row,docx_col,pdf_row,pdf_col,display_pdf,display_docx\n"
        "bc2.assets,keyed,true,int,Building Certifications,BC2,,Number of Assets,,Number of Assets,P,D\n"
    )
    entries = load_crosswalk(str(csv))
    docx = [_docx("BC2", "Hotel | United States", "Energy Star Portfolio Manager", "Number of Assets", 1)]
    pdf = [_pdf("BC2", "Hotel | United States", "Energy Star Portfolio Manager", "Number of Assets", 2)]
    pairs = align(entries, pdf, docx)
    assert len(pairs) == 1
    entry, pt, p, d, key = pairs[0]
    assert pt == "Hotel | United States"
    assert key == "Energy Star Portfolio Manager"
    assert p.value_num == 2.0 and d.value_num == 1.0


def test_align_cell_iterates_property_types(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text(
        "canonical_id,mode,compare,value_type,section,question,docx_row,docx_col,pdf_row,pdf_col,display_pdf,display_docx\n"
        "en1.x,cell,true,decimal,Energy,EN1,Whole Site: Indirect Fuel,Absolute | Reporting Year Usage (MWh),Whole Building | Tenant Controlled | Fuels,Absolute | 2025 Consumption (MWh),P,D\n"
    )
    entries = load_crosswalk(str(csv))
    docx = [_docx("EN1", "Hotel | United States", "Whole Site: Indirect Fuel", "Absolute | Reporting Year Usage (MWh)", 1046.8)]
    pdf = [_pdf("EN1", "Hotel | United States", "Whole Building | Tenant Controlled | Fuels", "Absolute | 2025 Consumption (MWh)", 1046.8)]
    pairs = align(entries, pdf, docx)
    assert len(pairs) == 1
    entry, pt, p, d, key = pairs[0]
    assert pt == "Hotel | United States" and p.value_num == d.value_num == 1046.8


def test_align_reports_missing_side(tmp_path):
    csv = tmp_path / "m.csv"
    csv.write_text(
        "canonical_id,mode,compare,value_type,section,question,docx_row,docx_col,pdf_row,pdf_col,display_pdf,display_docx\n"
        "bc2.assets,keyed,true,int,Building Certifications,BC2,,Number of Assets,,Number of Assets,P,D\n"
    )
    entries = load_crosswalk(str(csv))
    docx = [_docx("BC2", "Hotel | United States", "LEED", "Number of Assets", 1)]
    pdf = []
    pairs = align(entries, pdf, docx)
    assert len(pairs) == 1
    _, _, p, d, _ = pairs[0]
    assert p is None and d is not None


def test_align_cell_no_match_on_either_side_yields_sentinel_pair(tmp_path):
    """A compare=true cell entry that matches no records on either side must
    produce exactly one sentinel pair (entry, "", None, None, "") instead of
    vanishing silently."""
    csv_path = tmp_path / "m.csv"
    csv_path.write_text(
        "canonical_id,mode,compare,value_type,section,question,docx_row,docx_col,pdf_row,pdf_col,display_pdf,display_docx\n"
        "ghost.field,cell,true,decimal,Energy,GHOST,NoSuchRow,NoSuchCol,NoSuchRow,NoSuchCol,P,D\n"
    )
    entries = load_crosswalk(str(csv_path))
    # records that do NOT match the entry's labels at all
    docx = [_docx("EN1", "Hotel | United States", "SomeOtherRow", "SomeOtherCol", 1.0)]
    pdf = [_pdf("EN1", "Hotel | United States", "SomeOtherRow", "SomeOtherCol", 1.0)]
    pairs = align(entries, pdf, docx)
    assert len(pairs) == 1
    entry, pt, p_rec, d_rec, key = pairs[0]
    assert entry.canonical_id == "ghost.field"
    assert pt == ""
    assert p_rec is None
    assert d_rec is None
    assert key == ""
