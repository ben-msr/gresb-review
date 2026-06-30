"""Guard: the in-browser (stlite) build fetches each engine/app module listed
in index.html's `files` map. If a module is added/renamed but not listed, the
web app fails at import (ModuleNotFoundError) even though local runs are fine.
This test fails fast when a runtime module is missing from index.html."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = ROOT / "index.html"

# Modules that are NOT part of the browser app (dev-only). Keep empty unless a
# genuinely browser-irrelevant module is added under gresb_diff/ or app/.
_NOT_IN_BROWSER: set = set()


def _runtime_modules():
    for pkg in ("gresb_diff", "app"):
        for py in sorted((ROOT / pkg).glob("*.py")):
            if py.name not in _NOT_IN_BROWSER:
                yield py.relative_to(ROOT).as_posix()


def test_index_html_lists_every_runtime_module():
    html = INDEX.read_text(encoding="utf-8")
    missing = [m for m in _runtime_modules() if m not in html]
    assert not missing, (
        "These modules are not in index.html's files map, so the stlite build "
        f"will fail to import them: {missing}. Add an f(\"<path>\") entry.")


def test_index_html_lists_the_mapping_csv_and_wheel():
    html = INDEX.read_text(encoding="utf-8")
    assert "gresb_diff/mapping/gresb_2026.csv" in html
    assert "vendor/pdfplumber-0.11.8-py3-none-any.whl" in html
