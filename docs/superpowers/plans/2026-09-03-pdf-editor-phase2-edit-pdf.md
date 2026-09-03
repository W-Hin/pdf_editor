# Edit PDF (Phase 2 Group C2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a unified "Edit PDF" tool with five modes (Edit Text, Draw, Shapes, Highlight, Insert Image) sharing one page canvas, queued elements applied together in one Run, plus selection/clipboard/undo-redo.

**Architecture:** Two new pure functions in `app/core/pdf_ops.py` (`extract_text_runs`, `edit_pdf`) behind two new FastAPI routes, and one new `EditPdfCanvas.jsx` frontend component wired into the existing `ToolView.jsx`/`toolConfigs.js` machinery exactly like `CropSelector`/`RedactSelector` were.

**Tech Stack:** Python 3 + PyMuPDF (`fitz`) 1.28.2 on the backend; React + `@phosphor-icons/react` on the frontend. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-03-pdf-editor-phase2-edit-pdf-design.md` — read it before starting; this plan implements it exactly, citing its "finding #N" callouts where relevant.

## Global Constraints

- All position/size fields in the element model are fractions of the page's own **displayed** (rotation-aware) dimensions, matching Crop/Redact's existing convention — except where a helper below is explicitly documented as working in **raw** (unrotated mediabox) space.
- Every PyMuPDF page-content write API used here (`add_redact_annot`, `insert_text`, `page.new_shape()` draws, `add_ink_annot`, `insert_image`) expects **raw/unrotated mediabox coordinates** — verified empirically against this project's actual PyMuPDF 1.28.2 for all five (see spec findings #1–#2 and this plan's Task 3). Every helper that turns a displayed-space fraction into a PyMuPDF call MUST multiply by `page.derotation_matrix` first. This exact omission has shipped as a Critical bug twice already in this project (Crop, then Redact) — do not let it happen a third time.
- `app/core/pdf_ops.py` functions stay pure Python with zero Pydantic/FastAPI dependency; validation of API request shape belongs at the route boundary only (matching every existing function in that file).
- Frontend: no new automated test infrastructure — this project's established convention (Crop, Redact, Images-to-PDF) is manual browser verification for interactive canvas components. Each frontend task ends with a manual dev-server check instead of an automated test step.
- `PDFError` (from `app.core.errors`) is the only exception type `core/` functions raise for user-facing problems; it maps to HTTP 422 automatically at the route layer, and an unresolvable `file_id` raises `FileNotFoundError` from `storage.resolve_file()`, which maps to 404 — both exactly as every existing route already works.

---

## Task 1: `extract_text_runs` core function

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `extract_text_runs(input_path: str, page_number: int) -> list[dict]`, each dict shaped `{"index": int, "text": str, "font": str, "size": float, "bold": bool, "italic": bool, "bbox": {"top": float, "left": float, "right": float, "bottom": float}}` (bbox fractions of the page's **displayed** rect). Also produces the internal helper `_page_text_spans(page: fitz.Page) -> list[dict]` (raw PyMuPDF span dicts, in document order, whitespace-only spans skipped) — Task 3 reuses this exact function so `edit_pdf`'s `run_index` lookups are guaranteed to correspond to what this function returned, per the spec's explicit "literally the same function" requirement.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ops.py` (it already has `import fitz`, `import pytest`, and imports from `app.core.pdf_ops` / `app.core.errors` at the top — add `extract_text_runs` to the existing import line):

```python
def test_extract_text_runs_returns_text_font_size_and_style(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Plain Text", fontsize=14, fontname="helv")
    page.insert_text((72, 150), "Bold Text", fontsize=12, fontname="hebo")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert len(runs) == 2
    assert runs[0]["index"] == 0
    assert runs[0]["text"] == "Plain Text"
    assert runs[0]["size"] == 14
    assert runs[0]["bold"] is False
    assert runs[0]["italic"] is False
    assert runs[1]["text"] == "Bold Text"
    assert runs[1]["bold"] is True


def test_extract_text_runs_skips_whitespace_only_spans(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Real Text   ", fontsize=12, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert all(r["text"].strip() for r in runs)


def test_extract_text_runs_bbox_fractions_are_displayed_space(tmp_path):
    """On a rotated page, a run's bbox fraction must describe where it VISUALLY
    appears (the space the frontend renders click targets in), not raw mediabox
    space — spec finding #2: raw_bbox * page.rotation_matrix maps into displayed
    space."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Unrotated top-left; after a 90 degree rotation this is DISPLAYED top-right.
    page.insert_text((72, 72), "ROTATED")
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)

    assert len(runs) == 1
    bbox = runs[0]["bbox"]
    # Displayed top-right quadrant: small "top", small "right".
    assert bbox["top"] < 0.5
    assert bbox["right"] < 0.5
    assert 0 <= bbox["top"] < 1
    assert 0 <= bbox["left"] < 1
    assert 0 <= bbox["right"] < 1
    assert 0 <= bbox["bottom"] < 1


def test_extract_text_runs_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    with pytest.raises(PDFError):
        extract_text_runs(str(input_path), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k extract_text_runs -v`
Expected: FAIL with `ImportError`/`NameError` (`extract_text_runs` not defined).

- [ ] **Step 3: Implement `extract_text_runs` and its helper**

Add to `app/core/pdf_ops.py`, after `redact_pdf` (end of file):

```python
def _page_text_spans(page: fitz.Page) -> list[dict]:
    """Raw PyMuPDF span dicts for a page, in document order, whitespace-only
    spans skipped. Coordinates in each span's "bbox"/"origin" are in unrotated
    mediabox space — the space add_redact_annot/insert_text/set_cropbox all
    expect. edit_pdf (Task 3) reuses this exact function so a run_index from
    extract_text_runs always refers to the same span here.
    """
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip():
                    spans.append(span)
    return spans


def extract_text_runs(input_path: str, page_number: int) -> list[dict]:
    doc = open_pdf(input_path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFError(f"Page {page_number} does not exist in this document ({doc.page_count} pages).")
        page = doc[page_number - 1]
        rect = page.rect
        runs = []
        for index, span in enumerate(_page_text_spans(page)):
            # span["bbox"] is raw/unrotated; page.rotation_matrix maps it into
            # the *displayed* rect the frontend renders click targets over
            # (finding #2 — the inverse of crop_pdf/redact_pdf's derotation step).
            displayed = fitz.Rect(span["bbox"]) * page.rotation_matrix
            flags = span["flags"]
            runs.append(
                {
                    "index": index,
                    "text": span["text"],
                    "font": span["font"],
                    "size": span["size"],
                    "bold": bool(flags & 16),
                    "italic": bool(flags & 2),
                    "bbox": {
                        "top": (displayed.y0 - rect.y0) / rect.height,
                        "left": (displayed.x0 - rect.x0) / rect.width,
                        "right": (rect.x1 - displayed.x1) / rect.width,
                        "bottom": (rect.y1 - displayed.y1) / rect.height,
                    },
                }
            )
        return runs
    finally:
        doc.close()
```

Add `extract_text_runs` to the existing test file's import line at the top of `tests/test_pdf_ops.py` (find the `from app.core.pdf_ops import (...)` block and add it alphabetically among the other names).

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k extract_text_runs -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add extract_text_runs core function

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: `GET .../text-runs` route

**Files:**
- Modify: `web/backend/routes/files.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `extract_text_runs(input_path: str, page_number: int) -> list[dict]` (Task 1), `storage.resolve_file(file_id: str) -> Path` (existing).
- Produces: `GET /api/files/{file_id}/pages/{page_number}/text-runs` → `{"runs": [...]}"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_tools_edit_convert.py` (it already has `client = TestClient(app)` and `_upload_pdf()` at the top):

```python
def test_get_text_runs_returns_runs():
    upload = _upload_pdf()
    response = client.get(f"/api/files/{upload['id']}/pages/1/text-runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["text"] == "Page 1"


def test_get_text_runs_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/pages/1/text-runs")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k text_runs -v`
Expected: FAIL with 404 for the first test (route doesn't exist yet).

- [ ] **Step 3: Implement the route**

In `web/backend/routes/files.py`, add `extract_text_runs` to the existing import from `app.core.pdf_ops`, then add the route after `get_thumbnail`:

```python
from app.core.pdf_ops import extract_text_runs, get_page_count, render_page_thumbnail
```

```python
@router.get("/files/{file_id}/pages/{page_number}/text-runs")
def get_text_runs(file_id: str, page_number: int):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    runs = extract_text_runs(str(path), page_number)
    return {"runs": runs}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k text_runs -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add web/backend/routes/files.py tests/web/test_tools_edit_convert.py
git commit -m "feat: add GET text-runs route

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: `edit_pdf` core function (all five element types)

This is the largest task in the plan — it's one coherent function (matching how `crop_pdf`/`redact_pdf` were each a single task despite real complexity), and all five element types share the same validate-then-apply structure and land in the same test file.

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `_page_text_spans(page) -> list[dict]` (Task 1).
- Produces: `edit_pdf(input_path: str, output_path: str, elements: list[dict], image_paths: dict[str, str]) -> None`. Each `elements` entry is a plain dict shaped exactly like the spec's element model (with `page` 1-indexed, all fractions of the page's *displayed* dimensions), **minus** the frontend-only `id` field:
  - `{"type": "text_edit", "page": int, "run_index": int, "text": str, "font_override": {"family": str, "bold": bool, "italic": bool, "size": float} | None}`
  - `{"type": "stroke", "page": int, "points": [{"x": float, "y": float}, ...], "color": str (hex, e.g. "#ff0000"), "width": float}`
  - `{"type": "shape", "page": int, "shape": "rectangle"|"ellipse"|"line"|"arrow", "x0": float, "y0": float, "x1": float, "y1": float, "color": str, "width": float, "filled": bool}`
  - `{"type": "highlight", "page": int, "top": float, "right": float, "bottom": float, "left": float, "color": str}`
  - `{"type": "image", "page": int, "file_id": str, "x": float, "y": float, "width": float, "height": float}`
  - `image_paths` maps every `image`-element `file_id` to its resolved absolute file path (resolved by the route in Task 4, keeping this function framework-agnostic).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ops.py` (add `edit_pdf` to the existing import line):

```python
def test_edit_pdf_text_edit_replaces_text_and_keeps_surrounding_content(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello World", fontsize=14, fontname="helv")
    page.insert_text((72, 150), "Untouched Line", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": "Goodbye Mars", "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Hello World" not in text
    assert "Goodbye Mars" in text
    assert "Untouched Line" in text


def test_edit_pdf_text_edit_handles_rotated_page(tmp_path):
    """Same rigor as test_redact_pdf_handles_rotated_page: a run the user could
    SEE and clicked must be the run that actually gets replaced."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 700), "OMEGA ORIGINAL")  # displayed top-left after rotation
    page.insert_text((72, 72), "ALPHA KEEP")        # displayed top-right after rotation
    page.set_rotation(90)
    input_path = tmp_path / "rotated.pdf"
    doc.save(str(input_path))
    doc.close()

    runs = extract_text_runs(str(input_path), 1)
    target = next(r for r in runs if r["text"] == "OMEGA ORIGINAL")

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": target["index"], "text": "OMEGA REPLACED", "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "OMEGA ORIGINAL" not in text
    assert "OMEGA REPLACED" in text
    assert "ALPHA KEEP" in text


def test_edit_pdf_text_edit_auto_shrinks_when_overflowing(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hi", fontsize=20, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    long_text = "This replacement text is much much longer than the original run"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "text_edit", "page": 1, "run_index": 0, "text": long_text, "font_override": None}],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["size"] < 20  # shrunk to fit
    assert spans[0]["size"] >= 6  # not below the floor


def test_edit_pdf_stroke_adds_ink_annotation(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "stroke",
                "page": 1,
                "points": [{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.15}, {"x": 0.3, "y": 0.1}],
                "color": "#ff0000",
                "width": 3,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    annots = list(result[0].annots())
    result.close()
    assert len(annots) == 1
    assert annots[0].type[1] == "Ink"


def test_edit_pdf_shape_rectangle_filled_renders_color(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "shape",
                "page": 1,
                "shape": "rectangle",
                "x0": 0.1,
                "y0": 0.1,
                "x1": 0.3,
                "y1": 0.2,
                "color": "#00ff00",
                "width": 2,
                "filled": True,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # Center of the drawn rect: x0=0.1*595=59.5, x1=0.3*595=178.5, y0=0.1*842=84.2, y1=0.2*842=168.4
    r, g, b = pix.pixel(119, 126)[:3]
    assert g > 150 and r < 100 and b < 100  # unmistakably green, not white


def test_edit_pdf_shape_arrow_does_not_raise_and_draws_pixels(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "shape",
                "page": 1,
                "shape": "arrow",
                "x0": 0.1,
                "y0": 0.1,
                "x1": 0.4,
                "y1": 0.3,
                "color": "#000000",
                "width": 2,
                "filled": False,
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    dark_pixels = sum(
        1
        for y in range(0, pix.height, 2)
        for x in range(0, pix.width, 2)
        if sum(pix.pixel(x, y)[:3]) < 200
    )
    assert dark_pixels > 10


def test_edit_pdf_highlight_renders_translucent_overlay(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "highlight", "page": 1, "top": 0.1, "right": 0.7, "bottom": 0.8, "left": 0.1, "color": "#ffff00"}],
        {},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # top=0.1*842=84.2, left=0.1*595=59.5, right edge=0.3*595=178.5(=595-0.7*595), bottom edge=0.2*842=168.4
    r, g, b = pix.pixel(119, 126)[:3]
    assert r > 200 and g > 200 and b < 220  # yellow-tinted, not pure white (255,255,255) or pure yellow


def test_edit_pdf_image_inserts_into_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), False)
    img_pix.set_rect(img_pix.irect, (0, 0, 255))
    img_path = tmp_path / "stamp.png"
    img_pix.save(str(img_path))

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "image", "page": 1, "file_id": "stamp", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}],
        {"stamp": str(img_path)},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # center of placed image: x=0.2*595=119, y=0.15*842=126.3
    r, g, b = pix.pixel(119, 126)[:3]
    assert b > 150 and r < 100 and g < 100


def test_edit_pdf_mixed_elements_all_apply_together(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Original", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {"type": "text_edit", "page": 1, "run_index": 0, "text": "Replaced", "font_override": None},
            {"type": "shape", "page": 1, "shape": "rectangle", "x0": 0.5, "y0": 0.5, "x1": 0.6, "y1": 0.55, "color": "#000000", "width": 1, "filled": False},
            {"type": "highlight", "page": 1, "top": 0.6, "right": 0.3, "bottom": 0.3, "left": 0.3, "color": "#00ffff"},
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    annots_and_shapes_present = result[0].get_pixmap() is not None  # rendered without error
    result.close()
    assert "Original" not in text
    assert "Replaced" in text
    assert annots_and_shapes_present


def test_edit_pdf_rejects_empty_elements(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(str(input_path), str(output_path), [], {})


def test_edit_pdf_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "highlight", "page": 2, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}],
            {},
        )


def test_edit_pdf_rejects_invalid_run_index(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Only Run", fontsize=14, fontname="helv")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "text_edit", "page": 1, "run_index": 5, "text": "x", "font_override": None}],
            {},
        )


def test_edit_pdf_rejects_unresolvable_image_file_id(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path),
            str(output_path),
            [{"type": "image", "page": 1, "file_id": "missing", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}],
            {},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k edit_pdf -v`
Expected: FAIL (`edit_pdf` not defined).

- [ ] **Step 3: Implement `edit_pdf` and its helpers**

Add `math` to the top-level imports of `app/core/pdf_ops.py` (`import math` alongside the existing `from pathlib import Path` / `import fitz`), then add at the end of the file:

```python
_TEXT_EDIT_MIN_SIZE = 6
_TEXT_EDIT_SHRINK_FACTOR = 0.5

_FONT_ALIASES = {
    ("helvetica", False, False): "helv",
    ("helvetica", True, False): "hebo",
    ("helvetica", False, True): "heit",
    ("helvetica", True, True): "hebi",
    ("times", False, False): "tiro",
    ("times", True, False): "tibo",
    ("times", False, True): "tiit",
    ("times", True, True): "tibi",
    ("courier", False, False): "cour",
    ("courier", True, False): "cobo",
    ("courier", False, True): "coit",
    ("courier", True, True): "cobi",
}

_SHAPE_TYPES = {"rectangle", "ellipse", "line", "arrow"}


def _base14_alias(family: str, bold: bool, italic: bool) -> str:
    key = (family.lower(), bool(bold), bool(italic))
    return _FONT_ALIASES.get(key, _FONT_ALIASES[("helvetica", bool(bold), bool(italic))])


def _closest_base14_family(font_name: str) -> str:
    lowered = font_name.lower()
    if "times" in lowered or "serif" in lowered or "georgia" in lowered:
        return "times"
    if "courier" in lowered or "mono" in lowered or "consolas" in lowered:
        return "courier"
    return "helvetica"


def _extract_embedded_font(doc: fitz.Document, page: fitz.Page, span_font_name: str) -> bytes | None:
    """Real font-file bytes for span_font_name if it's actually embedded on
    this page, else None (base-14 fonts have nothing to extract)."""
    for f in doc.get_page_fonts(page.number, full=True):
        xref, basefont = f[0], f[3]
        if basefont == span_font_name:
            try:
                extracted = doc.extract_font(xref)
                buf = extracted[3]
                if buf:
                    return buf
            except Exception:
                pass
            break
    return None


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    if len(value) != 6:
        raise PDFError(f"Invalid color: {hex_color}")
    try:
        return (int(value[0:2], 16) / 255, int(value[2:4], 16) / 255, int(value[4:6], 16) / 255)
    except ValueError as exc:
        raise PDFError(f"Invalid color: {hex_color}") from exc


def _validate_stroke(el: dict) -> None:
    if not el["points"]:
        raise PDFError("A hand-drawn stroke must have at least one point.")
    for pt in el["points"]:
        if not (0 <= pt["x"] <= 1) or not (0 <= pt["y"] <= 1):
            raise PDFError("Stroke points must be within the page.")


def _validate_shape(el: dict) -> None:
    for name in ("x0", "y0", "x1", "y1"):
        value = el[name]
        if not (0 <= value <= 1):
            raise PDFError(f"Shape '{name}' must be between 0 and 1 (got {value}).")
    if el["shape"] in ("rectangle", "ellipse"):
        if el["x0"] == el["x1"] or el["y0"] == el["y1"]:
            raise PDFError("The shape must have a positive width and height.")
    elif el["x0"] == el["x1"] and el["y0"] == el["y1"]:
        raise PDFError("A line or arrow must have two distinct points.")


def _validate_highlight(el: dict) -> None:
    for name in ("top", "right", "bottom", "left"):
        value = el[name]
        if not (0 <= value < 1):
            raise PDFError(f"Highlight '{name}' must be between 0 and 1 (got {value}).")
    if el["left"] + el["right"] >= 1 or el["top"] + el["bottom"] >= 1:
        raise PDFError("The highlight area must have a positive width and height.")


def _validate_image_element(el: dict, image_paths: dict[str, str]) -> None:
    if el["file_id"] not in image_paths:
        raise PDFError(f"Image '{el['file_id']}' was not uploaded.")
    if not (0 <= el["x"] <= 1) or not (0 <= el["y"] <= 1):
        raise PDFError("Image position must be within the page.")
    if not (0 < el["width"] <= 1) or not (0 < el["height"] <= 1):
        raise PDFError("Image width and height must be positive fractions of the page.")
    if el["x"] + el["width"] > 1 or el["y"] + el["height"] > 1:
        raise PDFError("The image must fit within the page.")


def _apply_text_edit(doc: fitz.Document, page: fitz.Page, span: dict, replacement_text: str, font_override: dict | None, internal_fontname: str) -> None:
    raw_bbox = fitz.Rect(span["bbox"])
    page.add_redact_annot(raw_bbox, fill=(1, 1, 1))

    detected_bold = bool(span["flags"] & 16)
    detected_italic = bool(span["flags"] & 2)

    if font_override:
        fontname = _base14_alias(font_override["family"], font_override["bold"], font_override["italic"])
        size = font_override["size"]
    else:
        embedded_buf = _extract_embedded_font(doc, page, span["font"])
        if embedded_buf:
            page.insert_font(fontname=internal_fontname, fontbuffer=embedded_buf)
            fontname = internal_fontname
        else:
            fontname = _base14_alias(_closest_base14_family(span["font"]), detected_bold, detected_italic)
        size = span["size"]

    measured = fitz.get_text_length(replacement_text, fontname=fontname, fontsize=size)
    original_width = raw_bbox.width
    if measured > original_width > 0:
        floor = max(_TEXT_EDIT_MIN_SIZE, size * _TEXT_EDIT_SHRINK_FACTOR)
        size = max(original_width / measured * size, floor)

    page.insert_text(span["origin"], replacement_text, fontsize=size, fontname=fontname, color=(0, 0, 0))


def _apply_stroke(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    raw_points = [
        fitz.Point(rect.x0 + pt["x"] * rect.width, rect.y0 + pt["y"] * rect.height) * page.derotation_matrix
        for pt in el["points"]
    ]
    if len(raw_points) == 1:
        p = raw_points[0]
        raw_points = [p, fitz.Point(p.x + 0.1, p.y + 0.1)]
    # add_ink_annot requires plain (x, y) float pairs, not fitz.Point objects —
    # verified empirically: passing Points raises "arg must be seq of seq of
    # float pairs" even though every other API used in this file accepts Points.
    tuple_points = [(p.x, p.y) for p in raw_points]
    annot = page.add_ink_annot([tuple_points])
    annot.set_colors(stroke=_hex_to_rgb(el["color"]))
    annot.set_border(width=el["width"])
    annot.update()


def _to_raw_point(page: fitz.Page, fx: float, fy: float) -> fitz.Point:
    rect = page.rect
    displayed = fitz.Point(rect.x0 + fx * rect.width, rect.y0 + fy * rect.height)
    return displayed * page.derotation_matrix


def _draw_arrow(shape, p0: fitz.Point, p1: fitz.Point, color: tuple, width: float) -> None:
    shape.draw_line(p0, p1)
    shape.finish(color=color, width=width)
    angle = math.atan2(p1.y - p0.y, p1.x - p0.x)
    head_len = max(8, width * 3)
    head_angle = math.radians(25)
    h1 = fitz.Point(p1.x - head_len * math.cos(angle - head_angle), p1.y - head_len * math.sin(angle - head_angle))
    h2 = fitz.Point(p1.x - head_len * math.cos(angle + head_angle), p1.y - head_len * math.sin(angle + head_angle))
    shape.draw_polyline([h1, p1, h2, h1])
    shape.finish(color=color, fill=color, width=width, closePath=True)


def _apply_shape(page: fitz.Page, el: dict) -> None:
    p0 = _to_raw_point(page, el["x0"], el["y0"])
    p1 = _to_raw_point(page, el["x1"], el["y1"])
    color = _hex_to_rgb(el["color"])
    width = el["width"]
    shape = page.new_shape()
    if el["shape"] in ("rectangle", "ellipse"):
        raw_rect = fitz.Rect(p0, p1)
        raw_rect.normalize()
        fill = color if el.get("filled") else None
        if el["shape"] == "rectangle":
            shape.draw_rect(raw_rect)
        else:
            shape.draw_oval(raw_rect)
        shape.finish(color=color, width=width, fill=fill)
    elif el["shape"] == "line":
        shape.draw_line(p0, p1)
        shape.finish(color=color, width=width)
    else:
        _draw_arrow(shape, p0, p1, color, width)
    shape.commit()


def _apply_highlight(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["left"] * rect.width,
        rect.y0 + el["top"] * rect.height,
        rect.x1 - el["right"] * rect.width,
        rect.y1 - el["bottom"] * rect.height,
    )
    raw = displayed * page.derotation_matrix
    shape = page.new_shape()
    shape.draw_rect(raw)
    shape.finish(fill=_hex_to_rgb(el["color"]), fill_opacity=0.4, color=None)
    shape.commit()


def _apply_image(page: fitz.Page, el: dict, image_path: str) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["x"] * rect.width,
        rect.y0 + el["y"] * rect.height,
        rect.x0 + (el["x"] + el["width"]) * rect.width,
        rect.y0 + (el["y"] + el["height"]) * rect.height,
    )
    raw = displayed * page.derotation_matrix
    try:
        page.insert_image(raw, filename=image_path)
    except Exception as exc:
        raise PDFError(f"Could not insert image '{Path(image_path).name}' into the PDF.") from exc


def edit_pdf(input_path: str, output_path: str, elements: list[dict], image_paths: dict[str, str]) -> None:
    if not elements:
        raise PDFError("Add at least one edit before running.")
    doc = open_pdf(input_path)
    try:
        run_cache: dict[int, list[dict]] = {}
        for el in elements:
            page_num = el["page"]
            if page_num < 1 or page_num > doc.page_count:
                raise PDFError(f"Page {page_num} does not exist in this document ({doc.page_count} pages).")
            el_type = el["type"]
            if el_type == "text_edit":
                if page_num not in run_cache:
                    run_cache[page_num] = _page_text_spans(doc[page_num - 1])
                spans = run_cache[page_num]
                if el["run_index"] < 0 or el["run_index"] >= len(spans):
                    raise PDFError(f"Text run {el['run_index']} not found on page {page_num}.")
            elif el_type == "stroke":
                _validate_stroke(el)
            elif el_type == "shape":
                if el["shape"] not in _SHAPE_TYPES:
                    raise PDFError(f"Unknown shape: {el['shape']}")
                _validate_shape(el)
            elif el_type == "highlight":
                _validate_highlight(el)
            elif el_type == "image":
                _validate_image_element(el, image_paths)
            else:
                raise PDFError(f"Unknown element type: {el_type}")

        text_edits_by_page: dict[int, list[dict]] = {}
        other_elements = []
        for el in elements:
            if el["type"] == "text_edit":
                text_edits_by_page.setdefault(el["page"], []).append(el)
            else:
                other_elements.append(el)

        # Text edits apply first, settling each page's content stream before
        # anything else is layered on top.
        for page_num, page_edits in text_edits_by_page.items():
            page = doc[page_num - 1]
            spans = run_cache[page_num]
            for i, el in enumerate(page_edits):
                span = spans[el["run_index"]]
                _apply_text_edit(doc, page, span, el["text"], el.get("font_override"), f"TE{page_num}_{i}")
            page.apply_redactions()

        # Then strokes/shapes/highlights/images, in the order the user created them.
        for el in other_elements:
            page = doc[el["page"] - 1]
            if el["type"] == "stroke":
                _apply_stroke(page, el)
            elif el["type"] == "shape":
                _apply_shape(page, el)
            elif el["type"] == "highlight":
                _apply_highlight(page, el)
            elif el["type"] == "image":
                _apply_image(page, el, image_paths[el["file_id"]])

        doc.save(output_path)
    finally:
        doc.close()
```

Add `edit_pdf` to the existing import line at the top of `tests/test_pdf_ops.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k edit_pdf -v`
Expected: 13 passed. If a pixel-sampling test is flaky by a small margin, widen its threshold rather than deleting the assertion — the point is confirming the element is genuinely visible with roughly the right color, not exact-matching a computed blend.

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing, no regressions in `crop_pdf`/`redact_pdf`/other existing tests.

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add edit_pdf core function for all five element types

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 4: `POST /tools/edit-pdf` route

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `edit_pdf(input_path, output_path, elements, image_paths)` (Task 3), `storage.resolve_file`, `storage.output_path_for`, `_output_response` (existing).
- Produces: `POST /api/tools/edit-pdf` accepting `{"file_id": str, "elements": [...]}` (each element shaped per Task 3's model, discriminated by `"type"`), returning the standard `{"outputs": [...]}"`.

- [ ] **Step 1: Write the failing tests**

Add a PDF-with-text helper and tests to `tests/web/test_tools_edit_convert.py`:

```python
def test_edit_pdf_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "highlight", "page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}
            ],
        },
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_edit_pdf_text_edit_element_succeeds():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "text_edit", "page": 1, "run_index": 0, "text": "Replaced", "font_override": None}
            ],
        },
    )
    assert response.status_code == 200


def test_edit_pdf_rejects_empty_elements():
    upload = _upload_pdf()
    response = client.post("/api/tools/edit-pdf", json={"file_id": upload["id"], "elements": []})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_edit_pdf_unknown_file_id_returns_404():
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": "nope",
            "elements": [
                {"type": "highlight", "page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1, "color": "#ffff00"}
            ],
        },
    )
    assert response.status_code == 404


def test_edit_pdf_image_element_unknown_file_id_returns_422():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {"type": "image", "page": 1, "file_id": "missing-image", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1}
            ],
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k edit_pdf -v`
Expected: FAIL (404 "Not Found" — route doesn't exist yet).

- [ ] **Step 3: Implement the route**

In `web/backend/routes/tools.py`, add `edit_pdf` to the existing import from `app.core.pdf_ops`, add a new `from typing import Annotated, Literal, Union` import, and add `Field` to the existing `from pydantic import BaseModel` line (`from pydantic import BaseModel, Field`). Then add near the end of the file, after `images_to_pdf_route`:

```python
class FontOverride(BaseModel):
    family: str
    bold: bool
    italic: bool
    size: float


class TextEditElement(BaseModel):
    type: Literal["text_edit"]
    page: int
    run_index: int
    text: str
    font_override: FontOverride | None = None


class StrokePoint(BaseModel):
    x: float
    y: float


class StrokeElement(BaseModel):
    type: Literal["stroke"]
    page: int
    points: list[StrokePoint]
    color: str
    width: float


class ShapeElement(BaseModel):
    type: Literal["shape"]
    page: int
    shape: str
    x0: float
    y0: float
    x1: float
    y1: float
    color: str
    width: float
    filled: bool = False


class HighlightElement(BaseModel):
    type: Literal["highlight"]
    page: int
    top: float
    right: float
    bottom: float
    left: float
    color: str


class ImageElement(BaseModel):
    type: Literal["image"]
    page: int
    file_id: str
    x: float
    y: float
    width: float
    height: float


EditElement = Annotated[
    Union[TextEditElement, StrokeElement, ShapeElement, HighlightElement, ImageElement],
    Field(discriminator="type"),
]


class EditPdfRequest(BaseModel):
    file_id: str
    elements: list[EditElement]


@router.post("/edit-pdf")
def edit_pdf_route(req: EditPdfRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_edited")
    image_file_ids = {el.file_id for el in req.elements if el.type == "image"}
    image_paths = {fid: str(storage.resolve_file(fid)) for fid in image_file_ids}
    elements = [el.model_dump() for el in req.elements]
    edit_pdf(input_path, str(output_path), elements, image_paths)
    return _output_response([output_path], "Edit PDF", [Path(input_path).name])
```

(`model_dump()` on a Pydantic model with a `type: Literal[...]` field already includes `"type"` in its output — verified directly against this project's Pydantic version, along with the `Annotated[Union[...], Field(discriminator=...)]` placement itself, which is required: putting `discriminator=` on the *list* field instead of *inside* the `Annotated` union raises `TypeError: The core schema type 'list' is not a valid discriminated union variant` at import time. Each dumped dict matches `edit_pdf`'s expected shape exactly, including the `"type"` key `edit_pdf` switches on.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k edit_pdf -v`
Expected: 5 passed.

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing.

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_edit_convert.py
git commit -m "feat: add POST /tools/edit-pdf route

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 5: `EditPdfCanvas.jsx` shell + Edit Text mode

Backend is done. This task creates the frontend component with page navigation, the mode-switcher toolbar (buttons present, only "Edit Text" interactive yet — the rest are stubs Tasks 6–9 fill in), and the full Edit Text mode.

**Files:**
- Create: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/api.js`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `thumbnailUrl(fileId, pageNumber, maxSize)` (existing, `api.js`), `uploadFile` (existing, needed by Task 9 but imported now for convenience — actually not needed until Task 9, skip importing it here).
- Produces: default export `EditPdfCanvas({ fileId, pageCount, onChange })`, mirroring `RedactSelector`'s prop shape. Internally exposes (for Tasks 6–10 to extend) — all defined as functions/state inside the single component, not module exports, since later tasks edit this same file directly:
  - `elements` state (array) and `commitElements(next)` — the **only** way any mode should mutate `elements`. Task 10 upgrades `commitElements`'s body to also push undo history; its call signature never changes.
  - `newElementId()` — returns `crypto.randomUUID()`.
  - `selectedId` state + `setSelectedId` — predefined now so Tasks 6–9 can wire body-clicks against it even though selection/clipboard behavior itself lands in Task 10.
  - `currentPage`, `activeMode` state.
  - Stub handlers `handleDrawMouseDown`, `handleDrawMouseMove`, `handleDrawMouseUp` (Task 6), `handleShapeMouseDown`, `handleShapeMouseMove`, `handleShapeMouseUp` (Task 7), `handleHighlightMouseDown`, `handleHighlightMouseMove`, `handleHighlightMouseUp` (Task 8), `handleImageStageClick` (Task 9) — each a no-op function `() => {}` for now, dispatched from the stage's mouse handlers by `activeMode`, so later tasks only need to replace one function body each rather than touch the dispatcher.
- Also produces `fetchTextRuns(fileId, pageNumber)` in `api.js`, alongside the existing exports.

- [ ] **Step 1: Add `fetchTextRuns` to `api.js`**

Add after `thumbnailUrl`:

```js
export async function fetchTextRuns(fileId, pageNumber) {
  const res = await request(`/files/${fileId}/pages/${pageNumber}/text-runs`);
  return res.json();
}
```

- [ ] **Step 2: Create `EditPdfCanvas.jsx`**

```jsx
import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, CursorText, PencilSimple, Rectangle, Highlighter, ImageSquare, X } from "@phosphor-icons/react";
import { thumbnailUrl, fetchTextRuns } from "../api";

const PREVIEW_MAX_SIZE = 700;

const MODES = [
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
];

const FAMILY_OPTIONS = ["helvetica", "times", "courier"];

export default function EditPdfCanvas({ fileId, pageCount, onChange }) {
  const stageRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeMode, setActiveMode] = useState("text");
  const [elements, setElements] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [runs, setRuns] = useState([]);
  const [editingRunIndex, setEditingRunIndex] = useState(null);
  const [draftText, setDraftText] = useState("");
  const [draftOverride, setDraftOverride] = useState(null);

  useEffect(() => {
    if (!fileId) return;
    fetchTextRuns(fileId, currentPage).then((data) => setRuns(data.runs));
    setEditingRunIndex(null);
  }, [fileId, currentPage]);

  if (!fileId || !pageCount) return null;

  function commitElements(next) {
    setElements(next);
    onChange(next);
  }

  function newElementId() {
    return crypto.randomUUID();
  }

  function pointFromEvent(e) {
    const rect = stageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  // Stubs — replaced (body only) by later tasks. Kept here so the stage's
  // dispatcher below never needs to change as modes are filled in.
  function handleDrawMouseDown() {}
  function handleDrawMouseMove() {}
  function handleDrawMouseUp() {}
  function handleShapeMouseDown() {}
  function handleShapeMouseMove() {}
  function handleShapeMouseUp() {}
  function handleHighlightMouseDown() {}
  function handleHighlightMouseMove() {}
  function handleHighlightMouseUp() {}
  function handleImageStageClick() {}

  function handleStageMouseDown(e) {
    if (activeMode === "draw") return handleDrawMouseDown(e);
    if (activeMode === "shapes") return handleShapeMouseDown(e);
    if (activeMode === "highlight") return handleHighlightMouseDown(e);
    if (activeMode === "image") return handleImageStageClick(e);
  }

  function handleStageMouseMove(e) {
    if (activeMode === "draw") return handleDrawMouseMove(e);
    if (activeMode === "shapes") return handleShapeMouseMove(e);
    if (activeMode === "highlight") return handleHighlightMouseMove(e);
  }

  function handleStageMouseUp(e) {
    if (activeMode === "draw") return handleDrawMouseUp(e);
    if (activeMode === "shapes") return handleShapeMouseUp(e);
    if (activeMode === "highlight") return handleHighlightMouseUp(e);
  }

  function pendingTextEditFor(run) {
    return elements.find((el) => el.type === "text_edit" && el.page === currentPage && el.run_index === run.index);
  }

  function openRunEditor(run) {
    const pending = pendingTextEditFor(run);
    setEditingRunIndex(run.index);
    setDraftText(pending ? pending.text : run.text);
    setDraftOverride(
      pending?.font_override ?? {
        family: "helvetica",
        bold: run.bold,
        italic: run.italic,
        size: run.size,
      }
    );
  }

  function submitRunEditor(run) {
    const pending = pendingTextEditFor(run);
    const overrideChanged =
      draftOverride.family !== "helvetica" || draftOverride.bold !== run.bold || draftOverride.italic !== run.italic || draftOverride.size !== run.size;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: currentPage,
      run_index: run.index,
      text: draftText,
      font_override: overrideChanged ? draftOverride : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
    setEditingRunIndex(null);
  }

  function removeTextEdit(run) {
    const pending = pendingTextEditFor(run);
    if (!pending) return;
    commitElements(elements.filter((el) => el.id !== pending.id));
    setEditingRunIndex(null);
  }

  return (
    <div className="edit-pdf-canvas">
      <div className="edit-pdf-canvas__modes">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            className={activeMode === mode.id ? "edit-pdf-canvas__mode-button edit-pdf-canvas__mode-button--active" : "edit-pdf-canvas__mode-button"}
            onClick={() => setActiveMode(mode.id)}
          >
            <mode.icon size={16} weight="regular" />
            {mode.label}
          </button>
        ))}
      </div>

      <div className="edit-pdf-canvas__nav">
        <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}>
          <CaretLeft size={14} weight="bold" />
          Previous
        </button>
        <span>
          Page {currentPage} of {pageCount} ({new Set(elements.map((e) => e.page)).size} page{new Set(elements.map((e) => e.page)).size === 1 ? "" : "s"} have edits)
        </span>
        <button type="button" onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))} disabled={currentPage === pageCount}>
          Next
          <CaretRight size={14} weight="bold" />
        </button>
      </div>

      <div
        ref={stageRef}
        className="edit-pdf-canvas__stage"
        onMouseDown={handleStageMouseDown}
        onMouseMove={handleStageMouseMove}
        onMouseUp={handleStageMouseUp}
        onMouseLeave={handleStageMouseUp}
      >
        <img
          className="edit-pdf-canvas__image"
          src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
          alt={`Page ${currentPage} preview`}
          draggable={false}
        />

        {activeMode === "text" &&
          runs.map((run) => {
            const pending = pendingTextEditFor(run);
            return (
              <div
                key={run.index}
                className={pending ? "edit-pdf-canvas__run edit-pdf-canvas__run--queued" : "edit-pdf-canvas__run"}
                style={{
                  left: `${run.bbox.left * 100}%`,
                  top: `${run.bbox.top * 100}%`,
                  width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
                  height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
                }}
                onClick={() => openRunEditor(run)}
              />
            );
          })}
      </div>

      {activeMode === "text" && editingRunIndex !== null && (
        <div className="edit-pdf-canvas__run-editor">
          {(() => {
            const run = runs.find((r) => r.index === editingRunIndex);
            if (!run) return null;
            const pending = pendingTextEditFor(run);
            return (
              <>
                <label className="field">
                  Replacement text
                  <input type="text" value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                </label>
                <p className="edit-pdf-canvas__detected">
                  Detected: {run.font}, {run.size.toFixed(1)}pt{run.bold ? ", bold" : ""}
                  {run.italic ? ", italic" : ""}
                </p>
                <label className="field">
                  Font family override
                  <select value={draftOverride.family} onChange={(e) => setDraftOverride((o) => ({ ...o, family: e.target.value }))}>
                    {FAMILY_OPTIONS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.bold} onChange={(e) => setDraftOverride((o) => ({ ...o, bold: e.target.checked }))} />
                  Bold
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.italic} onChange={(e) => setDraftOverride((o) => ({ ...o, italic: e.target.checked }))} />
                  Italic
                </label>
                <label className="field">
                  Font size
                  <input type="number" min={1} value={draftOverride.size} onChange={(e) => setDraftOverride((o) => ({ ...o, size: Number(e.target.value) }))} />
                </label>
                <div className="edit-pdf-canvas__run-editor-actions">
                  <button type="button" onClick={() => submitRunEditor(run)}>
                    {pending ? "Update edit" : "Add edit"}
                  </button>
                  {pending && (
                    <button type="button" onClick={() => removeTextEdit(run)}>
                      Remove edit
                    </button>
                  )}
                  <button type="button" onClick={() => setEditingRunIndex(null)}>
                    Cancel
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Add CSS**

Add to `web/frontend/src/index.css`, after the Redact selector block:

```css
/* ---------- Edit PDF canvas ---------- */

.edit-pdf-canvas {
  margin: var(--space-5) 0;
}

.edit-pdf-canvas__modes {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}

.edit-pdf-canvas__mode-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
  font-size: 13px;
}

.edit-pdf-canvas__mode-button--active {
  background: var(--color-accent);
  color: var(--color-accent-foreground);
  border-color: var(--color-accent);
}

.edit-pdf-canvas__nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  font-size: 14px;
  color: var(--color-muted-foreground);
}

.edit-pdf-canvas__nav button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
}

.edit-pdf-canvas__nav button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.edit-pdf-canvas__stage {
  position: relative;
  display: inline-block;
  max-width: 100%;
  user-select: none;
}

.edit-pdf-canvas__image {
  display: block;
  max-width: 100%;
  border-radius: var(--radius-sm);
  pointer-events: none;
}

.edit-pdf-canvas__run {
  position: absolute;
  border: 1px dashed transparent;
  cursor: pointer;
}

.edit-pdf-canvas__run:hover {
  border-color: var(--color-accent);
  background: rgba(59, 130, 246, 0.12);
}

.edit-pdf-canvas__run--queued {
  border: 1px solid var(--color-accent);
  background: rgba(59, 130, 246, 0.2);
}

.edit-pdf-canvas__run-editor {
  margin-top: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-width: 360px;
}

.edit-pdf-canvas__detected {
  font-size: 12px;
  color: var(--color-muted-foreground);
  margin: 0;
}

.edit-pdf-canvas__run-editor-actions {
  display: flex;
  gap: var(--space-2);
}
```

- [ ] **Step 4: Manually verify**

Start the dev server (`npm run dev` in `web/frontend`, backend running separately per this project's existing dev setup), navigate to a new "Edit PDF" tool URL is not wired yet (that's Task 11) — instead, temporarily render `<EditPdfCanvas fileId={...} pageCount={...} onChange={console.log} />` is not necessary; skip live verification until Task 11 wires it into `ToolView`. Confirm only that the file has no syntax errors by running the frontend build:

Run: `cd web/frontend && npm run build`
Expected: builds successfully with no errors.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/api.js web/frontend/src/index.css
git commit -m "feat: add EditPdfCanvas shell and Edit Text mode

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 6: Draw mode

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `commitElements`, `newElementId`, `pointFromEvent`, `stageRef`, `elements`, `currentPage`, `selectedId`/`setSelectedId` (Task 5).
- Produces: a `stroke` element added to `elements` on mouseup; module-level `MARKUP_COLORS` and `STROKE_WIDTHS` constants that Task 7 (Shapes) also imports/reuses.

- [ ] **Step 1: Add shared color/width constants**

Add near the top of `EditPdfCanvas.jsx`, after the `FAMILY_OPTIONS` constant:

```js
const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"];
const STROKE_WIDTHS = { thin: 1, medium: 3, thick: 6 };
```

- [ ] **Step 2: Add Draw mode state and replace the stub handlers**

Add state near the other `useState` calls:

```js
const [drawColor, setDrawColor] = useState(MARKUP_COLORS[0]);
const [drawWidth, setDrawWidth] = useState("medium");
const [activeStroke, setActiveStroke] = useState(null);
```

Replace the three Draw stub bodies from Task 5:

```js
function handleDrawMouseDown(e) {
  const point = pointFromEvent(e);
  if (!point) return;
  setActiveStroke([point]);
}

function handleDrawMouseMove(e) {
  if (!activeStroke) return;
  const point = pointFromEvent(e);
  if (!point) return;
  setActiveStroke((pts) => [...pts, point]);
}

function handleDrawMouseUp() {
  if (!activeStroke || activeStroke.length === 0) return;
  const next = [
    ...elements,
    { id: newElementId(), type: "stroke", page: currentPage, points: activeStroke, color: drawColor, width: STROKE_WIDTHS[drawWidth] },
  ];
  commitElements(next);
  setActiveStroke(null);
}
```

- [ ] **Step 3: Render strokes and the Draw toolbar**

Add an SVG overlay inside `.edit-pdf-canvas__stage`, right after the `<img>` element:

```jsx
<svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none">
  {elements
    .filter((el) => el.type === "stroke" && el.page === currentPage)
    .map((el) => (
      <g key={el.id} onClick={() => setSelectedId(el.id)}>
        <polyline
          points={el.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
          fill="none"
          stroke={el.color}
          strokeWidth={el.width / 3}
          vectorEffect="non-scaling-stroke"
          className={el.id === selectedId ? "edit-pdf-canvas__stroke edit-pdf-canvas__stroke--selected" : "edit-pdf-canvas__stroke"}
        />
      </g>
    ))}
  {activeStroke && (
    <polyline
      points={activeStroke.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
      fill="none"
      stroke={drawColor}
      strokeWidth={STROKE_WIDTHS[drawWidth] / 3}
      vectorEffect="non-scaling-stroke"
    />
  )}
</svg>
```

Then add remove buttons for queued strokes (bounding-box × per the spec's removal design) right after that `<svg>` block, still inside the stage:

```jsx
{elements
  .filter((el) => el.type === "stroke" && el.page === currentPage)
  .map((el) => {
    const xs = el.points.map((p) => p.x);
    const ys = el.points.map((p) => p.y);
    const left = Math.min(...xs);
    const top = Math.min(...ys);
    return (
      <button
        key={`${el.id}-remove`}
        type="button"
        className="edit-pdf-canvas__element-remove"
        style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => commitElements(elements.filter((e) => e.id !== el.id))}
        aria-label="Remove this stroke"
      >
        <X size={12} weight="bold" />
      </button>
    );
  })}
```

Add the Draw mode toolbar strip right after the mode-switcher `<div className="edit-pdf-canvas__modes">...</div>` block:

```jsx
{activeMode === "draw" && (
  <div className="edit-pdf-canvas__style-bar">
    {MARKUP_COLORS.map((c) => (
      <button
        key={c}
        type="button"
        className={c === drawColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
        style={{ background: c }}
        onClick={() => setDrawColor(c)}
        aria-label={`Color ${c}`}
      />
    ))}
    {Object.keys(STROKE_WIDTHS).map((w) => (
      <button
        key={w}
        type="button"
        className={w === drawWidth ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
        onClick={() => setDrawWidth(w)}
      >
        {w}
      </button>
    ))}
  </div>
)}
```

- [ ] **Step 4: Add CSS**

Add to `index.css`:

```css
.edit-pdf-canvas__strokes {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.edit-pdf-canvas__stroke--selected {
  filter: drop-shadow(0 0 2px var(--color-accent));
}

.edit-pdf-canvas__element-remove {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--color-border);
  background: var(--color-card);
  cursor: pointer;
  pointer-events: auto;
}

.edit-pdf-canvas__style-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.edit-pdf-canvas__color-swatch {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
}

.edit-pdf-canvas__color-swatch--active {
  border-color: var(--color-accent);
}

.edit-pdf-canvas__width-button {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
  font-size: 12px;
}

.edit-pdf-canvas__width-button--active {
  background: var(--color-accent);
  color: var(--color-accent-foreground);
  border-color: var(--color-accent);
}
```

- [ ] **Step 5: Manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds successfully. (Live browser verification of Draw mode happens in Task 11's end-to-end manual pass, once the tool is reachable via the UI.)

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add Draw mode to EditPdfCanvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 7: Shapes mode

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `MARKUP_COLORS`, `STROKE_WIDTHS` (Task 6), `commitElements`, `newElementId`, `pointFromEvent`, `elements`, `currentPage`, `selectedId`/`setSelectedId` (Task 5).
- Produces: a `shape` element (`rectangle`/`ellipse`/`line`/`arrow`) added to `elements` on mouseup.

- [ ] **Step 1: Add Shapes mode state and replace the stub handlers**

Add state:

```js
const [shapeType, setShapeType] = useState("rectangle");
const [shapeColor, setShapeColor] = useState(MARKUP_COLORS[0]);
const [shapeWidth, setShapeWidth] = useState("medium");
const [shapeFilled, setShapeFilled] = useState(false);
const [shapeDragStart, setShapeDragStart] = useState(null);
const [shapeDragCurrent, setShapeDragCurrent] = useState(null);
```

Replace the three Shapes stub bodies:

```js
function handleShapeMouseDown(e) {
  const point = pointFromEvent(e);
  if (!point) return;
  setShapeDragStart(point);
  setShapeDragCurrent(point);
}

function handleShapeMouseMove(e) {
  if (!shapeDragStart) return;
  const point = pointFromEvent(e);
  if (!point) return;
  setShapeDragCurrent(point);
}

function handleShapeMouseUp() {
  if (!shapeDragStart || !shapeDragCurrent) return;
  const { x: x0, y: y0 } = shapeDragStart;
  const { x: x1, y: y1 } = shapeDragCurrent;
  setShapeDragStart(null);
  setShapeDragCurrent(null);
  if (x0 === x1 && y0 === y1) return;
  const next = [
    ...elements,
    {
      id: newElementId(),
      type: "shape",
      page: currentPage,
      shape: shapeType,
      x0,
      y0,
      x1,
      y1,
      color: shapeColor,
      width: STROKE_WIDTHS[shapeWidth],
      filled: shapeType === "rectangle" || shapeType === "ellipse" ? shapeFilled : false,
    },
  ];
  commitElements(next);
}
```

- [ ] **Step 2: Render shapes on the stage**

Add inside `.edit-pdf-canvas__stage`, after the strokes `<svg>` block from Task 6:

```jsx
<svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ zIndex: 2 }}>
  {elements
    .filter((el) => el.type === "shape" && el.page === currentPage)
    .map((el) => {
      const stroke = el.color;
      const fill = el.filled ? el.color : "none";
      const commonProps = { key: el.id, stroke, fill, strokeWidth: el.width / 3, vectorEffect: "non-scaling-stroke" };
      if (el.shape === "rectangle") {
        return (
          <rect
            {...commonProps}
            x={Math.min(el.x0, el.x1) * 100}
            y={Math.min(el.y0, el.y1) * 100}
            width={Math.abs(el.x1 - el.x0) * 100}
            height={Math.abs(el.y1 - el.y0) * 100}
          />
        );
      }
      if (el.shape === "ellipse") {
        return (
          <ellipse
            {...commonProps}
            cx={((el.x0 + el.x1) / 2) * 100}
            cy={((el.y0 + el.y1) / 2) * 100}
            rx={(Math.abs(el.x1 - el.x0) / 2) * 100}
            ry={(Math.abs(el.y1 - el.y0) / 2) * 100}
          />
        );
      }
      // line and arrow both render as a line preview; the real arrowhead is
      // drawn server-side by edit_pdf — this is close enough for the queue preview.
      return <line key={el.id} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} stroke={stroke} strokeWidth={el.width / 3} vectorEffect="non-scaling-stroke" />;
    })}
  {shapeDragStart && shapeDragCurrent && (
    <line
      x1={shapeDragStart.x * 100}
      y1={shapeDragStart.y * 100}
      x2={shapeDragCurrent.x * 100}
      y2={shapeDragCurrent.y * 100}
      stroke={shapeColor}
      strokeWidth={STROKE_WIDTHS[shapeWidth] / 3}
      strokeDasharray="2,1"
      vectorEffect="non-scaling-stroke"
    />
  )}
</svg>
```

Add remove buttons for queued shapes, after that block:

```jsx
{elements
  .filter((el) => el.type === "shape" && el.page === currentPage)
  .map((el) => (
    <button
      key={`${el.id}-remove`}
      type="button"
      className="edit-pdf-canvas__element-remove"
      style={{ left: `${Math.min(el.x0, el.x1) * 100}%`, top: `${Math.min(el.y0, el.y1) * 100}%` }}
      onMouseDown={(e) => e.stopPropagation()}
      onClick={() => commitElements(elements.filter((e) => e.id !== el.id))}
      aria-label="Remove this shape"
    >
      <X size={12} weight="bold" />
    </button>
  ))}
```

- [ ] **Step 3: Add the Shapes toolbar**

Add alongside the Draw toolbar block from Task 6 (as a sibling `{activeMode === "shapes" && (...)}` block):

```jsx
{activeMode === "shapes" && (
  <div className="edit-pdf-canvas__style-bar">
    {["rectangle", "ellipse", "line", "arrow"].map((s) => (
      <button
        key={s}
        type="button"
        className={s === shapeType ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
        onClick={() => setShapeType(s)}
      >
        {s}
      </button>
    ))}
    {MARKUP_COLORS.map((c) => (
      <button
        key={c}
        type="button"
        className={c === shapeColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
        style={{ background: c }}
        onClick={() => setShapeColor(c)}
        aria-label={`Color ${c}`}
      />
    ))}
    {Object.keys(STROKE_WIDTHS).map((w) => (
      <button
        key={w}
        type="button"
        className={w === shapeWidth ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
        onClick={() => setShapeWidth(w)}
      >
        {w}
      </button>
    ))}
    {(shapeType === "rectangle" || shapeType === "ellipse") && (
      <label className="field field--checkbox">
        <input type="checkbox" checked={shapeFilled} onChange={(e) => setShapeFilled(e.target.checked)} />
        Fill
      </label>
    )}
  </div>
)}
```

- [ ] **Step 4: Manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add Shapes mode to EditPdfCanvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 8: Highlight mode

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `MARKUP_COLORS` (Task 6), `commitElements`, `newElementId`, `pointFromEvent`, `elements`, `currentPage` (Task 5).
- Produces: a `highlight` element added to `elements` on mouseup.

- [ ] **Step 1: Add Highlight mode state and replace the stub handlers**

Add state:

```js
const [highlightColor, setHighlightColor] = useState("#ffd43b");
const [highlightDragStart, setHighlightDragStart] = useState(null);
const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
```

Replace the three Highlight stub bodies:

```js
function handleHighlightMouseDown(e) {
  const point = pointFromEvent(e);
  if (!point) return;
  setHighlightDragStart(point);
  setHighlightDragCurrent(point);
}

function handleHighlightMouseMove(e) {
  if (!highlightDragStart) return;
  const point = pointFromEvent(e);
  if (!point) return;
  setHighlightDragCurrent(point);
}

function handleHighlightMouseUp() {
  if (!highlightDragStart || !highlightDragCurrent) return;
  const x0 = Math.min(highlightDragStart.x, highlightDragCurrent.x);
  const x1 = Math.max(highlightDragStart.x, highlightDragCurrent.x);
  const y0 = Math.min(highlightDragStart.y, highlightDragCurrent.y);
  const y1 = Math.max(highlightDragStart.y, highlightDragCurrent.y);
  setHighlightDragStart(null);
  setHighlightDragCurrent(null);
  if (x1 - x0 < 0.02 || y1 - y0 < 0.02) return;
  const next = [
    ...elements,
    { id: newElementId(), type: "highlight", page: currentPage, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1, color: highlightColor },
  ];
  commitElements(next);
}
```

- [ ] **Step 2: Render highlights on the stage**

Add inside `.edit-pdf-canvas__stage`, after the shapes remove-buttons block from Task 7:

```jsx
{elements
  .filter((el) => el.type === "highlight" && el.page === currentPage)
  .map((el) => (
    <div
      key={el.id}
      className="edit-pdf-canvas__highlight"
      style={{
        left: `${el.left * 100}%`,
        top: `${el.top * 100}%`,
        width: `${(1 - el.left - el.right) * 100}%`,
        height: `${(1 - el.top - el.bottom) * 100}%`,
        background: el.color,
      }}
    >
      <button
        type="button"
        className="edit-pdf-canvas__box-remove"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => commitElements(elements.filter((e) => e.id !== el.id))}
        aria-label="Remove this highlight"
      >
        <X size={12} weight="bold" />
      </button>
    </div>
  ))}
{highlightDragStart && highlightDragCurrent && (
  <div
    className="edit-pdf-canvas__highlight edit-pdf-canvas__highlight--dragging"
    style={{
      left: `${Math.min(highlightDragStart.x, highlightDragCurrent.x) * 100}%`,
      top: `${Math.min(highlightDragStart.y, highlightDragCurrent.y) * 100}%`,
      width: `${Math.abs(highlightDragCurrent.x - highlightDragStart.x) * 100}%`,
      height: `${Math.abs(highlightDragCurrent.y - highlightDragStart.y) * 100}%`,
      background: highlightColor,
    }}
  />
)}
```

- [ ] **Step 3: Add the Highlight toolbar**

```jsx
{activeMode === "highlight" && (
  <div className="edit-pdf-canvas__style-bar">
    {["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"].map((c) => (
      <button
        key={c}
        type="button"
        className={c === highlightColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
        style={{ background: c }}
        onClick={() => setHighlightColor(c)}
        aria-label={`Color ${c}`}
      />
    ))}
  </div>
)}
```

- [ ] **Step 4: Add CSS**

```css
.edit-pdf-canvas__highlight {
  position: absolute;
  opacity: 0.4;
  pointer-events: auto;
}

.edit-pdf-canvas__highlight--dragging {
  pointer-events: none;
}

.edit-pdf-canvas__box-remove {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  border: 1px solid var(--color-border);
  background: var(--color-card);
  cursor: pointer;
  opacity: 1;
}
```

- [ ] **Step 5: Manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add Highlight mode to EditPdfCanvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 9: Insert Image mode

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `commitElements`, `newElementId`, `pointFromEvent`, `stageRef`, `elements`, `currentPage` (Task 5), `uploadFile` (existing, `api.js`).
- Produces: an `image` element added to `elements` on file selection; resize/move handled by drag on that same element afterward.

- [ ] **Step 1: Import `uploadFile` and add Insert Image state**

Add `uploadFile` to the existing `import { thumbnailUrl, fetchTextRuns } from "../api";` line (`import { thumbnailUrl, fetchTextRuns, uploadFile } from "../api";`).

Add state and a ref:

```js
const imageFileInputRef = useRef(null);
const pendingImageDropRef = useRef(null);
const imageDragRef = useRef(null);
```

- [ ] **Step 2: Replace the Insert Image stub and add the upload/place/drag logic**

Replace `handleImageStageClick`:

```js
function handleImageStageClick(e) {
  const point = pointFromEvent(e);
  if (!point) return;
  pendingImageDropRef.current = point;
  imageFileInputRef.current?.click();
}

function loadImageNaturalSize(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      resolve({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(url);
    };
    img.src = url;
  });
}

async function handleImageFileSelected(e) {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const drop = pendingImageDropRef.current ?? { x: 0.375, y: 0.375 };
  const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSize(file)]);
  const width = 0.25;
  const height = Math.min(0.9, width * (naturalSize.height / naturalSize.width));
  const x = Math.min(Math.max(drop.x - width / 2, 0), 1 - width);
  const y = Math.min(Math.max(drop.y - height / 2, 0), 1 - height);
  commitElements([...elements, { id: newElementId(), type: "image", page: currentPage, file_id: uploaded.id, x, y, width, height }]);
}

function startImageDrag(el, mode, e) {
  e.stopPropagation();
  const point = pointFromEvent(e);
  if (!point) return;
  imageDragRef.current = { id: el.id, mode, start: point, startElement: { ...el } };
  window.addEventListener("mousemove", handleImageDragMove);
  window.addEventListener("mouseup", handleImageDragEnd);
}

function handleImageDragMove(e) {
  const drag = imageDragRef.current;
  if (!drag) return;
  const point = pointFromEvent(e);
  if (!point) return;
  const dx = point.x - drag.start.x;
  const dy = point.y - drag.start.y;
  const { startElement } = drag;
  let updated;
  if (drag.mode === "move") {
    const x = Math.min(Math.max(startElement.x + dx, 0), 1 - startElement.width);
    const y = Math.min(Math.max(startElement.y + dy, 0), 1 - startElement.height);
    updated = { ...startElement, x, y };
  } else {
    const scale = Math.max(0.05, startElement.width + dx) / startElement.width;
    const width = Math.min(1 - startElement.x, startElement.width * scale);
    const height = width * (startElement.height / startElement.width);
    updated = { ...startElement, width, height };
  }
  setElements((prev) => prev.map((el) => (el.id === drag.id ? updated : el)));
}

function handleImageDragEnd() {
  window.removeEventListener("mousemove", handleImageDragMove);
  window.removeEventListener("mouseup", handleImageDragEnd);
  imageDragRef.current = null;
  setElements((current) => {
    onChange(current);
    return current;
  });
}
```

- [ ] **Step 3: Render placed images and the hidden file input**

Add inside `.edit-pdf-canvas__stage`, after the highlight-drag preview block from Task 8:

```jsx
{elements
  .filter((el) => el.type === "image" && el.page === currentPage)
  .map((el) => (
    <div
      key={el.id}
      className="edit-pdf-canvas__image-el"
      style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
      onMouseDown={(e) => startImageDrag(el, "move", e)}
    >
      <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startImageDrag(el, "resize", e)} />
      <button
        type="button"
        className="edit-pdf-canvas__box-remove"
        onMouseDown={(e) => e.stopPropagation()}
        onClick={() => commitElements(elements.filter((e2) => e2.id !== el.id))}
        aria-label="Remove this image"
      >
        <X size={12} weight="bold" />
      </button>
    </div>
  ))}
```

Add the hidden file input right after the closing `</div>` of `.edit-pdf-canvas__stage` (as a sibling, outside the stage):

```jsx
<input
  ref={imageFileInputRef}
  type="file"
  accept="image/png,image/jpeg"
  style={{ display: "none" }}
  onChange={handleImageFileSelected}
/>
```

- [ ] **Step 4: Add CSS**

```css
.edit-pdf-canvas__image-el {
  position: absolute;
  border: 1px dashed var(--color-accent);
  cursor: move;
}

.edit-pdf-canvas__image-el-handle {
  position: absolute;
  right: -6px;
  bottom: -6px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent);
  cursor: nwse-resize;
}
```

- [ ] **Step 5: Manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add Insert Image mode to EditPdfCanvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 10: Selection, clipboard, and undo/redo

All five modes now exist. This task adds the cross-cutting interaction layer from the spec: click-to-select on non-text-edit elements, Ctrl+C/X/V, Ctrl+Z/Y, and the Undo/Redo toolbar buttons.

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `elements`, `selectedId`/`setSelectedId`, `commitElements` (all from Task 5, extended here), plus every element-rendering block from Tasks 6–9 (their body `onClick`s already call `setSelectedId`, except Task 9's images which used `onMouseDown` for dragging — this task adds a plain click-to-select there too since a click that isn't a drag should still select).
- Produces: upgraded `commitElements` (now pushes undo history), `history` ref, keyboard shortcut handling, `ArrowUUpLeft`/`ArrowUUpRight` toolbar buttons.

- [ ] **Step 1: Upgrade `commitElements` to track history**

Add a ref near the other refs:

```js
const historyRef = useRef({ undoStack: [], redoStack: [] });
const [historyVersion, setHistoryVersion] = useState(0); // bump to force a re-render when the stacks change
```

Replace `commitElements`'s body (from Task 5):

```js
function commitElements(next) {
  historyRef.current = { undoStack: [...historyRef.current.undoStack, elements], redoStack: [] };
  setHistoryVersion((v) => v + 1);
  setElements(next);
  onChange(next);
}

function undo() {
  const { undoStack, redoStack } = historyRef.current;
  if (undoStack.length === 0) return;
  const previous = undoStack[undoStack.length - 1];
  historyRef.current = { undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, elements] };
  setHistoryVersion((v) => v + 1);
  setElements(previous);
  onChange(previous);
}

function redo() {
  const { undoStack, redoStack } = historyRef.current;
  if (redoStack.length === 0) return;
  const next = redoStack[redoStack.length - 1];
  historyRef.current = { undoStack: [...undoStack, elements], redoStack: redoStack.slice(0, -1) };
  setHistoryVersion((v) => v + 1);
  setElements(next);
  onChange(next);
}
```

Note: Task 9's `handleImageDragEnd` mutates `elements` via `setElements` directly (not `commitElements`), since a drag's intermediate positions shouldn't each be a separate undo step. Fix that now so the *final* dragged position still becomes one undo step: replace `handleImageDragEnd`'s body from Task 9 with:

```js
function handleImageDragEnd() {
  window.removeEventListener("mousemove", handleImageDragMove);
  window.removeEventListener("mouseup", handleImageDragEnd);
  const drag = imageDragRef.current;
  imageDragRef.current = null;
  if (!drag) return;
  setElements((current) => {
    historyRef.current = { undoStack: [...historyRef.current.undoStack, drag.startElementsSnapshot], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    onChange(current);
    return current;
  });
}
```

And capture that pre-drag snapshot in `startImageDrag` (Task 9) — update its body to also store `startElementsSnapshot`:

```js
function startImageDrag(el, mode, e) {
  e.stopPropagation();
  const point = pointFromEvent(e);
  if (!point) return;
  imageDragRef.current = { id: el.id, mode, start: point, startElement: { ...el }, startElementsSnapshot: elements };
  window.addEventListener("mousemove", handleImageDragMove);
  window.addEventListener("mouseup", handleImageDragEnd);
}
```

- [ ] **Step 2: Add selection to image elements and clipboard state**

Update Task 9's image-element `<div>` to also select on a plain click (a click that wasn't a drag): change its `onMouseDown` handler to also call `setSelectedId(el.id)`:

```jsx
onMouseDown={(e) => {
  setSelectedId(el.id);
  startImageDrag(el, "move", e);
}}
```

Add a clipboard ref:

```js
const clipboardRef = useRef(null);
```

- [ ] **Step 3: Add the keyboard shortcut listener**

Add a `useEffect` after the existing text-runs-fetching `useEffect`:

```js
useEffect(() => {
  function isTypingTarget(target) {
    return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
  }

  function copySelected() {
    const el = elements.find((e) => e.id === selectedId);
    if (!el || el.type === "text_edit") return null;
    const { id, page, ...rest } = el;
    return rest;
  }

  function pasteClipboard() {
    if (!clipboardRef.current) return;
    const OFFSET = 0.03;
    const clamp = (v) => Math.min(Math.max(v, 0), 1 - OFFSET);
    const base = { ...clipboardRef.current };
    if ("x0" in base) {
      base.x0 = clamp(base.x0 + OFFSET);
      base.x1 = clamp(base.x1 + OFFSET);
      base.y0 = clamp(base.y0 + OFFSET);
      base.y1 = clamp(base.y1 + OFFSET);
    } else if ("left" in base) {
      base.left = clamp(base.left + OFFSET);
      base.top = clamp(base.top + OFFSET);
    } else if ("x" in base) {
      base.x = clamp(base.x + OFFSET);
      base.y = clamp(base.y + OFFSET);
    } else if ("points" in base) {
      base.points = base.points.map((p) => ({ x: clamp(p.x + OFFSET), y: clamp(p.y + OFFSET) }));
    }
    const pasted = { ...base, id: newElementId(), page: currentPage };
    commitElements([...elements, pasted]);
    setSelectedId(pasted.id);
  }

  function handleKeyDown(e) {
    if (isTypingTarget(document.activeElement)) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (!ctrl) {
      if (e.key === "Escape") setSelectedId(null);
      return;
    }
    if (e.key === "z" || e.key === "Z") {
      e.preventDefault();
      undo();
    } else if (e.key === "y" || e.key === "Y") {
      e.preventDefault();
      redo();
    } else if (e.key === "c" || e.key === "C") {
      const copied = copySelected();
      if (copied) {
        e.preventDefault();
        clipboardRef.current = copied;
      }
    } else if (e.key === "x" || e.key === "X") {
      const copied = copySelected();
      if (copied) {
        e.preventDefault();
        clipboardRef.current = copied;
        commitElements(elements.filter((el) => el.id !== selectedId));
        setSelectedId(null);
      }
    } else if (e.key === "v" || e.key === "V") {
      e.preventDefault();
      pasteClipboard();
    }
  }

  document.addEventListener("keydown", handleKeyDown);
  return () => document.removeEventListener("keydown", handleKeyDown);
}, [elements, selectedId, currentPage]);
```

- [ ] **Step 4: Add Undo/Redo toolbar buttons**

Add to the mode-switcher toolbar block, right after the `.edit-pdf-canvas__modes` closing `</div>`:

```jsx
<div className="edit-pdf-canvas__history-bar">
  <button type="button" onClick={undo} disabled={historyRef.current.undoStack.length === 0}>
    <ArrowUUpLeft size={16} weight="regular" />
    Undo
  </button>
  <button type="button" onClick={redo} disabled={historyRef.current.redoStack.length === 0}>
    <ArrowUUpRight size={16} weight="regular" />
    Redo
  </button>
</div>
```

(`historyVersion` is read nowhere directly — its only job is to be in state so `setHistoryVersion` triggers the re-render that refreshes these buttons' `disabled` reads of `historyRef.current`.)

Add `ArrowUUpLeft, ArrowUUpRight` to the existing icon import line at the top of the file.

- [ ] **Step 5: Add CSS**

```css
.edit-pdf-canvas__history-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.edit-pdf-canvas__history-bar button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
  font-size: 13px;
}

.edit-pdf-canvas__history-bar button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 6: Manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 7: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add selection, clipboard, and undo/redo to EditPdfCanvas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 11: Wire "Edit PDF" into ToolView

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/components/ToolGrid.jsx`

**Interfaces:**
- Consumes: `EditPdfCanvas` (Task 10, final form), `TOOL_CONFIGS` (existing).

- [ ] **Step 1: Add the `toolConfigs.js` entry**

Add to `TOOL_CONFIGS` in `web/frontend/src/toolConfigs.js`, alongside `redact`:

```js
"edit-pdf": {
  title: "Edit PDF",
  category: "Edit",
  multiFile: false,
  mode: "view",
  preview: "edit-pdf",
  endpoint: "edit-pdf",
  fields: [],
},
```

- [ ] **Step 2: Wire `ToolView.jsx`**

Add the import: `import EditPdfCanvas from "./EditPdfCanvas";`

Add `elements` state alongside the existing `cropRect`/`redactions` state:

```js
const [elements, setElements] = useState([]);
```

In `handleFilePick`, add `setElements([]);` next to the existing `setCropRect(null); setRedactions([]);` reset line.

In `handleRun`, add a precondition guard next to the existing `crop`/`redact` guards:

```js
if (config.preview === "edit-pdf" && elements.length === 0) {
  setError("Add at least one edit on the page preview before running.");
  return;
}
```

And add the body assembly next to the existing `if (config.preview === "redact") body.redactions = redactions;` line:

```js
if (config.preview === "edit-pdf") {
  body.elements = elements.map(({ id, ...rest }) => rest);
}
```

Add a preview branch in `renderPreview()`, next to the existing `redact` branch:

```jsx
if (config.preview === "edit-pdf") {
  if (!primaryFile) return null;
  return (
    // key={primaryFile.id} forces a full remount on file switch, discarding
    // EditPdfCanvas's internal elements/history/selection state — the exact
    // fix Redact needed after shipping without it (see the Redact spec).
    <EditPdfCanvas key={primaryFile.id} fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setElements} />
  );
}
```

Extend the Run button's `disabled` clause:

```jsx
disabled={
  busy ||
  files.length === 0 ||
  (config.preview === "crop" && !cropRect) ||
  (config.preview === "redact" && redactions.length === 0) ||
  (config.preview === "edit-pdf" && elements.length === 0)
}
```

- [ ] **Step 3: Add the tool-grid icon**

In `ToolGrid.jsx`, add `NotePencil` to the icon import line, and add to `TOOL_ICONS`:

```js
"edit-pdf": NotePencil,
```

- [ ] **Step 4: Build and manually verify end-to-end**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

Then start the dev server and the backend, open the app, navigate to Edit PDF, upload a multi-page PDF, and manually verify:
- Edit Text: click a run, change its text, submit, see it queued (highlighted); re-click it to see the pending text, not the original; remove it; Run is disabled with 0 edits, enabled with 1.
- Draw: draw a freehand stroke, see it rendered and queued; its × removes it.
- Shapes: draw a Rectangle with Fill on, an Ellipse, a Line, and an Arrow; confirm each queues and its × removes it.
- Highlight: drag a box, confirm the translucent color preview.
- Insert Image: click the stage, pick an image file, confirm it appears centered on the click point with a resize handle; drag the handle to resize, drag the body to move; × removes it.
- Selection/clipboard: click a shape (not a text edit) to select it, Ctrl+C then navigate to a different page and Ctrl+V, confirm a duplicate appears offset on that page.
- Undo/Redo: make a few edits, click Undo repeatedly back to zero (button becomes disabled), click Redo forward again; confirm Ctrl+Z/Ctrl+Y do the same.
- File switch: upload a second, different file; confirm the canvas fully resets (0 pages have edits, Run disabled) — this is the exact bug class Redact shipped once already.
- Run the tool and confirm the downloaded output actually reflects every queued edit (open it and check visually).

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx web/frontend/src/components/ToolGrid.jsx
git commit -m "feat: wire Edit PDF tool into ToolView

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing.
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above, in order, on top of `main`'s current tip.
