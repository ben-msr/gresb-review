"""Parse the GRESB portal PDF export into FieldRecords.

Pure interpreters operate on already-extracted structures so they are unit
tested without a real PDF. parse_pdf() wires pdfplumber extraction to them and
is validated by the calibration task against the real (local, uncommitted) file.
"""
from __future__ import annotations

import io
import logging
import re

import pdfplumber

from .models import FieldRecord, parse_value

# pdfminer (under pdfplumber) logs benign warnings such as "Could get FontBBox
# from font descriptor because None cannot be parsed as 4 floats" for PDFs with
# incomplete font metrics. They do not affect extraction — silence the noise.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
# RA2 topic line: the topic word must be immediately followed by a number, so
# efficiency-measure rows like "Waste stream audit 3 ..." (RA5) do NOT match.
_TOPIC = re.compile(r"\s*(Energy|Water|Waste)\s+(-?\d[\d,]*\.?\d*.*)")


def _rec(section, question, property_type, row_label, col_label, raw):
    vr, vn = parse_value(raw)
    return FieldRecord(section, question, property_type, row_label,
                       col_label, vr, vn, "pdf")


def _norm_pt(ptype: str, country: str) -> str:
    """Join property type and country, collapsing internal whitespace/newlines.
    Hyphens at end-of-line (PDF line continuation) are preserved without extra space.
    """
    # Collapse hyphen+newline line continuations before splitting on whitespace.
    ptype = re.sub(r"-\s*\n\s*", "-", ptype)
    country = re.sub(r"-\s*\n\s*", "-", country)
    p = " ".join(ptype.split())
    c = " ".join(country.split())
    return f"{p} | {c}".strip(" |") if c else p.strip()


def _extract_pt_from_cell(cell: str) -> str:
    """Return the property-type string from a cell that may embed it as the
    last line containing ' | '.  Normalises whitespace/line-continuations."""
    lines = cell.split("\n")
    for ln in reversed(lines):
        ln = ln.strip()
        if " | " in ln:
            return " ".join(ln.split())
    return ""


def _make_row_label(group: str, control: str, fuel: str) -> str:
    """Build a row label, collapsing empty segments to avoid double-pipes."""
    parts = [p.strip() for p in [group, control, fuel] if p.strip()]
    return " | ".join(parts)


def interpret_r1(rows: list[list[str]]) -> list[FieldRecord]:
    """Extract property-type rows from the R1 table.

    The PDF R1 table has 5 columns: property type, country, assets, floor area,
    % GAV.  Header/note/total rows are identified by col[1] (country) and col[2]
    (assets): a valid data row has a numeric assets value and a non-blank country.
    This avoids fragile keyword matching against boilerplate text.
    """
    out: list[FieldRecord] = []
    for row in rows:
        if not row:
            continue
        padded = [(c or "") for c in (row + [""] * 5)[:5]]
        ptype, country, assets, area, gav = padded
        # Valid data row: assets col is numeric, country is present
        assets_stripped = assets.strip()
        country_stripped = country.strip()
        if not assets_stripped or not _NUM.match(assets_stripped):
            continue
        if not country_stripped:
            continue
        property_type = _norm_pt(ptype, country)
        if not property_type:
            continue
        out.append(_rec("Reporting Characteristics", "R1", property_type, "",
                        "Number of Assets", assets))
        out.append(_rec("Reporting Characteristics", "R1", property_type, "",
                        "Floor Area (ft²)", area))
        out.append(_rec("Reporting Characteristics", "R1", property_type, "",
                        "% of GAV", gav))
    return out


def interpret_ra2(lines: list[str]) -> list[FieldRecord]:
    out: list[FieldRecord] = []
    for line in lines:
        m = _TOPIC.match(line)
        if not m:
            continue
        topic, rest = m.group(1), m.group(2)
        nums = _NUM.findall(rest)
        if not nums:
            continue
        out.append(_rec("Risk Assessment", "RA2", "", topic,
                        "Number of Assets", nums[0]))
    return out


def interpret_bc(question: str, property_type: str,
                 lines: list[str]) -> list[FieldRecord]:
    """Legacy text-line BC interpreter retained for unit-test compatibility.

    Kept for the existing unit suite (test_pdf_clean_tables.py).  The real
    parse_pdf now calls interpret_bc_table (table-cell extraction) instead,
    which correctly handles multiple property types on one page and scheme
    names that contain digits.
    """
    out: list[FieldRecord] = []
    for line in lines:
        nums = list(_NUM.finditer(line))
        if not nums:
            continue
        scheme = line[: nums[0].start()].strip()
        if not scheme:
            continue
        values = [n.group(0) for n in nums]
        if len(values) < 3:
            continue
        assets = values[2]
        out.append(_rec("Building Certifications", question, property_type,
                        scheme, "Number of Assets", assets))
    return out


def interpret_bc_table(question: str, tbl: list[list[str]]) -> list[FieldRecord]:
    """Extract per-property-type BC records from a pdfplumber table.

    In the real GRESB PDF export, all BC data for all property types is merged
    into a single first column.  The structure per property type is:

      [description cell that ends with the PT header]  <- sets current_pt
      [column header row: "Energy Rating", "Number of assets", ...]  <- skip
      [data row: "<scheme> <area> <pct_covered> <assets> [<pct_gav>]
                  <NEXT_PT> | <country>"]  <- emit current_pt record, then update PT

    We scan every cell[0] in every row:
    - Extract any " | " line from the cell and use it as current_pt.
    - If the first line of the cell starts with a known scheme name followed by
      numbers, treat it as a data row and emit a record for current_pt.
    - Layout: <area> <pct_covered> <assets> [<pct_gav>]  -> assets = 3rd number.
    """
    out: list[FieldRecord] = []
    current_pt = ""

    for row in tbl:
        cells = [c or "" for c in row]
        first = (cells[0] or "").strip()
        if not first:
            continue

        lines_in_cell = first.split("\n")
        data_line = lines_in_cell[0].strip()

        # Collect any property-type update from any line in this cell.
        next_pt = None
        for ln in lines_in_cell:
            ln = ln.strip()
            if " | " in ln:
                # Make sure it looks like a PT (not a column header or footnote).
                if not any(kw in ln.lower() for kw in
                           ("energy rating", "floor area", "% of floor", "% gav")):
                    next_pt = " ".join(ln.split())

        # Column-header rows: first cell is "Energy Rating" exactly (case-insensitive).
        if data_line.lower() == "energy rating":
            if next_pt:
                current_pt = next_pt
            continue

        # Try to parse a data row: scheme name followed by numeric values.
        # The scheme name is text before the first digit on the first line.
        m = re.match(r"([A-Za-z][^\d\n]*?)\s+([-\d])", data_line)
        if m:
            scheme = m.group(1).strip()
            rest = data_line[m.start(2):]
            all_nums = _NUM.findall(rest)
            # Layout: area, %covered, assets, [%gav]  -> assets = 3rd number
            if len(all_nums) >= 3:
                assets_raw = all_nums[2]
            elif len(all_nums) >= 1:
                assets_raw = all_nums[-1]
            else:
                assets_raw = ""

            if current_pt and scheme and assets_raw:
                out.append(_rec("Building Certifications", question, current_pt,
                                scheme, "Number of Assets", assets_raw))
            # Update PT after emitting (next_pt applies to the NEXT record).
            if next_pt:
                current_pt = next_pt
            continue

        # Pure property-type-only cell (no data on first line).
        if next_pt:
            current_pt = next_pt

    return out


# Header tokens that mark a non-data (column-header / label) line on a BC page.
# NB: do NOT include "certified" — it appears in the data rows
# "Energy Star Certified - NN-NN Points", which must be read, not skipped.
_BC_HEADER_TOKENS = ("energy rating", "area covered", "number of", "% of",
                     "% gav", "scheme name", "level",
                     "floor area covered", "within property type")

# An energy rating split into point-band rows ("Energy Star Certified - 90-95
# Points") that the docx aggregates into one scheme ("Energy Star Certified").
_BC_POINT_BAND = re.compile(r"\s*-\s*[\d\-]+\s*points?$", re.I)


_BC_TOKENS = ("BC1.1", "BC1.2", "BC2")


def bc_question_segments(page, default_q):
    """Split a BC page into (question, top_lo, top_hi) vertical bands.

    A page can hold more than one BC question (e.g. BC1.2 stacked above BC2).
    Each band runs from one question heading down to the next, so the caller can
    parse each table under its own question with its own column anchor. Rows
    above the first heading belong to ``default_q`` — the question carried in
    from a previous page (a BC table can continue across a page break with no
    repeated heading). Adjacent same-question bands are merged.

    Returns a single full-page band ``[(default_q, -inf, inf)]`` when the page
    has no heading (a continuation page), preserving the prior behaviour."""
    groups: dict = {}
    for w in page.extract_words():
        groups.setdefault(round(w["top"]), []).append(w)
    headings = []  # (top, question)
    for top in sorted(groups):
        ws = sorted(groups[top], key=lambda w: w["x0"])
        tok = ws[0]["text"].strip() if ws else ""
        if tok in _BC_TOKENS:
            headings.append((float(top), tok))
    if not headings:
        return [(default_q, float("-inf"), float("inf"))]

    bands = []
    prev_top, prev_q = float("-inf"), default_q
    for htop, hq in headings:
        bands.append((prev_q, prev_top, htop))
        prev_top, prev_q = htop, hq
    bands.append((prev_q, prev_top, float("inf")))

    merged = []
    for q, lo, hi in bands:
        if merged and merged[-1][0] == q:
            merged[-1] = (q, merged[-1][1], hi)
        else:
            merged.append((q, lo, hi))
    return merged


def interpret_bc_geom(question: str, page, seed_pt: str = "", top_range=None):
    """Geometry-based BC extraction: read 'Number of Assets' by COLUMN POSITION.

    The text-order heuristic (assets = 3rd number on the line) misreads when a
    preceding column — e.g. '% of Floor Area covered' — is blank for a row.
    Here we anchor on the right edge of the 'Assets' header word and pick the
    numeric value in that column for each scheme row, so area / % covered / %
    GAV can never be mistaken for the asset count.

    The current property type carries across pages (``seed_pt``): a BC table can
    split over a page break, so the continuation rows on the next page have no
    repeated property-type header and would otherwise be dropped (e.g. Mid-Rise
    Office's LEED Interior Design and Construction rows on the following page).

    A page may carry more than one BC question (e.g. BC1.2 above BC2). The
    caller restricts each question to its own vertical band via ``top_range``
    (lo, hi) so each table gets its own assets-column anchor — without it a
    single page-level anchor from one table misreads the other's columns.

    Returns (records, last_property_type); records is None if the assets-column
    header is not found (caller falls back to the text-based parser)."""
    words = page.extract_words()
    if top_range is not None:
        lo, hi = top_range
        words = [w for w in words if lo <= w["top"] < hi]
    # Tolerant line grouping: header words ("Number of assets") and data values
    # can render ~1px apart, so exact round(top) would split them and the
    # header (and rows) would be missed on some pages.
    groups: list = []
    for w in sorted(words, key=lambda w: w["top"]):
        if groups and abs(w["top"] - groups[-1]["top"]) <= 3:
            groups[-1]["ws"].append(w)
        else:
            groups.append({"top": w["top"], "ws": [w]})
    line_lists = [sorted(g["ws"], key=lambda w: w["x0"]) for g in groups]

    # Anchor on the 'assets' word that is part of a 'Number of assets' header
    # line — NOT a stray 'assets' in a footnote (which sits in a different
    # column and would misdirect the column pick).
    assets_x1 = None
    for lws in line_lists:
        if "number of assets" in " ".join(w["text"] for w in lws).lower():
            for w in lws:
                if w["text"].strip().lower() == "assets":
                    assets_x1 = w["x1"]
            break
    if assets_x1 is None:
        # Wrapped column header: "Number of" on one line and "assets" directly
        # below it (same column), so the two never join into one line. Anchor on
        # the 'assets' word that has a 'Number' word just above it at the same x.
        numbers = [w for w in words if w["text"].strip().lower() == "number"]
        for w in words:
            if w["text"].strip().lower() != "assets":
                continue
            if any(0 < (w["top"] - n["top"]) <= 25 and abs(n["x0"] - w["x0"]) <= 30
                   for n in numbers):
                assets_x1 = w["x1"]
                break
    if assets_x1 is None:
        return None, seed_pt

    # Accumulate assets per (property type, scheme). Point-band rows of the same
    # scheme (e.g. "Energy Star Certified - 90-95 Points" + "... - 85-89 Points")
    # are summed into one scheme ("Energy Star Certified"), matching the docx,
    # which reports a single aggregated row per scheme.
    totals: dict = {}
    order: list = []
    current_pt = seed_pt
    for g in groups:
        lws = sorted(g["ws"], key=lambda w: w["x0"])
        top = g["top"]
        text = " ".join(w["text"] for w in lws).strip()
        low = text.lower()
        if " | " in text and not any(k in low for k in _BC_HEADER_TOKENS):
            pt = _extract_pt_from_cell(text)
            if pt:
                current_pt = pt
            continue
        if any(k in low for k in _BC_HEADER_TOKENS):
            continue
        nums = [w for w in lws if _is_number(w["text"])]
        if not nums or not current_pt:
            continue
        scheme = " ".join(w["text"] for w in lws
                          if not _is_number(w["text"])).strip()
        if not scheme:
            # Scheme name wraps around its own data row (label text on the line
            # above and below, only numbers on the middle line). Gather the
            # label fragments from the left columns within a tight window.
            left_bound = min((w["x0"] for w in nums), default=0.0) - 5.0
            frag = sorted((w for w in words
                           if not _is_number(w["text"]) and w["x0"] < left_bound
                           and abs(w["top"] - top) <= 12),
                          key=lambda w: (w["top"], w["x0"]))
            scheme = " ".join(w["text"] for w in frag).strip()
        if not scheme:
            continue
        scheme = _BC_POINT_BAND.sub("", scheme).strip()
        # Data values right-align to the column edge while the header text does
        # not, so the data 'assets' value can sit ~35px right of the 'assets'
        # header word; pick the numeric value nearest the assets column (closest
        # wins over %-covered / %-GAV).
        assets = nearest_value_to([(w["x1"], w["text"]) for w in nums], assets_x1)
        _, assets_num = parse_value(assets)
        if assets_num is None:
            continue
        key = (current_pt, scheme)
        if key not in totals:
            totals[key] = 0.0
            order.append(key)
        totals[key] += assets_num

    out: list[FieldRecord] = []
    for pt, scheme in order:
        total = totals[(pt, scheme)]
        raw = str(int(total)) if total == int(total) else str(total)
        out.append(_rec("Building Certifications", question, pt,
                        scheme, "Number of Assets", raw))
    return out, current_pt


def parse_bc_page(page, default_q, matrix_state):
    """Parse every BC question on one page, splitting it into per-question
    vertical bands (see ``bc_question_segments``) so each table is read under
    its own question and column anchor. ``matrix_state`` is the per-question
    carry-over dict (mutated to record the last property type).

    The legacy text-table fallback (for pages where geometry finds no assets
    header) runs ONLY for a single full-page band: on a multi-band page it would
    parse the WHOLE page and mis-file every row under the header-less band, so a
    header-less band on such a page correctly yields nothing."""
    out: list[FieldRecord] = []
    segments = bc_question_segments(page, default_q)
    for q, lo, hi in segments:
        state = matrix_state.get(q, {})
        geom, last_pt = interpret_bc_geom(
            q, page, seed_pt=state.get("pt", ""), top_range=(lo, hi))
        if geom is not None:
            out.extend(geom)
            matrix_state[q] = {"pt": last_pt or state.get("pt", "")}
        elif len(segments) == 1:  # whole page, no anchor: legacy text fallback
            for tbl in page.extract_tables():
                out.extend(interpret_bc_table(q, tbl))
    return out


# The 7 numeric columns of the EN1/WT1/GH1 consumption matrices, in order.
_MATRIX_COLS = [
    "Absolute | 2024 Consumption",
    "Absolute | 2025 Consumption",
    "Absolute | Floor Area Covered (sq. ft.)",
    "Absolute | Maximum Floor Area (sq. ft.)",
    "Like-for-Like | 2024 Consumption",
    "Like-for-Like | 2025 Consumption",
    "Like-for-Like | Floor Area Covered (sq. ft.)",
]

# Per-question unit suffix for Consumption columns.
_MATRIX_UNIT = {
    "EN1": " (MWh)",
    "GH1": " (tonnes)",
    "WT1": " (m3)",
    "WS1": " (tonnes)",
}

_MATRIX_SECTION = {"EN1": "Energy", "GH1": "GHG", "WT1": "Water", "WS1": "Waste"}


def _matrix_cols(question: str) -> list[str]:
    """Return the 7 column labels with the correct unit suffix for this question."""
    unit = _MATRIX_UNIT.get(question, "")
    return [
        col.replace("Consumption", f"Consumption{unit}") if "Consumption" in col else col
        for col in _MATRIX_COLS
    ]


def decode_rotated(text: str) -> str:
    """GRESB prints group/control labels rotated; pdfplumber returns them
    reversed by line and by character. Restore reading order."""
    lines = [ln for ln in text.split("\n") if ln.strip()]
    restored = [ln[::-1] for ln in reversed(lines)]
    return " ".join(restored).strip()


def _is_number(text: str) -> bool:
    try:
        float(text.replace(",", "").rstrip("%"))
        return True
    except (ValueError, AttributeError):
        return False


def bucket_by_anchor(words, anchors, tol: float = 25.0):
    """Assign right-aligned numeric words to columns by nearest right-edge (x1).

    The GRESB matrices right-align numbers under each column, and blank columns
    leave NO placeholder in the flattened text — so column identity must come
    from geometry, not text order. ``words`` is a list of ``(x1, text)``;
    returns one value per anchor (``""`` for an empty column).

    Each word is assigned to its nearest anchor within ``tol``; the first word
    to claim a column keeps it. Suited to the multi-column matrices, where the
    column anchors are well separated (~70px) and each holds one value. (For a
    single tightly-contested column — BC2 'Number of assets' — use
    nearest_value_to instead, which picks the closest of several candidates.)"""
    slots = [""] * len(anchors)
    for x1, text in words:
        best, best_d = None, tol
        for i, anchor in enumerate(anchors):
            d = abs(anchor - x1)
            if d <= best_d:
                best, best_d = i, d
        if best is not None and slots[best] == "":
            slots[best] = text
    return slots


def nearest_value_to(words, anchor, tol: float = 70.0):
    """Return the text of the word whose x1 is nearest ``anchor`` within ``tol``
    (or "" if none). Used for a single contested column (BC 'Number of assets'),
    where the data value right-aligns well past its header word and a '% covered'
    value also sits within range — the closest must win."""
    best, best_d = "", tol
    for x1, text in words:
        d = abs(anchor - x1)
        if d <= best_d:
            best, best_d = text, d
    return best


def _detect_anchors(numeric_words):
    """Derive the 7 column right-edge (x1) anchors from the richest data row on
    a matrix page. ``numeric_words`` is a list of ``(x1, top, text)``. Returns a
    sorted list of 7 x1 anchors, or None if no full 7-value row is present (the
    caller then reuses anchors carried from a previous page)."""
    by_top: dict[int, list[float]] = {}
    for x1, top, _text in numeric_words:
        by_top.setdefault(round(top), []).append(x1)
    for xs in by_top.values():
        if len(xs) == 7:
            return sorted(xs)
    return None


# WS1 disposal routes (PDF section 2). Longer/qualified names first so
# "diverted (total)" matches before "diverted" and "other / unknown" before
# "other".
_WS1_ROUTES = ("landfill", "incineration", "recycling", "reuse",
               "waste to energy", "diverted (total)", "diverted",
               "other / unknown", "other")


def interpret_ws1(page, seed_pt: str = ""):
    """Parse the WS1 waste section. The PDF splits waste into two tables per
    property type: (1) tonnes by Landlord/Tenant control (Hazardous /
    Non-hazardous, 2024 & 2025) and (2) proportion of waste by disposal route
    (%). The docx combines both. Emit FieldRecords with canonical-friendly row
    labels so canonical_row() can pair them with the docx rows.

    Returns (records, last_property_type) so the PT can carry across pages.
    """
    records = []
    current_pt = seed_pt
    all_words = page.extract_words()
    numeric_words = [(w["x1"], w["top"], w["text"]) for w in all_words
                     if _is_number(w["text"])]
    tonne_anchors = _detect_anchors(numeric_words)  # 7-col tonnes table if present

    # Control markers ("Landlord"/"Tenant") in the left label band — used to
    # recover a control label that WRAPS around its tonnes data row ("Landlord"
    # above, "Controlled" below), so the data row's own line carries no label.
    ctrl_markers = [(w["top"], w["text"].lower()) for w in all_words
                    if w["x0"] < 300 and w["text"].lower() in ("landlord", "tenant")]

    # Group words into lines with a small vertical tolerance: in the disposal-
    # route table the row label and its values render ~1px apart (e.g. "Landfill"
    # at top=128, its values at 129), so exact-top grouping would split them.
    line_groups: list = []
    for w in sorted(all_words, key=lambda w: w["top"]):
        if line_groups and abs(w["top"] - line_groups[-1]["top"]) <= 3:
            line_groups[-1]["ws"].append(w)
        else:
            line_groups.append({"top": w["top"], "ws": [w]})

    for grp in line_groups:
        lws = sorted(grp["ws"], key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in lws).strip()
        low = text.lower()
        nums = [w for w in lws if _is_number(w["text"])]
        label = " ".join(w["text"] for w in lws
                         if w["x0"] < 300 and not _is_number(w["text"])
                         ).strip().lower()

        if " | " in text and not any(k in low for k in (
                "hazardous", "disposal", "proportion", "data coverage",
                "absolute", "floor area")):
            pt = _extract_pt_from_cell(text)
            if pt:
                current_pt = pt
            continue
        if not current_pt or not nums:
            continue

        # --- Section 1: tonnes by control ---
        control = None
        if label.startswith("landlord controlled"):
            control = "Managed"
        elif label.startswith("tenant controlled"):
            control = "Indirect"
        elif tonne_anchors:
            # Wrapped control label straddling the data row: anchor on the
            # nearest control marker within a tight window (see interpret_wt1).
            near = [(abs(mt - grp["top"]), t) for mt, t in ctrl_markers
                    if abs(mt - grp["top"]) <= 12]
            if near:
                _, t = min(near)
                control = "Managed" if t == "landlord" else "Indirect"
        if control:
            if not tonne_anchors:
                continue
            slots = bucket_by_anchor([(w["x1"], w["text"]) for w in nums],
                                     tonne_anchors, tol=20.0)
            # anchors: haz2024, nonhaz2024, cov2024, haz2025, nonhaz2025, cov, wt
            for metric, haz, nonhaz in [("Prior Year Usage", slots[0], slots[1]),
                                        ("Reporting Year Usage", slots[3], slots[4])]:
                col = f"Absolute | {metric} (MT)"
                records.append(_rec("Waste", "WS1", current_pt,
                                    f"{control} Hazardous", col, haz or "0"))
                records.append(_rec("Waste", "WS1", current_pt,
                                    f"{control} Non-hazardous", col, nonhaz or "0"))
            continue

        # --- Section 2: proportion by disposal route ---
        # Each route row has 2 values (2024, 2025). Table indentation varies per
        # property type, so use relative order (leftmost=2024, rightmost=2025)
        # rather than fixed column x-bands.
        route = next((r for r in _WS1_ROUTES if label.startswith(r)), None)
        if route:
            by_x = sorted(nums, key=lambda w: w["x1"])
            prior = reporting = ""
            if len(by_x) >= 2:
                prior, reporting = by_x[0]["text"], by_x[-1]["text"]
            elif len(by_x) == 1:
                reporting = by_x[0]["text"]
            row = "Other / Unknown" if route.startswith("other") \
                else route.title()
            records.append(_rec("Waste", "WS1", current_pt, row,
                                "Absolute | Prior Year Usage (MT)", prior or "0"))
            records.append(_rec("Waste", "WS1", current_pt, row,
                                "Absolute | Reporting Year Usage (MT)",
                                reporting or "0"))
            continue

    return records, current_pt


# WT1 zone labels (horizontal, left column) -> canonical-recognised zone string.
_WT1_ZONE_KEYS = [
    ("whole building", "Whole Building"),
    ("common area", "Base Common Building Areas"),
    ("shared service", "Base Shared Building Services"),
    ("shared area", "Base Shared Building Services"),
    ("tenant spaces", "Tenant Spaces"),
    ("outdoor", "Outdoor / Exterior areas / Parking"),
]


def interpret_wt1(page, seed_pt: str = "", seed_anchors=None):
    """Parse the WT1 water matrix. Each zone (Whole Building, Base Common/Shared,
    Tenant Spaces, Outdoor) has Landlord/Tenant-Controlled rows, but the zone
    label is a horizontal label that can render ABOVE, BETWEEN, or BELOW its
    control rows. So assign each control row to the NEAREST zone label by
    vertical position (not the last-seen one), which fixes e.g. an Exterior
    value being attributed to Tenant Spaces. Values read by column geometry
    (Absolute 2024/2025).

    Column anchors carry across pages (``seed_anchors``): a sparse continuation
    page (e.g. one whose only table is a near-empty property type like Mixed
    use: Other) may have no row rich enough for ``_detect_anchors``, and without
    a carried fallback its rows would be silently dropped."""
    records = []
    all_words = page.extract_words()
    numeric_words = [(w["x1"], w["top"], w["text"]) for w in all_words
                     if _is_number(w["text"])]
    anchors = _detect_anchors(numeric_words) or seed_anchors

    groups = []
    for w in sorted(all_words, key=lambda w: w["top"]):
        if groups and abs(w["top"] - groups[-1]["top"]) <= 3:
            groups[-1]["ws"].append(w)
        else:
            groups.append({"top": w["top"], "ws": [w]})

    # Control markers ("Landlord"/"Tenant") in the control label band. Used to
    # recover a control label that WRAPS around its data row ("Landlord" on the
    # line above, "Controlled" on the line below), leaving the data row's own
    # line with no label text.
    ctrl_markers = [(w["top"], w["text"].lower()) for w in all_words
                    if 165 <= w["x0"] < 265
                    and w["text"].lower() in ("landlord", "tenant")]

    pt_headers = [(-1.0, seed_pt)] if seed_pt else []
    zone_labels = []   # (y, zone)
    ctrl_rows = []     # (y, control, nums)
    for g in groups:
        ws = sorted(g["ws"], key=lambda w: w["x0"])
        top = g["top"]
        full = " ".join(w["text"] for w in ws)
        low = full.lower()
        left = " ".join(w["text"] for w in ws if w["x0"] < 165).lower()
        if " | " in full and not any(k in low for k in (
                "controlled", "consumption", "absolute", "coverage",
                "(m3)", "floor area")):
            pt = _extract_pt_from_cell(full)
            if pt:
                pt_headers.append((top, pt))
            continue
        zone = next((z for k, z in _WT1_ZONE_KEYS if k in left), None)
        if zone:
            zone_labels.append((top, zone))
        ctrl_text = " ".join(w["text"] for w in ws
                             if 165 <= w["x0"] < 265 and not _is_number(w["text"])
                             ).lower()
        control = ("Landlord Controlled" if ctrl_text.startswith("landlord controlled")
                   else "Tenant Controlled" if ctrl_text.startswith("tenant controlled")
                   else None)
        nums = [w for w in ws if _is_number(w["text"])]
        if control is None and nums and anchors:
            # Wrapped control label: anchor on the nearest control marker within
            # a tight vertical window (rows are ~40px apart, so ±12 cannot reach
            # a neighbouring row, and a Sub-total/Total row — with no marker
            # within the window — stays unlabelled and is skipped).
            near = [(abs(mt - top), t) for mt, t in ctrl_markers
                    if abs(mt - top) <= 12]
            if near:
                _, t = min(near)
                control = ("Landlord Controlled" if t == "landlord"
                           else "Tenant Controlled")
        if control and nums and anchors:
            ctrl_rows.append((top, control, nums))

    def pt_for(y):
        cur = seed_pt
        for hy, p in pt_headers:
            if hy <= y:
                cur = p
        return cur

    for top, control, nums in ctrl_rows:
        if not zone_labels:
            continue
        zone = min(zone_labels, key=lambda zl: abs(zl[0] - top))[1]
        pt = pt_for(top)
        if not pt:
            continue
        slots = bucket_by_anchor([(w["x1"], w["text"]) for w in nums],
                                 anchors, tol=22.0)
        row = f"{zone} | {control}"
        # Same 7-column layout as EN1/GH1: Absolute 2024/2025/FloorAreaCovered/
        # MaxFloorArea, then Like-for-Like 2024/2025/FloorAreaCovered. Emit all
        # so Like-for-Like (and coverage) water mismatches are compared too —
        # not just Absolute (e.g. a Like-for-Like Exterior water discrepancy).
        for slot, col in (
            (0, "Absolute | Prior Year Usage (m3)"),
            (1, "Absolute | Reporting Year Usage (m3)"),
            (2, "Absolute | Floor Area Covered (sq. ft.)"),
            (3, "Absolute | Maximum Floor Area (sq. ft.)"),
            (4, "Like-for-Like | Prior Year Usage (m3)"),
            (5, "Like-for-Like | Reporting Year Usage (m3)"),
            (6, "Like-for-Like | Floor Area Covered (sq. ft.)"),
        ):
            records.append(_rec("Water", "WT1", pt, row, col,
                                slots[slot] if slot < len(slots) and slots[slot]
                                else "0"))

    last_pt = pt_headers[-1][1] if pt_headers else seed_pt
    return records, last_pt, anchors


def interpret_en1_floorarea(page, seed_pt: str = ""):
    """Parse the EN1 'Floor Areas' section (its own pages, before consumption).
    It is a tree: Whole Building -> Landlord/Tenant Controlled; Common Areas;
    Shared Services; Tenant Space -> Landlord/Tenant Controlled. We emit the
    LEAF rows (the ones the docx 'Floor Area by Type' table holds), with the
    single floor-area value (right-aligned in the value column, x>700)."""
    records = []
    current_pt = seed_pt
    parent = None
    all_words = page.extract_words()
    groups = []
    for w in sorted(all_words, key=lambda w: w["top"]):
        if groups and abs(w["top"] - groups[-1]["top"]) <= 3:
            groups[-1]["ws"].append(w)
        else:
            groups.append({"top": w["top"], "ws": [w]})
    for g in groups:
        ws = sorted(g["ws"], key=lambda w: w["x0"])
        full = " ".join(w["text"] for w in ws)
        low = full.lower()
        if " | " in full and "floor area" not in low and not any(
                k in low for k in ("whole building", "tenant space",
                                   "common area", "shared", "controlled")):
            pt = _extract_pt_from_cell(full)
            if pt:
                current_pt, parent = pt, None
            continue
        if "floor areas" in low and "sq. ft." in low:
            continue
        vals = [w["text"] for w in ws if _is_number(w["text"]) and w["x0"] > 700]
        val = vals[0] if vals else "0"
        left = " ".join(w["text"] for w in ws
                        if w["x0"] < 170 and not _is_number(w["text"]))
        left = left.replace("├", "").replace("└", "").strip().lower()
        if left.startswith("whole building"):
            parent = "Whole Building"
            continue
        if left.startswith("tenant space"):
            parent = "Tenant Space"
            continue
        if left.startswith("common"):
            zone = "Common Areas"
        elif left.startswith("shared"):
            zone = "Shared Services"
        elif left.startswith("landlord controlled") and parent:
            zone = f"{parent} | Landlord Controlled"
        elif left.startswith("tenant controlled") and parent:
            zone = f"{parent} | Tenant Controlled"
        else:
            continue
        if current_pt:
            records.append(_rec("Energy", "EN1FA", current_pt, zone,
                                "Floor Area", val))
    return records, current_pt


def interpret_en1_renewables(page, seed_pt: str = ""):
    """Parse the PDF 'Renewable energy generated' table (its own pages). Per
    property type it lists 5 generated rows — on-site consumed/exported by
    landlord and consumed by third-party (or tenant), then off-site procured by
    landlord/tenant — with columns 2024 MWh, 2024 %, 2025 MWh, 2025 %. We emit
    the prior (2024) and reporting (2025) MWh; sub-total/total rows have no
    canonical key and are skipped. Property type carries across pages."""
    from .canonical import canonical_renewable

    records = []
    current_pt = seed_pt
    all_words = page.extract_words()
    groups = []
    for w in sorted(all_words, key=lambda w: w["top"]):
        if groups and abs(w["top"] - groups[-1]["top"]) <= 3:
            groups[-1]["ws"].append(w)
        else:
            groups.append({"top": w["top"], "ws": [w]})
    for g in groups:
        ws = sorted(g["ws"], key=lambda w: w["x0"])
        full = " ".join(w["text"] for w in ws).strip()
        low = full.lower()
        if " | " in full and "renewable" not in low \
                and canonical_renewable(full) is None:
            pt = _extract_pt_from_cell(full)
            if pt:
                current_pt = pt
            continue
        ck = canonical_renewable(full)
        if ck is None or not current_pt:
            continue
        # Columns: 2024 MWh, 2024 %, 2025 MWh, 2025 %. An all-zero row collapses
        # to just "0.0 0" (the 2025 columns are dropped), so the reporting MWh
        # (nums[2]) may be absent — default it to "0".
        nums = [w["text"] for w in ws if _is_number(w["text"])]
        if not nums:
            continue
        records.append(_rec("Energy", "EN1RE", current_pt, full,
                            "Prior Year (MWh)", nums[0]))
        records.append(_rec("Energy", "EN1RE", current_pt, full,
                            "Reporting Year (MWh)", nums[2] if len(nums) >= 3 else "0"))
    return records, current_pt


def interpret_matrix(question, property_type, groups, data_rows):
    section = _MATRIX_SECTION[question]
    cols = _matrix_cols(question)
    out = []
    for (group, control), (fuel, values) in zip(groups, data_rows):
        row_label = _make_row_label(group, control, fuel)
        for col_label, raw in zip(cols, values):
            out.append(_rec(section, question, property_type, row_label,
                            col_label, raw))
    return out


# Headings that signal a matrix question is starting.  The match is
# case-insensitive so "Total GHG Emissions" and "Total energy consumption" both
# work.
_MATRIX_HEADINGS = {
    "EN1": "total energy consumption",
    "GH1": "total ghg emissions",
    "WT1": "total water consumption",
    "WS1": "total waste generation",
}


def _extract_matrix(page, question: str, seed_pt: str = "",
                    seed_group: str = "", seed_control: str = "",
                    seed_anchors=None):
    """Reconstruct (group, control) per data row and (fuel/scope, values) rows
    from a consumption-matrix page.

    EN1/WT1 layout (10 cols):
      col[0]: rotated group  col[1]: rotated control or sub-group label
      col[2]: fuel/control text (may embed numeric data)
      col[3..9]: Absolute 2024, 2025, area-covered, max-area, L4L 2024, 2025, area

    GH1 layout (10 cols):
      col[0]: rotated group  col[1]: rotated scope label  col[2]: data text

    WS1 layout (9 cols):
      Property-type rows are embedded as col[0] header rows.
      Data rows are "Total waste generation" with values in col[2..8].

    For EN1/WT1 the 7 value columns are read GEOMETRICALLY: each row's numeric
    words are bucketed into columns by their right-edge x against per-page
    anchors (``bucket_by_anchor``). pdfplumber drops blank columns from the
    flattened cell text, so text-order reading misassigns values when
    consumption is blank but floor area is not; geometry fixes that. GH1/WS1
    keep the text-based path.

    Returns: list of (property_type, group, control, fuel, values), and the
    final current_pt, current_group, current_control, anchors (to carry across
    pages).
    """
    results: list[tuple[str, str, str, str, list[str]]] = []
    current_pt = seed_pt
    current_group = seed_group
    current_control = seed_control

    all_words = page.extract_words()
    numeric_words = [(w["x1"], w["top"], w["text"])
                     for w in all_words if _is_number(w["text"])]
    # Fuel/scope/control label words in the left label columns, with their
    # text-line y. Threshold 280 covers the fuel column (x~96, EN1) AND the
    # control column (x~178, WT1 'Landlord/Tenant Controlled') while staying
    # left of the first value column (x~288).
    label_words = [(w["top"], w["bottom"], w["text"])
                   for w in all_words if w["x0"] < 280]
    anchors = _detect_anchors(numeric_words) or seed_anchors
    use_geometry = bool(anchors) and question in ("EN1", "WT1", "GH1")
    if question in ("EN1", "WT1", "GH1") and not use_geometry:
        # No column anchors on this page and none carried from a prior page:
        # we fall back to the text-order path, which can misassign columns when
        # blank cells are dropped. Surface it rather than degrade silently.
        logging.warning("gresb_diff.pdf_parser: no column anchors for %s on a "
                        "matrix page; using text-order extraction (values may "
                        "be misassigned).", question)

    def _label_line(fuel: str, rtop, rbottom):
        """Find the exact text-line y of this row's fuel label inside the row's
        (possibly loose) bounding box, so values are read from the label's own
        line only — not a neighbouring row's line. Prefer an exact label match;
        fall back to a first-word prefix (e.g. 'District Heating & Cooling' is
        split into separate words by extract_words)."""
        in_band = [(tp, bt, txt) for (tp, bt, txt) in label_words
                   if rtop - 2 <= tp <= rbottom + 2]
        exact = [(tp, bt) for (tp, bt, txt) in in_band if txt == fuel]
        if exact:
            return min(exact)
        first = fuel.split(" ")[0]
        pref = [(tp, bt) for (tp, bt, txt) in in_band if txt.startswith(first)]
        return min(pref) if pref else (rtop, rbottom)

    def _geom_values(fuel, rtop, rbottom):
        line_top, line_bottom = _label_line(fuel, rtop, rbottom)
        row_words = [(x1, t) for (x1, tp, t) in numeric_words
                     if line_top - 3 <= tp <= line_bottom + 3]
        return bucket_by_anchor(row_words, anchors)

    def _geom_band(rtop, rbottom):
        """Bucket the numeric words in a row's y-band by column anchor (used for
        GH1 scope rows, which have no left-column fuel label to anchor on)."""
        row_words = [(x1, t) for (x1, tp, t) in numeric_words
                     if rtop - 2 <= tp <= rbottom + 2]
        return bucket_by_anchor(row_words, anchors)

    def _fuels_in_band(rtop, rbottom):
        """All distinct fuel-label lines (Fuels / Electricity / District Heating
        & Cooling) within a row's y-band. A single find_tables row can merge
        several fuel sub-rows when the PDF lacks separating rules (e.g. Shared
        Services at a page bottom), so reading every fuel line keeps each from
        being dropped. Each is returned with its own line band for value reading."""
        found: list = []
        names = {"Fuels": "Fuels", "Electricity": "Electricity",
                 "District": "District Heating & Cooling"}
        for w in sorted(all_words, key=lambda w: w["top"]):
            if w["x0"] >= 160 or w["text"] not in names:
                continue
            if rtop - 2 <= w["top"] <= rbottom + 2:
                name = names[w["text"]]
                if name not in [n for n, _, _ in found]:
                    found.append((name, w["top"], w["bottom"]))
        return found

    for table in page.find_tables():
        row_text = table.extract()
        for r, erow in enumerate(row_text):
            cells = [c or "" for c in erow]
            n = len(cells)
            try:
                rbbox = table.rows[r].bbox
                rtop, rbottom = rbbox[1], rbbox[3]
            except (IndexError, AttributeError, TypeError):
                rtop = rbottom = None

            # --- Property-type header row: first cell embeds " | " (standalone or
            #     as last line of a multi-line description), all other cells blank ---
            first = cells[0].strip()
            rest_blank = all(not (cells[i] or "").strip() for i in range(1, n))
            if rest_blank and " | " in first:
                pt = _extract_pt_from_cell(first)
                if pt:
                    current_pt = pt
                    current_group = ""
                    current_control = ""
                continue

            # --- Skip header rows (Absolute/Like-for-Like labels etc.) ---
            if any("absolute" in (cells[i] or "").lower() or
                   "like-for-like" in (cells[i] or "").lower()
                   for i in range(n)):
                continue
            if any("consumption" in (cells[i] or "").lower() or
                   "emissions" in (cells[i] or "").lower() or
                   "floor area" in (cells[i] or "").lower()
                   for i in range(n)):
                continue

            # --- Rotated group label in col[0] ---
            if cells[0] and "\n" in cells[0] and not any(
                    ch.isdigit() for ch in cells[0]):
                current_group = decode_rotated(cells[0])

            # --- EN1 / WT1 style: col[1] is rotated control, col[2] has fuel+data ---
            if n >= 10 and question in ("EN1", "WT1"):
                # col[1] may be rotated control label
                if cells[1] and "\n" in cells[1]:
                    decoded = decode_rotated(cells[1])
                    # For WT1, col[1] can be sub-group (e.g. "Whole Building")
                    # or control ("Landlord Controlled"). We treat everything as
                    # the control label.
                    current_control = decoded
                # col[2]: "Fuel 1.0 2.0 ..." or plain "Fuel" (zero row) or
                #         "Control 1.0 2.0 ..." for WT1
                c2 = cells[2]
                m = re.match(
                    r"(Fuels|Electricity|District Heating & Cooling"
                    r"|Landlord Controlled|Tenant Controlled"
                    r"|Landlord\nControlled|Tenant\nControlled)\s*(.*)",
                    c2)
                if m:
                    fuel = m.group(1).replace("\n", " ").strip()
                    if use_geometry and rtop is not None:
                        # Emit every fuel line in the band (handles find_tables
                        # merging Fuels/Electricity/District into one row), each
                        # read from its own line; fall back to the matched fuel.
                        fuels = _fuels_in_band(rtop, rbottom)
                        if fuels:
                            for fname, ftop, fbottom in fuels:
                                row_words = [(x1, t) for (x1, tp, t) in numeric_words
                                             if ftop - 3 <= tp <= fbottom + 3]
                                results.append((
                                    current_pt, current_group, current_control,
                                    fname, bucket_by_anchor(row_words, anchors)))
                            continue
                        values = _geom_values(fuel, rtop, rbottom)
                    else:
                        rest = m.group(2).strip()
                        values = _NUM.findall(rest) if rest else []
                        if not values:
                            vals_from_cols = []
                            for ci in range(3, min(10, n)):
                                v = (cells[ci] or "").strip()
                                if v and v.upper() != "N/A":
                                    vals_from_cols.extend(_NUM.findall(v))
                                elif v.upper() == "N/A":
                                    vals_from_cols.append("N/A")
                            values = vals_from_cols
                    results.append((current_pt, current_group, current_control,
                                    fuel, values))
                    continue

            # --- GH1 style: col[1] is scope label, col[2] has data text ---
            if n >= 10 and question == "GH1":
                scope_just_set = False
                if cells[1] and "\n" in cells[1]:
                    scope = decode_rotated(cells[1])
                    current_control = scope
                    scope_just_set = True
                c2 = cells[2]
                nums_in_c2 = _NUM.findall(c2)
                geom = use_geometry and rtop is not None
                if nums_in_c2 and current_control and not any(
                        kw in c2.lower() for kw in ("total", "optional", "based")):
                    values = _geom_band(rtop, rbottom) if geom else nums_in_c2
                    results.append((current_pt, current_group, current_control,
                                    "", values))
                    continue
                # For "Location Based" / "Market Based" rows with text prefix
                m = re.match(r"(Location Based|Market Based[^0-9]*)(.*)", c2)
                if m:
                    fuel = m.group(1).strip()
                    if geom:
                        values = _geom_band(rtop, rbottom)
                    else:
                        values = _NUM.findall(m.group(2))
                        if not values:
                            vals_from_cols = []
                            for ci in range(3, min(10, n)):
                                v = (cells[ci] or "").strip()
                                if v and v.upper() != "N/A":
                                    vals_from_cols.extend(_NUM.findall(v))
                                elif v.upper() == "N/A":
                                    vals_from_cols.append("N/A")
                            values = vals_from_cols
                    results.append((current_pt, current_group, current_control,
                                    fuel, values))
                    continue
                # Zero-value scope row: scope label set in this row but no data
                # in col[2] and no Location/Market Based pattern.
                if scope_just_set and current_pt and not nums_in_c2:
                    results.append((current_pt, current_group, current_control,
                                    "", []))
                    continue

            # --- WS1 style: "Total waste generation" row has data in cols 2-8 ---
            if n >= 9 and question == "WS1":
                if cells[0] and "total waste" in cells[0].lower():
                    vals = []
                    for ci in range(2, min(9, n)):
                        v = (cells[ci] or "").strip()
                        if v and v.upper() != "N/A":
                            vals.extend(_NUM.findall(v.rstrip("%")))
                    results.append((current_pt, "Whole Building", "Total",
                                    "Total waste generation", vals))
                    continue

    # The per-band fuel scan can emit the same (zone, control, fuel) from more
    # than one overlapping find_tables band; keep the richest (most non-empty
    # values) per identity, preserving first-seen order.
    if results:
        best: dict = {}
        order: list = []
        for tup in results:
            pt, group, control, fuel, values = tup
            key = (pt, group, control, fuel)
            score = sum(1 for v in values if str(v).strip() not in ("", "N/A"))
            if key not in best:
                best[key] = (score, tup)
                order.append(key)
            elif score > best[key][0]:
                best[key] = (score, tup)
        results = [best[k][1] for k in order]

    return results, current_pt, current_group, current_control, anchors


def _is_floor_area_page(text_lower: str) -> bool:
    """True for the EN1 energy 'Floor Areas' (by type) section pages.

    These list the floor-area zone tree (Whole Building, Common Areas, Shared
    Services, Tenant Space) with a single 'Floor Area (sq. ft.)' column. They
    must be told apart from two look-alikes:
      * the consumption/emission MATRIX pages, which repeat the same zone labels
        but under 'Absolute' + 'Like-for-Like' column-group headers; and
      * a GHG table's note ("...Maximum Floor Areas ... changes (%) in
        emissions"), which mentions "floor areas" only in prose.
    Requiring the zone tree AND the absence of the Absolute/Like-for-Like matrix
    headers selects only the genuine floor-area pages. Note we must NOT exclude
    on the word "consumption": the first floor-area page also carries the
    "Energy Consumption" section intro, so a "consumption"-based exclusion drops
    that page's property types (Healthcare, Hotel)."""
    return ("floor areas" in text_lower
            and "sq. ft." in text_lower
            and "whole building" in text_lower
            and "shared services" in text_lower
            and not ("absolute" in text_lower and "like-for-like" in text_lower))


def parse_pdf(src) -> list[FieldRecord]:
    records: list[FieldRecord] = []
    question: str | None = None
    # Carry matrix parsing state (pt, group, control) across pages per question.
    _matrix_state: dict[str, dict] = {}
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    with pdfplumber.open(src) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            lines = text.split("\n")
            text_lower = text.lower()

            # --- Detect question from standalone tokens ---
            for ln in lines:
                token = ln.strip().split(" ")[0]
                # RA1/RA3/RA4/RA5 are recognised only to switch `question` away
                # from RA2 (they are not compared), so RA2's interpret_ra2 does
                # not run on later RA pages.
                if token in ("R1", "RA1", "RA2", "RA3", "RA4", "RA5",
                             "BC1.1", "BC1.2", "BC2"):
                    question = token
                    break

            # --- EN1 'Floor Areas' section (own pages, before consumption) ---
            if _is_floor_area_page(text_lower):
                question = "EN1FA"

            # --- Detect matrix question from heading text (case-insensitive) ---
            for q, head in _MATRIX_HEADINGS.items():
                if head in text_lower:
                    question = q
                    break

            # --- EN1 'Renewable energy generated' section (its own pages) ---
            if "renewable energy generated" in text_lower:
                question = "EN1RE"

            # --- Route by question ---
            if question == "R1":
                for tbl in page.extract_tables():
                    records.extend(interpret_r1(tbl))

            elif question == "RA2":
                records.extend(interpret_ra2(lines))

            elif question in ("BC1.1", "BC1.2", "BC2"):
                # A page may stack two BC questions (e.g. BC1.2 above BC2); parse
                # each vertical band under its own question and column anchor.
                records.extend(parse_bc_page(page, question, _matrix_state))

            elif question == "WS1":
                state = _matrix_state.get("WS1", {})
                recs, last_pt = interpret_ws1(page, seed_pt=state.get("pt", ""))
                _matrix_state["WS1"] = {"pt": last_pt or state.get("pt", "")}
                records.extend(recs)

            elif question == "WT1":
                state = _matrix_state.get("WT1", {})
                recs, last_pt, anchors = interpret_wt1(
                    page, seed_pt=state.get("pt", ""),
                    seed_anchors=state.get("anchors"))
                _matrix_state["WT1"] = {
                    "pt": last_pt or state.get("pt", ""),
                    "anchors": anchors or state.get("anchors"),
                }
                records.extend(recs)

            elif question == "EN1FA":
                state = _matrix_state.get("EN1FA", {})
                recs, last_pt = interpret_en1_floorarea(
                    page, seed_pt=state.get("pt", ""))
                _matrix_state["EN1FA"] = {"pt": last_pt or state.get("pt", "")}
                records.extend(recs)

            elif question == "EN1RE":
                state = _matrix_state.get("EN1RE", {})
                recs, last_pt = interpret_en1_renewables(
                    page, seed_pt=state.get("pt", ""))
                _matrix_state["EN1RE"] = {"pt": last_pt or state.get("pt", "")}
                records.extend(recs)

            elif question in _MATRIX_SECTION:
                cols = _matrix_cols(question)
                state = _matrix_state.get(question, {})
                page_results, last_pt, last_group, last_control, anchors = (
                    _extract_matrix(
                        page, question,
                        seed_pt=state.get("pt", ""),
                        seed_group=state.get("group", ""),
                        seed_control=state.get("control", ""),
                        seed_anchors=state.get("anchors"),
                    ))
                _matrix_state[question] = {
                    "pt": last_pt or state.get("pt", ""),
                    "group": last_group,
                    "control": last_control,
                    "anchors": anchors or state.get("anchors"),
                }
                for pt, group, control, fuel, values in page_results:
                    if not pt:
                        continue
                    section = _MATRIX_SECTION[question]
                    row_label = _make_row_label(group, control, fuel)
                    # Blank matrix columns mean zero in these tables (and the docx
                    # stores explicit "0"); normalise empties to "0" and pad any
                    # short rows so all 7 columns compare cleanly. Geometry has
                    # already placed each present value in its correct column, so
                    # "" here is a genuinely-empty (zero) column. (A true PDF
                    # parse-miss that turned a real value into "" would make the
                    # row's values disagree with the docx, so value-anchored
                    # auto-pairing drops it to the excluded list rather than
                    # silently comparing a fabricated zero.)
                    values = [v if str(v).strip() not in ("", "N/A") else "0"
                              for v in values]
                    if len(values) < len(cols):
                        values = values + ["0"] * (len(cols) - len(values))
                    for col_label, raw in zip(cols, values):
                        records.append(_rec(section, question, pt,
                                            row_label, col_label, raw))

    return records
