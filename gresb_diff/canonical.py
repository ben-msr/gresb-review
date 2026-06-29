"""Canonical-identity alignment for the matrix sections (EN1/GH1/WT1).

The docx and PDF describe the same matrix rows with different vocabularies
(docx: "Whole Site: Indirect Fuel"; PDF: "Whole Building | Tenant Controlled |
Fuels"). Rather than hand-list every pairing per fund, we normalise BOTH sides
to a shared canonical key (zone × fuel/scope) and compare every row by that key.
The row vocabularies are stable across funds, so this transfers without
re-calibration and — unlike value-anchored pairing — compares rows whose values
*differ*, which is exactly what catches missed mismatches.

WS1 is intentionally unsupported: the GRESB PDF exposes only a single aggregate
"Total waste generation" row, so the docx's detailed waste breakdown has no PDF
counterpart to compare against.
"""
from __future__ import annotations

import re

# --- Property-type normalisation -------------------------------------------
# Align labels that differ only by formatting, e.g. docx "Other: Parking
# Indoors" vs PDF "Other: Parking (Indoors)".

def normalize_pt(pt: str) -> str:
    cleaned = pt.replace("(", " ").replace(")", " ")
    return " ".join(cleaned.split()).casefold()


# --- EN1 / WT1 zone mapping --------------------------------------------------
# docx row-label prefix -> canonical zone
_DOCX_ZONE_PREFIXES = [
    ("whole site: indirect", "WB_TENANT"),
    ("whole site", "WB_LANDLORD"),
    ("common area", "COMMON"),
    ("shared services", "SHARED"),
    ("shared area", "SHARED"),
    ("landlord purchased", "TS_LANDLORD"),
    ("tenant purchased", "TS_TENANT"),
    ("indirect exterior", "EXT_TENANT"),
    ("direct exterior", "EXT_LANDLORD"),
    ("landlord controlled: exterior", "EXT_LANDLORD"),
]


def _docx_zone(label: str):
    low = label.strip().lower()
    for prefix, zone in _DOCX_ZONE_PREFIXES:
        if low.startswith(prefix):
            return zone
    return None


def _pdf_zone(group: str, control: str):
    g, c = group.strip().lower(), control.strip().lower()
    landlord, tenant = "landlord" in c, "tenant" in c
    if g.startswith("whole building"):
        return "WB_TENANT" if tenant else "WB_LANDLORD" if landlord else None
    if g.startswith("base common"):
        return "COMMON"
    if g.startswith("base shared"):
        return "SHARED"
    if g.startswith("tenant spaces"):
        return "TS_LANDLORD" if landlord else "TS_TENANT" if tenant else None
    if g.startswith("outdoor"):
        return "EXT_LANDLORD" if landlord else "EXT_TENANT" if tenant else None
    return None


def _fuel(label: str):
    low = label.lower()
    if "district" in low:
        return "DISTRICT"
    if "electric" in low:
        return "ELECTRIC"
    if "fuel" in low:
        return "FUEL"
    return None


_SCOPE_RE = re.compile(r"scope\s*([123])", re.I)


def canonical_row(question: str, source: str, label: str):
    """Return a canonical key string shared by the docx and PDF labels of the
    same logical row, or None if the row has no cross-document counterpart
    (subtotals, floor-area-type rows, renewable rows, WS1, optional Market-Based
    GHG rows, EV-charging, etc.)."""
    label = label.strip()
    low = label.lower()

    if question in ("EN1", "WT1"):
        if source == "docx":
            zone = _docx_zone(label)
            fuel = _fuel(label) if question == "EN1" else "WATER"
        else:  # pdf "group | control [| fuel]"
            parts = [p.strip() for p in label.split("|")]
            if len(parts) < 2:
                return None
            zone = _pdf_zone(parts[0], parts[1])
            fuel = _fuel(parts[2]) if (question == "EN1" and len(parts) >= 3) \
                else "WATER"
        if zone and fuel:
            return f"{zone}|{fuel}"
        return None

    if question == "GH1":
        if "market based" in low:   # optional, usually N/A — not compared
            return None
        m = _SCOPE_RE.search(label)
        if not m:
            return None
        scope = m.group(1)
        if source == "docx":
            zone = "EXT" if "exterior" in low else "WB"
        else:
            parts = [p.strip().lower() for p in label.split("|")]
            head = parts[0] if parts else ""
            zone = "EXT" if head.startswith("outdoor") else \
                "WB" if head.startswith("whole building") else None
        if zone:
            return f"{zone}|SCOPE_{scope}"
        return None

    if question == "WS1":
        return _ws1_canonical(source, low)

    return None  # anything else: unsupported


# WS1 (Waste): the PDF splits waste into two tables (tonnes by Landlord/Tenant
# control, and proportion by disposal route); the docx combines them. Map both
# sides to shared keys. Rows with no clean counterpart (docx "Other Diverted",
# "Share of (Indirectly) Managed Portfolio"; PDF "Reuse") return None.
def _ws1_canonical(source: str, low: str):
    if source == "docx":
        if low.startswith("indirectly managed asset non-hazardous"):
            return "WS_NONHAZ_INDIRECT"
        if low.startswith("indirectly managed asset hazardous"):
            return "WS_HAZ_INDIRECT"
        if low.startswith("non-hazardous waste"):
            return "WS_NONHAZ_MANAGED"
        if low.startswith("hazardous waste"):
            return "WS_HAZ_MANAGED"
        if "landfill" in low:
            return "WS_LANDFILL"
        if "incineration" in low:
            return "WS_INCINERATION"
        if "recycling" in low:
            return "WS_RECYCLING"
        if "waste to energy" in low:
            return "WS_WTE"
        if "total diverted" in low:
            return "WS_DIVERTED"
        if "other disposal route" in low:
            return "WS_OTHER"
        return None
    # pdf (row labels emitted by interpret_ws1)
    if low.startswith("managed non-hazardous"):
        return "WS_NONHAZ_MANAGED"
    if low.startswith("managed hazardous"):
        return "WS_HAZ_MANAGED"
    if low.startswith("indirect non-hazardous"):
        return "WS_NONHAZ_INDIRECT"
    if low.startswith("indirect hazardous"):
        return "WS_HAZ_INDIRECT"
    if low.startswith("landfill"):
        return "WS_LANDFILL"
    if low.startswith("incineration"):
        return "WS_INCINERATION"
    if low.startswith("recycling"):
        return "WS_RECYCLING"
    if low.startswith("waste to energy"):
        return "WS_WTE"
    if low.startswith("diverted"):
        return "WS_DIVERTED"
    if low.startswith("other"):
        return "WS_OTHER"
    return None  # PDF "Reuse" has no docx counterpart


def canonical_floor_area(label: str):
    """Map an EN1 'Floor Area by Type' row (docx or PDF) to a shared zone key.
    docx: "Whole Building: Landlord Controlled", "Common Area", "Shared
    Services", "Tenant Space: Tenant Controlled". PDF: "Whole Building |
    Landlord Controlled", "Common Areas", "Shared Services", "Tenant Space |
    Tenant Controlled"."""
    low = label.lower()
    if "whole building" in low:
        if "landlord" in low:
            return "FA_WB_LANDLORD"
        if "tenant" in low:
            return "FA_WB_TENANT"
        return None
    if "common area" in low:
        return "FA_COMMON"
    if "shared" in low:
        return "FA_SHARED"
    if "tenant space" in low:
        if "landlord" in low:
            return "FA_TS_LANDLORD"
        if "tenant" in low:
            return "FA_TS_TENANT"
    return None


def canonical_renewable(label: str):
    """Canonical key for an EN1 renewable-energy row, shared by the docx and PDF
    vocabularies (1:1):
      docx "Generated On-site and Consumed by Landlord"  / PDF "Generated and
        consumed by landlord"                              -> RE_ON_CONSUMED_LL
      docx "... Exported by Landlord" / PDF "... exported by landlord"
                                                           -> RE_ON_EXPORTED_LL
      docx "... by Third Party or Tenant" / PDF "... consumed by third-party
        (or tenant)"                                       -> RE_ON_TPT
      docx "... Off-site and Purchased by Landlord" / PDF "Procured by Landlord"
                                                           -> RE_OFF_LL
      docx "... Off-site and Purchased by Tenant" / PDF "Procured by Tenant"
                                                           -> RE_OFF_TENANT
    Sub-total / total rows return None. Only applied to renewable (EN1RE) rows,
    so consumption labels like "Tenant Purchased Electric" are never seen here."""
    low = label.lower()
    if "third" in low:
        return "RE_ON_TPT"
    if "exported" in low:
        return "RE_ON_EXPORTED_LL"
    if "procured" in low or "purchased" in low or "off-site" in low:
        if "tenant" in low:
            return "RE_OFF_TENANT"
        if "landlord" in low:
            return "RE_OFF_LL"
        return None
    if "consumed" in low and "landlord" in low:
        return "RE_ON_CONSUMED_LL"
    return None


def canonical_bc_scheme(label: str):
    """Canonical "PROGRAM|FAMILY" key for a BC1.1/BC1.2 certification scheme,
    shared by the docx family-level names and the PDF per-level names.

    The docx names a scheme by family ("LEED Building Design and Construction");
    the PDF splits it per certification level ("LEED/Building Design and
    Construction (BD+C) / Gold", "... / Silver"). Mapping both to PROGRAM|FAMILY
    lets the per-level PDF rows aggregate to the single docx row and lets a
    scheme present on only one side (e.g. "LEED Core & Shell", in the docx but
    absent from the PDF) be detected. Returns None if unrecognised."""
    low = label.lower()
    if "fitwel" in low:
        prog = "FITWEL"
    elif "boma" in low:
        prog = "BOMA"
    elif "leed" in low:
        prog = "LEED"
    elif "well" in low:
        prog = "WELL"
    else:
        prog = None
    if "core" in low and "shell" in low:
        fam = "CS"
    elif "interior" in low or "id+c" in low:
        fam = "IDC"
    elif ("building" in low and "design" in low) or "bd+c" in low:
        fam = "BDC"
    elif ("operations" in low and "maintenance" in low) or "o+m" in low:
        fam = "OM"
    elif "health" in low and "safety" in low:
        fam = "HS"
    elif "homes" in low:
        fam = "HOMES"
    elif "360" in low:
        fam = "360"
    elif "design" in low and "construction" in low:  # Fitwel D&C (no building)
        fam = "DC"
    else:
        fam = None
    return f"{prog}|{fam}" if prog and fam else None


def col_metric(col_label: str):
    """Map a matrix value column to a canonical metric key shared by docx and
    PDF, or None if the column is not a comparable value column.

    The key is "<group>.<field>" where group is ABS (Absolute) or L4L
    (Like-for-Like), and field is one of:
      prior      - prior-year usage/emissions  (docx "Prior Year", PDF "2024")
      reporting  - reporting-year usage/emissions (docx "Reporting Year", PDF "2025")
      fa_covered - floor area covered (docx "Data Coverage", PDF "Floor Area Covered")
      fa_max     - maximum floor area (docx "Max Coverage", PDF "Maximum Floor Area")

    Comparing all four fields in BOTH groups catches Like-for-Like and
    floor-area-coverage discrepancies, not just Absolute usage.
    """
    low = col_label.lower()
    if low.startswith("absolute"):
        group = "ABS"
    elif low.startswith("like-for-like"):
        group = "L4L"
    else:
        return None
    if "prior year" in low or "2024" in low:
        field = "prior"
    elif "reporting year" in low or "2025" in low:
        field = "reporting"
    elif "max" in low:
        field = "fa_max"
    elif "coverage" in low or "covered" in low:
        field = "fa_covered"
    else:
        return None
    return f"{group}.{field}"


# Absolute usage columns define whether a matrix row exists at all (both
# documents always populate them); a one-sided occurrence here means a genuinely
# missing row. Other columns (Like-for-Like, coverage) are compared for value
# only when present on both sides — the GRESB PDF omits them entirely for water
# and waste, so a one-sided occurrence there is structural, not a real mismatch.
ROW_PRESENCE_METRICS = ("ABS.prior", "ABS.reporting")
