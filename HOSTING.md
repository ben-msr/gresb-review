# Hosting the diff tool in the browser (stlite + GitHub Pages)

`index.html` runs the Streamlit app entirely in the browser via
[stlite](https://github.com/whitphx/stlite) (Python compiled to WebAssembly).
There is **no server**: uploaded PDFs/docx are processed client-side and never
leave the user's machine, which is exactly what GitHub Pages needs and keeps
customer files off any server.

## 1. Test locally first (no GitHub needed)

stlite fetches the app files over HTTP, so open the page through a local web
server (not `file://`):

```bash
cd /Users/ben.tran/Projects/gresb_review
python3 -m http.server 8000
```

Open <http://localhost:8000/> in a browser.

- The **first load is slow** (it downloads the Python runtime + packages; can
  take a minute). Subsequent loads are cached.
- **The make-or-break check:** upload a real GRESB Fund PDF and the matching
  Measurabl `.docx`, click **Run Review**, and confirm the differences match
  what the local CLI/Streamlit app produces. If `pdfplumber` fails to load or
  parse under WebAssembly, this is where it shows up — tell me and we adjust
  (pin different versions, or fall back to a hosted option).

## 2. Publish on GitHub Pages

1. Create a GitHub repo and push this project (the data files stay out — they
   are git-ignored).
2. In the repo: **Settings → Pages → Build and deployment → Source: Deploy from
   a branch**, branch `main`, folder `/ (root)`, **Save**.
3. Wait for the green check, then open
   `https://<your-username>.github.io/<repo-name>/`.

Because the file URLs in `index.html` are **relative** (`./gresb_diff/...`),
the same page works locally and on Pages with no changes.

## Notes / caveats

- **Public repo = public code.** The repo's code (parsing logic, GRESB field
  mappings) is visible to anyone. No customer data is exposed — PDFs/docx,
  baselines, and worksheets are git-ignored and never committed, and file
  processing is client-side. Confirm public hosting is acceptable for internal
  tooling before sharing the link widely.
- **Vendored pdfplumber wheel.** `pdfplumber` normally requires `pypdfium2`, a
  native binary with no pure-Python wheel, so micropip can't install it under
  Pyodide. pypdfium2 is only used for image rendering, which this tool never
  does, so `vendor/pdfplumber-0.11.8-py3-none-any.whl` is the same pdfplumber
  0.11.8 with that one dependency removed from its metadata. `index.html`
  installs that wheel instead of `pdfplumber` from PyPI (micropip still pulls
  `pdfminer.six` + `Pillow`). To refresh it for a new pdfplumber version,
  re-run the patch: download the wheel, delete the `Requires-Dist: pypdfium2`
  line from its `*.dist-info/METADATA`, blank that file's hash in `RECORD`
  (`<distinfo>/METADATA,,`), re-zip, and drop it in `vendor/`.
- **Keeping it in sync:** `index.html` lists the engine/app files by path and
  fetches their current contents, so ordinary code edits need no change here.
  Only adding/removing/renaming a module requires editing the `files` map.
- **stlite version** is pinned to `@stlite/browser@0.85.1` in `index.html`;
  bump it there to upgrade.
