"""Streamlit UI for the GRESB diff engine. Run:
    streamlit run app/streamlit_app.py
Files are processed in memory only — nothing is written to disk or logged.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import streamlit as st

from app.presenters import (clipboard_tsv, client_name_from_filename,
                            printable_html, report_title, safe_filename)
from gresb_diff.__main__ import DEFAULT_MAPPING, run
from gresb_diff.reconcile import AssetData, reconcile, reconcile_report
from gresb_diff.report import readable_report, result_to_rows, section_label

# Package-anchored (resolves regardless of working directory, incl. in-browser
# via stlite) rather than a CWD-relative path.
MAPPING = DEFAULT_MAPPING
# Screenshot of GRESB's "Print Response" export settings to use. Anchored to
# this file so it resolves both locally and in the stlite browser filesystem.
PDF_FORMAT_IMG = str(Path(__file__).resolve().parent / "assets"
                     / "pdf-download-format.png")
# st.image renamed use_column_width -> use_container_width; the in-browser stlite
# build is newer than the pinned local Streamlit, so pick whichever kwarg the
# running version supports (avoids both a TypeError and a deprecation warning).
_IMG_WIDTH_KW = ("use_container_width"
                 if "use_container_width" in inspect.signature(st.image).parameters
                 else "use_column_width")


@st.dialog("How to export the GRESB PDF", width="large")
def _show_pdf_format_help():
    st.image(PDF_FORMAT_IMG, **{_IMG_WIDTH_KW: True})
    st.caption("In GRESB's 'Print Response' screen, select A4 and the sections "
               "shown above, then click Generate PDF.")

st.set_page_config(page_title="GRESB Diff", layout="wide")
st.title("GRESB ↔ Measurabl Asset-Level Diff")
st.caption("Compares the GRESB Fund PDF against the Measurabl Word-for-Diff "
           "export. Files are processed in your session only.")

# Render the help trigger as compact, label-sized link text rather than a full
# button. Scoped to this one button via its key class (st-key-<key>, stable
# since Streamlit 1.39) so other buttons are untouched.
st.markdown(
    """
    <style>
    .st-key-pdf_help_btn button {
        min-height: 0; height: auto; padding: 0 0 0 .4rem;
        border: none; background: transparent;
        font-size: .875rem; line-height: 1.4; color: #2563eb;
    }
    .st-key-pdf_help_btn button:hover,
    .st-key-pdf_help_btn button:focus,
    .st-key-pdf_help_btn button:active {
        background: transparent; color: #1d4ed8;
        text-decoration: underline; box-shadow: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Bottom-aligned so the two upload boxes line up even though the PDF column has
# an extra title+help row above its (label-collapsed) uploader.
col1, col2 = st.columns(2, vertical_alignment="bottom")
with col1:
    title_l, title_r = st.columns([0.4, 0.6], gap="small",
                                   vertical_alignment="center")
    with title_l:
        st.markdown("**GRESB Fund PDF**")
    with title_r:
        if st.button("ⓘ GRESB PDF Export Format", key="pdf_help_btn",
                     help="Show the GRESB 'Print Response' export settings "
                     "to use"):
            _show_pdf_format_help()
    # Title is rendered above (with the help link); collapse the uploader's own.
    pdf_file = st.file_uploader("GRESB Fund PDF", type=["pdf"],
                                label_visibility="collapsed")
with col2:
    docx_file = st.file_uploader("Measurabl Word-for-Diff (.docx)", type=["docx"])
xlsx_file = st.file_uploader(
    "GRESB Asset-Level Data (.xlsx) — optional, enables per-asset reconciliation",
    type=["xlsx"])

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

    # Summary above the table: grouped bullets ("GRESB - x vs Word Dif - y")
    # that can be pasted straight into a Jira description.
    readable = readable_report(result)
    if readable:
        st.markdown("#### Summary")
        st.markdown(readable)
        with st.expander("📋 Copy for Jira (Markdown)"):
            st.code(readable, language="markdown")

    # Reconciliation: if the asset-level Excel was provided, explain each flagged
    # like-for-like line by the asset(s)/cause behind it.
    if xlsx_file is not None and result.differences:
        try:
            recon_md = reconcile_report(reconcile(
                AssetData(xlsx_file.getvalue()), result))
        except Exception as exc:
            import traceback
            st.warning(f"Reconciliation skipped: {type(exc).__name__}: {exc}")
            st.code(traceback.format_exc())
            recon_md = ""
        if recon_md:
            st.markdown("#### Reconciliation — which asset(s) explain each mismatch")
            st.caption("EN1/GH1/WT1 like-for-like lines only; ownership-weighted. "
                       "Negatives, GRESB-side adjustments, and Word-doc add/drop "
                       "are classified separately.")
            st.markdown(recon_md)
            with st.expander("📋 Copy reconciliation for Jira (Markdown)"):
                st.code(recon_md, language="markdown")
    if readable:
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
