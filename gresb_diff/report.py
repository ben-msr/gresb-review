"""Render comparison results to structured rows and Markdown (mismatches only)."""
from __future__ import annotations

import re
from collections import OrderedDict, defaultdict

from .compare import CompareResult

# Display units, normalised from the raw column parenthetical.
_UNIT_FIX = {"sq. ft.": "sq ft", "ft²": "sq ft", "m3": "m³", "mt": "MT"}


def _split_field(field: str):
    """Split a field name into (group, row, metric_column).

    Matrix fields look like 'Zone | Control | Fuel | Absolute | 2024
    Consumption (MWh)'; the last two segments are the Absolute/Like-for-Like
    group and the metric column. Non-matrix fields ('Shared Services | Floor
    Area', 'LEED Core & Shell') have no group."""
    parts = [p.strip() for p in field.split("|")]
    if len(parts) >= 3 and parts[-2] in ("Absolute", "Like-for-Like"):
        group = "LFL" if "Like" in parts[-2] else "Abs"
        return group, " | ".join(parts[:-2]), parts[-1]
    if len(parts) >= 2:
        return None, " | ".join(parts[:-1]), parts[-1]
    return None, field.strip(), ""


def _metric_label(col: str) -> str:
    """Human metric label: the calendar year if present (PDF columns carry it),
    else Prior/Reporting Year, floor-area, or assets."""
    low = col.lower()
    year = re.search(r"(20\d\d)", col)
    if year:
        return year.group(1)
    if "prior" in low:
        return "Prior Year"
    if "reporting" in low:
        return "Reporting Year"
    if "max" in low:
        return "Maximum Floor Area"
    if "floor area" in low or "coverage" in low or "covered" in low:
        return "Floor Area Covered"
    if "number of assets" in low:
        return "Number of Assets"
    return col


def _unit(col: str) -> str:
    m = re.search(r"\(([^)]+)\)", col)
    if not m:
        return ""
    u = m.group(1).strip()
    return _UNIT_FIX.get(u.lower(), u)


def readable_report(result: CompareResult) -> str:
    """A copy-paste-friendly Markdown summary of the differences, grouped by
    '<CODE> <Section> - <Property Type>' → field row → per-metric line
    ('GRESB - <pdf> vs Word Dif - <docx>'). Mirrors the readable layout used
    for ticket descriptions. Returns '' when there are no differences."""
    groups: "OrderedDict" = OrderedDict()
    for d in result.differences:
        code = category_code(d.canonical_id)
        group, row, mcol_docx = _split_field(d.docx_field_name)
        _gp, _rp, mcol_pdf = _split_field(d.pdf_field_name)
        mcol = mcol_pdf or mcol_docx
        metric = _metric_label(mcol)
        unit = _unit(mcol) or _unit(mcol_docx)
        # GHG emissions are reported in MTCO2e; the GRESB PDF column just says
        # "tonnes". Show the standard emissions unit.
        if code == "GH1" and unit.lower() == "tonnes":
            unit = "MTCO2e"
        row_label = (group + " " if group else "") + row
        head = f"{code} {d.section} - {d.property_type}".strip()
        groups.setdefault(head, OrderedDict()).setdefault(row_label, []).append(
            (metric, d.pdf_value, d.docx_value, unit))

    lines: list[str] = []
    for head, rows in groups.items():
        lines.append(f"**{head}**")
        for row_label, metrics in rows.items():
            lines.append(f"- {row_label}")
            for metric, pdf_val, docx_val, unit in metrics:
                u = f" {unit}" if unit else ""
                prefix = f"{metric}: " if metric else ""
                lines.append(
                    f"    - {prefix}GRESB - ({pdf_val}{u}) "
                    f"vs Word Dif - ({docx_val}{u})")
        lines.append("")
    return "\n".join(lines).strip()


# Canonical-id prefixes -> GRESB indicator code, longest/most-specific first.
# EN1FA (our internal floor-area tag) is part of the EN1 indicator.
_CATEGORY_PREFIXES = [
    ("EN1FA", "EN1"), ("EN1", "EN1"), ("GH1", "GH1"), ("WT1", "WT1"),
    ("WS1", "WS1"), ("RA2", "RA2"), ("BC1.1", "BC1.1"), ("BC1.2", "BC1.2"),
    ("BC2", "BC2"), ("R1", "R1"),
]


def category_code(canonical_id: str) -> str:
    """GRESB indicator code for a difference, derived from its canonical_id
    (e.g. 'EN1.SHARED|ELECTRIC...' -> 'EN1', 'bc2.assets' -> 'BC2',
    'BC1.1 LEED ...' -> 'BC1.1'). Empty string if unrecognised."""
    cid = canonical_id.upper()
    for prefix, code in _CATEGORY_PREFIXES:
        if cid.startswith(prefix):
            return code
    return ""


def section_label(d) -> str:
    """Section name with its GRESB indicator code, e.g. 'Energy (EN1)'."""
    code = category_code(d.canonical_id)
    return f"{d.section} ({code})" if code else d.section


def order_differences(diffs: list) -> list:
    """Order differences for display so the Energy section mirrors the docx:
    each property type's floor-area rows (EN1FA) appear *before* its consumption
    rows, and the floor-area rows sit with the Energy block rather than stranded
    at the end of the list (they are appended last during assembly).

    Each section keeps the position where it first appears, so non-Energy
    sections are left in their original relative order. The sort is stable, so
    within every group the original ordering is preserved as the final tiebreak.
    """
    first_index: dict[str, int] = {}
    for i, d in enumerate(diffs):
        first_index.setdefault(d.section, i)

    def key(item):
        i, d = item
        block = first_index[d.section]
        if d.section == "Energy":
            kind = 0 if d.canonical_id.startswith("EN1FA") else 1
            sub = (d.property_type, kind)
        else:
            sub = ("", 0)
        return (block, sub, i)

    return [d for _, d in sorted(enumerate(diffs), key=key)]


def result_to_rows(result: CompareResult) -> list[dict]:
    return [
        {
            "Section": section_label(d),
            "Property Type": d.property_type,
            "PDF field": d.pdf_field_name,
            "PDF value": d.pdf_value,
            "docx field": d.docx_field_name,
            "docx value": d.docx_value,
        }
        for d in result.differences
    ]


def _plural(n: int) -> str:
    return "" if n == 1 else "s"


def _md_cell(value: str) -> str:
    return str(value).replace("|", "\\|")


def render_markdown(result: CompareResult) -> str:
    diffs = result.differences
    n = len(diffs)
    lines = [f"# GRESB Diff — {n} difference{_plural(n)} found", ""]

    grouped: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for d in diffs:
        grouped[section_label(d)][d.property_type].append(d)

    for section in sorted(grouped):
        lines.append(f"## {section}")
        for ptype in sorted(grouped[section]):
            lines.append(f"### {ptype}")
            lines.append("| PDF field | PDF value | docx field | docx value |")
            lines.append("|---|---|---|---|")
            for d in grouped[section][ptype]:
                lines.append(
                    f"| {_md_cell(d.pdf_field_name)} | {_md_cell(d.pdf_value)} "
                    f"| {_md_cell(d.docx_field_name)} | {_md_cell(d.docx_value)} |")
            lines.append("")

    if result.unlocated:
        u = len(result.unlocated)
        lines.append(f"## {u} field{_plural(u)} could not be located on one side")
        for d in result.unlocated:
            if d.status == "unmapped_field":
                lines.append(f"- {section_label(d)}: '{d.canonical_id}' matched no "
                             f"records on either side (check crosswalk labels)")
            else:
                side = "PDF" if d.status == "missing_pdf" else "docx"
                lines.append(f"- {section_label(d)} / {d.property_type}: "
                             f"missing in {side} ({d.canonical_id})")
    return "\n".join(lines)
