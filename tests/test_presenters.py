import datetime

from app.presenters import (clipboard_tsv, client_name_from_filename,
                            printable_html, report_title, safe_filename)

ROWS = [
    {"Section": "Energy", "Property Type": "Hotel | United States",
     "PDF field": "PDF F", "PDF value": "113.94",
     "docx field": "DOCX F", "docx value": "114.1"},
]


def test_clipboard_tsv_has_header_and_tab_separated_row():
    out = clipboard_tsv(ROWS)
    lines = out.splitlines()
    assert lines[0].split("\t") == [
        "Section", "Property Type", "PDF field", "PDF value",
        "docx field", "docx value"]
    assert lines[1].split("\t")[3] == "113.94"


def test_clipboard_tsv_empty():
    out = clipboard_tsv([])
    assert out.splitlines()[0].startswith("Section")
    assert len(out.splitlines()) == 1


def test_printable_html_is_standalone_and_contains_values():
    html = printable_html(ROWS, "1 difference found", ["Energy / Hotel: missing in PDF"])
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "1 difference found" in html
    assert "113.94" in html and "114.1" in html
    assert "missing in PDF" in html
    assert "window.print" in html  # print button present


def test_printable_html_escapes_content():
    rows = [{**ROWS[0], "PDF field": "<script>x</script>"}]
    html = printable_html(rows, "1 difference found", [])
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_title_format_with_explicit_date():
    title = report_title("Example Capital Fund, LLC",
                         datetime.date(2026, 6, 28))
    assert title == ("2026-06-28 Example Capital Fund, LLC "
                     "GRESB Diff Analysis")


def test_report_title_collapses_whitespace_and_falls_back():
    assert report_title("  Acme   Fund\n III ", datetime.date(2026, 1, 2)) == \
        "2026-01-02 Acme Fund III GRESB Diff Analysis"
    assert report_title(None, datetime.date(2026, 1, 2)) == \
        "2026-01-02 Client GRESB Diff Analysis"


def test_report_title_defaults_to_today():
    title = report_title("Acme")
    assert title.startswith(datetime.date.today().strftime("%Y-%m-%d"))


def test_safe_filename_strips_illegal_chars_and_trailing_period():
    # Illegal across OSes: / \ : * ? " < > | — colon and slash removed here.
    assert safe_filename("2026-06-28 Fund: A/B GRESB Diff Analysis") == \
        "2026-06-28 Fund AB GRESB Diff Analysis"
    # Commas/periods kept; a trailing period (e.g. 'L.P.') is stripped.
    assert safe_filename("2026-06-28 Sample Holdings L.P.") == \
        "2026-06-28 Sample Holdings L.P"


def test_client_name_from_filename_middle_segment_with_separator():
    name = client_name_from_filename(
        "2026-06-25__Sample-Holdings--Fund-IV__GRESB-Word-for-Diff.docx")
    assert name == "Sample Holdings - Fund IV"


def test_client_name_from_filename_case_insensitive_extension():
    assert client_name_from_filename(
        "2026-01-02__Acme-Fund__GRESB-Word-for-Diff.DOCX") == "Acme Fund"


def test_client_name_from_filename_fallback_to_whole_name():
    # No '__' delimiters -> use the whole filename (minus extension).
    assert client_name_from_filename("Acme-Fund-2026.docx") == "Acme Fund 2026"


def test_client_name_from_filename_empty():
    assert client_name_from_filename(None) is None
    assert client_name_from_filename("") is None


def test_report_title_from_docx_filename_end_to_end():
    name = client_name_from_filename(
        "2026-06-25__Sample-Holdings--Fund-IV__GRESB-Word-for-Diff.docx")
    title = report_title(name, datetime.date(2026, 6, 28))
    assert title == "2026-06-28 Sample Holdings - Fund IV GRESB Diff Analysis"


def test_printable_html_uses_title_in_head_and_h1():
    title = "2026-06-28 Acme Fund GRESB Diff Analysis"
    html = printable_html(ROWS, "1 difference found", [], title)
    assert f"<title>{title}</title>" in html
    assert f"<h1>{title}</h1>" in html
