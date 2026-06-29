## Run the web app

```bash
python -m pip install -r requirements-ui.txt
streamlit run app/streamlit_app.py
```

Upload the GRESB Fund PDF and the Measurabl Word-for-Diff `.docx`, then click
**Run Review**. The table shows only mismatching data points. Use **Download
printable report** for a print-to-PDF copy, or the TSV box to copy into a
spreadsheet. Files are processed in your browser session only — nothing is
written to disk.
