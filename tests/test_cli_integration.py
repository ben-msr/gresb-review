import gresb_diff.__main__ as cli
from gresb_diff.models import FieldRecord
from tests.conftest import make_docx


def test_run_end_to_end_flags_bc_assets(tmp_path, monkeypatch):
    # PDF says Hotel BC2 assets = 2; docx (synthetic) says 1 -> one difference.
    def fake_parse_pdf(src):
        return [FieldRecord("Building Certifications", "BC2",
                            "Hotel | United States", "Energy Star Portfolio Manager",
                            "Number of Assets", "2", 2.0, "pdf")]
    monkeypatch.setattr(cli, "parse_pdf", fake_parse_pdf)

    mapping = tmp_path / "m.csv"
    mapping.write_text(
        "canonical_id,mode,compare,value_type,section,question,docx_row,docx_col,pdf_row,pdf_col,display_pdf,display_docx\n"
        "bc2.assets,keyed,true,int,Building Certifications,BC2,,Number of Assets,,Number of Assets,BC2 assets,BC2 assets\n"
    )
    result = cli.run(b"ignored", make_docx(), str(mapping))
    assert len(result.differences) == 1
    d = result.differences[0]
    assert d.pdf_value == "2" and d.docx_value == "1"
