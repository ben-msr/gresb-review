from gresb_diff.pdf_parser import (
    bucket_by_anchor,
    decode_rotated,
    interpret_matrix,
)

# Real EN1 column right-edge (x1) anchors measured from the GRESB PDF.
_EN1_ANCHORS = [287.5, 357.9, 458.2, 563.9, 634.3, 704.7, 805.1]


def test_bucket_full_row_maps_each_value_to_its_column():
    words = [(287.5, "164.97"), (357.9, "169.21"), (458.2, "38725.8"),
             (563.9, "50241.7"), (634.3, "164.97"), (704.7, "169.21"),
             (805.1, "38725.8")]
    assert bucket_by_anchor(words, _EN1_ANCHORS) == [
        "164.97", "169.21", "38725.8", "50241.7", "164.97", "169.21", "38725.8"]


def test_bucket_right_aligned_wide_number_lands_in_correct_column():
    # The real bug: '964298.1' (a Maximum Floor Area value, x1~565) must land in
    # column 3, NOT be shifted left into a Consumption column. '0' is the Floor
    # Area Covered value (col 2). Consumption columns stay empty.
    words = [(458.0, "0"), (565.0, "964298.1")]
    slots = bucket_by_anchor(words, _EN1_ANCHORS)
    assert slots[3] == "964298.1"      # Absolute Maximum Floor Area
    assert slots[2] == "0"             # Absolute Floor Area Covered
    assert slots[0] == "" and slots[1] == ""   # consumption columns blank
    assert slots[4] == "" and slots[5] == "" and slots[6] == ""


def test_bucket_ignores_words_far_from_any_anchor():
    # A stray number well outside the column band is dropped, not misassigned.
    assert bucket_by_anchor([(150.0, "99")], _EN1_ANCHORS) == [""] * 7


def test_bucket_does_not_overwrite_an_occupied_column():
    words = [(287.5, "10.0"), (288.0, "20.0")]
    slots = bucket_by_anchor(words, _EN1_ANCHORS)
    assert slots[0] == "10.0"  # first wins; second is not silently swapped in


def test_bucket_single_anchor_selects_assets_column_only():
    # BC2 row: area@295, %covered@436, assets@532, %gav@801. With the assets
    # column anchor (~530) we must pick the assets value, never %covered/%gav —
    # this is what makes "Number of assets" robust to blank preceding columns.
    words = [(295.0, "68764.782"), (436.0, "100"), (532.0, "1"), (801.0, "100")]
    assert bucket_by_anchor(words, [530.0], tol=30.0) == ["1"]


def test_decode_rotated_reverses_lines_and_chars():
    assert decode_rotated("gnidliuB\nelohW") == "Whole Building"
    assert decode_rotated("dellortnoC\ntnaneT") == "Tenant Controlled"


def test_interpret_matrix_builds_qualified_labels():
    groups = [("Whole Building", "Tenant Controlled")]
    data_rows = [("Fuels", ["990.48", "1046.8", "68764.78", "68764.78",
                            "990.48", "1046.8", "68764.78"])]
    recs = interpret_matrix("EN1", "Hotel | United States", groups, data_rows)
    by_col = {r.col_label: r.value_num for r in recs}
    assert recs[0].row_label == "Whole Building | Tenant Controlled | Fuels"
    assert by_col["Absolute | 2025 Consumption (MWh)"] == 1046.8
    assert by_col["Absolute | 2024 Consumption (MWh)"] == 990.48
    assert by_col["Like-for-Like | 2025 Consumption (MWh)"] == 1046.8
