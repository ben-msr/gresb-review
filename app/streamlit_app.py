"""Streamlit UI for the GRESB diff engine. Run:
    streamlit run app/streamlit_app.py
Files are processed in memory only — nothing is written to disk or logged.
"""
from __future__ import annotations

import streamlit as st

from app.presenters import (clipboard_tsv, client_name_from_filename,
                            printable_html, report_title, safe_filename)
from gresb_diff.__main__ import DEFAULT_MAPPING, run
from gresb_diff.report import readable_report, result_to_rows, section_label

# Package-anchored (resolves regardless of working directory, incl. in-browser
# via stlite) rather than a CWD-relative path.
MAPPING = DEFAULT_MAPPING

st.set_page_config(page_title="GRESB Diff", layout="wide")
st.title("GRESB ↔ Measurabl Asset-Level Diff")
st.caption("Compares the GRESB Fund PDF against the Measurabl Word-for-Diff "
           "export. Files are processed in your session only.")

col1, col2 = st.columns(2)
with col1:
    pdf_file = st.file_uploader("GRESB Fund PDF", type=["pdf"])
with col2:
    docx_file = st.file_uploader("Measurabl Word-for-Diff (.docx)", type=["docx"])

if st.button("Run Review", type="primary"):
    # Always clickable; guard inside so a click always produces visible feedback
    # (a disabled button can silently no-op if the uploaders aren't seen as set).
    if not (pdf_file and docx_file):
        st.warning("Upload both the GRESB PDF and the Measurabl .docx, "
                   "then click Run Review.")
        st.stop()
    try:
        # A client-side overlay (see index.html) shows the live spinner; the
        # st.spinner here only paints at the end under stlite's batched render.
        with st.spinner("Comparing… (large PDFs can take a while in the browser)"):
            result = run(pdf_file.getvalue(), docx_file.getvalue(), MAPPING)
    except Exception as exc:  # surface the error on the page, not just console
        import traceback
        st.error(f"Review failed: {type(exc).__name__}: {exc}")
        st.code(traceback.format_exc())
        st.stop()
    # Build the report name: "YYYY-MM-DD Client Name GRESB Diff Analysis".
    # Client name is parsed from the uploaded docx filename; date is the local
    # computer date.
    client_name = client_name_from_filename(docx_file.name)
    report_name = report_title(client_name)
    rows = result_to_rows(result)
    n = len(rows)
    u = len(result.unlocated)
    sections = len({r["Section"] for r in rows})
    summary = (f"{n} difference{'' if n == 1 else 's'} across {sections} "
               f"section{'' if sections == 1 else 's'}; "
               f"{u} field{'' if u == 1 else 's'} could not be located.")
    st.subheader(summary)

    # Readable summary above the table: grouped bullets ("GRESB - x vs Word Dif
    # - y") that can be pasted straight into a Jira description.
    readable = readable_report(result)
    if readable:
        st.markdown("#### Readable summary")
        st.markdown(readable)
        with st.expander("📋 Copy for Jira (Markdown)"):
            st.code(readable, language="markdown")
        st.divider()

    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.success("No differences found.")

    unlocated_lines = [
        f"{section_label(d)} / {d.property_type}: missing in "
        f"{'PDF' if d.status == 'missing_pdf' else 'docx'} ({d.canonical_id})"
        for d in result.unlocated
    ]
    if unlocated_lines:
        with st.expander(f"{u} field(s) could not be located on one side"):
            for line in unlocated_lines:
                st.write("• " + line)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download printable report (HTML)",
            data=printable_html(rows, summary, unlocated_lines, report_name),
            file_name=f"{safe_filename(report_name)}.html", mime="text/html")
    with c2:
        st.text_area("Copy to clipboard (TSV)", value=clipboard_tsv(rows),
                     height=160,
                     help="Select all and copy; paste into Excel/Sheets/email.")
