from gresb_diff.models import Difference
from gresb_diff.reconcile import (
    column_for,
    reconcile_one,
    reconcile_report,
)


class _FakeAsset:
    """Stand-in for AssetData: returns a fixed pool for any column lookup."""
    def __init__(self, pool):
        self.pool = pool

    def column(self, sheet, code, year, ptcode, scale):
        return dict(self.pool)


def _diff(cid, pdf, docx, pt="Residential: Multi-Family: Low-Rise Multi-Family | United States"):
    return Difference("Energy", pt, cid, "pdf", pdf, "docx", docx, "value_mismatch")


def test_column_for_maps_zone_fuel_scope():
    assert column_for("EN1", "COMMON", "FUEL", "abs") == ("Energy", "en_abs_lc_bcf", 0.001)
    assert column_for("EN1", "COMMON", "FUEL", "cov") == ("Energy", "en_cov_lc_bcf", 1.0)
    assert column_for("EN1", "EXT_TENANT", "ELECTRIC", "abs") == ("Energy", "en_abs_tc_oe", 0.001)
    assert column_for("WT1", "WB_LANDLORD", "WATER", "abs") == ("Water", "wat_abs_w", 1.0)
    assert column_for("WT1", "COMMON", "WATER", "abs") == ("Water", "wat_abs_lc_bc", 1.0)
    assert column_for("GH1", "WB", "SCOPE_2", "abs") == ("GHG", "ghg_abs_s2_lb_w", 1.0)
    assert column_for("GH1", "EXT", "SCOPE_3", "abs") == ("GHG", "ghg_abs_s3_o", 1.0)


def test_word_dropped_identifies_the_asset():
    # pool sums to 1284.57; GRESB LFL keeps all, Word drops 'Brigham' (941.24-343.33).
    pool = {"Brigham": 941.24, "Other A": 200.0, "Other B": 143.33}
    # Word total = pool - Brigham contribution to the gap; gap = 941.24 - 343.33 ... here
    # model it directly: GRESB 1284.57, Word 343.33 -> gap 941.24 == Brigham.
    r = reconcile_one(_FakeAsset(pool), _diff("EN1.COMMON|FUEL.L4L.prior", "1284.57", "343.33"))
    assert r["category"] == "word_dropped"
    assert r["assets"] == ["Brigham"]


def test_negatives_flagged_first():
    pool = {"Neg Asset": -88.19, "Pos": 50.0}
    r = reconcile_one(_FakeAsset(pool), _diff("EN1.EXT_LANDLORD|ELECTRIC.L4L.prior", "0", "-88.19"))
    assert r["category"] == "negatives"
    assert r["assets"] == ["Neg Asset"]


def test_gresb_adjustment_when_gresb_exceeds_asset_total():
    # GRESB 98301.63 is above the asset-data total (94989.29) -> not an asset drop.
    pool = {"A": 50000.0, "B": 44989.29}
    r = reconcile_one(_FakeAsset(pool), _diff("WT1.WB_LANDLORD|WATER.L4L.prior", "98301.63", "94989.29"))
    assert r["category"] == "gresb_adjustment"
    assert r["assets"] == []


def test_out_of_scope_returns_none():
    assert reconcile_one(_FakeAsset({}), _diff("WS1.WS_DIVERTED.ABS.prior", "1", "2")) is None
    assert reconcile_one(_FakeAsset({}), _diff("EN1FA.FA_SHARED", "1", "2")) is None


def test_reconcile_report_groups_and_labels():
    pool = {"Brigham": 941.24, "Other A": 200.0, "Other B": 143.33}
    recs = [reconcile_one(_FakeAsset(pool),
                          _diff("EN1.COMMON|FUEL.L4L.prior", "1284.57", "343.33"))]
    md = reconcile_report(recs)
    assert "EN1 Energy - Residential" in md
    assert "Common Areas Fuel" in md           # row bullet
    assert "2024 — Word doc dropped from like-for-like: Brigham" in md  # per-metric


def test_reconcile_report_splits_mixed_causes_per_metric():
    base = {"question": "EN1", "section": "Energy",
            "property_type": "Office: Corporate: High-Rise Office | United States",
            "row_label": "Tenant Space (Landlord) Electric"}
    recs = [
        {**base, "metric": "prior", "category": "negatives", "assets": ["One Lakeside"]},
        {**base, "metric": "reporting", "category": "negatives", "assets": ["One Lakeside"]},
        {**base, "metric": "fa_covered", "category": "word_added", "assets": ["One Lakeside"]},
    ]
    md = reconcile_report(recs)
    # 2024 + 2025 share a cause and are combined on one sub-line:
    assert "2024, 2025 — Negative asset value" in md
    # Floor Area Covered is its own sub-line with its own cause:
    assert "Floor Area Covered — Word doc included" in md
