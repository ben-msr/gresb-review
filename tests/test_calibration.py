import json
import os

import pytest

import gresb_diff.__main__ as cli
from gresb_diff.report import result_to_rows

# Local calibration files (git-ignored, never committed). Defaults are generic;
# point at your real local export via GRESB_SAMPLE_PDF / GRESB_SAMPLE_DOCX, or
# rename your local copies to these names. No client name lives in this repo.
PDF = os.environ.get("GRESB_SAMPLE_PDF", "sample.pdf")
DOCX = os.environ.get("GRESB_SAMPLE_DOCX", "sample.docx")
BASELINE = "tests/baseline/expected_diffs.json"


@pytest.mark.skipif(not (os.path.exists(PDF) and os.path.exists(DOCX)
                         and os.path.exists(BASELINE)),
                    reason="local sample files / baseline not present")
def test_real_sample_matches_baseline():
    with open(PDF, "rb") as fh:
        pdf_bytes = fh.read()
    with open(DOCX, "rb") as fh:
        docx_bytes = fh.read()
    result = cli.run(pdf_bytes, docx_bytes, "gresb_diff/mapping/gresb_2026.csv")
    with open(BASELINE) as fh:
        expected = json.load(fh)
    assert result_to_rows(result) == expected
