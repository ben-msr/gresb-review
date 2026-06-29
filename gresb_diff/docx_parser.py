"""Parse the Measurabl 'Word-for-Diff' docx into FieldRecords."""
from __future__ import annotations

import io

import docx
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .models import FieldRecord, parse_value

SKIP_PROPERTY = "All Use Types, All Countries"

SECTION_OF_QUESTION = {
    "R1": "Reporting Characteristics",
    "RA2": "Risk Assessment",
    "EN1": "Energy", "GH1": "GHG", "WT1": "Water", "WS1": "Waste",
    "EN1FA": "Energy",  # EN1 "Floor Area by Type" table (separate from consumption)
    "EN1RE": "Energy",  # EN1 "Renewable Energy" table (separate from consumption)
    "BC1.1": "Building Certifications", "BC1.2": "Building Certifications",
    "BC2": "Building Certifications",
}

# Header-3 category suffixes that follow "<property type> " in matrix sections.
MATRIX_CATEGORIES = [
    "Energy by Floor Area Type", "Energy Consumption", "Energy Data Coverage",
    "Renewable Energy",
    "GHG Emissions Boundary", "GHG Emissions", "GHG Data Coverage",
    "Water Consumption", "Water Data Coverage",
    "Waste Management", "Waste Data Coverage", "Absolute Output",
]


def _heading_level(style_name: str) -> int | None:
    """Map both 'Header N' (real doc) and 'Heading N' (test docs) to N."""
    for prefix in ("Header ", "Heading "):
        if style_name.startswith(prefix):
            try:
                return int(style_name[len(prefix):])
            except ValueError:
                continue
    return None


def _iter_blocks(document):
    body = document.element.body
    for child in body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _question_from_h2(text: str) -> str | None:
    token = text.split(" ", 1)[0]
    return token if token in SECTION_OF_QUESTION else None


def _split_property_and_category(h3: str) -> tuple[str, str | None]:
    for cat in MATRIX_CATEGORIES:
        if h3.endswith(" " + cat):
            return h3[: -len(cat) - 1].strip(), cat
        if h3 == cat:
            return "", cat
    return h3.strip(), None  # BC header-3 is just the property type


def _rows(table: Table) -> list[list[str]]:
    # python-docx repeats a horizontally-merged cell once per grid column it
    # spans. We rely on that: the consumption tables' group header ("Absolute"
    # spanning 4 sub-columns, "Like-for-Like" spanning 3) must repeat so each
    # data column lines up with its group. Do NOT deduplicate merged cells —
    # collapsing the group header misaligns every matrix column label.
    return [[c.text.strip() for c in r.cells] for r in table.rows]


def parse_docx(src) -> list[FieldRecord]:
    if isinstance(src, (bytes, bytearray)):
        src = io.BytesIO(src)
    document = docx.Document(src)

    records: list[FieldRecord] = []
    question = None
    property_type = None

    # R1 in this docx is split: one 1-row table per property type (first is
    # the column-header row, subsequent ones are data rows).  Accumulate all
    # tables in the R1 section and process them together as a single table.
    r1_tables: list[list[str]] = []  # accumulated rows (header + data)

    def _flush_r1():
        if r1_tables:
            records.extend(_parse_table("R1", None, r1_tables))
            r1_tables.clear()

    for block in _iter_blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            level = _heading_level(block.style.name)
            if level == 2:
                _flush_r1()
                question = _question_from_h2(text)  # None if unrecognized -> tables skipped
                property_type = None
            elif level == 3:
                property_type, _ = _split_property_and_category(text)
        elif isinstance(block, Table) and question:
            if question == "R1":
                # Each table is a single row; accumulate for later processing.
                for row in _rows(block):
                    r1_tables.append(row)
            else:
                records.extend(_parse_table(question, property_type, _rows(block)))

    _flush_r1()
    return records


def _emit(records, question, property_type, row_label, col_label, raw):
    vr, vn = parse_value(raw)
    records.append(FieldRecord(
        SECTION_OF_QUESTION[question], question, property_type or "",
        row_label, col_label, vr, vn, "docx",
    ))


def _parse_table(question, property_type, rows):
    if not rows:
        return []
    out: list[FieldRecord] = []
    header = rows[0]

    if question == "R1":
        for row in rows[1:]:
            pt = row[0]
            if pt == SKIP_PROPERTY or not pt:
                continue
            for j, col in enumerate(header[1:], start=1):
                if j < len(row):
                    _emit(out, "R1", pt, "", col, row[j])
        return out

    if question == "RA2":
        try:
            assets_col = header.index("Number of Assets")
        except ValueError:
            return out
        for row in rows[1:]:
            topic = row[0]
            if not topic or topic == SKIP_PROPERTY:
                continue
            _emit(out, "RA2", "", topic, "Number of Assets",
                  row[assets_col] if assets_col < len(row) else "")
        return out

    if question in ("BC1.1", "BC1.2", "BC2"):
        if property_type == SKIP_PROPERTY:
            return out
        try:
            assets_col = header.index("Number of Assets")
        except ValueError:
            return out
        for row in rows[1:]:
            scheme = row[0].strip()
            if not scheme:
                continue
            _emit(out, question, property_type, scheme, "Number of Assets",
                  row[assets_col] if assets_col < len(row) else "")
        return out

    # EN1 "Floor Area by Type" table: single header "Floor Area Type | Floor
    # Area (ft²)". Emit as EN1FA so it is compared separately from consumption.
    if question == "EN1" and header and header[0].strip() == "Floor Area Type":
        if property_type == SKIP_PROPERTY:
            return out
        for row in rows[1:]:
            fa_type = row[0].strip()
            if fa_type:
                _emit(out, "EN1FA", property_type, fa_type, "Floor Area",
                      row[1] if len(row) > 1 else "")
        return out

    # EN1 "Renewable Energy" table: single header "| Prior Year (MWh) |
    # Reporting Year (MWh)". Emit as EN1RE so it is compared separately and is
    # NOT mis-read by the two-header matrix logic (which would drop its first
    # data row, "Generated On-site and Consumed by Landlord").
    if question == "EN1" and len(header) >= 3 \
            and header[1].strip().lower().startswith("prior year") \
            and header[2].strip().lower().startswith("reporting year"):
        if property_type == SKIP_PROPERTY:
            return out
        for row in rows[1:]:
            rl = row[0].strip()
            if rl:
                _emit(out, "EN1RE", property_type, rl, "Prior Year (MWh)",
                      row[1] if len(row) > 1 else "")
                _emit(out, "EN1RE", property_type, rl, "Reporting Year (MWh)",
                      row[2] if len(row) > 2 else "")
        return out

    # Matrix questions (EN1/GH1/WT1/WS1): two header rows (group, sub).
    if property_type == SKIP_PROPERTY or len(rows) < 2:
        return out
    groups, subs = rows[0], rows[1]
    for row in rows[2:]:
        row_label = row[0]
        if not row_label:
            continue
        for j in range(1, len(row)):
            group = groups[j] if j < len(groups) else ""
            sub = subs[j] if j < len(subs) else ""
            col_label = f"{group} | {sub}".strip(" |")
            _emit(out, question, property_type, row_label, col_label, row[j])
    return out
