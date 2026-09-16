# Desktop App: The 10 Easy Missing Dialogs — Design

**Status:** Approved by user 2026-09-17.

## Context

The desktop (PySide6) app and the web app share the exact same core PDF
engine (`app/core/`), but the desktop UI has fallen well behind: `app/main.py`
registers only 10 of the web app's 26 tools (verified fresh against
`web/frontend/src/toolConfigs.js`, not assumed from memory — the earlier
figure of "24 tools" floated in conversation was off by two). The 16 missing
tools split into two very different buckets by UI complexity:

- **10 fit the existing dialog pattern directly** (a few option widgets, one
  input file, one output) — these are this spec's scope: Add page numbers,
  Repair PDF, Protect PDF, OCR PDF, PDF to PDF/A, Unlock PDF, PDF to
  Markdown, PDF to PowerPoint, PDF to Excel, Images to PDF.
- **6 need genuinely new interactive widgets** PySide6 doesn't have yet
  (drag-a-rectangle page selectors, a signature canvas, a form-filling
  overlay, a diff view, and — by far the largest — a full port of the
  1900+ line `EditPdfCanvas.jsx` canvas editor). Explicitly out of scope
  here; each gets its own future brainstorm: Crop PDF, Redact PDF, Sign PDF,
  PDF Forms, Compare PDF, Edit PDF.

`app/ui/dialogs/base.py`'s `ToolDialog` already does everything a simple
dialog needs — file picking, a thumbnail-strip preview, a background
`Worker` thread, progress, and a "Show in folder" button — via three
override points: `build_options(container)`, `gather_params() -> dict`, and
`run_operation(input_paths, params) -> list[str]`. The existing
`CompressDialog` (one slider, ~20 lines) is the template every one of these
10 follows.

## Scope decisions (from brainstorming)

- **This spec covers exactly the 10 easy tools**, chosen over full parity
  (all 16) because the 6 hard ones are a different order of effort — Edit
  PDF alone is a multi-session project on its own — and bundling them here
  would block the quick, low-risk wins on the hardest, riskiest piece.
- **`ToolDialog.run_operation`'s contract gains one backward-compatible
  extension**: it may return either `list[str]` (unchanged for every
  existing dialog) or `(list[str], message)`, where `message` overrides the
  default "Done — N file(s) created." status text. Used by the new
  `RepairDialog` and `OcrDialog` specifically, to match the web app's own
  friendly result messages ("File is healthy — 3 pages.", "OCR'd 3 of 5
  pages — 2 already had text.") rather than leaving the desktop app with a
  generic message the web app doesn't show for these two tools.
- **Every new dialog slots into an existing category file** (`edit_dialogs.py`,
  `optimize_dialogs.py`, `convert_dialogs.py`) rather than creating new
  files — matching the current one-file-per-category organization, and
  keeping each file's growth proportionate (the biggest, `optimize_dialogs.py`,
  goes from 1 dialog to 6, still well within a single readable file).
- **Images to PDF's filename validation is duplicated, not centralized.**
  The exact same empty/path-separator checks already exist independently in
  both `web/backend/routes/tools.py`'s `_sanitize_output_filename` and
  `MergeDialog.run_operation` (the desktop app's own pre-existing multi-file
  dialog) — a third copy for `ImagesToPdfDialog` matches the established
  precedent in this exact file rather than introducing a new shared helper
  that would touch otherwise-unrelated code just for this project.
- **Images to PDF's thumbnail preview only shows the first selected image**,
  not one thumbnail per image — not a new gap, but the exact same limitation
  `MergeDialog` already has today (the base class's thumbnail strip only
  ever renders `paths[0]`'s own pages, regardless of how many files are
  selected). Not fixed here; out of scope for this project.

## Architecture

### `ToolDialog` base class change

In `app/ui/dialogs/base.py`, `_on_success` currently does:
```python
def _on_success(self, output_paths) -> None:
    self.progress.setVisible(False)
    self.run_button.setEnabled(True)
    self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
    self.status_label.setText(f"Done — {len(self._output_paths)} file(s) created.")
    self.open_folder_button.setEnabled(True)
```
It becomes:
```python
def _on_success(self, result) -> None:
    self.progress.setVisible(False)
    self.run_button.setEnabled(True)
    if isinstance(result, tuple):
        output_paths, message = result
    else:
        output_paths, message = result, None
    self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
    if message is None:
        message = f"Done — {len(self._output_paths)} file(s) created."
    self.status_label.setText(message)
    self.open_folder_button.setEnabled(True)
```
`run_operation`'s docstring gains one sentence documenting the new optional
return shape. `Worker.finished_ok = Signal(object)` already accepts any
Python object, so no change needed there.

### The 10 new dialogs

Each is a `ToolDialog` subclass; every field/option below was read directly
from `web/frontend/src/toolConfigs.js` and the exact `app/core` function
signature it calls, not inferred:

| Dialog | File | Options | Core call | Output |
|---|---|---|---|---|
| `AddPageNumbersDialog` | `edit_dialogs.py` | 2× `QComboBox`: position (6 values: `bottom-center`/`bottom-right`/`bottom-left`/`top-center`/`top-right`/`top-left`), format (3 values: `number`/`number-of-total`/`page-x-of-y`) | `add_page_numbers(input_path, output_path, position, format)` | `<stem>_numbered.pdf` |
| `RepairDialog` | `optimize_dialogs.py` | none | `repair_pdf(input_path, output_path) -> {"page_count", "warnings_count"}` | `<stem>_repaired.pdf`, message: `"File is healthy — N page(s)."` or `"Recovered N page(s) after M structural issue(s) found."` |
| `ProtectDialog` | `optimize_dialogs.py` | `QLineEdit` password, `EchoMode.Password`, `setMaxLength(127)` | `protect_pdf(input_path, output_path, password)` (already raises `PDFError("Enter a password.")` for empty — no dialog-side check needed) | `<stem>_protected.pdf` |
| `OcrDialog` | `optimize_dialogs.py` | 8× `QCheckBox` in a grid (eng/spa/fra/deu/por/chi_sim/jpn/ara, English checked by default), 1× `QCheckBox` "Also convert to PDF/A" | `ocr_pdf(input_path, output_path, languages, convert_to_pdfa) -> {"pages_ocred", "pages_skipped"}` (already raises `PDFError("Select at least one language.")` for an empty list — no dialog-side check needed) | `<stem>_ocr.pdf`, message: `"OCR'd all N page(s)."` or `"OCR'd N of M pages — K already had text."` |
| `PdfToPdfaDialog` | `optimize_dialogs.py` | none | `pdf_to_pdfa(input_path, output_path)` | `<stem>_pdfa.pdf` |
| `UnlockDialog` | `optimize_dialogs.py` | `QLineEdit` password, `EchoMode.Password` (no length cap — `unlock_pdf` just tries opening with whatever's given) | `unlock_pdf(input_path, output_path, password)` | `<stem>_unlocked.pdf` |
| `PdfToMarkdownDialog` | `convert_dialogs.py` | none | `pdf_to_markdown_zip(input_path, output_path)` | `<stem>_markdown.zip` |
| `PdfToPptxDialog` | `convert_dialogs.py` | none | `pdf_to_pptx(input_path, output_path)` | `<stem>.pptx` |
| `PdfToXlsxDialog` | `convert_dialogs.py` | none | `pdf_to_xlsx(input_path, output_path)` (already raises `PDFError("No tables found in this document.")` — no dialog-side check needed) | `<stem>.xlsx` |
| `ImagesToPdfDialog` | `convert_dialogs.py` | `allow_multiple_files = True`, `file_filter = "Image files (*.jpg *.jpeg *.png)"`; `QLineEdit` filename (auto-filled `<first-image-stem>_combined.pdf` via `on_files_changed`, matching `MergeDialog`'s exact pattern); `QComboBox` fit mode (`fit`/`fill`) | `images_to_pdf(image_paths, output_path, fit_mode)` | `<filename>.pdf` (user-named, like Merge) |

Password fields use `QLineEdit.EchoMode.Password` — no existing dialog has
a password field yet, so this is the first one; matches Qt's standard
masked-input convention, nothing custom needed.

### `app/main.py`

Ten new `window.add_tool(category, label, DialogClass)` calls, matching
each tool's category from `toolConfigs.js` exactly (Add page numbers →
"Edit"; Repair/Protect/OCR/PDF to PDF/A/Unlock → "Optimize"; PDF to
Markdown/PowerPoint/Excel/Images to PDF → "Convert") and ten new imports
from the three category dialog modules.

## Testing

This project has no existing test suite of its own — `app/ui/` has never
had automated tests this session or before (its dialogs are thin
wrappers around already-tested `app/core/` functions, and PySide6 widget
tests would need a `pytest-qt`-style harness this codebase doesn't have).
No automated tests are added here, matching that established (absence of)
convention — manual verification only:

For each of the 10 dialogs: launch the desktop app (`python -m app.main`),
open the dialog from its category group box, load a real test file,
exercise every option field, click Run, confirm the output file exists with
the correct name/extension in the same folder as the input, confirm "Show
in folder" opens it, and confirm a deliberately-invalid input (wrong
password for Unlock, a table-less PDF for PDF to Excel) surfaces the
correct error via `QMessageBox.critical` rather than crashing. For Repair
and OCR specifically, confirm the status label shows the new friendly
message text, not the generic fallback.

## Out of scope

- The 6 hard tools (Crop, Redact, Sign, PDF Forms, Compare, Edit PDF) —
  each needs its own future brainstorm; Edit PDF in particular is a
  substantial project on its own.
- Centralizing the duplicated output-filename validation logic (see scope
  decisions above) — matches existing precedent, not a new gap introduced
  here.
- Per-file thumbnail previews for multi-file dialogs (`MergeDialog`,
  `ImagesToPdfDialog`) — pre-existing limitation, unrelated to closing the
  tool gap.
- Any change to the web app's tools, routes, or `app/core/` — every
  function this spec calls already exists and is already tested via the
  web app's own test suite; this is a pure desktop-UI addition.
