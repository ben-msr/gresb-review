from gresb_diff.canonical import (
    canonical_bc_scheme,
    canonical_floor_area,
    canonical_renewable,
    canonical_row,
    col_metric,
    normalize_pt,
)


def test_canonical_renewable_pairs_docx_and_pdf():
    for docx_label, pdf_label, key in [
        ("Generated On-site and Consumed by Landlord",
         "Generated and consumed by landlord", "RE_ON_CONSUMED_LL"),
        ("Generated On-site and Exported by Landlord",
         "Generated and exported by landlord", "RE_ON_EXPORTED_LL"),
        ("Generated On-site by Third Party or Tenant",
         "Generated and consumed by third-party (or tenant)", "RE_ON_TPT"),
        ("Generated Off-site and Purchased by Landlord",
         "Procured by Landlord", "RE_OFF_LL"),
        ("Generated Off-site and Purchased by Tenant",
         "Procured by Tenant", "RE_OFF_TENANT"),
    ]:
        d, p = canonical_renewable(docx_label), canonical_renewable(pdf_label)
        assert d == key == p, f"{docx_label!r}({d}) / {pdf_label!r}({p}) != {key}"
    # Sub-total / total rows have no canonical key.
    assert canonical_renewable("On-site - Sub-total") is None
    assert canonical_renewable("Off-site - Sub-total") is None
    assert canonical_renewable("Renewable Energy - Total") is None


def test_canonical_bc_scheme_pairs_docx_and_pdf_vocab():
    # docx family name and PDF per-level name canonicalise to the same key.
    for docx_label, pdf_label, key in [
        ("LEED Building Design and Construction",
         "LEED/Building Design and Construction (BD+C) / Gold", "LEED|BDC"),
        ("LEED Interior Design and Construction",
         "LEED/Interior Design and Construction (ID+C) / Silver", "LEED|IDC"),
        ("LEED Core & Shell", "LEED/Core & Shell / Gold", "LEED|CS"),
        ("LEED for Homes", "LEED/for Homes / Platinum", "LEED|HOMES"),
        ("LEED Building Operations and Maintenance",
         "LEED/Building Operations and Maintenance (O+M) / Certified", "LEED|OM"),
        ("Fitwel (Design and Construction)",
         "Fitwel/Fitwel - Design & Construction / Stars", "FITWEL|DC"),
        ("WELL Core and Shell",
         "WELL Building Standard/Core and Shell / Gold", "WELL|CS"),
        ("WELL Health-Safety Rating", "WELL/Health-Safety Rating / Pass", "WELL|HS"),
        ("BOMA 360", "BOMA/360", "BOMA|360"),
    ]:
        d, p = canonical_bc_scheme(docx_label), canonical_bc_scheme(pdf_label)
        assert d == key == p, f"{docx_label!r}({d}) / {pdf_label!r}({p}) != {key}"


def test_canonical_bc_scheme_distinguishes_families_and_programs():
    # WELL Core & Shell must not collide with LEED Core & Shell.
    assert canonical_bc_scheme("WELL Core and Shell") != \
        canonical_bc_scheme("LEED Core & Shell")
    # Fitwel D&C (no "building") is distinct from LEED Building Design & Constr.
    assert canonical_bc_scheme("Fitwel (Design and Construction)") == "FITWEL|DC"
    assert canonical_bc_scheme("LEED Building Design and Construction") == "LEED|BDC"
    assert canonical_bc_scheme("Some Unknown Cert") is None


def test_floor_area_zone_pairs():
    # docx label vs PDF label must canonicalise to the same floor-area zone.
    for docx_label, pdf_label in [
        ("Whole Building: Landlord Controlled", "Whole Building | Landlord Controlled"),
        ("Whole Building: Tenant Controlled", "Whole Building | Tenant Controlled"),
        ("Common Area", "Common Areas"),
        ("Shared Services", "Shared Services"),
        ("Tenant Space: Landlord Controlled", "Tenant Space | Landlord Controlled"),
        ("Tenant Space: Tenant Controlled", "Tenant Space | Tenant Controlled"),
    ]:
        d, p = canonical_floor_area(docx_label), canonical_floor_area(pdf_label)
        assert d is not None and d == p, f"{docx_label!r}({d}) != {pdf_label!r}({p})"


def _pair(question, docx_label, pdf_label):
    """Both labels must canonicalise to the same non-None key."""
    d = canonical_row(question, "docx", docx_label)
    p = canonical_row(question, "pdf", pdf_label)
    assert d is not None and d == p, f"{docx_label!r} ({d}) != {pdf_label!r} ({p})"


def test_normalize_pt_ignores_parentheses_and_case():
    assert normalize_pt("Other: Parking (Indoors) | United States") == \
        normalize_pt("Other: Parking Indoors | United States")


def test_en1_zone_fuel_pairs():
    _pair("EN1", "Whole Site: Indirect Fuel",
          "Whole Building | Tenant Controlled | Fuels")
    _pair("EN1", "Whole Site Electric",
          "Whole Building | Landlord Controlled | Electricity")
    _pair("EN1", "Common Area Electric",
          "Base Common Building Areas - | Landlord Controlled | Electricity")
    _pair("EN1", "Shared Services District",
          "Base Shared Building Services - | Landlord Controlled | District Heating & Cooling")
    _pair("EN1", "Tenant Purchased District",
          "Tenant Spaces | Tenant Controlled | District Heating & Cooling")
    _pair("EN1", "Landlord Purchased Fuel",
          "Tenant Spaces | Landlord Controlled | Fuels")
    _pair("EN1", "Indirect Exterior Electric",
          "Outdoor / Exterior areas / Parking | Tenant Controlled | Electricity")
    _pair("EN1", "Direct Exterior Electric",
          "Outdoor / Exterior areas / Parking | Landlord Controlled | Electricity")


def test_en1_subtotal_and_floorarea_rows_are_unmapped():
    assert canonical_row("EN1", "docx", "Whole Site Energy") is None
    assert canonical_row("EN1", "docx", "Whole Building: Tenant Controlled") is None
    assert canonical_row("EN1", "docx", "Generated On-site by Third Party or Tenant") is None


def test_gh1_scope_pairs_and_market_based_ignored():
    _pair("GH1", "Scope 1", "Whole Building | Scope 1")
    _pair("GH1", "Scope 3", "Whole Building | Scope 3")
    _pair("GH1", "Scope 2", "Whole Building | Scope 2 | Location Based")
    _pair("GH1", "Scope 2 Exterior",
          "Outdoor / Exterior areas / Parking | Scope 2 | Location Based")
    assert canonical_row(
        "GH1", "pdf",
        "Whole Building | Scope 2 | Market Based (optional) - - -") is None


def test_wt1_zone_pairs_water():
    _pair("WT1", "Whole Site: Indirect Water", "Whole Building | Tenant Controlled")
    _pair("WT1", "Tenant Purchased Water", "Tenant Spaces | Tenant Controlled")


def test_ws1_tonnes_and_route_pairs():
    # Tonnes: managed = Landlord-controlled; indirect = Tenant-controlled.
    _pair("WS1", "Hazardous Waste (MT)", "Managed Hazardous")
    _pair("WS1", "Non-hazardous Waste (MT)", "Managed Non-hazardous")
    _pair("WS1", "Indirectly Managed Asset Hazardous Waste (MT)", "Indirect Hazardous")
    _pair("WS1", "Indirectly Managed Asset Non-Hazardous Waste (MT)",
          "Indirect Non-hazardous")
    # Disposal routes.
    _pair("WS1", "Landfill (Disposal Route % Share)", "Landfill")
    _pair("WS1", "Recycling (Disposal Route % Share)", "Recycling")
    _pair("WS1", "Total Diverted (Disposal Route % Share)", "Diverted (Total)")
    _pair("WS1", "Other Disposal Route (Disposal Route % Share)", "Other / Unknown")


def test_ws1_unmapped_rows_return_none():
    # docx "Other Diverted" / portfolio shares and PDF "Reuse" have no counterpart
    assert canonical_row("WS1", "docx", "Other Diverted (Disposal Route % Share)") is None
    assert canonical_row("WS1", "docx", "Share of Managed Portfolio (%)") is None
    assert canonical_row("WS1", "pdf", "Reuse") is None


def test_col_metric_groups_and_fields():
    # Absolute usage (the original behaviour).
    assert col_metric("Absolute | Prior Year Usage (MWh)") == "ABS.prior"
    assert col_metric("Absolute | 2025 Consumption (MWh)") == "ABS.reporting"
    # Like-for-Like usage is now compared, not ignored.
    assert col_metric("Like-for-Like | Prior Year Usage (MWh)") == "L4L.prior"
    assert col_metric("Like-for-Like | Reporting Year Usage (MWh)") == "L4L.reporting"
    # Coverage / floor-area columns, both vocabularies.
    assert col_metric("Absolute | Data Coverage (ft²)") == "ABS.fa_covered"
    assert col_metric("Like-for-Like | Floor Area Covered (sq. ft.)") == "L4L.fa_covered"
    assert col_metric("Absolute | Max Coverage (ft²)") == "ABS.fa_max"
    assert col_metric("Absolute | Maximum Floor Area (sq. ft.)") == "ABS.fa_max"
    # Non-value columns map to None.
    assert col_metric("Prior Year (MWh) | 0") is None
