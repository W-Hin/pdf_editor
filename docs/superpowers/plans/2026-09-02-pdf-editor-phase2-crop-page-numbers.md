# Phase 2 Group A: Crop + Add Page Numbers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two tools to the web app — Crop (drag a box on the page to trim a uniform margin
off every page) and Add page numbers (stamp a formatted page number into a chosen corner of
every page) — following the existing tool-grid pattern.

**Architecture:** Crop sets each page's CropBox via PyMuPDF (`page.set_cropbox()`), non-destructive
to content; the crop box is stored/transmitted as 0–1 fractions of page width/height so one
rectangle drawn against page 1 applies sensibly to every page regardless of page size. Add page
numbers draws formatted text via `page.insert_textbox()` into a small rect anchored at the chosen
corner. The frontend gains a new `CropSelector` component (drag-to-draw a rectangle on a
higher-resolution single-page preview, converting screen pixels to page fractions) and extends
the existing `PageGrid` `overlay` mechanism (built for Watermark's live preview) to support
corner-anchored, not just centered, overlay content.

**Tech Stack:** Python/FastAPI/PyMuPDF backend (unchanged), React/Vite frontend (unchanged).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-crop-page-numbers-design.md` — read
  it first; this plan implements it exactly.
- Crop fractions must each be validated `0 <= value < 0.5` — this single bound is sufficient to
  guarantee positive resulting area (see spec's Architecture section for the proof); do not add a
  separate "positive area" check, it would be unreachable dead code.
- Crop applies one rectangle to every page, as fractions — never absolute point coordinates.
- Page number positions are a fixed six-item enum; formats are a fixed three-item enum. No
  free-text template, no click-to-place.
- All user-facing errors raise `app.core.errors.PDFError` — never a raw exception surfaced to the
  API layer (matches every existing tool in `app/core/pdf_ops.py`).
- Every new backend function/route follows the exact patterns already established by the ten
  existing tools in `app/core/pdf_ops.py` and `web/backend/routes/tools.py` — read
  `add_watermark`/`rotate_pages` and the `watermark`/`rotate` routes as the closest precedents
  before writing new code.
- No new frontend automated test infrastructure — frontend behavior is verified by manual browser
  testing at the end (matching how Watermark/Rotate/Merge/Split previews were verified previously),
  not by adding a component-testing framework.

---

### Task 1: Crop — core function

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `crop_pdf(input_path: str, output_path: str, top: float, right: float, bottom: float, left: float) -> None`, raising `PDFError` on any fraction outside `[0, 0.5)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py` (the file already has `import fitz`, `import pytest`, and
imports from `app.core.pdf_ops` / `app.core.errors` at the top — add `crop_pdf` to the existing
`from app.core.pdf_ops import ...` line):

```python
def test_crop_pdf_reduces_cropbox_size(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    original_rect = fitz.open(input_path)[0].rect

    crop_pdf(input_path, str(output_path), top=0.1, right=0.1, bottom=0.1, left=0.1)

    doc = fitz.open(str(output_path))
    assert doc[0].rect.width == pytest.approx(original_rect.width * 0.8)
    assert doc[0].rect.height == pytest.approx(original_rect.height * 0.8)
    doc.close()


def test_crop_pdf_applies_same_fraction_across_mixed_page_sizes(tmp_path):
    doc = fitz.open()
    doc.new_page(width=200, height=300)
    doc.new_page(width=400, height=600)
    input_path = tmp_path / "mixed.pdf"
    doc.save(str(input_path))
    doc.close()
    output_path = tmp_path / "cropped.pdf"

    crop_pdf(str(input_path), str(output_path), top=0.1, right=0.1, bottom=0.1, left=0.1)

    result = fitz.open(str(output_path))
    assert result[0].rect.width == pytest.approx(200 * 0.8)
    assert result[0].rect.height == pytest.approx(300 * 0.8)
    assert result[1].rect.width == pytest.approx(400 * 0.8)
    assert result[1].rect.height == pytest.approx(600 * 0.8)
    result.close()


def test_crop_pdf_near_boundary_fractions_still_succeed(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"

    crop_pdf(input_path, str(output_path), top=0.49, right=0.49, bottom=0.49, left=0.49)

    doc = fitz.open(str(output_path))
    assert doc[0].rect.width > 0
    assert doc[0].rect.height > 0
    doc.close()


def test_crop_pdf_rejects_fraction_at_or_above_half(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    with pytest.raises(PDFError):
        crop_pdf(input_path, str(output_path), top=0.5, right=0.1, bottom=0.1, left=0.1)


def test_crop_pdf_rejects_negative_fraction(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "cropped.pdf"
    with pytest.raises(PDFError):
        crop_pdf(input_path, str(output_path), top=0.1, right=0.1, bottom=0.1, left=-0.1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k crop_pdf -v`
Expected: FAIL with `ImportError` / `NameError` — `crop_pdf` doesn't exist yet.

- [ ] **Step 3: Implement `crop_pdf`**

Add to `app/core/pdf_ops.py` (after `add_watermark`, before `compress_pdf` — keep the
Edit-category functions grouped together):

```python
def crop_pdf(input_path: str, output_path: str, top: float, right: float, bottom: float, left: float) -> None:
    for name, value in (("top", top), ("right", right), ("bottom", bottom), ("left", left)):
        if not (0 <= value < 0.5):
            raise PDFError(f"Crop '{name}' must be between 0 and 0.5 (got {value}).")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            rect = page.rect
            new_rect = fitz.Rect(
                rect.x0 + left * rect.width,
                rect.y0 + top * rect.height,
                rect.x1 - right * rect.width,
                rect.y1 - bottom * rect.height,
            )
            page.set_cropbox(new_rect)
        doc.save(output_path)
    finally:
        doc.close()
```

Also add `crop_pdf` to the test file's import line:
`from app.core.pdf_ops import open_pdf, get_page_count, merge_pdfs, extract_pages, remove_pages, reorder_pages, split_pdf, rotate_pages, add_watermark, crop_pdf`

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k crop_pdf -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add crop_pdf core function"
```

---

### Task 2: Add page numbers — core function

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `add_page_numbers(input_path: str, output_path: str, position: str, format: str) -> None`, raising `PDFError` for an unknown `position` or `format`.
- `position` ∈ `{"bottom-center", "bottom-right", "bottom-left", "top-center", "top-right", "top-left"}`.
- `format` ∈ `{"number", "number-of-total", "page-x-of-y"}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py`:

```python
def test_add_page_numbers_page_x_of_y_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=3)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="page-x-of-y")

    doc = fitz.open(str(output_path))
    assert "Page 1 of 3" in doc[0].get_text()
    assert "Page 2 of 3" in doc[1].get_text()
    assert "Page 3 of 3" in doc[2].get_text()
    doc.close()


def test_add_page_numbers_number_of_total_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=2)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="number-of-total")

    doc = fitz.open(str(output_path))
    assert "1 / 2" in doc[0].get_text()
    doc.close()


def test_add_page_numbers_plain_number_appears_at_bottom(make_pdf, tmp_path):
    # make_pdf's own fixture text ("Page N") sits near the top-left (72, 72).
    # Checking for a standalone "1" token in the page's bottom half proves
    # add_page_numbers actually added something there — a plain substring
    # check on the whole page's text couldn't distinguish our output from
    # the fixture's own pre-existing "Page 1" text.
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="bottom-center", format="number")

    doc = fitz.open(str(output_path))
    page = doc[0]
    page_height = page.rect.height
    bottom_words = [w[4] for w in page.get_text("words") if w[1] > page_height / 2]
    assert "1" in bottom_words
    doc.close()


def test_add_page_numbers_top_position_places_text_in_top_half(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"

    add_page_numbers(input_path, str(output_path), position="top-right", format="number-of-total")

    doc = fitz.open(str(output_path))
    page = doc[0]
    page_height = page.rect.height
    page_width = page.rect.width
    top_right_words = [
        w[4] for w in page.get_text("words")
        if w[1] < page_height / 2 and w[0] > page_width / 2
    ]
    # A 1-page document formatted as "number-of-total" renders "1 / 1",
    # tokenized as separate words "1" and "/" — either confirms the text
    # landed in the top-right quadrant.
    assert any(w in ("1", "/") for w in top_right_words)
    doc.close()


def test_add_page_numbers_rejects_unknown_position(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"
    with pytest.raises(PDFError):
        add_page_numbers(input_path, str(output_path), position="middle", format="number")


def test_add_page_numbers_rejects_unknown_format(make_pdf, tmp_path):
    input_path = make_pdf(num_pages=1)
    output_path = tmp_path / "numbered.pdf"
    with pytest.raises(PDFError):
        add_page_numbers(input_path, str(output_path), position="bottom-center", format="roman")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k add_page_numbers -v`
Expected: FAIL — `add_page_numbers` doesn't exist yet.

- [ ] **Step 3: Implement `add_page_numbers`**

Add to `app/core/pdf_ops.py`, directly after `crop_pdf`:

```python
_PAGE_NUMBER_ALIGN = {
    "bottom-left": fitz.TEXT_ALIGN_LEFT,
    "bottom-center": fitz.TEXT_ALIGN_CENTER,
    "bottom-right": fitz.TEXT_ALIGN_RIGHT,
    "top-left": fitz.TEXT_ALIGN_LEFT,
    "top-center": fitz.TEXT_ALIGN_CENTER,
    "top-right": fitz.TEXT_ALIGN_RIGHT,
}

_PAGE_NUMBER_FORMATS = {"number", "number-of-total", "page-x-of-y"}

_PAGE_NUMBER_MARGIN = 36  # points; 0.5in, the conventional print margin
_PAGE_NUMBER_BAND_HEIGHT = 20  # points


def _format_page_number(fmt: str, page_num: int, total: int) -> str:
    if fmt == "number":
        return str(page_num)
    if fmt == "number-of-total":
        return f"{page_num} / {total}"
    return f"Page {page_num} of {total}"


def add_page_numbers(input_path: str, output_path: str, position: str, format: str) -> None:
    if position not in _PAGE_NUMBER_ALIGN:
        raise PDFError(f"Unknown page number position: {position}")
    if format not in _PAGE_NUMBER_FORMATS:
        raise PDFError(f"Unknown page number format: {format}")
    doc = open_pdf(input_path)
    try:
        total = doc.page_count
        for i, page in enumerate(doc, start=1):
            rect = page.rect
            if position.startswith("bottom"):
                band = fitz.Rect(
                    rect.x0 + _PAGE_NUMBER_MARGIN,
                    rect.y1 - _PAGE_NUMBER_MARGIN - _PAGE_NUMBER_BAND_HEIGHT,
                    rect.x1 - _PAGE_NUMBER_MARGIN,
                    rect.y1 - _PAGE_NUMBER_MARGIN,
                )
            else:
                band = fitz.Rect(
                    rect.x0 + _PAGE_NUMBER_MARGIN,
                    rect.y0 + _PAGE_NUMBER_MARGIN,
                    rect.x1 - _PAGE_NUMBER_MARGIN,
                    rect.y0 + _PAGE_NUMBER_MARGIN + _PAGE_NUMBER_BAND_HEIGHT,
                )
            page.insert_textbox(
                band,
                _format_page_number(format, i, total),
                fontsize=10,
                fontname="helv",
                color=(0, 0, 0),
                align=_PAGE_NUMBER_ALIGN[position],
            )
        doc.save(output_path)
    finally:
        doc.close()
```

Also add `add_page_numbers` to the test file's import line from Task 1.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k add_page_numbers -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the full core test suite**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all PASS (no regressions in existing tests).

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add add_page_numbers core function"
```

---

### Task 3: Backend routes for Crop and Add Page Numbers

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `crop_pdf` and `add_page_numbers` from Tasks 1–2 (exact signatures above).
- Produces: `POST /api/tools/crop` and `POST /api/tools/add-page-numbers`, both returning
  `{"outputs": [{"id": str, "filename": str, "download_url": str}]}` — the same shape every
  other tool endpoint already returns via `_output_response`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_tools_edit_convert.py` (the file already has `_upload_pdf()` defined at
module level — reuse it, don't redefine it):

```python
def test_crop_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_crop_rejects_out_of_range_fraction():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/crop",
        json={"file_id": upload["id"], "top": 0.6, "right": 0.1, "bottom": 0.1, "left": 0.1},
    )
    assert response.status_code == 422


def test_add_page_numbers_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/add-page-numbers",
        json={"file_id": upload["id"], "position": "bottom-center", "format": "number"},
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_add_page_numbers_rejects_unknown_position():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/add-page-numbers",
        json={"file_id": upload["id"], "position": "middle", "format": "number"},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -k "crop or page_numbers" -v`
Expected: FAIL with 404 (routes don't exist yet).

- [ ] **Step 3: Implement the routes**

In `web/backend/routes/tools.py`, add `crop_pdf` and `add_page_numbers` to the existing
`from app.core.pdf_ops import (...)` block (keep it alphabetically sorted like the rest of that
block):

```python
from app.core.pdf_ops import (
    add_page_numbers,
    add_watermark,
    compress_pdf,
    crop_pdf,
    extract_pages,
    get_page_count,
    merge_pdfs,
    remove_pages,
    render_to_images,
    reorder_pages,
    rotate_pages,
    split_pdf,
)
```

Then add, after the `watermark` route (keeping Edit-category tools grouped together):

```python
class CropRequest(BaseModel):
    file_id: str
    top: float
    right: float
    bottom: float
    left: float


@router.post("/crop")
def crop(req: CropRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_cropped")
    crop_pdf(input_path, str(output_path), top=req.top, right=req.right, bottom=req.bottom, left=req.left)
    return _output_response([output_path], "Crop PDF", [Path(input_path).name])


class AddPageNumbersRequest(BaseModel):
    file_id: str
    position: str
    format: str


@router.post("/add-page-numbers")
def add_page_numbers_route(req: AddPageNumbersRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_numbered")
    add_page_numbers(input_path, str(output_path), position=req.position, format=req.format)
    return _output_response([output_path], "Add page numbers", [Path(input_path).name])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_edit_convert.py
git commit -m "feat: add /tools/crop and /tools/add-page-numbers routes"
```

---

### Task 4: Expose a `max_size` query param on the thumbnail route

**Files:**
- Modify: `web/backend/routes/files.py`
- Test: `tests/web/test_files.py`

**Interfaces:**
- Consumes: `render_page_thumbnail(input_path, page_number, max_size)` — already accepts
  `max_size` (see `app/core/pdf_ops.py:170`), just wasn't exposed as a route parameter.
- Produces: `GET /api/files/{file_id}/pages/{page_number}/thumbnail?max_size=N` — `max_size`
  optional, defaults to 220 (today's hardcoded value, so every existing caller is unaffected),
  validated to `50 <= max_size <= 2000`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_files.py`:

```python
def test_thumbnail_default_max_size_is_220():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/pages/1/thumbnail")

    pix = fitz.Pixmap(response.content)
    # Off-by-one is possible from floating-point rounding in the render
    # pipeline's scale computation — assert closeness, not exact equality.
    assert abs(max(pix.width, pix.height) - 220) <= 1


def test_thumbnail_respects_custom_max_size():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/pages/1/thumbnail?max_size=700")

    assert response.status_code == 200
    pix = fitz.Pixmap(response.content)
    assert abs(max(pix.width, pix.height) - 700) <= 1


def test_thumbnail_rejects_max_size_out_of_bounds():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/pages/1/thumbnail?max_size=10")

    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_files.py -k max_size -v`
Expected: `test_thumbnail_respects_custom_max_size` FAILs (still returns 220, the param is
ignored); `test_thumbnail_rejects_max_size_out_of_bounds` FAILs (still returns 200, no
validation yet); `test_thumbnail_default_max_size_is_220` already PASSes (it's the current
behavior) — that's fine, it's here to lock in the default going forward.

- [ ] **Step 3: Implement the query param**

In `web/backend/routes/files.py`, change:

```python
@router.get("/files/{file_id}/pages/{page_number}/thumbnail")
def get_thumbnail(file_id: str, page_number: int):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    thumb_bytes = render_page_thumbnail(str(path), page_number, max_size=220)
    return Response(content=thumb_bytes, media_type="image/png")
```

to:

```python
@router.get("/files/{file_id}/pages/{page_number}/thumbnail")
def get_thumbnail(file_id: str, page_number: int, max_size: int = 220):
    if not 50 <= max_size <= 2000:
        raise HTTPException(status_code=422, detail="max_size must be between 50 and 2000.")
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    thumb_bytes = render_page_thumbnail(str(path), page_number, max_size=max_size)
    return Response(content=thumb_bytes, media_type="image/png")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/test_files.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/files.py tests/web/test_files.py
git commit -m "feat: expose max_size query param on the thumbnail route"
```

---

### Task 5: Frontend — Add Page Numbers tool

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/components/PageGrid.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `POST /tools/add-page-numbers` from Task 3 (`{file_id, position, format}`).
- Produces: a `select` field option shape `{value, label}` (in addition to the existing plain-scalar shape) that `ToolView.jsx`'s field renderer now supports — later tasks/tools can use either shape.
- Produces: `PageGrid`'s new `overlayPosition` prop (string, one of the six position values, or omitted for the existing centered behavior).

- [ ] **Step 1: Add the `add-page-numbers` tool config**

In `web/frontend/src/toolConfigs.js`, add a new entry (category `"Edit"`, alongside `rotate` and
`watermark`):

```javascript
"add-page-numbers": {
  title: "Add page numbers",
  category: "Edit",
  multiFile: false,
  mode: "view",
  preview: "page-numbers",
  endpoint: "add-page-numbers",
  fields: [
    {
      name: "position",
      label: "Position",
      type: "select",
      options: [
        { value: "bottom-center", label: "Bottom center" },
        { value: "bottom-right", label: "Bottom right" },
        { value: "bottom-left", label: "Bottom left" },
        { value: "top-center", label: "Top center" },
        { value: "top-right", label: "Top right" },
        { value: "top-left", label: "Top left" },
      ],
      default: "bottom-center",
    },
    {
      name: "format",
      label: "Format",
      type: "select",
      options: [
        { value: "number", label: "3" },
        { value: "number-of-total", label: "3 / 12" },
        { value: "page-x-of-y", label: "Page 3 of 12" },
      ],
      default: "number",
    },
  ],
},
```

- [ ] **Step 2: Support `{value, label}` select options in `ToolView.jsx`**

Every existing `select` field (`rotate`'s `angle`, `to-images`'s `image_format`) uses plain
scalar options where the value and displayed label are the same string/number. The new
`position`/`format` fields need a human-readable label distinct from their machine value (e.g.
`"number-of-total"` should display as `"3 / 12"`), so the option renderer needs to support both
shapes without breaking the existing plain-scalar tools.

In `web/frontend/src/components/ToolView.jsx`, find this block inside the `field.type === "select"`
branch:

```jsx
{field.options.map((opt) => (
  <option key={opt} value={opt}>
    {opt}
  </option>
))}
```

Replace it with:

```jsx
{field.options.map((opt) => {
  const optValue = typeof opt === "object" ? opt.value : opt;
  const optLabel = typeof opt === "object" ? opt.label : opt;
  return (
    <option key={optValue} value={optValue}>
      {optLabel}
    </option>
  );
})}
```

- [ ] **Step 3: Add `overlayPosition` to `PageGrid`**

In `web/frontend/src/components/PageGrid.jsx`, add `overlayPosition` to the destructured props:

```jsx
export default function PageGrid({
  fileId,
  pageCount,
  mode = "view",
  selected,
  onToggle,
  order,
  onReorder,
  pageRange,
  rotateAngle,
  overlay,
  overlayPosition,
}) {
```

Then update the overlay's rendered `className` (currently
`className="page-thumb__overlay"`) to:

```jsx
{overlay && (
  <div
    className={`page-thumb__overlay${overlayPosition ? ` page-thumb__overlay--${overlayPosition}` : ""}`}
    aria-hidden="true"
  >
    {overlay(pageNumber)}
  </div>
)}
```

- [ ] **Step 4: Add the position modifier CSS**

In `web/frontend/src/index.css`, directly after the existing `.page-thumb__overlay` rule, add:

```css
.page-thumb__overlay--bottom-center { align-items: flex-end; justify-content: center; }
.page-thumb__overlay--bottom-right { align-items: flex-end; justify-content: flex-end; }
.page-thumb__overlay--bottom-left { align-items: flex-end; justify-content: flex-start; }
.page-thumb__overlay--top-center { align-items: flex-start; justify-content: center; }
.page-thumb__overlay--top-right { align-items: flex-start; justify-content: flex-end; }
.page-thumb__overlay--top-left { align-items: flex-start; justify-content: flex-start; }

.page-thumb__page-number-preview {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-secondary);
  background: rgba(255, 255, 255, 0.85);
  padding: 1px 4px;
  border-radius: 3px;
}
```

(No change needed to `.page-thumb__overlay` itself — its existing centered `align-items`/
`justify-content` remain the default for Watermark, which never passes `overlayPosition`.)

- [ ] **Step 5: Add the `page-numbers` preview branch to `ToolView.jsx`**

Add a small formatting helper near the top of `web/frontend/src/components/ToolView.jsx` (after
the existing `clampNumberField` function):

```javascript
function formatPageNumberPreview(format, pageNumber, total) {
  if (format === "number-of-total") return `${pageNumber} / ${total}`;
  if (format === "page-x-of-y") return `Page ${pageNumber} of ${total}`;
  return String(pageNumber);
}
```

Then add a new branch inside `renderPreview()`, directly after the existing `watermark` branch:

```jsx
if (config.preview === "page-numbers") {
  if (!primaryFile) return null;
  const position = fieldValues.position ?? "bottom-center";
  const format = fieldValues.format ?? "number";
  const total = primaryFile.page_count;
  return (
    <PageGrid
      fileId={primaryFile.id}
      pageCount={primaryFile.page_count}
      mode="view"
      overlayPosition={position}
      overlay={(pageNumber) => (
        <span className="page-thumb__page-number-preview">
          {formatPageNumberPreview(format, pageNumber, total)}
        </span>
      )}
    />
  );
}
```

- [ ] **Step 6: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors.

- [ ] **Step 7: Run the full backend test suite (confirm no regressions)**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS (this task touched no backend code, but confirm nothing else broke).

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx web/frontend/src/components/PageGrid.jsx web/frontend/src/index.css
git commit -m "feat: add Add Page Numbers tool with live corner-positioned preview"
```

---

### Task 6: Frontend — `CropSelector` component

**Files:**
- Create: `web/frontend/src/components/CropSelector.jsx`
- Modify: `web/frontend/src/api.js`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `thumbnailUrl(fileId, pageNumber, maxSize)` — `maxSize` is a new optional third
  parameter added in this task.
- Produces: `<CropSelector fileId={string} onChange={(rect) => void}>` where `rect` is
  `{top, right, bottom, left}` (each a 0–1 fraction) — `onChange` fires once per completed drag
  of at least 2% of the image's width/height in both dimensions (guards against an accidental
  click registering as an empty crop).

- [ ] **Step 1: Add the `maxSize` parameter to `thumbnailUrl`**

In `web/frontend/src/api.js`, change:

```javascript
export function thumbnailUrl(fileId, pageNumber) {
  return `${BASE}/files/${fileId}/pages/${pageNumber}/thumbnail`;
}
```

to:

```javascript
export function thumbnailUrl(fileId, pageNumber, maxSize) {
  const query = maxSize ? `?max_size=${maxSize}` : "";
  return `${BASE}/files/${fileId}/pages/${pageNumber}/thumbnail${query}`;
}
```

(Every existing call site omits the third argument, so this is backward compatible — they keep
getting the default 220px thumbnail.)

- [ ] **Step 2: Create `CropSelector.jsx`**

Create `web/frontend/src/components/CropSelector.jsx`:

```jsx
import { useRef, useState } from "react";
import { thumbnailUrl } from "../api";

const PREVIEW_MAX_SIZE = 700;
const MIN_DRAG_FRACTION = 0.02;

export default function CropSelector({ fileId, onChange }) {
  const containerRef = useRef(null);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);
  const [committedBox, setCommittedBox] = useState(null);

  if (!fileId) return null;

  function pointFromEvent(e) {
    const rect = containerRef.current.getBoundingClientRect();
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(e) {
    const point = pointFromEvent(e);
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(e) {
    if (!dragStart) return;
    setDragCurrent(pointFromEvent(e));
  }

  function handleMouseUp() {
    if (!dragStart || !dragCurrent) return;
    const x0 = Math.min(dragStart.x, dragCurrent.x);
    const x1 = Math.max(dragStart.x, dragCurrent.x);
    const y0 = Math.min(dragStart.y, dragCurrent.y);
    const y1 = Math.max(dragStart.y, dragCurrent.y);
    setDragStart(null);
    setDragCurrent(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) {
      return; // too small to be a deliberate drag — keep any already-committed box
    }
    setCommittedBox({ x0, y0, x1, y1 });
    onChange({ top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 });
  }

  const activeBox =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : committedBox;

  return (
    <div
      ref={containerRef}
      className="crop-selector"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    >
      <img
        className="crop-selector__image"
        src={thumbnailUrl(fileId, 1, PREVIEW_MAX_SIZE)}
        alt="Page 1 preview — drag to select the area to keep"
        draggable={false}
      />
      {activeBox && (
        <>
          <div
            className="crop-selector__mask"
            style={{ left: 0, right: 0, top: 0, height: `${activeBox.y0 * 100}%` }}
          />
          <div
            className="crop-selector__mask"
            style={{ left: 0, right: 0, top: `${activeBox.y1 * 100}%`, bottom: 0 }}
          />
          <div
            className="crop-selector__mask"
            style={{
              top: `${activeBox.y0 * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
              left: 0,
              width: `${activeBox.x0 * 100}%`,
            }}
          />
          <div
            className="crop-selector__mask"
            style={{
              top: `${activeBox.y0 * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
              right: 0,
              width: `${(1 - activeBox.x1) * 100}%`,
            }}
          />
          <div
            className="crop-selector__box"
            style={{
              left: `${activeBox.x0 * 100}%`,
              top: `${activeBox.y0 * 100}%`,
              width: `${(activeBox.x1 - activeBox.x0) * 100}%`,
              height: `${(activeBox.y1 - activeBox.y0) * 100}%`,
            }}
          />
        </>
      )}
    </div>
  );
}
```

The four `.crop-selector__mask` divs dim everything *outside* the current box (top band, bottom
band, and left/right bands spanning just the box's own vertical range) — simpler and more
robust than a single clip-path-with-a-hole, at the cost of four small divs instead of one.

- [ ] **Step 3: Add the CSS**

In `web/frontend/src/index.css`, add a new section (near the Page Grid section):

```css
/* ---------- Crop selector ---------- */

.crop-selector {
  position: relative;
  display: inline-block;
  max-width: 100%;
  cursor: crosshair;
  user-select: none;
  margin: var(--space-5) 0;
}

.crop-selector__image {
  display: block;
  max-width: 100%;
  border-radius: var(--radius-sm);
  pointer-events: none;
}

.crop-selector__mask {
  position: absolute;
  background: rgba(15, 23, 42, 0.55);
  pointer-events: none;
}

.crop-selector__box {
  position: absolute;
  border: 2px solid var(--color-accent);
  pointer-events: none;
}
```

- [ ] **Step 4: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors. (`CropSelector` isn't wired into `ToolView` yet — Task 7 — so
this just confirms the new file and CSS compile cleanly on their own.)

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/CropSelector.jsx web/frontend/src/api.js web/frontend/src/index.css
git commit -m "feat: add CropSelector drag-to-select component"
```

---

### Task 7: Frontend — wire Crop into `ToolView`

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`

**Interfaces:**
- Consumes: `CropSelector` from Task 6, `POST /tools/crop` from Task 3.

- [ ] **Step 1: Add the `crop` tool config**

In `web/frontend/src/toolConfigs.js`, add (category `"Edit"`, alongside `rotate`, `watermark`,
`add-page-numbers`):

```javascript
crop: {
  title: "Crop PDF",
  category: "Edit",
  multiFile: false,
  mode: "view",
  preview: "crop",
  endpoint: "crop",
  fields: [],
},
```

- [ ] **Step 2: Import `CropSelector` and add `cropRect` state**

In `web/frontend/src/components/ToolView.jsx`, add the import near the top:

```javascript
import CropSelector from "./CropSelector";
```

Add a new piece of state alongside the existing `selected`/`order` state:

```javascript
const [cropRect, setCropRect] = useState(null);
```

- [ ] **Step 3: Reset `cropRect` on a new file pick**

In `handleFilePick`, find this block:

```javascript
if (primary) {
  setSelected([]);
  setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
  if (config.filenameSuffix && !fieldValues.filename) {
```

Add `setCropRect(null);` right after `setSelected([]);`:

```javascript
if (primary) {
  setSelected([]);
  setCropRect(null);
  setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
  if (config.filenameSuffix && !fieldValues.filename) {
```

- [ ] **Step 4: Add the `crop` preview branch**

In `renderPreview()`, add a new branch directly after the `page-numbers` branch added in Task 5:

```jsx
if (config.preview === "crop") {
  if (!primaryFile) return null;
  return <CropSelector fileId={primaryFile.id} onChange={setCropRect} />;
}
```

- [ ] **Step 5: Guard `handleRun` and include the crop rect in the request body**

In `handleRun`, add a guard right after the initial `setError(""); setResult(null);` lines and
before `setBusy(true)`:

```javascript
if (config.preview === "crop" && !cropRect) {
  setError("Drag a box on the page preview to select the area to keep.");
  return;
}
```

Then, inside the `try` block, right after the existing `if (config.mode === "reorder") body.order = order;`
line, add:

```javascript
if (config.preview === "crop") Object.assign(body, cropRect);
```

- [ ] **Step 6: Disable Run until a box is drawn**

Find the Run button:

```jsx
<button className="run-button" disabled={busy || files.length === 0} onClick={handleRun}>
```

Change its `disabled` condition to:

```jsx
<button
  className="run-button"
  disabled={busy || files.length === 0 || (config.preview === "crop" && !cropRect)}
  onClick={handleRun}
>
```

- [ ] **Step 7: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors.

- [ ] **Step 8: Run the full backend test suite (confirm no regressions)**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx
git commit -m "feat: wire Crop tool into ToolView with drag-to-select preview"
```

---

## Final Verification (done by the controller, not a dispatched task)

After all seven tasks land:

1. Run the full test suite once more: `venv/Scripts/python -m pytest -q` — expect all green.
2. Rebuild the frontend (`cd web/frontend && npm run build`) and launch the dev server
   (`venv/Scripts/python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8756`).
3. Manually verify Crop in the browser: upload a multi-page PDF, drag a box on the page 1
   preview, confirm the dimmed mask/box render correctly, confirm Run is disabled until a box is
   drawn, run it, download the result, and confirm (via a quick script or PyMuPDF check) the
   output's page dimensions actually shrank by roughly the dragged fraction on *every* page, not
   just page 1.
4. Manually verify Add Page Numbers in the browser: upload a multi-page PDF, cycle through a few
   position/format combinations and confirm the live preview overlay updates and moves to the
   correct corner, run it, download the result, and confirm (via a quick script or PyMuPDF check)
   the expected text appears on the expected page in the expected quadrant.
5. Rebuild the packaged PyInstaller exe and smoke-test it launches and serves both new tools.
6. Push to `main`.
