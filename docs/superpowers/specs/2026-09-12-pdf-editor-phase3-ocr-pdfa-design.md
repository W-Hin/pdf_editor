# Phase 3, Group 4: OCR + PDF→PDF/A — Design

**Status:** Approved by user 2026-09-12.

## Context

Last remaining group of Phase 3 (see the decomposition and queue order in
`docs/superpowers/specs/2026-09-06-pdf-editor-phase3-compare-markdown-design.md`'s Context
section). Originally bundled with Office→PDF (via headless LibreOffice) as "both need the same
kind of external-binary investigation" — that pairing is now dissolved. **Office→PDF via
LibreOffice is DROPPED from scope entirely** (not deferred — permanently excluded), per the
user's own explicit decision: LibreOffice has no official slim/headless-only build (~350-400MB
installer, ~1.5-2GB installed) and no realistic way to trim it down for just PDF export, versus
this group's two dependencies which are genuinely small enough to bundle; the user can export
Office documents to PDF from within Office itself instead.

Both required external binaries — Tesseract (OCR engine) and Ghostscript (PDF/A engine, via
`ocrmypdf`) — are now installed and verified working in the dev environment: Tesseract 5.4.0 (via
winget, UB Mannheim build) and Ghostscript 10.08.0 (official Artifex GitHub release, download
hash verified before running). Before writing this spec, both directions were verified
empirically end-to-end:

- `ocrmypdf` (MPL-2.0, pip-installable, wraps both Tesseract and Ghostscript internally) produces
  a genuinely searchable PDF from a real image-only test fixture — the exact original text was
  recovered correctly via a single `ocrmypdf.ocr(...)` call, no manual page-rendering or
  PyMuPDF text-merging needed.
- `ocrmypdf --skip-text --output-type pdfa` on an already-text-only PDF correctly skips OCR
  entirely and converts straight to PDF/A-2b — confirmed via its own log output
  (`"skipping all processing on this page"`) — proving the same library cleanly serves the
  standalone PDF→PDF/A use case with zero OCR involvement.
- `ocrmypdf`'s own "auto" output-type default silently converts to PDF/A unless explicitly told
  `output_type="pdf"` — a real gotcha, now an explicit Global Constraint below.
- Tesseract's `-l LANG[+LANG]` flag (and `ocrmypdf`'s `language=` parameter) supports running
  multiple languages in one pass, confirmed via `tesseract --help-extra`.
- `ocrmypdf` does NOT rely on `PATH` alone to find Tesseract/Ghostscript on Windows — it also
  checks the Windows Registry (`HKLM\SOFTWARE\Tesseract-OCR\InstallDir`,
  `HKLM\SOFTWARE\Artifex\GPL Ghostscript\<version>`) and scans `%PROGRAMFILES%` for folders named
  `Tesseract-OCR`/`gs` (confirmed by reading `ocrmypdf/subprocess/_windows.py`'s `SHIMS` list).
  `PATH` is checked first in that list, so explicitly prepending our bundled binaries' folder to
  `os.environ["PATH"]` at app startup is what guarantees our tested, vendored copies are used
  rather than whatever might (or might not) already be installed on an end user's machine. This
  was proven, not just reasoned about: a dedicated isolation test set `os.environ["PATH"]` (via
  Python, before importing `ocrmypdf` — matching real app startup order) to point at ONLY a
  trimmed copy of each binary, with no access to the machine's actual Tesseract/Ghostscript
  installs at all, and confirmed both `ocrmypdf.subprocess`'s own debug log (showing it resolved
  and ran the trimmed copies' exact paths) and the resulting output (correct OCR'd text, valid
  PDF/A-2b) end-to-end.
- A trimmed Tesseract runtime (just `tesseract.exe` + its DLLs + trained-data files, dropping the
  training-tool executables, Java-based `ScrollView` GUI, and docs the full installer ships) is
  ~160MB — dominated by a single unavoidable 101MB `libtesseract-5.dll` (the actual OCR engine,
  can't be shrunk without a custom from-source build, out of scope). A trimmed Ghostscript runtime
  (dropping `doc/`, `examples/`, and the 32-bit binary) is ~42MB and confirmed to run standalone
  (`gswin64c.exe -c quit`, and a real PDF/A conversion via its own `lib/PDFA_def.ps`).

## Scope decisions (from brainstorming)

- **Two separate tools, not one combined tool.** OCR (make a scanned/image-only PDF searchable)
  and PDF/A (convert to a locked-down archival format) solve unrelated problems and are almost
  never wanted together in the same action — matches this app's established one-tile-one-job
  pattern (e.g. Repair/Unlock/Protect are three tiles despite sharing one `pikepdf`-based core
  module). They share one internal module (`app/core/ocr.py`) exactly the way those three share
  `pdf_repair.py`.
- **OCR only touches pages that need it.** `skip_text=True` is always on for the OCR tool — pages
  that already have real, extractable text are left completely untouched, matching this project's
  established "only fix what genuinely needs it" pattern (e.g. PDF→Excel only includes pages with
  a genuinely detected table).
- **OCR output stays a plain PDF unless the user explicitly opts into PDF/A.** A checkbox on the
  OCR tool, *"Also convert to PDF/A"*, with a tooltip explaining PDF/A in plain terms. This
  requires overriding `ocrmypdf`'s own default behavior (see Context above) — `output_type` is
  always passed explicitly (`"pdf"` or `"pdfa"`), never left to `ocrmypdf`'s own `"auto"` default.
- **PDF/A always targets conformance level 2b**, with no level picker exposed anywhere — the
  modern default most archival systems expect, and matches this app's established pattern of not
  exposing configuration nobody needs (e.g. Protect's fixed AES-256/R=6 encryption, no separate
  permissions UI).
- **Eight bundled OCR languages**: English (default-checked), Spanish, French, German, Portuguese,
  Chinese (Simplified), Japanese, Arabic — chosen from Tesseract's official `tessdata_fast` release
  (the compact/general-purpose trained-data variant, confirmed via the GitHub releases listing:
  each file is under 2.5MB, dramatically smaller than the "full"/"best" variants). The OCR tool
  exposes these as a multi-select checkbox list (not a single dropdown) since Tesseract can OCR
  multiple languages in one pass — useful for a genuinely mixed-language document — and running
  OCR narrowly focused on the actual language(s) present is more accurate than trying to guess
  across all eight simultaneously.
- **Automatic page-orientation correction is included** (`osd.traineddata`, 10.5MB — bigger than
  all seven non-English languages combined) — a genuinely common real-world problem with scanned
  documents (misfed pages, wrong scanner orientation setting), and OCR accuracy on a sideways or
  upside-down page is otherwise near zero.
- **Total installer size impact accepted by the user**: ~230MB added (Tesseract runtime + all
  language/orientation data ≈ 188MB, Ghostscript runtime ≈ 42MB), taking the installer from its
  current 73MB to roughly 300MB. Confirmed explicitly after two upward revisions from an initial
  rougher estimate — the user reviewed the real, itemized numbers before approving.

## Architecture

### Core module

`app/core/ocr.py` (new):

```python
def ocr_pdf(input_path: str, output_path: str, languages: list[str], convert_to_pdfa: bool) -> dict:
```

Wraps `ocrmypdf.ocr(input_path, output_path, language="+".join(languages), skip_text=True,
output_type="pdfa" if convert_to_pdfa else "pdf", progress_bar=False)`. Returns a small dict
report (pages OCR'd vs. skipped) for the route's success message — derived by comparing each
page's extractable-text state before and after via PyMuPDF (`page.get_text()` non-empty check),
not by parsing `ocrmypdf`'s own log output.

```python
def pdf_to_pdfa(input_path: str, output_path: str) -> None:
```

Wraps `ocrmypdf.ocr(input_path, output_path, skip_text=True, output_type="pdfa",
progress_bar=False)` unconditionally — never re-OCRs anything, purely a format conversion. Works
correctly (confirmed empirically) even on a document that's already 100% real text, or already
PDF/A-compliant (harmless re-save).

Both functions:
- Validate the bundled binaries exist (see Packaging below) before calling `ocrmypdf`, raising a
  clear `PDFError` if the installation is broken rather than letting a missing-dependency error
  from `ocrmypdf` itself surface.
- Wrap any exception `ocrmypdf` itself raises (a malformed input it can't process, a page that
  exceeds its size guard) in a plain-message `PDFError` — never let a third-party exception escape
  as a raw 500, matching the established pattern from the PDF-to-Office fix wave.
- `ocr_pdf` additionally rejects an empty `languages` list with
  `PDFError("Select at least one language.")` before calling `ocrmypdf` at all — matches Protect's
  empty-password guard.

### Packaging

A new `ocr_binaries/` folder (top-level, git-ignored like `venv/`) holds the vendored runtime:
`tesseract.exe` + its DLLs + `tessdata/{eng,osd,spa,fra,deu,por,chi_sim,jpn,ara}.traineddata` **plus
`tessdata/configs/`, `tessdata/tessconfigs/`, and `tessdata/pdf.ttf`** (40KB total, negligible —
found only after a dedicated isolation test: a `.traineddata`-only `tessdata/` folder fails with
`TesseractConfigError: Error occurred while parsing a Tesseract configuration file`, because
`ocrmypdf`'s hocr/pdf output modes need Tesseract's own plain-text config files and PDF-embedding
font, not just the trained-data models), and
`gswin64c.exe` + its DLL + `Resource/`, `lib/`, `iccprofiles/` (the exact file sets verified this
session — `doc/`, `examples/`, training-tool executables, and the 32-bit Ghostscript binary are
excluded). Populated by a new `scripts/vendor_ocr_binaries.py` (documents exactly which files come
from where, so a future Tesseract/Ghostscript version bump has a clear, repeatable process rather
than someone re-deriving the trimmed file set from scratch).

`PDFEditorWeb.spec` gains `binaries`/`datas` entries pointing at `ocr_binaries/`, landing at
`ocr_binaries/` inside the PyInstaller bundle (same `sys._MEIPASS`-relative pattern
`web/backend/main.py` already uses for `frontend/dist` and `VERSION`).

At startup, before any OCR/PDF/A call, the app resolves the bundled binaries' directory (using the
same `hasattr(sys, "_MEIPASS")` branch `appinfo.py` already uses) and prepends it to
`os.environ["PATH"]`. This is necessary — not optional — because `ocrmypdf`'s own binary-discovery
falls back to the Windows Registry and a `Program Files` scan if `PATH` doesn't resolve; putting
our bundled folder first in `PATH` is what guarantees the app uses its own tested binaries rather
than silently picking up whatever (if anything) happens to already be installed system-wide on an
end user's machine.

### API and frontend

- `POST /api/tools/ocr` — `{file_id, languages: list[str], convert_to_pdfa: bool}`, following the
  established `_output_response(paths, tool, source_filenames, message=None)` pattern, with the
  message reporting pages OCR'd vs. skipped (e.g. `"OCR'd 4 of 6 pages — 2 already had text."`,
  singular/plural handled the same way Repair's message already does).
- `POST /api/tools/pdf-to-pdfa` — `{file_id}`, no fields, matching Repair's shape exactly.
- Two new grid tiles under the **Optimize** category (alongside Repair/Protect) — this app's
  existing home for "fix up an existing file" tools, rather than a new category for just two tools.
- `toolConfigs.js` gains two entries. The OCR entry needs a new field TYPE this project's generic
  `ToolView.jsx` field renderer doesn't have yet: a multi-select checkbox group (for the 8
  languages) and a single checkbox with an attached tooltip (for "Also convert to PDF/A") — both
  small, justified generalizations of the same generic field-rendering `switch` that already grew
  a `password` branch (with `maxLength`) during the Repair/Unlock/Protect group. `pdf-to-pdfa`
  needs no new field types — `fields: []`, matching Repair.

## Testing

`tests/test_ocr.py` (new file, house style — throwaway PDFs built with `fitz` at test time, every
empirically-derived number verified this session before being written here):

- `test_ocr_pdf_adds_searchable_text_to_image_only_page`: a genuine image-only fixture (rendered
  text baked into a raster image, zero extractable text going in — mirrors this session's own
  `probe_ocr_input.pdf`/`probe_ocr_output.pdf` verification) — asserts the exact source text is
  extractable afterward.
- `test_ocr_pdf_skips_pages_that_already_have_text`: a 2-page mixed document (one image-only page,
  one already-text page) — asserts the already-text page's content is byte-identical, only the
  image-only page gains new text.
- `test_ocr_pdf_with_pdfa_checkbox_produces_valid_pdfa`: asserts the output's PDF/A identifier
  metadata is present when `convert_to_pdfa=True`, absent when `False`.
- `test_pdf_to_pdfa_converts_text_only_document_without_ocr`: asserts a plain-text input converts
  to PDF/A correctly and that no OCR pass occurs (verifiable — `ocrmypdf`'s own `skip_text` logic
  means an all-text document's OCR step is a genuine no-op, confirmed this session via its
  `"skipping all processing on this page"` log line for exactly this case).
- `test_ocr_pdf_rejects_empty_language_list`: asserts `PDFError`.
- `test_ocr_pdf_raises_when_bundled_binaries_missing`: simulates a broken/missing
  `ocr_binaries/` install and asserts a clean `PDFError`, not a raw `ocrmypdf` exception.

No automated test for actual OCR *accuracy* (inherently fuzzy, model- and fixture-dependent) —
only correctness of the plumbing (text present/absent, pages skipped/not, PDF/A metadata
present/not).

No frontend automated tests (established convention) — manual checklist: OCR a real scanned
(or scan-simulated) PDF and confirm the text becomes selectable/searchable in the downloaded
file; run PDF-to-PDF/A on a normal document and confirm the output opens correctly; verify the
language checkboxes and the PDF/A tooltip render and behave correctly.

## Out of scope

- Any language beyond the eight bundled — a future addition if genuinely needed, not blocking this
  pass. Adding one is a small, low-risk change (one more `.traineddata` file + one more checkbox).
- A PDF/A conformance-level picker (1b/1a/3b, etc.) — fixed at 2b per the scope decision above.
- OCR accuracy tuning (DPI overrides, image preprocessing/deskew flags `ocrmypdf` exposes,
  `--redo-ocr`/`--force-ocr` re-OCR modes) — the default `skip_text` behavior with `ocrmypdf`'s own
  internal rendering is the only mode this pass exposes.
- Office→PDF via LibreOffice — permanently dropped from the roadmap, per the Context section above.
