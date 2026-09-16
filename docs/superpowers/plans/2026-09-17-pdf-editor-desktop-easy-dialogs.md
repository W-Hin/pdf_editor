# Desktop App: The 10 Easy Missing Dialogs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 10 of the desktop (PySide6) app's 16 missing tools, bringing it to 20 of the web app's 26 tools — the 10 that fit the existing simple-dialog pattern without needing any new interactive widgets.

**Architecture:** Each tool becomes a `ToolDialog` subclass (file picker + options + background worker + progress, already provided by the base class) slotted into the existing category dialog file it belongs in, calling an already-existing, already-tested `app/core` function. One small, backward-compatible extension to the base class lets two of the new dialogs show a custom result message instead of the generic one.

**Tech Stack:** Python, PySide6.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task in this plan ships new, intentional behavior — commits are `feat:` and must **not** carry the trailer.
- No automated tests exist for `app/ui/` and none are added here — every task ends in a manual verification pass, not a pytest run.
- Every new dialog's output filename/extension must exactly match what's given in each task below — these were copied verbatim from the web app's own backend routes, so both UIs produce identically-named output files for the same operation.

---

### Task 1: `optimize_dialogs.py` — Repair, Protect, OCR, PDF to PDF/A, Unlock + the base-class result-message extension

**Files:**
- Modify: `app/ui/dialogs/base.py` (`ToolDialog._on_success`, currently lines 161-166, and `run_operation`'s docstring, currently lines 93-97)
- Modify: `app/ui/dialogs/optimize_dialogs.py` (currently 27 lines, just `CompressDialog`)
- Modify: `app/main.py` (import line 9, registration lines 15-24)

**Interfaces:**
- Consumes: nothing from another task (this is the first task).
- Produces: `ToolDialog.run_operation`'s new optional return shape `(list[str], str)` — Tasks 2 and 3 don't need this, but any future dialog can use it the same way `RepairDialog`/`OcrDialog` do here.

- [ ] **Step 1: Extend the base class to support a custom result message**

In `app/ui/dialogs/base.py`, replace `_on_success` (currently):
```python
    def _on_success(self, output_paths) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
        self.status_label.setText(f"Done — {len(self._output_paths)} file(s) created.")
        self.open_folder_button.setEnabled(True)
```
with:
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

Replace `run_operation`'s docstring (currently):
```python
    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        """Override in subclasses: perform the operation, return output path(s).
        Runs on a background thread — read only from `params` (see `gather_params`),
        never from `self.<widget>`."""
        raise NotImplementedError
```
with:
```python
    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        """Override in subclasses: perform the operation, return output path(s).
        Runs on a background thread — read only from `params` (see `gather_params`),
        never from `self.<widget>`. May instead return `(output_paths, message)` to
        override the default "Done — N file(s) created." status text with a custom
        one (e.g. a result summary)."""
        raise NotImplementedError
```
`Worker.finished_ok = Signal(object)` (`app/ui/workers.py`) already accepts any
Python object unchanged — no change needed there.

- [ ] **Step 2: Add the 5 new dialogs to `optimize_dialogs.py`**

Replace the whole file's imports and add these five classes after `CompressDialog` (keep `CompressDialog` exactly as-is):
```python
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel, QSlider, QLineEdit, QCheckBox

from app.core.pdf_ops import compress_pdf
from app.core.pdf_repair import repair_pdf, protect_pdf, unlock_pdf
from app.core.ocr import ocr_pdf, pdf_to_pdfa
from app.ui.dialogs.base import ToolDialog


class CompressDialog(ToolDialog):
    # ... unchanged, keep exactly as it is today ...


class RepairDialog(ToolDialog):
    title = "Repair PDF"

    def run_operation(self, input_paths: list[str], params: dict) -> tuple[list[str], str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_repaired.pdf"))
        result = repair_pdf(input_path, out_path)
        if result["warnings_count"] == 0:
            message = f"File is healthy — {result['page_count']} page{'s' if result['page_count'] != 1 else ''}."
        else:
            message = (
                f"Recovered {result['page_count']} page{'s' if result['page_count'] != 1 else ''} "
                f"after {result['warnings_count']} structural issue{'s' if result['warnings_count'] != 1 else ''} found."
            )
        return [out_path], message


class ProtectDialog(ToolDialog):
    title = "Protect PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMaxLength(127)
        layout.addWidget(self.password_input)

    def gather_params(self) -> dict:
        return {"password": self.password_input.text()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_protected.pdf"))
        protect_pdf(input_path, out_path, params["password"])
        return [out_path]


class UnlockDialog(ToolDialog):
    title = "Unlock PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Password:"))
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.password_input)

    def gather_params(self) -> dict:
        return {"password": self.password_input.text()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_unlocked.pdf"))
        unlock_pdf(input_path, out_path, params["password"])
        return [out_path]


# (code, checkbox label) pairs — matches the web app's OCR language list exactly.
_OCR_LANGUAGES = [
    ("eng", "English"),
    ("spa", "Spanish"),
    ("fra", "French"),
    ("deu", "German"),
    ("por", "Portuguese"),
    ("chi_sim", "Chinese (Simplified)"),
    ("jpn", "Japanese"),
    ("ara", "Arabic"),
]


class OcrDialog(ToolDialog):
    title = "OCR PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Language(s):"))
        grid = QGridLayout()
        self.language_checks: dict[str, QCheckBox] = {}
        for i, (code, label) in enumerate(_OCR_LANGUAGES):
            box = QCheckBox(label)
            if code == "eng":
                box.setChecked(True)
            self.language_checks[code] = box
            row, col = divmod(i, 2)
            grid.addWidget(box, row, col)
        layout.addLayout(grid)
        self.pdfa_check = QCheckBox("Also convert to PDF/A")
        layout.addWidget(self.pdfa_check)

    def gather_params(self) -> dict:
        languages = [code for code, box in self.language_checks.items() if box.isChecked()]
        return {"languages": languages, "convert_to_pdfa": self.pdfa_check.isChecked()}

    def run_operation(self, input_paths: list[str], params: dict) -> tuple[list[str], str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_ocr.pdf"))
        result = ocr_pdf(input_path, out_path, params["languages"], params["convert_to_pdfa"])
        if result["pages_skipped"] == 0:
            message = f"OCR'd all {result['pages_ocred']} page{'s' if result['pages_ocred'] != 1 else ''}."
        else:
            message = (
                f"OCR'd {result['pages_ocred']} of {result['pages_ocred'] + result['pages_skipped']} pages "
                f"— {result['pages_skipped']} already had text."
            )
        return [out_path], message


class PdfToPdfaDialog(ToolDialog):
    title = "PDF to PDF/A"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_pdfa.pdf"))
        pdf_to_pdfa(input_path, out_path)
        return [out_path]
```
Note `ocr_pdf`/`pdf_to_pdfa` live in `app/core/ocr.py`, NOT `app/core/pdf_repair.py` —
double-check this import split matches what's actually in the codebase (it did as
of this plan being written; `app/core/ocr.py` also handles `_ensure_ocr_binaries_on_path()`
internally, so the dialog doesn't need to call anything extra before using either
function). `ocr_pdf` already raises `PDFError("Select at least one language.")`
for an empty list and `protect_pdf`/`unlock_pdf` already validate their own
password requirements — no extra validation needed in any of these dialogs.

- [ ] **Step 3: Register the 5 new tools in `app/main.py`**

Change the import line (currently line 9):
```python
from app.ui.dialogs.optimize_dialogs import CompressDialog
```
to:
```python
from app.ui.dialogs.optimize_dialogs import CompressDialog, RepairDialog, ProtectDialog, OcrDialog, PdfToPdfaDialog, UnlockDialog
```
Add these lines directly after `window.add_tool("Optimize", "Compress PDF", CompressDialog)` (currently line 22):
```python
    window.add_tool("Optimize", "Repair PDF", RepairDialog)
    window.add_tool("Optimize", "Protect PDF", ProtectDialog)
    window.add_tool("Optimize", "OCR PDF", OcrDialog)
    window.add_tool("Optimize", "PDF to PDF/A", PdfToPdfaDialog)
    window.add_tool("Optimize", "Unlock PDF", UnlockDialog)
```

- [ ] **Step 4: Manual verification**

Launch the app: `python -m app.main`. Build these test files first with a throwaway script (`venv/Scripts/python.exe` with `fitz`/`pikepdf` available):

```python
import fitz, pikepdf, io
from PIL import Image

# A normal 3-page PDF for Repair/PDF-to-PDF/A.
doc = fitz.open()
for i in range(3):
    page = doc.new_page()
    page.insert_text((72, 72), f"Page {i + 1}")
doc.save("normal.pdf")
doc.close()

# An image-only (no real text layer) PDF for OCR.
doc = fitz.open()
page = doc.new_page(width=612, height=792)
page.insert_text((72, 100), "This is a scanned-looking test page.", fontsize=14)
pix = page.get_pixmap(matrix=fitz.Matrix(300 / 72, 300 / 72))
scanned = fitz.open()
scanned.new_page(width=612, height=792).insert_image(fitz.Rect(0, 0, 612, 792), pixmap=pix)
scanned.save("scanned.pdf")
doc.close(); scanned.close()

# A password-protected PDF for Unlock (password: "secret123").
pdf = pikepdf.new()
pdf.add_blank_page(page_size=(612, 792))
pdf.save("protected_input.pdf", encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
pdf.close()
```

- **Repair PDF**: open `normal.pdf` → Run. Confirm `normal_repaired.pdf` appears next to
  it and the status label reads `"File is healthy — 3 pages."` (the "Recovered N
  page(s) after M structural issue(s) found." branch is hard to force reliably with a
  valid fixture — skip it unless a genuinely repairable-but-warned file is easy to
  produce; don't fabricate one just to exercise this branch).
- **Protect PDF**: open `normal.pdf`, type a password, Run. Confirm
  `normal_protected.pdf` exists; verify it's actually password-protected with
  `pikepdf.open("normal_protected.pdf")` (should raise `PasswordError` with no
  password given).
- **OCR PDF**: open `scanned.pdf` (English pre-checked), Run. Confirm
  `scanned_ocr.pdf` exists, the status label reads `"OCR'd all 1 page."`, and
  `fitz.open("scanned_ocr.pdf")[0].get_text()` contains the original sentence.
- **PDF to PDF/A**: open `normal.pdf` → Run. Confirm `normal_pdfa.pdf` exists.
- **Unlock PDF**: open `protected_input.pdf`, type `secret123`, Run. Confirm
  `protected_input_unlocked.pdf` exists and `fitz.open(...)` on it needs no
  password. Then retry with a deliberately wrong password — confirm a
  `QMessageBox.critical` error dialog appears (not a crash) and no output file
  is created for that attempt.

- [ ] **Step 5: Commit**

```bash
git add app/ui/dialogs/base.py app/ui/dialogs/optimize_dialogs.py app/main.py
git commit -m "feat: add Repair, Protect, OCR, PDF to PDF/A, and Unlock dialogs to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: `convert_dialogs.py` — PDF to Markdown, PDF to PowerPoint, PDF to Excel, Images to PDF

**Files:**
- Modify: `app/ui/dialogs/convert_dialogs.py` (currently 37 lines: `ToImagesDialog`, `ToWordDialog`)
- Modify: `app/main.py` (import line 10, registration lines 25-26)

**Interfaces:**
- Consumes: nothing from Task 1 (independent of it).
- Produces: nothing consumed by Task 3.

- [ ] **Step 1: Add the 4 new dialogs to `convert_dialogs.py`**

Replace the file's imports and add these four classes after `ToWordDialog` (keep
`ToImagesDialog`/`ToWordDialog` exactly as they are today):
```python
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QLineEdit

from app.core.errors import PDFError
from app.core.pdf_ops import render_to_images, pdf_to_markdown_zip, images_to_pdf
from app.core.convert import convert_to_word
from app.core.pdf_to_office import pdf_to_pptx, pdf_to_xlsx
from app.ui.dialogs.base import ToolDialog


class ToImagesDialog(ToolDialog):
    # ... unchanged ...


class ToWordDialog(ToolDialog):
    # ... unchanged ...


class PdfToMarkdownDialog(ToolDialog):
    title = "PDF to Markdown"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_markdown.zip"))
        pdf_to_markdown_zip(input_path, out_path)
        return [out_path]


class PdfToPptxDialog(ToolDialog):
    title = "PDF to PowerPoint"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".pptx"))
        pdf_to_pptx(input_path, out_path)
        return [out_path]


class PdfToXlsxDialog(ToolDialog):
    title = "PDF to Excel"

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".xlsx"))
        pdf_to_xlsx(input_path, out_path)
        return [out_path]


class ImagesToPdfDialog(ToolDialog):
    title = "Images to PDF"
    allow_multiple_files = True
    file_filter = "Image files (*.jpg *.jpeg *.png)"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Output filename:"))
        self.filename_input = QLineEdit()
        layout.addWidget(self.filename_input)
        layout.addWidget(QLabel("Fit mode:"))
        self.fit_mode_box = QComboBox()
        self.fit_mode_box.addItem("Fit (show the whole image)", "fit")
        self.fit_mode_box.addItem("Fill (crop to fill the page)", "fill")
        layout.addWidget(self.fit_mode_box)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths and not self.filename_input.text().strip():
            default_name = Path(paths[0]).stem + "_combined.pdf"
            self.filename_input.setText(default_name)

    def gather_params(self) -> dict:
        return {
            "filename": self.filename_input.text().strip(),
            "fit_mode": self.fit_mode_box.currentData(),
        }

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        filename = params["filename"]
        if not filename:
            raise PDFError("Enter an output filename.")
        if any(sep in filename for sep in ("/", "\\", ":")):
            raise PDFError("Output filename must be a plain file name, not a path.")
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        output_path = str(Path(input_paths[0]).parent / filename)
        images_to_pdf(input_paths, output_path, params["fit_mode"])
        return [output_path]
```
Note `ImagesToPdfDialog` uses `QComboBox.addItem(label, userData)` +
`.currentData()` instead of `RotateDialog`'s `.addItems()` + `.currentText()`
pattern — deliberate, not an inconsistency: fit mode's display labels ("Fit
(show the whole image)") differ from the actual values `images_to_pdf` needs
("fit"), unlike `RotateDialog`'s angle box where the displayed text ("90")
already *is* the value. `ImagesToPdfDialog`'s filename validation is its own
copy of `MergeDialog`'s (`app/ui/dialogs/organize_dialogs.py`) — deliberately
*without* MergeDialog's extra "output filename matches an input file" check,
since that can't happen here (inputs are images, output is always `.pdf`).

- [ ] **Step 2: Register the 4 new tools in `app/main.py`**

Change the import line (currently line 10):
```python
from app.ui.dialogs.convert_dialogs import ToImagesDialog, ToWordDialog
```
to:
```python
from app.ui.dialogs.convert_dialogs import ToImagesDialog, ToWordDialog, PdfToMarkdownDialog, PdfToPptxDialog, PdfToXlsxDialog, ImagesToPdfDialog
```
Add these lines directly after `window.add_tool("Convert", "PDF to Word", ToWordDialog)` (currently line 26):
```python
    window.add_tool("Convert", "PDF to Markdown", PdfToMarkdownDialog)
    window.add_tool("Convert", "PDF to PowerPoint", PdfToPptxDialog)
    window.add_tool("Convert", "PDF to Excel", PdfToXlsxDialog)
    window.add_tool("Convert", "Images to PDF", ImagesToPdfDialog)
```

- [ ] **Step 3: Manual verification**

Launch the app: `python -m app.main`. Build these test files first:

```python
import fitz
from PIL import Image

# A normal 2-page PDF with real text, for Markdown/PowerPoint.
doc = fitz.open()
for i in range(2):
    page = doc.new_page()
    page.insert_text((72, 72), f"Hello page {i + 1}")
doc.save("text_only.pdf")
doc.close()

# A PDF with a real ruled table, for the Excel success case.
def draw_ruled_table(page, x0, y0, col_w, row_h, values):
    rows, cols = len(values), len(values[0])
    for r in range(rows + 1):
        page.draw_line((x0, y0 + r * row_h), (x0 + cols * col_w, y0 + r * row_h))
    for c in range(cols + 1):
        page.draw_line((x0 + c * col_w, y0), (x0 + c * col_w, y0 + rows * row_h))
    for r, row in enumerate(values):
        for c, val in enumerate(row):
            page.insert_text((x0 + c * col_w + 10, y0 + r * row_h + 20), val, fontsize=12)

doc = fitz.open()
page = doc.new_page(width=612, height=792)
draw_ruled_table(page, 72, 100, 100, 30, [("A1", "B1"), ("A2", "B2")])
doc.save("with_table.pdf")
doc.close()

# Three small test images, for Images to PDF.
for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
    Image.new("RGB", (400, 300), color).save(f"image{i + 1}.png")
```

- **PDF to Markdown**: open `text_only.pdf` → Run. Confirm `text_only_markdown.zip`
  exists and, when unzipped, contains a `document.md` with "Hello page 1" and
  "Hello page 2" in it.
- **PDF to PowerPoint**: open `text_only.pdf` → Run. Confirm `text_only.pptx` exists
  and loads without error via `from pptx import Presentation; Presentation("text_only.pptx")`.
- **PDF to Excel (success)**: open `with_table.pdf` → Run. Confirm `with_table.xlsx`
  exists and loads via `openpyxl.load_workbook("with_table.xlsx")` with a sheet
  containing `[("A1", "B1"), ("A2", "B2")]`.
- **PDF to Excel (no table)**: open `text_only.pdf` → Run. Confirm a
  `QMessageBox.critical` error appears ("No tables found in this document.") and
  no `.xlsx` file is created.
- **Images to PDF**: switch the file filter/pick `image1.png`, `image2.png`,
  `image3.png` together (multi-select in the file dialog). Confirm the filename
  field auto-fills to `image1_combined.pdf`; change the fit mode between "Fit"
  and "Fill" and Run once with each. Confirm the resulting PDF has 3 pages (one
  per image) via `fitz.open(...).page_count == 3`, and that "Fill" visually crops
  more aggressively than "Fit" if you open both outputs and compare (the 400×300
  images are a different aspect ratio than the default page sizes, so this should
  be visible). Also clear the filename field entirely and Run — confirm a
  `QMessageBox.critical` error appears ("Enter an output filename.") rather than
  a silent failure or crash.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/convert_dialogs.py app/main.py
git commit -m "feat: add PDF to Markdown, PowerPoint, Excel, and Images to PDF dialogs to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 3: `edit_dialogs.py` — Add page numbers

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (currently 56 lines: `RotateDialog`, `WatermarkDialog`)
- Modify: `app/main.py` (import line 8, registration lines 20-21)

**Interfaces:**
- Consumes: nothing from Tasks 1 or 2 (independent of both).
- Produces: nothing consumed by any other task (this is the last task).

- [ ] **Step 1: Add `AddPageNumbersDialog` to `edit_dialogs.py`**

Change the import line (currently line 6):
```python
from app.core.pdf_ops import rotate_pages, add_watermark
```
to:
```python
from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers
```
Add this class at the end of the file, after `WatermarkDialog`:
```python
class AddPageNumbersDialog(ToolDialog):
    title = "Add page numbers"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Position:"))
        self.position_box = QComboBox()
        self.position_box.addItem("Bottom center", "bottom-center")
        self.position_box.addItem("Bottom right", "bottom-right")
        self.position_box.addItem("Bottom left", "bottom-left")
        self.position_box.addItem("Top center", "top-center")
        self.position_box.addItem("Top right", "top-right")
        self.position_box.addItem("Top left", "top-left")
        layout.addWidget(self.position_box)
        layout.addWidget(QLabel("Format:"))
        self.format_box = QComboBox()
        self.format_box.addItem("3", "number")
        self.format_box.addItem("3 / 12", "number-of-total")
        self.format_box.addItem("Page 3 of 12", "page-x-of-y")
        layout.addWidget(self.format_box)

    def gather_params(self) -> dict:
        return {
            "position": self.position_box.currentData(),
            "format": self.format_box.currentData(),
        }

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_numbered.pdf"))
        add_page_numbers(input_path, out_path, params["position"], params["format"])
        return [out_path]
```
`QComboBox`, `QVBoxLayout`, `QLabel`, `QWidget` are already imported in this
file (used by `RotateDialog`/`WatermarkDialog`) — no new Qt imports needed.
Uses `.addItem(label, userData)` + `.currentData()` for the same reason
`ImagesToPdfDialog` does in Task 2 (the displayed labels differ from the
actual values `add_page_numbers` needs).

- [ ] **Step 2: Register the new tool in `app/main.py`**

Change the import line (currently line 7):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog
```
to:
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog
```
Add this line directly after `window.add_tool("Edit", "Add watermark", WatermarkDialog)` (currently line 21):
```python
    window.add_tool("Edit", "Add page numbers", AddPageNumbersDialog)
```

- [ ] **Step 3: Manual verification**

Launch the app: `python -m app.main`. Use any existing multi-page PDF (or
build one: `fitz.open(); [doc.new_page().insert_text((72,72), f"Page {i+1}") for i in range(3)]; doc.save("numbered_test.pdf")`
— note this needs a real loop, not a list-comprehension one-liner, since
`new_page()` needs to be called on `doc` each iteration).

- Open the file, leave Position/Format at their defaults (Bottom center / "3"),
  Run. Confirm `<name>_numbered.pdf` exists and visually shows "1", "2", "3" at
  the bottom center of each page (open it in any PDF viewer, or check via
  `fitz.open(...)[0].get_text()` contains "1").
- Re-run with Position = "Top right" and Format = "Page 3 of 12" — confirm the
  output now shows "Page 1 of 3" (etc.) near the top-right of each page instead.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py
git commit -m "feat: add an Add page numbers dialog to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.
