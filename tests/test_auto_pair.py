from auto_pair import _vectors_agree, pair_matrix
from gresb_diff.models import FieldRecord


def _r(pt, row, col, num, src):
    return FieldRecord("Energy", "EN1", pt, row, col, str(num), float(num), src)


def test_vectors_agree_within_tolerance():
    assert _vectors_agree({"A": 10.0, "B": 20.0}, {"A": 10.0, "B": 20.04})


def test_vectors_disagree_beyond_tolerance():
    assert not _vectors_agree({"A": 10.0}, {"A": 10.1})


def test_vectors_all_zero_is_not_a_match():
    assert not _vectors_agree({"A": 0.0, "B": 0.0}, {"A": 0.0, "B": 0.0})


def test_vectors_different_property_sets():
    assert not _vectors_agree({"A": 1.0}, {"A": 1.0, "B": 2.0})


def _matrix(rows_by_src):
    """rows_by_src: {src: {row_label: {pt: (prior, reporting)}}} -> FieldRecords."""
    recs = []
    cols = {"docx": ("Absolute | Prior Year Usage (MWh)",
                     "Absolute | Reporting Year Usage (MWh)"),
            "pdf": ("Absolute | 2024 Consumption (MWh)",
                    "Absolute | 2025 Consumption (MWh)")}
    for src, rows in rows_by_src.items():
        pcol, rcol = cols[src]
        for row, vals in rows.items():
            for pt, (pr, rep) in vals.items():
                recs.append(_r(pt, row, pcol, pr, src))
                recs.append(_r(pt, row, rcol, rep, src))
    return recs


def test_pair_matrix_unique_value_match():
    recs = _matrix({
        "docx": {"Whole Site: Indirect Fuel": {"P1": (101.81, 113.94), "P2": (0, 0)}},
        "pdf": {"Whole Building | Tenant Controlled | Fuels": {"P1": (101.81, 113.94), "P2": (0, 0)}},
    })
    docx = [r for r in recs if r.source == "docx"]
    pdf = [r for r in recs if r.source == "pdf"]
    paired, excluded = pair_matrix(docx, pdf, "EN1")
    assert len(paired) == 1
    assert paired[0]["docx_row"] == "Whole Site: Indirect Fuel"
    assert paired[0]["pdf_row"] == "Whole Building | Tenant Controlled | Fuels"
    assert excluded == []


def test_pair_matrix_no_value_match_is_excluded_not_guessed():
    recs = _matrix({
        "docx": {"RowD": {"P1": (5.0, 6.0)}},
        "pdf": {"RowP": {"P1": (99.0, 98.0)}},
    })
    docx = [r for r in recs if r.source == "docx"]
    pdf = [r for r in recs if r.source == "pdf"]
    paired, excluded = pair_matrix(docx, pdf, "EN1")
    assert paired == []
    assert [d for d, _reason in excluded] == ["RowD"]


def test_pair_matrix_ambiguous_match_is_excluded():
    recs = _matrix({
        "docx": {"RowD": {"P1": (7.0, 8.0)}},
        "pdf": {"RowP1": {"P1": (7.0, 8.0)}, "RowP2": {"P1": (7.0, 8.0)}},
    })
    docx = [r for r in recs if r.source == "docx"]
    pdf = [r for r in recs if r.source == "pdf"]
    paired, excluded = pair_matrix(docx, pdf, "EN1")
    assert paired == []
    assert "ambiguous" in excluded[0][1]


def test_pair_matrix_double_claim_is_excluded():
    # Two docx rows with identical vectors must NOT both claim one pdf row.
    recs = _matrix({
        "docx": {"RowA": {"P1": (5.0, 6.0)}, "RowB": {"P1": (5.0, 6.0)}},
        "pdf": {"RowP": {"P1": (5.0, 6.0)}},
    })
    docx = [r for r in recs if r.source == "docx"]
    pdf = [r for r in recs if r.source == "pdf"]
    paired, excluded = pair_matrix(docx, pdf, "EN1")
    assert paired == []
    assert len(excluded) == 2


def test_vectors_agree_rejects_tiny_value_vs_zero_pad():
    # docx tiny non-zero vs pdf zero-padded ghost must not match.
    assert not _vectors_agree({"P": 0.03}, {"P": 0.0})
