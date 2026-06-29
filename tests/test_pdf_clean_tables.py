from gresb_diff.pdf_parser import (
    _is_floor_area_page,
    interpret_bc,
    interpret_bc_geom,
    interpret_r1,
    interpret_ra2,
)


class _FakePage:
    """Minimal stand-in for a pdfplumber page: only extract_words() is used."""
    def __init__(self, words):
        self._words = words

    def extract_words(self):
        return self._words


def _w(text, x0, x1, top):
    return {"text": text, "x0": x0, "x1": x1, "top": top}


def _bc_line(words_xpairs, top):
    """Build a line of word dicts: list of (text, x0, x1) at a shared top."""
    return [_w(t, x0, x1, top) for (t, x0, x1) in words_xpairs]


def test_interpret_bc_geom_aggregates_certified_point_bands():
    # 'Energy Star Certified - NN-NN Points' rows (one per point band in the
    # PDF) must be summed into one 'Energy Star Certified' scheme to match the
    # docx, which reports a single aggregated row. Assets column anchor is the
    # 'assets' header word; the asset count right-aligns nearest it.
    words = []
    words += _bc_line([("Office", 50, 78), ("|", 82, 86),
                       ("United", 90, 120), ("States", 122, 152)], top=0)
    words += _bc_line([("Number", 200, 230), ("of", 232, 240),
                       ("assets", 242, 280)], top=10)
    # Certified 90-95 Points: area 147009, %1.62, assets 3 (nearest x1=278)
    words += _bc_line([("Energy", 50, 80), ("Star", 84, 104),
                       ("Certified", 108, 150), ("-", 154, 158),
                       ("90-95", 160, 182), ("Points", 186, 214),
                       ("147009", 230, 262), ("1.62", 244, 266),
                       ("3", 270, 278)], top=20)
    # Certified 85-89 Points: assets 1
    words += _bc_line([("Energy", 50, 80), ("Star", 84, 104),
                       ("Certified", 108, 150), ("-", 154, 158),
                       ("85-89", 160, 182), ("Points", 186, 214),
                       ("251630", 230, 262), ("6.22", 244, 266),
                       ("1", 272, 278)], top=30)
    # Portfolio Manager: assets 7 (separate scheme, not aggregated with Certified)
    words += _bc_line([("Energy", 50, 80), ("Star", 84, 104),
                       ("Portfolio", 108, 150), ("Manager", 154, 200),
                       ("1712332", 230, 262), ("42.36", 244, 266),
                       ("7", 272, 278)], top=40)
    recs, last_pt = interpret_bc_geom("BC2", _FakePage(words))
    got = {(r.row_label, r.value_raw) for r in recs}
    assert got == {("Energy Star Certified", "4"),       # 3 + 1
                   ("Energy Star Portfolio Manager", "7")}
    assert all(r.col_label == "Number of Assets" for r in recs)
    assert all(r.property_type == "Office | United States" for r in recs)
    assert last_pt == "Office | United States"


def test_interpret_bc_geom_carries_property_type_across_pages():
    # A continuation page has no property-type header — its leading scheme rows
    # must be attributed to the seed_pt carried from the previous page (the
    # Mid-Rise Office LEED ID+C rows that split onto the next page).
    words = []
    words += _bc_line([("Number", 200, 230), ("of", 232, 240),
                       ("assets", 242, 280)], top=10)
    words += _bc_line([("LEED/Interior", 50, 130), ("Design", 134, 160),
                       ("18937", 230, 262), ("1", 272, 278)], top=20)
    recs, last_pt = interpret_bc_geom(
        "BC1.1", _FakePage(words),
        seed_pt="Office: Corporate: Mid-Rise Office | United States")
    assert len(recs) == 1
    assert recs[0].property_type == "Office: Corporate: Mid-Rise Office | United States"
    assert recs[0].value_raw == "1"


def test_is_floor_area_page_matches_energy_section_only():
    # Genuine EN1 energy 'Floor Areas' page: the zone tree with a single
    # 'Floor Area (sq. ft.)' column.
    genuine = ("floor areas floor area (sq. ft.) whole building "
               "common areas shared services tenant space")
    assert _is_floor_area_page(genuine)
    # The FIRST floor-area page also carries the 'Energy Consumption' section
    # intro — it must still match (regression: Healthcare/Hotel were dropped
    # because a 'consumption'-based exclusion rejected this page).
    assert _is_floor_area_page("energy consumption " + genuine)
    # GHG emissions page whose note says "Maximum Floor Areas ... in emissions"
    # — not the floor-area section (no zone tree).
    assert not _is_floor_area_page(
        "total scope 1&2 ghg emissions 162.54 ... maximum floor areas and "
        "like-for-like changes (%) in emissions. sq. ft.")
    # A consumption/emission MATRIX page repeats the zone labels but under the
    # Absolute + Like-for-Like column headers — must be excluded.
    assert not _is_floor_area_page(
        "absolute like-for-like 2024 consumption floor area covered (sq. ft.) "
        "whole building shared services tenant space")


def test_interpret_r1_skips_total_and_maps_columns():
    rows = [
        ["Property Type", "Country", "Assets", "Floor Area sq. ft.", "% GAV"],
        ["Hotel", "United States", "1", "600", "60"],
        ["Office: Corporate: Low-Rise Office", "United States", "4", "400", "40"],
        ["Total", "", "5", "1000", "100"],
    ]
    recs = interpret_r1(rows)
    hotel = {r.col_label: r.value_num for r in recs
             if r.property_type == "Hotel | United States"}
    assert hotel["Number of Assets"] == 1.0
    assert hotel["Floor Area (ft²)"] == 600.0
    assert hotel["% of GAV"] == 60.0
    assert not [r for r in recs if r.property_type.startswith("Total")]


def test_interpret_ra2_keyed_by_topic():
    lines = ["Energy 28 37.661", "Water 28 40.0858", "Waste 27 35.2677"]
    recs = interpret_ra2(lines)
    energy = [r for r in recs if r.row_label == "Energy"][0]
    assert energy.col_label == "Number of Assets"
    assert energy.value_num == 28.0
    assert energy.property_type == ""


def test_interpret_bc_rating_and_assets_ignoring_area():
    lines = ["Energy Star Portfolio Manager 68764.782 100 1 100"]
    recs = interpret_bc("BC2", "Hotel | United States", lines)
    assert len(recs) == 1
    r = recs[0]
    assert r.row_label == "Energy Star Portfolio Manager"
    assert r.col_label == "Number of Assets"
    assert r.value_num == 1.0  # the integer asset count, not the area
