# PDF Editor

A personal, offline, open-source PDF toolkit covering organizing, editing, optimizing,
and converting PDFs, all running locally on your own machine. No internet connection is
required — the only thing that ever reaches the network is an optional, best-effort
check for newer releases, which fails silently if you're offline.

There are two ways to use it:

- **Web app** (recommended) — a local browser-based app with a clickable page-thumbnail
  grid and a Recent Files history. This is what the Windows installer packages.
- **Desktop app** — a native PySide6 window. It now has **every tool the web app has**
  (all 26), including the full Edit PDF editor. It is run from source (see below); the
  installer does not include it.

Both share the same underlying PDF engine (`app/core/`), so results are identical
either way — they just differ in the UI. See [CHANGELOG.md](CHANGELOG.md) for what
changed in each release.

## Features

- **Organize** — Merge, Split, Remove pages, Extract pages, Reorder pages
- **Edit** — Rotate, Add watermark, Add page numbers, Crop, Redact, Sign, Fill PDF
  forms, Compare two PDFs, and **Edit PDF**: add text and images, draw freehand, draw
  shapes and arrows, highlight, and edit or restyle existing text in place — with undo /
  redo, copy / paste and arrow-key nudging
- **Optimize** — Compress, Repair a damaged file, Protect with a password, Unlock
  a password-protected file, OCR (adds a searchable text layer to scanned pages,
  with optional PDF/A conversion for long-term archiving)
- **Convert** — PDF to Image, PDF to Word, PDF to Markdown, PDF to PowerPoint,
  PDF to Excel, Images to PDF

## Easiest way to get it (Windows, no setup required)

Download and run the installer from the
[latest release](https://github.com/W-Hin/pdf_editor/releases/latest) —
`PDFEditorSetup.exe`. It installs the **web app** to your user folder (no admin rights
needed), adds a Start Menu entry, and optionally a Desktop shortcut. No Python, no Node,
nothing else to install. The app checks for newer releases on launch and shows a
banner if one's available — updating just means running the newer installer.

Everything below is for building it from source instead.

## Requirements

- **Python 3.11+**
- **Node.js + npm** — only needed for the web app's frontend, and only to build it
  (not needed at runtime once built)
- **Tesseract + Ghostscript** (only for the OCR/PDF-to-PDF/A tools) — the packaged
  Windows installer bundles trimmed copies of both, so end users never need to
  install anything. Building from source instead, `app/core/ocr.py` only looks
  under a git-ignored `ocr_binaries/` folder at the repo root (it does not fall
  back to a system-wide install on `PATH`) — install Tesseract and Ghostscript via
  their normal installers, then run `scripts/vendor_ocr_binaries.py` once to
  populate that folder. Every other tool works without either.

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
- Drop in a PDF (or image files, for **Images to PDF**) — you'll see a real
  thumbnail grid of its pages.
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

This opens the PySide6 desktop window directly — no browser, no server. Tools are
grouped Organize / Edit / Optimize / Convert on the home window, matching the web app.

**Edit PDF** works on all pages at once (scroll through them). Pick a mode, then work
directly on the page:

- **New Text** — click to place a box and type. **Insert Image** — click, pick a picture.
- **Draw**, **Shapes** (rectangle / ellipse / line / arrow, optionally filled) and
  **Highlight** — drag on the page; each tool has its own colour (and width) row.
- **Edit Text** — double-click an existing line of text to edit it in place. Select part
  of it and use the family / size / **B** / *I* controls to restyle just that part;
  **Revert** restores the original.
- Click any element to select it, then drag to move, use the corner handle to resize
  (where it applies), or the small red button to delete. Arrow keys nudge (hold Shift for
  bigger steps); Ctrl+Z / Ctrl+Y undo and redo; Ctrl+C / Ctrl+X / Ctrl+V copy, cut and
  paste (edited text can't be copied). The toolbar buttons do the same, plus bring-to-front
  and send-to-back.
- Press **Run** to write `<name>_edited.pdf`.

A prebuilt Windows executable can be made with PyInstaller (see
`docs/superpowers/plans/2026-09-01-pdf-editor-v1.md` for the exact build command) — rebuild
it after any change to `app/`, since an older build won't have newer tools — and
`scripts/create_desktop_shortcut.py` can create a Desktop shortcut pointing at it.

## Running tests

```bash
venv/Scripts/python -m pytest -v
```

This runs the full suite — `app/core/`'s tests (used by both apps), `app/ui/`'s
tests (desktop-only interactive-widget behavior), and `web/backend/`'s tests (the
web app's own routes).

## Project layout

```
app/            — desktop app (PySide6) + the shared core PDF logic (app/core/)
web/backend/    — FastAPI backend for the web app, reuses app/core/ unchanged
web/frontend/   — React (Vite) frontend for the web app
web/launch.py   — starts the web app's local server and opens your browser
tests/          — pytest suite for both apps
docs/           — design specs and implementation plans for both builds
scripts/        — Desktop-shortcut creation script, and the one-time OCR-binary
                  vendoring script used to prepare the packaged installer
```

## Notes

- Everything runs entirely on your own machine — no data ever leaves it.
- `app/core/` uses PyMuPDF, which is AGPL-3.0 licensed. That's a non-issue for this
  personal, non-commercial project; see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`
  for the reasoning if you're curious.
