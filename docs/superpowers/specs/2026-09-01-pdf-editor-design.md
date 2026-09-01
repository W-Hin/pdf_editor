# PDF Editor — Design Spec

Date: 2026-09-01
Status: Approved for planning

## Purpose

A personal, offline, open-source desktop PDF toolkit that replicates the
useful subset of iLovePDF's feature set, for the user's own use (not for
distribution or monetization). The original motivation: converting PDFs to
.docx to edit them causes alignment/layout drift, and there's no offline
open-source app that covers PDF editing + conversion in one place.

Not a goal: pixel-perfect replication of every iLovePDF feature. AI-driven
features (summarization, translation) are explicitly out of scope — they
require a different class of dependency (a bundled LLM / translation model)
than the rest of this app and don't fit the "lightweight open-source PDF
toolkit" framing.

## Architecture

- **Language**: Python.
- **PDF engine**: [PyMuPDF](https://pymupdf.readthedocs.io/) (`fitz`) as the
  primary library for nearly all operations — merge, split, rotate,
  delete/reorder/extract pages, watermark, crop, page numbers, render-to-image,
  basic compression (stream deflate + garbage collection), redaction, and
  (in Phase 2) direct text editing and form filling. Chosen because one
  capable library covers most of the feature list instead of stitching
  together four narrower ones.
  - License note: PyMuPDF is AGPL-3.0 (or a paid commercial license). Since
    this app is personal, non-monetized, and fine being open-source itself,
    AGPL is a non-issue. If that ever changes, the fallback is `pypdf`
    (BSD) for page ops, but it can't render pages to images, so a second
    library would be needed anyway.
- **PDF→Word**: [`pdf2docx`](https://github.com/dothinking/pdf2docx) (built
  on PyMuPDF). Produces layout-preserving DOCX using positioned text
  boxes/tables rather than true flowing paragraphs — better alignment
  fidelity than a naive converter, but not perfect on complex/multi-column
  layouts. This limitation is inherent to any PDF→DOCX conversion (PDF is
  fixed-layout, DOCX is flow-based) and is why Phase 2 adds direct in-PDF
  text editing as the pixel-perfect alternative for simple edits.
- **UI**: PySide6 (Qt for Python, LGPL) — a tool-grid home screen (à la
  iLovePDF), where each tool opens a dialog with a consistent pattern:
  select input file(s) → configure options → run → show output location.
- **Threading**: Long-running operations (compress, convert, OCR) run on a
  `QThread` worker so the UI doesn't freeze, with a progress indicator.
- **Packaging**: PyInstaller (`--onedir`) builds a standalone Windows folder
  with a `.exe` — no Python install required to run it. Once built and
  verified, a `.lnk` shortcut is created on the Desktop pointing at the exe.

## Components

```
app/
  main.py            — Qt app entry point
  ui/
    main_window.py    — tool-grid home screen
    tool_dialogs.py   — shared dialog pattern: pick file(s) → options → run → output
  core/
    pdf_ops.py         — merge, split, rotate, delete/reorder/extract pages,
                          watermark, crop, page numbers, compress, render-to-images
    convert.py          — PDF → Word (pdf2docx)
    workers.py          — QThread wrappers for background execution
tests/
  test_pdf_ops.py       — pytest; generates small sample PDFs on the fly and
                           asserts each operation's output (page count,
                           rotation angle, watermark presence, image dims)
```

Each tool in the grid is: a `core/` function (pure, testable, no Qt
dependency) + a thin dialog registered in the grid. Adding a tool later is
"write the function, register the dialog" — no architectural change needed.

## Data flow

1. User opens the app to the tool grid.
2. Clicks a tool → dialog opens, asking for input file(s) (file picker or
   drag-drop) and any options (rotation angle, watermark text, etc).
3. On submit, the operation runs on a background thread with a progress bar.
4. Output is written next to the input file with a suffix (e.g.
   `report_merged.pdf`) — never overwrites the original — with a "Show in
   folder" button on completion.

## Error handling

- Every file open is validated (corrupt file / not actually a PDF) with a
  plain-language error dialog instead of a raw exception/stack trace.
- Password-protected PDFs: v1 shows a clear "this file is encrypted, unlock
  it first" message rather than crashing (actual unlock/protect support is
  a Phase 3 tool).
- Output write failures (permissions, disk full) are caught and reported
  the same way, not swallowed.

## Testing

- `pytest` unit tests for everything in `core/`. Each test generates a
  small throwaway PDF at run time (via PyMuPDF) and asserts the operation
  did what it claims.
- No automated UI tests for v1 — Qt UI testing is heavy machinery for a
  solo personal project, and the risk surface lives in the PDF logic, not
  the widgets. UI gets a manual smoke-test checklist instead.

## Feature roadmap

### V1 (this build)
Merge, Split, Remove pages, Extract pages, Organize/reorder pages, Rotate,
Add watermark, Compress, PDF→JPG (render to images), PDF→Word.

(Extract pages and Organize/reorder are folded into v1 alongside the
originally-agreed 8, since they reuse the same page-manipulation code as
Split/Remove at near-zero extra cost.)

### Phase 2
Crop, Add page numbers, direct in-PDF text editing (find/replace a text run
in place — pixel-perfect alignment, not a word processor), Redact, PDF
Forms (fill AcroForms), Sign (place a signature image/drawing — not
cryptographic signing), JPG→PDF, Scan to PDF.

### Phase 3
Repair (pikepdf/qpdf recovery), OCR (`ocrmypdf` wrapping Tesseract), Unlock
/ Protect (pikepdf encrypt/decrypt), Word/PowerPoint/Excel/HTML→PDF
(headless LibreOffice — the only solid open-source route for office
formats), PDF→PowerPoint and PDF→Excel (best-effort only — no strong
open-source converter exists for these; low fidelity expected), PDF→PDF/A,
Compare PDF (text diff), PDF→Markdown (`pymupdf4llm`).

### Not planned
AI Summarizer, Translate PDF — require a bundled LLM / translation model,
a different dependency class than the rest of the app. Could be revisited
as a separate stretch project later, but out of scope here.

## Open questions / risks

- PDF→Word and PDF→PowerPoint/Excel fidelity is inherently limited by the
  format mismatch; this is communicated to the user in-app (not a bug to
  "fix" later, a known ceiling).
- AGPL licensing of PyMuPDF is accepted as fine for this personal,
  non-monetized, open project (see Architecture section).
