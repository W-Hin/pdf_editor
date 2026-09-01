# PDF Editor v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal, offline, open-source Windows desktop PDF toolkit (v1: Merge, Split, Remove pages, Extract pages, Reorder pages, Rotate, Add watermark, Compress, PDF→Images, PDF→Word), packaged as a standalone .exe with a Desktop shortcut.

**Architecture:** A tool-grid PySide6 desktop app. Nearly all PDF logic runs through PyMuPDF (`fitz`) in pure, UI-free functions under `app/core/`; `pdf2docx` (built on PyMuPDF) handles PDF→Word. Each tool is a thin `QDialog` subclass that collects input/options and runs the matching core function on a background `QThread`, so the UI never freezes. PyInstaller packages the app into a standalone folder; a small script then drops a `.lnk` shortcut on the Desktop.

**Tech Stack:** Python 3.11+, PyMuPDF, pdf2docx, PySide6, pytest, PyInstaller.

## Global Constraints

- Windows-only target (matches the user's machine); Python 3.11+.
- Dependency floors (see `requirements.txt` in Task 1): `PyMuPDF>=1.24.0`, `pdf2docx>=0.5.8`, `PySide6>=6.6.0`, `pytest>=8.0.0`, `pyinstaller>=6.0.0`.
- PyMuPDF is AGPL-3.0. Per the approved spec, this is accepted as fine for this personal, non-monetized, open project — no workaround needed.
- Every operation writes its result to a **new** file next to the input, using a fixed suffix convention, and never overwrites the original: `_merged`, `_removed`, `_extracted`, `_reordered`, `_rotated`, `_watermarked`, `_compressed`, `_partN` (split), `_pageN.<ext>` (images), and `.docx` (Word) all replace/append onto the input's stem.
- All user-facing errors are raised as `PDFError` (see Task 2) with a plain-language message — never a raw stack trace shown to the user.
- Per the spec's testing policy: `app/core/` (pure PDF logic) and `app/ui/workers.py` (threading glue, no widgets) get automated `pytest` coverage. `QDialog`/`QMainWindow` code does not get automated tests — those tasks end with a manual verification step (run the app, do X, confirm Y) instead.
- Project root is `C:\Users\chinw\Documents\Project\PDF Editor`. The spec lives at `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`; refer back to it for the full feature roadmap (Phase 2/3 are separate future plans, out of scope here).

---

## Task 1: Project scaffolding & dependencies

**Files:**
- Create: `requirements.txt`
- Create: `pytest.ini`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/core/__init__.py`
- Create: `app/ui/__init__.py`
- Create: `app/ui/dialogs/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `tests/conftest.py` fixture `make_pdf(num_pages=3, text_prefix="Page") -> str` (returns a path to a generated multi-page PDF in a temp dir), used by every core test task from here on.

- [ ] **Step 1: Create the directory structure and empty package files**

```bash
mkdir -p app/core app/ui/dialogs tests scripts
touch app/__init__.py app/core/__init__.py app/ui/__init__.py app/ui/dialogs/__init__.py
```

- [ ] **Step 2: Write `requirements.txt`**

```
PyMuPDF>=1.24.0
pdf2docx>=0.5.8
PySide6>=6.6.0
pytest>=8.0.0
pyinstaller>=6.0.0
```

- [ ] **Step 3: Write `pytest.ini`**

```ini
[pytest]
testpaths = tests
pythonpath = .
```

- [ ] **Step 4: Write `.gitignore`**

```
venv/
__pycache__/
*.pyc
dist/
build/
.pytest_cache/
*.egg-info/
```

- [ ] **Step 5: Create a virtual environment and install dependencies**

```bash
python -m venv venv
venv/Scripts/python -m pip install --upgrade pip
venv/Scripts/python -m pip install -r requirements.txt
```

- [ ] **Step 6: Verify the environment**

Run: `venv/Scripts/python -c "import fitz, pdf2docx, PySide6, pytest; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 7: Write the shared sample-PDF test fixture**

`tests/conftest.py`:

```python
import fitz
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    def _make(num_pages=3, text_prefix="Page"):
        path = tmp_path / "sample.pdf"
        doc = fitz.open()
        for i in range(num_pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"{text_prefix} {i + 1}")
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make
```

- [ ] **Step 8: Verify pytest collects with no tests yet**

Run: `venv/Scripts/python -m pytest -v`
Expected: "no tests ran" (or 0 collected), no collection errors.

- [ ] **Step 9: Commit**

```bash
git add requirements.txt pytest.ini .gitignore app tests/conftest.py
git commit -m "chore: project scaffolding, dependencies, and shared test fixture"
```

---

## Task 2: Core — errors, open_pdf/get_page_count, merge_pdfs

**Files:**
- Create: `app/core/errors.py`
- Create: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `make_pdf` fixture from Task 1.
- Produces: `PDFError(Exception)`; `open_pdf(path: str) -> fitz.Document`; `get_page_count(path: str) -> int`; `merge_pdfs(input_paths: list[str], output_path: str) -> None`. All later core tasks add functions to this same `pdf_ops.py` and reuse `open_pdf`/`PDFError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pdf_ops.py`:

```python
import fitz
import pytest

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs


def test_open_pdf_missing_file_raises(tmp_path):
    with pytest.raises(PDFError):
        open_pdf(str(tmp_path / "missing.pdf"))


def test_open_pdf_not_a_pdf_raises(tmp_path):
    bad_file = tmp_path / "not_a_pdf.pdf"
    bad_file.write_text("this is not a pdf")
    with pytest.raises(PDFError):
        open_pdf(str(bad_file))


def test_get_page_count(make_pdf):
    path = make_pdf(num_pages=4)
    assert get_page_count(path) == 4


def test_merge_pdfs_combines_page_counts(make_pdf, tmp_path):
    pdf_a = make_pdf(num_pages=2, text_prefix="A")
    pdf_b = make_pdf(num_pages=3, text_prefix="B")
    out_path = str(tmp_path / "merged.pdf")

    merge_pdfs([pdf_a, pdf_b], out_path)

    assert get_page_count(out_path) == 5
    doc = fitz.open(out_path)
    assert "A 1" in doc[0].get_text()
    assert "B 1" in doc[2].get_text()
    doc.close()


def test_merge_pdfs_requires_two_files(make_pdf, tmp_path):
    pdf_a = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        merge_pdfs([pdf_a], str(tmp_path / "out.pdf"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.errors'` (or similar import error).

- [ ] **Step 3: Write `app/core/errors.py`**

```python
class PDFError(Exception):
    """Raised when a PDF file can't be opened, is invalid, or an operation fails."""
```

- [ ] **Step 4: Write `app/core/pdf_ops.py`**

```python
from pathlib import Path

import fitz

from app.core.errors import PDFError


def open_pdf(path: str) -> fitz.Document:
    p = Path(path)
    if not p.exists():
        raise PDFError(f"File not found: {path}")
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise PDFError(f"Could not open '{p.name}' — it may not be a valid PDF.") from exc
    if doc.is_encrypted:
        doc.close()
        raise PDFError(f"'{p.name}' is password-protected. Unlock it before using this tool.")
    return doc


def get_page_count(path: str) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def merge_pdfs(input_paths: list[str], output_path: str) -> None:
    if len(input_paths) < 2:
        raise PDFError("Select at least two PDF files to merge.")
    result = fitz.open()
    try:
        for path in input_paths:
            doc = open_pdf(path)
            try:
                result.insert_pdf(doc)
            finally:
                doc.close()
        result.save(output_path)
    finally:
        result.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/core/errors.py app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: PDFError, open_pdf/get_page_count validation, merge_pdfs"
```

---

## Task 3: Core — extract_pages, remove_pages, reorder_pages, split_pdf

**Files:**
- Modify: `app/core/pdf_ops.py`
- Modify: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `open_pdf`, `get_page_count`, `PDFError` from Task 2.
- Produces: `extract_pages(input_path: str, page_numbers: list[int], output_path: str) -> None` (1-indexed, output order = list order); `remove_pages(input_path: str, page_numbers: list[int], output_path: str) -> None`; `reorder_pages(input_path: str, new_order: list[int], output_path: str) -> None`; `split_pdf(input_path: str, output_dir: str, ranges: list[tuple[int, int]]) -> list[str]` (1-indexed inclusive ranges, returns output file paths in range order). All UI dialog tasks for these tools (Task 11) call these four functions directly.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:

```python
from app.core.pdf_ops import extract_pages, remove_pages, reorder_pages, split_pdf


def test_extract_pages_selects_in_order(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_path = str(tmp_path / "extracted.pdf")

    extract_pages(path, [3, 1], out_path)

    assert get_page_count(out_path) == 2
    doc = fitz.open(out_path)
    assert "Page 3" in doc[0].get_text()
    assert "Page 1" in doc[1].get_text()
    doc.close()


def test_extract_pages_rejects_out_of_range(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        extract_pages(path, [5], str(tmp_path / "out.pdf"))


def test_remove_pages_drops_selected(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_path = str(tmp_path / "removed.pdf")

    remove_pages(path, [2, 3], out_path)

    assert get_page_count(out_path) == 2
    doc = fitz.open(out_path)
    assert "Page 1" in doc[0].get_text()
    assert "Page 4" in doc[1].get_text()
    doc.close()


def test_remove_pages_rejects_removing_everything(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        remove_pages(path, [1, 2], str(tmp_path / "out.pdf"))


def test_reorder_pages(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    out_path = str(tmp_path / "reordered.pdf")

    reorder_pages(path, [3, 1, 2], out_path)

    doc = fitz.open(out_path)
    assert "Page 3" in doc[0].get_text()
    assert "Page 1" in doc[1].get_text()
    assert "Page 2" in doc[2].get_text()
    doc.close()


def test_reorder_pages_rejects_incomplete_order(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    with pytest.raises(PDFError):
        reorder_pages(path, [1, 2], str(tmp_path / "out.pdf"))


def test_split_pdf_by_ranges(make_pdf, tmp_path):
    path = make_pdf(num_pages=4)
    out_dir = str(tmp_path / "split_out")

    outputs = split_pdf(path, out_dir, [(1, 2), (3, 4)])

    assert len(outputs) == 2
    assert get_page_count(outputs[0]) == 2
    assert get_page_count(outputs[1]) == 2


def test_split_pdf_rejects_invalid_range(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    with pytest.raises(PDFError):
        split_pdf(path, str(tmp_path / "out"), [(1, 5)])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: the 8 new tests FAIL with `ImportError`/`AttributeError` (functions don't exist yet); the 5 existing tests still PASS.

- [ ] **Step 3: Add the four functions to `app/core/pdf_ops.py`**

```python
def extract_pages(input_path: str, page_numbers: list[int], output_path: str) -> None:
    """page_numbers are 1-indexed, in the desired output order. Duplicates allowed."""
    if not page_numbers:
        raise PDFError("No pages selected.")
    doc = open_pdf(input_path)
    try:
        for n in page_numbers:
            if n < 1 or n > doc.page_count:
                raise PDFError(f"Page {n} does not exist in this document ({doc.page_count} pages).")
        result = fitz.open()
        try:
            for n in page_numbers:
                result.insert_pdf(doc, from_page=n - 1, to_page=n - 1)
            result.save(output_path)
        finally:
            result.close()
    finally:
        doc.close()


def remove_pages(input_path: str, page_numbers: list[int], output_path: str) -> None:
    total = get_page_count(input_path)
    to_remove = set(page_numbers)
    keep = [n for n in range(1, total + 1) if n not in to_remove]
    if not keep:
        raise PDFError("Cannot remove all pages from the document.")
    extract_pages(input_path, keep, output_path)


def reorder_pages(input_path: str, new_order: list[int], output_path: str) -> None:
    total = get_page_count(input_path)
    if sorted(new_order) != list(range(1, total + 1)):
        raise PDFError("New order must include every page exactly once.")
    extract_pages(input_path, new_order, output_path)


def split_pdf(input_path: str, output_dir: str, ranges: list[tuple[int, int]]) -> list[str]:
    total = get_page_count(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(input_path).stem
    output_paths = []
    for i, (start, end) in enumerate(ranges, start=1):
        if start < 1 or end > total or start > end:
            raise PDFError(f"Invalid page range {start}-{end} for a {total}-page document.")
        pages = list(range(start, end + 1))
        out_path = out_dir / f"{stem}_part{i}.pdf"
        extract_pages(input_path, pages, str(out_path))
        output_paths.append(str(out_path))
    return output_paths
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: extract/remove/reorder pages and split_pdf"
```

---

## Task 4: Core — rotate_pages, add_watermark

**Files:**
- Modify: `app/core/pdf_ops.py`
- Modify: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `open_pdf`, `PDFError` from Task 2.
- Produces: `rotate_pages(input_path: str, output_path: str, angle: int, page_numbers: list[int] | None = None) -> None` (angle must be a multiple of 90; `page_numbers=None` means all pages); `add_watermark(input_path: str, output_path: str, text: str, opacity: float = 0.3, font_size: int = 40, rotate: int = 0) -> None` (`rotate` must be one of 0/90/180/270).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:

```python
from app.core.pdf_ops import rotate_pages, add_watermark


def test_rotate_pages_all(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    out_path = str(tmp_path / "rotated.pdf")

    rotate_pages(path, out_path, 90)

    doc = fitz.open(out_path)
    assert doc[0].rotation == 90
    assert doc[1].rotation == 90
    doc.close()


def test_rotate_pages_specific(make_pdf, tmp_path):
    path = make_pdf(num_pages=2)
    out_path = str(tmp_path / "rotated.pdf")

    rotate_pages(path, out_path, 180, page_numbers=[1])

    doc = fitz.open(out_path)
    assert doc[0].rotation == 180
    assert doc[1].rotation == 0
    doc.close()


def test_rotate_pages_rejects_non_multiple_of_90(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        rotate_pages(path, str(tmp_path / "out.pdf"), 45)


def test_add_watermark_inserts_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    out_path = str(tmp_path / "watermarked.pdf")

    add_watermark(path, out_path, "CONFIDENTIAL")

    doc = fitz.open(out_path)
    assert "CONFIDENTIAL" in doc[0].get_text()
    doc.close()


def test_add_watermark_rejects_empty_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        add_watermark(path, str(tmp_path / "out.pdf"), "   ")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: the 5 new tests FAIL (`AttributeError`/`ImportError`); prior tests still PASS.

- [ ] **Step 3: Add the two functions to `app/core/pdf_ops.py`**

```python
def rotate_pages(input_path: str, output_path: str, angle: int, page_numbers: list[int] | None = None) -> None:
    if angle % 90 != 0:
        raise PDFError("Rotation angle must be a multiple of 90 degrees.")
    doc = open_pdf(input_path)
    try:
        targets = page_numbers if page_numbers is not None else list(range(1, doc.page_count + 1))
        for n in targets:
            if n < 1 or n > doc.page_count:
                raise PDFError(f"Page {n} does not exist in this document ({doc.page_count} pages).")
            page = doc[n - 1]
            page.set_rotation((page.rotation + angle) % 360)
        doc.save(output_path)
    finally:
        doc.close()


def add_watermark(
    input_path: str,
    output_path: str,
    text: str,
    opacity: float = 0.3,
    font_size: int = 40,
    rotate: int = 0,
) -> None:
    if not text.strip():
        raise PDFError("Watermark text cannot be empty.")
    if rotate not in (0, 90, 180, 270):
        raise PDFError("Watermark rotation must be 0, 90, 180, or 270 degrees.")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            page.insert_textbox(
                page.rect,
                text,
                fontsize=font_size,
                fontname="helv",
                color=(0.5, 0.5, 0.5),
                fill_opacity=opacity,
                rotate=rotate,
                align=fitz.TEXT_ALIGN_CENTER,
            )
        doc.save(output_path)
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all 18 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: rotate_pages and add_watermark"
```

---

## Task 5: Core — compress_pdf

**Files:**
- Modify: `app/core/pdf_ops.py`
- Modify: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `open_pdf`, `PDFError` from Task 2.
- Produces: `compress_pdf(input_path: str, output_path: str, image_quality: int = 60) -> None` (`image_quality` 1-100; re-encodes embedded raster images as JPEG at the given quality and re-saves with stream compression/garbage collection).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:

```python
from app.core.pdf_ops import compress_pdf


def _make_pdf_with_image(tmp_path):
    path = tmp_path / "with_image.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # a small solid-color image, embedded via a Pixmap
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(0, 0, 200, 200), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_compress_pdf_keeps_page_count(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    out_path = str(tmp_path / "compressed.pdf")

    compress_pdf(path, out_path, image_quality=40)

    doc = fitz.open(out_path)
    assert doc.page_count == 1
    doc.close()


def test_compress_pdf_reduces_or_maintains_size(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    out_path = str(tmp_path / "compressed.pdf")

    compress_pdf(path, out_path, image_quality=10)

    original_size = Path(path).stat().st_size
    compressed_size = Path(out_path).stat().st_size
    assert compressed_size <= original_size * 1.1  # aggressive JPEG compression should not bloat the file


def test_compress_pdf_rejects_bad_quality(tmp_path):
    path = _make_pdf_with_image(tmp_path)
    with pytest.raises(PDFError):
        compress_pdf(path, str(tmp_path / "out.pdf"), image_quality=150)
```

Add the missing import at the top of `tests/test_pdf_ops.py`:

```python
from pathlib import Path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: the 3 new tests FAIL (`AttributeError`); prior tests still PASS.

- [ ] **Step 3: Add `compress_pdf` to `app/core/pdf_ops.py`**

```python
def compress_pdf(input_path: str, output_path: str, image_quality: int = 60) -> None:
    if not 1 <= image_quality <= 100:
        raise PDFError("Image quality must be between 1 and 100.")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            for img in page.get_images(full=True):
                xref = img[0]
                pix = None
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.colorspace and pix.colorspace.n >= 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.alpha:
                        pix = fitz.Pixmap(pix, 0)
                    jpeg_bytes = pix.tobytes("jpeg", jpg_quality=image_quality)
                    page.replace_image(xref, stream=jpeg_bytes)
                except Exception:
                    continue  # skip images that can't be recompressed (e.g. stencil masks)
                finally:
                    pix = None
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all 21 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: compress_pdf via image re-encoding and stream deflation"
```

---

## Task 6: Core — render_to_images

**Files:**
- Modify: `app/core/pdf_ops.py`
- Modify: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `open_pdf`, `PDFError` from Task 2.
- Produces: `render_to_images(input_path: str, output_dir: str, dpi: int = 150, image_format: str = "png") -> list[str]` (`image_format` is `"png"` or `"jpg"`; returns output file paths, one per page, in page order).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:

```python
from app.core.pdf_ops import render_to_images


def test_render_to_images_one_file_per_page(make_pdf, tmp_path):
    path = make_pdf(num_pages=3)
    out_dir = str(tmp_path / "images_out")

    outputs = render_to_images(path, out_dir, dpi=72, image_format="png")

    assert len(outputs) == 3
    for out_path in outputs:
        assert Path(out_path).exists()
        assert out_path.endswith(".png")


def test_render_to_images_jpg_format(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    out_dir = str(tmp_path / "images_out")

    outputs = render_to_images(path, out_dir, dpi=72, image_format="jpg")

    assert outputs[0].endswith(".jpg")
    assert Path(outputs[0]).exists()


def test_render_to_images_rejects_bad_format(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        render_to_images(path, str(tmp_path / "out"), image_format="bmp")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: the 3 new tests FAIL (`AttributeError`); prior tests still PASS.

- [ ] **Step 3: Add `render_to_images` to `app/core/pdf_ops.py`**

```python
def render_to_images(
    input_path: str, output_dir: str, dpi: int = 150, image_format: str = "png"
) -> list[str]:
    fmt = image_format.lower()
    if fmt not in ("png", "jpg", "jpeg"):
        raise PDFError("Image format must be png or jpg.")
    doc = open_pdf(input_path)
    try:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(input_path).stem
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        output_paths = []
        for i, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=matrix)
            out_path = out_dir / f"{stem}_page{i}.{fmt}"
            pix.save(str(out_path))
            output_paths.append(str(out_path))
        return output_paths
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all 24 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: render_to_images"
```

---

## Task 7: Core — convert_to_word (pdf2docx)

**Files:**
- Create: `app/core/convert.py`
- Create: `tests/test_convert.py`

**Interfaces:**
- Consumes: `open_pdf`, `PDFError` from Task 2.
- Produces: `convert_to_word(input_path: str, output_path: str) -> None`.

- [ ] **Step 1: Write the failing test**

`tests/test_convert.py`:

```python
from pathlib import Path

import pytest

from app.core.convert import convert_to_word
from app.core.errors import PDFError


def test_convert_to_word_creates_docx(make_pdf, tmp_path):
    path = make_pdf(num_pages=1, text_prefix="Hello")
    out_path = str(tmp_path / "out.docx")

    convert_to_word(path, out_path)

    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 0


def test_convert_to_word_rejects_missing_file(tmp_path):
    with pytest.raises(PDFError):
        convert_to_word(str(tmp_path / "missing.pdf"), str(tmp_path / "out.docx"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_convert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.convert'`.

- [ ] **Step 3: Write `app/core/convert.py`**

```python
from pathlib import Path

from pdf2docx import Converter

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf


def convert_to_word(input_path: str, output_path: str) -> None:
    doc = open_pdf(input_path)  # validates existence, format, and not-encrypted
    doc.close()
    try:
        converter = Converter(input_path)
        try:
            converter.convert(output_path)
        finally:
            converter.close()
    except Exception as exc:
        raise PDFError(f"Could not convert '{Path(input_path).name}' to Word.") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_convert.py -v`
Expected: both tests PASS. (The conversion itself may take a few seconds — this is expected for `pdf2docx`.)

- [ ] **Step 5: Commit**

```bash
git add app/core/convert.py tests/test_convert.py
git commit -m "feat: convert_to_word via pdf2docx"
```

---

## Task 8: UI infra — Worker thread wrapper + ToolDialog base

**Files:**
- Create: `app/ui/workers.py`
- Create: `app/ui/dialogs/base.py`
- Test: `tests/test_workers.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure Qt infra).
- Produces:
  - `Worker(QThread)`: `__init__(self, fn, *args, **kwargs)`; signals `finished_ok(object)`, `failed(str)`; after `.wait()`, attributes `.result` and `.error` hold the outcome.
  - `ToolDialog(QDialog)`: class attributes `title: str = "Tool"`, `file_filter: str = "PDF files (*.pdf)"`, `allow_multiple_files: bool = False`; overridable methods `build_options(self, container: QWidget) -> None`, `on_files_changed(self, paths: list[str]) -> None`, `run_operation(self, input_paths: list[str]) -> list[str]` (must be overridden — raises `NotImplementedError` by default); helper `selected_files(self) -> list[str]`. All tool dialog tasks (10-14) subclass `ToolDialog`.

- [ ] **Step 1: Write the failing test for Worker**

`tests/test_workers.py`:

```python
from PySide6.QtCore import QCoreApplication

from app.ui.workers import Worker

_app = QCoreApplication.instance() or QCoreApplication([])


def test_worker_runs_function_and_stores_result():
    worker = Worker(lambda a, b: a + b, 2, 3)
    worker.start()
    worker.wait()
    assert worker.result == 5
    assert worker.error is None


def test_worker_captures_exception_message():
    def boom():
        raise ValueError("bad input")

    worker = Worker(boom)
    worker.start()
    worker.wait()
    assert worker.result is None
    assert worker.error == "bad input"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/Scripts/python -m pytest tests/test_workers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ui.workers'`.

- [ ] **Step 3: Write `app/ui/workers.py`**

```python
from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.result = None
        self.error = None

    def run(self) -> None:
        try:
            self.result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)
        else:
            self.finished_ok.emit(self.result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/Scripts/python -m pytest tests/test_workers.py -v`
Expected: both tests PASS.

- [ ] **Step 5: Write `app/ui/dialogs/base.py`**

```python
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QLabel,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QWidget,
)

from app.ui.workers import Worker


class ToolDialog(QDialog):
    """Base dialog: input file picker + subclass-provided options + run button + progress."""

    title = "Tool"
    file_filter = "PDF files (*.pdf)"
    allow_multiple_files = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.title)
        self.resize(480, 360)
        self._worker: Worker | None = None
        self._output_paths: list[str] = []

        layout = QVBoxLayout(self)

        file_row = QHBoxLayout()
        self.file_list = QListWidget()
        file_row.addWidget(self.file_list)
        pick_btn = QPushButton("Add file(s)…")
        pick_btn.clicked.connect(self._pick_files)
        file_row.addWidget(pick_btn)
        layout.addLayout(file_row)

        self.options_widget = QWidget()
        self.build_options(self.options_widget)
        layout.addWidget(self.options_widget)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        button_row = QHBoxLayout()
        self.run_button = QPushButton("Run")
        self.run_button.clicked.connect(self._run)
        button_row.addWidget(self.run_button)
        self.open_folder_button = QPushButton("Show in folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        button_row.addWidget(self.open_folder_button)
        layout.addLayout(button_row)

    def build_options(self, container: QWidget) -> None:
        """Override in subclasses to add tool-specific option widgets into `container`."""

    def on_files_changed(self, paths: list[str]) -> None:
        """Override in subclasses to react when the selected file list changes."""

    def run_operation(self, input_paths: list[str]) -> list[str]:
        """Override in subclasses: perform the operation, return output path(s)."""
        raise NotImplementedError

    def selected_files(self) -> list[str]:
        return [self.file_list.item(i).text() for i in range(self.file_list.count())]

    def _pick_files(self) -> None:
        if not self.allow_multiple_files:
            self.file_list.clear()
        paths, _ = QFileDialog.getOpenFileNames(self, "Select file(s)", "", self.file_filter)
        for path in paths:
            self.file_list.addItem(path)
        self.on_files_changed(self.selected_files())

    def _run(self) -> None:
        input_paths = self.selected_files()
        if not input_paths:
            QMessageBox.warning(self, "No file selected", "Add at least one file first.")
            return
        self.run_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.progress.setVisible(True)
        self.status_label.setText("Working…")
        self._worker = Worker(self.run_operation, input_paths)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, output_paths) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self._output_paths = output_paths if isinstance(output_paths, list) else [output_paths]
        self.status_label.setText(f"Done — {len(self._output_paths)} file(s) created.")
        self.open_folder_button.setEnabled(True)

    def _on_failure(self, message: str) -> None:
        self.progress.setVisible(False)
        self.run_button.setEnabled(True)
        self.status_label.setText("Failed.")
        QMessageBox.critical(self, "Operation failed", message)

    def _open_output_folder(self) -> None:
        if not self._output_paths:
            return
        folder = str(Path(self._output_paths[0]).parent)
        os.startfile(folder)
```

- [ ] **Step 6: Manual verification**

Run: `venv/Scripts/python -c "from app.ui.dialogs.base import ToolDialog; print('imports ok')"`
Expected: prints `imports ok` with no errors (full interactive verification happens once a concrete dialog exists, in Task 10).

- [ ] **Step 7: Commit**

```bash
git add app/ui/workers.py app/ui/dialogs/base.py tests/test_workers.py
git commit -m "feat: Worker thread wrapper and ToolDialog base class"
```

---

## Task 9: UI — MainWindow shell + main.py entry point

**Files:**
- Create: `app/ui/main_window.py`
- Create: `app/main.py`

**Interfaces:**
- Consumes: nothing from earlier tasks directly (pure Qt shell).
- Produces: `MainWindow(QMainWindow)` with `add_tool(self, category: str, label: str, dialog_cls: type[QDialog]) -> None`, where `category` is one of `"Organize"`, `"Edit"`, `"Optimize"`, `"Convert"`. `app/main.py: main() -> int`. All dialog tasks (10-14) modify `app/main.py` to register their tools via `window.add_tool(...)`.

- [ ] **Step 1: Write `app/ui/main_window.py`**

```python
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QGridLayout, QPushButton, QGroupBox


class MainWindow(QMainWindow):
    CATEGORIES = ("Organize", "Edit", "Optimize", "Convert")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Editor")
        self.resize(700, 500)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self._grids: dict[str, QGridLayout] = {}
        for name in self.CATEGORIES:
            box = QGroupBox(name)
            grid = QGridLayout(box)
            self._grids[name] = grid
            layout.addWidget(box)

    def add_tool(self, category: str, label: str, dialog_cls) -> None:
        grid = self._grids[category]
        row, col = divmod(grid.count(), 3)
        button = QPushButton(label)
        button.clicked.connect(lambda: dialog_cls(self).exec())
        grid.addWidget(button, row, col)
```

- [ ] **Step 2: Write `app/main.py`**

```python
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
Expected: a window titled "PDF Editor" opens with four empty group boxes labeled Organize, Edit, Optimize, Convert. Close the window to exit.

- [ ] **Step 4: Commit**

```bash
git add app/ui/main_window.py app/main.py
git commit -m "feat: MainWindow tool-grid shell and app entry point"
```

---

## Task 10: UI — Merge & Split dialogs

**Files:**
- Create: `app/ui/dialogs/organize_dialogs.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ToolDialog` (Task 8); `merge_pdfs`, `split_pdf`, `get_page_count` (Task 2/3); `MainWindow.add_tool` (Task 9).
- Produces: `MergeDialog`, `SplitDialog` — consumed later only via registration in `main.py`.

- [ ] **Step 1: Write `app/ui/dialogs/organize_dialogs.py`**

```python
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QSpinBox, QLabel

from app.core.pdf_ops import merge_pdfs, split_pdf, get_page_count
from app.ui.dialogs.base import ToolDialog


class MergeDialog(ToolDialog):
    title = "Merge PDF"
    allow_multiple_files = True

    def run_operation(self, input_paths: list[str]) -> list[str]:
        first = Path(input_paths[0])
        output_path = str(first.with_name(first.stem + "_merged.pdf"))
        merge_pdfs(input_paths, output_path)
        return [output_path]


class SplitDialog(ToolDialog):
    title = "Split PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Pages per output file:"))
        self.pages_per_file = QSpinBox()
        self.pages_per_file.setRange(1, 9999)
        self.pages_per_file.setValue(1)
        layout.addWidget(self.pages_per_file)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        total = get_page_count(input_path)
        step = self.pages_per_file.value()
        ranges = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
        output_dir = str(Path(input_path).parent)
        return split_pdf(input_path, output_dir, ranges)
```

- [ ] **Step 2: Register both tools in `app/main.py`**

Modify `app/main.py` — add the import and two registration calls before `window.show()`:

```python
from app.ui.dialogs.organize_dialogs import MergeDialog, SplitDialog
```

```python
    window = MainWindow()
    window.add_tool("Organize", "Merge PDF", MergeDialog)
    window.add_tool("Organize", "Split PDF", SplitDialog)
    window.show()
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
Expected: the Organize group now shows "Merge PDF" and "Split PDF" buttons.
- Click "Merge PDF", add two real PDF files via "Add file(s)…", click Run. Confirm a `..._merged.pdf` appears next to the first file and "Show in folder" opens Explorer there.
- Click "Split PDF", add one multi-page PDF, set pages-per-file to 1, click Run. Confirm one `..._partN.pdf` file per page appears in the same folder.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/organize_dialogs.py app/main.py
git commit -m "feat: Merge and Split PDF dialogs"
```

---

## Task 11: UI — Remove/Extract/Reorder pages dialogs

**Files:**
- Create: `app/ui/dialogs/pages_dialogs.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ToolDialog` (Task 8); `get_page_count`, `remove_pages`, `extract_pages`, `reorder_pages` (Task 2/3); `MainWindow.add_tool` (Task 9).
- Produces: `RemovePagesDialog`, `ExtractPagesDialog`, `ReorderPagesDialog`.

- [ ] **Step 1: Write `app/ui/dialogs/pages_dialogs.py`**

```python
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QLabel,
)

from app.core.pdf_ops import get_page_count, remove_pages, extract_pages, reorder_pages
from app.ui.dialogs.base import ToolDialog


class _PageCheckList(QListWidget):
    def populate(self, count: int) -> None:
        self.clear()
        for i in range(1, count + 1):
            item = QListWidgetItem(f"Page {i}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, i)
            self.addItem(item)

    def checked_pages(self) -> list[int]:
        return [
            self.item(i).data(Qt.UserRole)
            for i in range(self.count())
            if self.item(i).checkState() == Qt.Checked
        ]


class RemovePagesDialog(ToolDialog):
    title = "Remove pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Check the pages to remove:"))
        self.page_list = _PageCheckList()
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths:
            self.page_list.populate(get_page_count(paths[0]))

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        pages = self.page_list.checked_pages()
        if not pages:
            raise ValueError("Check at least one page to remove.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_removed.pdf"))
        remove_pages(input_path, pages, out_path)
        return [out_path]


class ExtractPagesDialog(ToolDialog):
    title = "Extract pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Check the pages to extract:"))
        self.page_list = _PageCheckList()
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if paths:
            self.page_list.populate(get_page_count(paths[0]))

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        pages = self.page_list.checked_pages()
        if not pages:
            raise ValueError("Check at least one page to extract.")
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_extracted.pdf"))
        extract_pages(input_path, pages, out_path)
        return [out_path]


class ReorderPagesDialog(ToolDialog):
    title = "Reorder pages"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Drag pages into the order you want:"))
        self.page_list = QListWidget()
        self.page_list.setDragDropMode(QAbstractItemView.InternalMove)
        layout.addWidget(self.page_list)

    def on_files_changed(self, paths: list[str]) -> None:
        if not paths:
            return
        count = get_page_count(paths[0])
        self.page_list.clear()
        for i in range(1, count + 1):
            item = QListWidgetItem(f"Page {i}")
            item.setData(Qt.UserRole, i)
            self.page_list.addItem(item)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        order = [self.page_list.item(i).data(Qt.UserRole) for i in range(self.page_list.count())]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_reordered.pdf"))
        reorder_pages(input_path, order, out_path)
        return [out_path]
```

- [ ] **Step 2: Register the three tools in `app/main.py`**

Add the import:

```python
from app.ui.dialogs.pages_dialogs import RemovePagesDialog, ExtractPagesDialog, ReorderPagesDialog
```

Add registrations alongside the existing ones:

```python
    window.add_tool("Organize", "Remove pages", RemovePagesDialog)
    window.add_tool("Organize", "Extract pages", ExtractPagesDialog)
    window.add_tool("Organize", "Reorder pages", ReorderPagesDialog)
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
- Click "Remove pages", add a multi-page PDF, confirm the page checklist populates immediately, check 1-2 pages, Run, confirm the output has the right page count.
- Click "Extract pages", same file, check pages 2 and 4 in that order, Run, confirm output has exactly those 2 pages.
- Click "Reorder pages", same file, drag page 3 to the top, Run, confirm output's first page is what was page 3.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/pages_dialogs.py app/main.py
git commit -m "feat: Remove/Extract/Reorder pages dialogs"
```

---

## Task 12: UI — Rotate & Watermark dialogs

**Files:**
- Create: `app/ui/dialogs/edit_dialogs.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ToolDialog` (Task 8); `rotate_pages`, `add_watermark` (Task 4); `MainWindow.add_tool` (Task 9).
- Produces: `RotateDialog`, `WatermarkDialog`.

- [ ] **Step 1: Write `app/ui/dialogs/edit_dialogs.py`**

```python
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QLabel, QLineEdit, QSlider

from app.core.pdf_ops import rotate_pages, add_watermark
from app.ui.dialogs.base import ToolDialog


class RotateDialog(ToolDialog):
    title = "Rotate PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Rotate all pages by:"))
        self.angle_box = QComboBox()
        self.angle_box.addItems(["90", "180", "270"])
        layout.addWidget(self.angle_box)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        angle = int(self.angle_box.currentText())
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_rotated.pdf"))
        rotate_pages(input_path, out_path, angle)
        return [out_path]


class WatermarkDialog(ToolDialog):
    title = "Add watermark"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Watermark text:"))
        self.text_input = QLineEdit()
        layout.addWidget(self.text_input)
        layout.addWidget(QLabel("Opacity (%):"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(30)
        layout.addWidget(self.opacity_slider)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        text = self.text_input.text()
        opacity = self.opacity_slider.value() / 100
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_watermarked.pdf"))
        add_watermark(input_path, out_path, text, opacity=opacity)
        return [out_path]
```

- [ ] **Step 2: Register the two tools in `app/main.py`**

Add the import:

```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog
```

Add registrations:

```python
    window.add_tool("Edit", "Rotate PDF", RotateDialog)
    window.add_tool("Edit", "Add watermark", WatermarkDialog)
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
- Click "Rotate PDF", add a PDF, pick 90, Run, confirm the output file opens rotated in a PDF viewer.
- Click "Add watermark", add a PDF, type "DRAFT", Run, confirm the output shows the watermark text on every page.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py
git commit -m "feat: Rotate and Add watermark dialogs"
```

---

## Task 13: UI — Compress dialog

**Files:**
- Create: `app/ui/dialogs/optimize_dialogs.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ToolDialog` (Task 8); `compress_pdf` (Task 5); `MainWindow.add_tool` (Task 9).
- Produces: `CompressDialog`.

- [ ] **Step 1: Write `app/ui/dialogs/optimize_dialogs.py`**

```python
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSlider

from app.core.pdf_ops import compress_pdf
from app.ui.dialogs.base import ToolDialog


class CompressDialog(ToolDialog):
    title = "Compress PDF"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Image quality:"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(10, 100)
        self.quality_slider.setValue(60)
        layout.addWidget(self.quality_slider)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_compressed.pdf"))
        compress_pdf(input_path, out_path, image_quality=self.quality_slider.value())
        return [out_path]
```

- [ ] **Step 2: Register the tool in `app/main.py`**

Add the import:

```python
from app.ui.dialogs.optimize_dialogs import CompressDialog
```

Add registration:

```python
    window.add_tool("Optimize", "Compress PDF", CompressDialog)
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
Click "Compress PDF", add a PDF with images, set quality to 40, Run, confirm the output file is smaller than the original (check file sizes in Explorer).

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/optimize_dialogs.py app/main.py
git commit -m "feat: Compress PDF dialog"
```

---

## Task 14: UI — PDF→Images & PDF→Word dialogs

**Files:**
- Create: `app/ui/dialogs/convert_dialogs.py`
- Modify: `app/main.py`

**Interfaces:**
- Consumes: `ToolDialog` (Task 8); `render_to_images` (Task 6), `convert_to_word` (Task 7); `MainWindow.add_tool` (Task 9).
- Produces: `ToImagesDialog`, `ToWordDialog`.

- [ ] **Step 1: Write `app/ui/dialogs/convert_dialogs.py`**

```python
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox

from app.core.pdf_ops import render_to_images
from app.core.convert import convert_to_word
from app.ui.dialogs.base import ToolDialog


class ToImagesDialog(ToolDialog):
    title = "PDF to JPG"

    def build_options(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Format:"))
        self.format_box = QComboBox()
        self.format_box.addItems(["png", "jpg"])
        layout.addWidget(self.format_box)

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        output_dir = str(Path(input_path).parent)
        return render_to_images(input_path, output_dir, image_format=self.format_box.currentText())


class ToWordDialog(ToolDialog):
    title = "PDF to Word"

    def run_operation(self, input_paths: list[str]) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + ".docx"))
        convert_to_word(input_path, out_path)
        return [out_path]
```

- [ ] **Step 2: Register the two tools in `app/main.py`**

Add the import:

```python
from app.ui.dialogs.convert_dialogs import ToImagesDialog, ToWordDialog
```

Add registrations:

```python
    window.add_tool("Convert", "PDF to JPG", ToImagesDialog)
    window.add_tool("Convert", "PDF to Word", ToWordDialog)
```

- [ ] **Step 3: Manual verification**

Run: `venv/Scripts/python -m app.main`
- Click "PDF to JPG", add a multi-page PDF, Run, confirm one image file per page appears next to the input.
- Click "PDF to Word", add a PDF, Run (allow a few seconds), confirm a `.docx` appears and opens correctly in Word/LibreOffice with recognizable layout.

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/convert_dialogs.py app/main.py
git commit -m "feat: PDF to Images and PDF to Word dialogs"
```

---

## Task 15: Packaging — PyInstaller build

**Files:**
- Create: `PDFEditor.spec` (generated by PyInstaller, then committed)

**Interfaces:**
- Consumes: the complete `app/` package from Tasks 1-14.
- Produces: `dist/PDFEditor/PDFEditor.exe` (not committed — build output).

- [ ] **Step 1: Run PyInstaller to generate the build**

```bash
venv/Scripts/pyinstaller --name PDFEditor --onedir --windowed --collect-all PySide6 app/main.py
```

Expected: completes without errors; creates `build/`, `dist/PDFEditor/`, and `PDFEditor.spec` in the project root.

- [ ] **Step 2: Manual verification — run the packaged exe**

Run: `dist/PDFEditor/PDFEditor.exe` (double-click in Explorer, or `start dist/PDFEditor/PDFEditor.exe` from a shell)
Expected: the "PDF Editor" window opens standalone (no Python/console needed), all 10 tool buttons are present across the four categories, and at least one tool (e.g. Merge) runs successfully end-to-end on a real PDF from this standalone build.

- [ ] **Step 3: Commit the generated spec file for reproducible future builds**

```bash
git add PDFEditor.spec
git commit -m "build: PyInstaller spec for standalone Windows build"
```

---

## Task 16: Desktop shortcut

**Files:**
- Create: `scripts/create_desktop_shortcut.py`

**Interfaces:**
- Consumes: the built `dist/PDFEditor/PDFEditor.exe` from Task 15.
- Produces: a `PDF Editor.lnk` file on the user's Desktop.

- [ ] **Step 1: Write `scripts/create_desktop_shortcut.py`**

```python
import subprocess
import sys
from pathlib import Path


def create_shortcut(target_exe: str, shortcut_name: str = "PDF Editor") -> Path:
    desktop = Path.home() / "Desktop"
    shortcut_path = desktop / f"{shortcut_name}.lnk"
    target = Path(target_exe).resolve()
    working_dir = target.parent

    ps_script = (
        "$WshShell = New-Object -ComObject WScript.Shell\n"
        f'$Shortcut = $WshShell.CreateShortcut("{shortcut_path}")\n'
        f'$Shortcut.TargetPath = "{target}"\n'
        f'$Shortcut.WorkingDirectory = "{working_dir}"\n'
        "$Shortcut.Save()\n"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], check=True)
    return shortcut_path


if __name__ == "__main__":
    default_target = str(Path("dist/PDFEditor/PDFEditor.exe").resolve())
    target = sys.argv[1] if len(sys.argv) > 1 else default_target
    path = create_shortcut(target)
    print(f"Shortcut created at {path}")
```

- [ ] **Step 2: Run it against the built exe**

Run: `venv/Scripts/python scripts/create_desktop_shortcut.py`
Expected: prints `Shortcut created at C:\Users\<you>\Desktop\PDF Editor.lnk`.

- [ ] **Step 3: Manual verification**

Look at the Windows Desktop, confirm a "PDF Editor" shortcut icon is present. Double-click it and confirm the app launches.

- [ ] **Step 4: Commit**

```bash
git add scripts/create_desktop_shortcut.py
git commit -m "feat: script to create a Desktop shortcut to the packaged app"
```

---

## Plan complete

At the end of Task 16, `PDF Editor` is a standalone Windows app covering Merge, Split, Remove pages, Extract pages, Reorder pages, Rotate, Add watermark, Compress, PDF→JPG, and PDF→Word, launchable from a Desktop shortcut with no Python installation required. Phase 2 (Crop, page numbers, direct in-PDF text editing, Redact, PDF Forms, Sign, JPG→PDF, Scan to PDF) and Phase 3 (per the spec's roadmap) are separate future plans.
