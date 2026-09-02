# PDF Editor

A personal, offline, open-source PDF toolkit — merge, split, remove/extract/reorder
pages, rotate, crop, add page numbers, watermark, compress, and convert PDFs to
images or Word, all running locally on your own machine. No internet connection is
used or required.

There are two ways to use it:

- **Web app** (recommended) — a local browser-based app with a clickable page-thumbnail
  grid and a Recent Files history. This is the primary, actively developed version.
- **Desktop app** — the original PySide6 desktop version. Still fully working, kept as
  a fallback.

Both share the same underlying PDF engine (`app/core/`), so results are identical
either way — they just differ in the UI.

## Easiest way to get it (Windows, no setup required)

Download and run the installer from the
[latest release](https://github.com/W-Hin/pdf_editor/releases/latest) —
`PDFEditorSetup.exe`. It installs to your user folder (no admin rights needed),
adds a Start Menu entry, and optionally a Desktop shortcut. No Python, no Node,
nothing else to install. The app checks for newer releases on launch and shows a
banner if one's available — updating just means running the newer installer.

Everything below is for building it from source instead.

## Requirements

- **Python 3.11+**
- **Node.js + npm** — only needed for the web app's frontend, and only to build it
  (not needed at runtime once built)

## Setup

Clone the repo, then from the project root:

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt
```

(On macOS/Linux, use `venv/bin/python` instead of `venv/Scripts/python` throughout
this document.)

### Web app (recommended)

Build the frontend once (re-run this only when the frontend source changes):

```bash
cd web/frontend
npm install
npm run build
cd ../..
```

Then launch the app:

```bash
venv/Scripts/python -m web.launch
```

This starts a local server at `http://127.0.0.1:8756` and opens it in your default
browser automatically. Leave the terminal window open while you use the app — closing
it stops the server. To stop it manually, press `Ctrl+C` in that terminal.

**Or use the packaged version** — no Python/Node needed at runtime once built:

```bash
venv/Scripts/pyinstaller --name PDFEditorWeb --onedir --console \
  --collect-all uvicorn --collect-all fastapi --collect-all starlette \
  --add-data "web/frontend/dist;frontend/dist" -y web/launch.py
```

This produces `dist/PDFEditorWeb/PDFEditorWeb.exe`. Run it directly, or create a
Desktop shortcut to it with `venv/Scripts/python scripts/create_desktop_shortcut.py`
(this is also the script's default target). A console window stays open while the
server runs — close it to stop the app.

**Using it:**

- Pick a tool from the home screen (grouped into Organize / Edit / Optimize / Convert).
- Drop in a PDF — you'll see a real thumbnail grid of its pages.
  - **Remove pages** / **Extract pages**: click a page thumbnail to select it (checkmark
    badge appears), click again to deselect.
  - **Reorder pages**: drag thumbnails into the order you want.
  - Every other tool just shows the pages as a preview while you set options.
- Click **Run**, then **Download** the result once it finishes.
- **Recent Files** (top-right nav) lists everything the app has produced, with
  download and delete buttons.

**Where files go:** every output is saved to `~/Documents/PDF Editor Output/` (on
Windows: `C:\Users\<you>\Documents\PDF Editor Output\`), never overwriting your
original input files. That folder is also where the Recent Files history
(`history.json`) lives.

### Desktop app

```bash
venv/Scripts/python -m app.main
```

This opens the PySide6 desktop window directly — no browser, no server. A prebuilt
Windows executable also exists at `dist/PDFEditor/PDFEditor.exe` (rebuild it with
PyInstaller if you've changed `app/` — see `docs/superpowers/plans/2026-09-01-pdf-editor-v1.md`
for the exact build command), and `scripts/create_desktop_shortcut.py` can create a
Desktop shortcut pointing at it.

## Running tests

```bash
venv/Scripts/python -m pytest -v
```

This runs the full suite — both `app/core/`'s tests (used by the desktop app) and
`web/backend/`'s tests (used by the web app), since both sit on the same core PDF
logic.

## Project layout

```
app/            — desktop app (PySide6) + the shared core PDF logic (app/core/)
web/backend/    — FastAPI backend for the web app, reuses app/core/ unchanged
web/frontend/   — React (Vite) frontend for the web app
web/launch.py   — starts the web app's local server and opens your browser
tests/          — pytest suite for both apps
docs/           — design specs and implementation plans for both builds
scripts/        — Desktop-shortcut creation script (desktop app)
```

## Notes

- Everything runs entirely on your own machine — no data ever leaves it.
- `app/core/` uses PyMuPDF, which is AGPL-3.0 licensed. That's a non-issue for this
  personal, non-commercial project; see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`
  for the reasoning if you're curious.
