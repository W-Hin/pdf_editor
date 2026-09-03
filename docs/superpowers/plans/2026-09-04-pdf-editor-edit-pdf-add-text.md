# Edit PDF: Add Text Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sixth mode, "Add Text," to the already-shipped Edit PDF tool, letting users place freely-styled new text anywhere on a page (font family, size, bold, italic, underline, color, alignment), riding entirely on the existing `elements` array and `POST /tools/edit-pdf` endpoint.

**Architecture:** A new `new_text` element type joins the existing `text_edit`/`stroke`/`shape`/`highlight`/`image` types in the discriminated union both frontend and backend already share. Backend rendering is a new `_apply_new_text` helper doing manual greedy word-wrap (via `fitz.get_text_length`) plus per-line `insert_text`/`draw_line` calls — mirroring `_apply_highlight`/`_apply_image`'s existing fraction→raw-rect conversion pattern. Frontend work generalizes the existing `image` element's move/resize drag machinery (already type-agnostic in all but naming) to serve both `image` and `new_text`, and adds a new click-to-place-then-inline-edit interaction modeled on Edit Text's draft-and-submit pattern.

**Tech Stack:** PyMuPDF (`fitz`) 1.28.2, FastAPI/Pydantic, React (no new dependencies).

## Global Constraints

- Font families: exactly `helvetica`, `times`, `courier` (the same base-14 trio Edit Text already offers) — no other font loading.
- Alignment: exactly `left`, `center`, `right`.
- Underline has no native PyMuPDF parameter — draw a separate line per wrapped line via `page.draw_line()`, sized to that line's own measured width via `fitz.get_text_length()`.
- Wrapping is manual greedy word-wrap (not `insert_textbox()`), because per-line width/position is needed for underline and alignment — verified empirically in the design spec (a 12pt sentence in a 228pt-wide box wrapped into exactly 3 lines, each independently positioned and underlined correctly).
- Overflow (wrapped lines taller than the box): stop drawing at the box's bottom edge, no auto-shrink, no error — a documented ceiling, not a bug.
- Rich/partial styling within one box (e.g. bolding one word) is out of scope — one style per box, matching every other element type in this tool.
- No background fill or border on the text box itself.
- No new backend route — this rides entirely on the existing `POST /tools/edit-pdf` endpoint and its `EditElement` discriminated union.
- No `toolConfigs.js` changes — this is a new mode within the existing `edit-pdf` tool entry.
- **Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go ONLY on commits whose subject starts with `fix:`/`fix(scope):`.** Every task's initial implementation commit in this plan is a `feat:` commit and must NOT carry that trailer. This is a standing, explicit project policy — stated in every task's commit-message instructions below.

---

## Task 1: Backend — `_apply_new_text` core function

**Files:**
- Modify: `app/core/pdf_ops.py:725-798` (insert new helpers after `_apply_image`, before `edit_pdf`; wire into `edit_pdf`'s validate-then-apply loops)
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Consumes: `_base14_alias(family, bold, italic)`, `_hex_to_rgb(hex_color)` (existing, `app/core/pdf_ops.py`).
- Produces: `_validate_new_text(el: dict) -> None`, `_wrap_text_lines(text: str, fontname: str, fontsize: float, max_width: float) -> list[str]`, `_apply_new_text(page: fitz.Page, el: dict) -> None`. `edit_pdf()` gains support for `el["type"] == "new_text"` in both its validation and apply passes. Element shape consumed:
  ```python
  {
      "type": "new_text", "page": int,
      "x": float, "y": float, "width": float, "height": float,  # fractions of displayed page size
      "text": str,
      "family": str,   # "helvetica" | "times" | "courier"
      "bold": bool, "italic": bool, "underline": bool,
      "size": float, "color": str,  # hex string
      "align": str,    # "left" | "center" | "right"
  }
  ```

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ops.py`, after `test_edit_pdf_markup_elements_handle_rotated_page` (find the block ending around `test_edit_pdf_mixed_elements_all_apply_together` and insert before it — exact position doesn't matter, these are independent tests):

```python
def test_edit_pdf_new_text_inserts_at_position(tmp_path):
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
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1,
                "text": "Hello Stamp",
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 14, "color": "#1f2937", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "Hello Stamp" in text


def test_edit_pdf_new_text_wraps_multiple_lines(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    # This exact text/size/width combination was verified empirically (see the
    # design spec's Key technical findings) to wrap into exactly 3 lines:
    # "This is a longer note that should wrap" / "across multiple lines within
    # the box," / "underlined." — a raw-space box of (72,100)-(300,200) at
    # 12pt, reproduced here via fractions of a 595x842 page so the raw rect
    # matches exactly.
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 72 / 595, "y": 100 / 842, "width": 228 / 595, "height": 100 / 842,
                "text": "This is a longer note that should wrap across multiple lines within the box, underlined.",
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 12, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    line_count = len([l for l in text.split("\n") if l.strip()])
    assert line_count == 3
    assert "This is a longer note that should wrap" in text
    assert "underlined." in text


def test_edit_pdf_new_text_font_family_bold_italic(tmp_path):
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
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1,
                "text": "Styled",
                "family": "times", "bold": True, "italic": True, "underline": False,
                "size": 14, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    d = result[0].get_text("dict")
    result.close()
    spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
    assert len(spans) == 1
    assert spans[0]["font"] == "Times-BoldItalic"
    assert bool(spans[0]["flags"] & 16)  # bold
    assert bool(spans[0]["flags"] & 2)  # italic


def test_edit_pdf_new_text_underline_draws_line_per_line(tmp_path):
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
                "type": "new_text", "page": 1,
                "x": 0.12, "y": 0.12, "width": 0.4, "height": 0.1,
                "text": "Underlined Text",
                "family": "helvetica", "bold": False, "italic": False, "underline": True,
                "size": 20, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    drawings = result[0].get_drawings()
    result.close()
    assert len(drawings) == 1
    assert drawings[0]["items"][0][0] == "l"  # a line


def test_edit_pdf_new_text_alignment_positions_text(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    base_el = {
        "type": "new_text", "page": 1,
        "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1,
        "text": "Hi",
        "family": "helvetica", "bold": False, "italic": False, "underline": False,
        "size": 14, "color": "#000000",
    }

    def origin_x(align):
        out = tmp_path / f"{align}.pdf"
        edit_pdf(str(input_path), str(out), [{**base_el, "align": align}], {})
        doc2 = fitz.open(str(out))
        d = doc2[0].get_text("dict")
        doc2.close()
        spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        return spans[0]["origin"][0]

    left_x = origin_x("left")
    center_x = origin_x("center")
    right_x = origin_x("right")
    assert left_x < center_x < right_x


def test_edit_pdf_new_text_overflow_stops_at_box_bottom_without_raising(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    long_text = "One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen Fourteen"
    # A box only tall enough for one line at this size — the rest overflows
    # past the bottom edge and is simply never drawn (no auto-shrink, no error).
    edit_pdf(
        str(input_path),
        str(output_path),
        [
            {
                "type": "new_text", "page": 1,
                "x": 0.1, "y": 0.1, "width": 0.15, "height": 0.03,
                "text": long_text,
                "family": "helvetica", "bold": False, "italic": False, "underline": False,
                "size": 14, "color": "#000000", "align": "left",
            }
        ],
        {},
    )

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    result.close()
    assert "One" in text
    assert "Fourteen" not in text


def test_edit_pdf_rejects_new_text_empty_text(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "   ",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_invalid_color(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "not-a-color", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_unknown_family(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "comic-sans", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_unknown_align(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.1,
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "justify",
                }
            ],
            {},
        )


def test_edit_pdf_rejects_new_text_out_of_bounds_rect(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        edit_pdf(
            str(input_path), str(output_path),
            [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.9, "y": 0.1, "width": 0.3, "height": 0.1,  # x + width > 1
                    "text": "Hi",
                    "family": "helvetica", "bold": False, "italic": False, "underline": False,
                    "size": 14, "color": "#000000", "align": "left",
                }
            ],
            {},
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k new_text -v`
Expected: FAIL — `_validate_new_text`/`_apply_new_text` don't exist yet, and `edit_pdf` raises `PDFError(f"Unknown element type: new_text")` for every test (including the ones expecting `pytest.raises(PDFError)`, which will therefore pass for the WRONG reason at this stage — that's fine, Step 4 confirms they pass for the right reason once the real validators exist).

- [ ] **Step 3: Implement `_validate_new_text`, `_wrap_text_lines`, `_apply_new_text`, and wire them into `edit_pdf`**

In `app/core/pdf_ops.py`, insert this block after `_apply_image` ends (after the line `        raise PDFError(f"Could not insert image '{Path(image_path).name}' into the PDF.") from exc`) and before `def edit_pdf(...)`:

```python
_NEW_TEXT_FAMILIES = {"helvetica", "times", "courier"}
_NEW_TEXT_ALIGNS = {"left", "center", "right"}


def _validate_new_text(el: dict) -> None:
    if not el["text"].strip():
        raise PDFError("Add some text before running.")
    if not (0 <= el["x"] <= 1) or not (0 <= el["y"] <= 1):
        raise PDFError("Text box position must be within the page.")
    if not (0 < el["width"] <= 1) or not (0 < el["height"] <= 1):
        raise PDFError("Text box width and height must be positive fractions of the page.")
    if el["x"] + el["width"] > 1 or el["y"] + el["height"] > 1:
        raise PDFError("The text box must fit within the page.")
    if el["family"] not in _NEW_TEXT_FAMILIES:
        raise PDFError(f"Unknown font family: {el['family']}")
    if el["align"] not in _NEW_TEXT_ALIGNS:
        raise PDFError(f"Unknown text alignment: {el['align']}")
    _hex_to_rgb(el["color"])  # raises PDFError up front on a malformed hex


def _wrap_text_lines(text: str, fontname: str, fontsize: float, max_width: float) -> list[str]:
    """Greedy word-wrap using the same width-measurement primitive
    (fitz.get_text_length) auto-shrink-to-fit already relies on.
    insert_textbox() (used elsewhere for Watermark/Page Numbers) wraps text
    but doesn't expose per-line boundaries or widths, which _apply_new_text
    needs to draw a correctly-sized underline under each line and to align
    each line independently — verified empirically (see the Add Text design
    spec) that this manual approach produces the expected line breaks.
    """
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if fitz.get_text_length(candidate, fontname=fontname, fontsize=fontsize) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _apply_new_text(page: fitz.Page, el: dict) -> None:
    rect = page.rect
    displayed = fitz.Rect(
        rect.x0 + el["x"] * rect.width,
        rect.y0 + el["y"] * rect.height,
        rect.x0 + (el["x"] + el["width"]) * rect.width,
        rect.y0 + (el["y"] + el["height"]) * rect.height,
    )
    raw = displayed * page.derotation_matrix

    fontname = _base14_alias(el["family"], el["bold"], el["italic"])
    size = el["size"]
    color = _hex_to_rgb(el["color"])
    align = el["align"]

    lines = _wrap_text_lines(el["text"], fontname, size, raw.width)
    line_height = size * 1.2
    y = raw.y0 + size
    for line in lines:
        # Overflow: stop drawing past the box's bottom edge rather than
        # auto-shrinking — a documented ceiling (the box is user-resizable,
        # so it's recoverable), matching Edit Text's own white-fill limitation.
        if y > raw.y1:
            break
        width = fitz.get_text_length(line, fontname=fontname, fontsize=size)
        if align == "center":
            x = raw.x0 + (raw.width - width) / 2
        elif align == "right":
            x = raw.x1 - width
        else:
            x = raw.x0
        page.insert_text(fitz.Point(x, y), line, fontsize=size, fontname=fontname, color=color)
        if el["underline"]:
            underline_y = y + size * 0.15
            page.draw_line(
                fitz.Point(x, underline_y), fitz.Point(x + width, underline_y),
                color=color, width=max(0.5, size * 0.05),
            )
        y += line_height
```

Then modify `edit_pdf`'s validation loop — find this block:

```python
            elif el_type == "image":
                _validate_image_element(el, image_paths)
            else:
                raise PDFError(f"Unknown element type: {el_type}")
```

and change it to:

```python
            elif el_type == "image":
                _validate_image_element(el, image_paths)
            elif el_type == "new_text":
                _validate_new_text(el)
            else:
                raise PDFError(f"Unknown element type: {el_type}")
```

Then modify the apply loop for `other_elements` — find this block:

```python
            elif el["type"] == "image":
                _apply_image(page, el, image_paths[el["file_id"]])
```

and change it to:

```python
            elif el["type"] == "image":
                _apply_image(page, el, image_paths[el["file_id"]])
            elif el["type"] == "new_text":
                _apply_new_text(page, el)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k new_text -v`
Expected: 10 passed.

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (167 before this task; expect 177 after).

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add _apply_new_text core function for Add Text mode"
```

No `Co-Authored-By` trailer — this is a `feat:` commit (see Global Constraints).

---

## Task 2: Backend — `NewTextElement` route model

**Files:**
- Modify: `web/backend/routes/tools.py:337-350` (add `NewTextElement`, extend the `EditElement` union)
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `_validate_new_text`/`_apply_new_text` (Task 1), the existing `EditElement` union pattern.
- Produces: `NewTextElement` Pydantic model, accepted wherever `EditElement` is (i.e. in `POST /tools/edit-pdf`'s `elements` list) — no new route.

- [ ] **Step 1: Write the failing tests**

Add to `tests/web/test_tools_edit_convert.py`, near the other `test_edit_pdf_*` tests:

```python
def test_edit_pdf_new_text_element_succeeds():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1,
                    "text": "Hello", "family": "helvetica", "bold": False,
                    "italic": False, "underline": False, "size": 14,
                    "color": "#000000", "align": "left",
                }
            ],
        },
    )
    assert response.status_code == 200


def test_edit_pdf_new_text_rejects_non_positive_size():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/edit-pdf",
        json={
            "file_id": upload["id"],
            "elements": [
                {
                    "type": "new_text", "page": 1,
                    "x": 0.1, "y": 0.1, "width": 0.3, "height": 0.1,
                    "text": "Hello", "family": "helvetica", "bold": False,
                    "italic": False, "underline": False, "size": 0,
                    "color": "#000000", "align": "left",
                }
            ],
        },
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k new_text -v`
Expected: FAIL — Pydantic rejects `"type": "new_text"` since no such discriminated-union member exists yet (422 with a "no match for discriminator" style error either way, but the first test expects 200, so it fails).

- [ ] **Step 3: Add `NewTextElement` and extend the union**

In `web/backend/routes/tools.py`, insert this class after `ImageElement` ends (after the line `    height: float`, right before `EditElement = Annotated[`):

```python
class NewTextElement(BaseModel):
    type: Literal["new_text"]
    page: int
    x: float
    y: float
    width: float
    height: float
    text: str
    family: str
    bold: bool
    italic: bool
    underline: bool
    # A blanked number input arrives as 0 from the frontend; insert_text()
    # accepts fontsize=0 silently, rendering the text invisibly. Reject it
    # here, matching FontOverride.size's identical guard above.
    size: float = Field(gt=0)
    color: str
    align: str
```

Then change the `EditElement` union from:

```python
EditElement = Annotated[
    Union[TextEditElement, StrokeElement, ShapeElement, HighlightElement, ImageElement],
    Field(discriminator="type"),
]
```

to:

```python
EditElement = Annotated[
    Union[TextEditElement, StrokeElement, ShapeElement, HighlightElement, ImageElement, NewTextElement],
    Field(discriminator="type"),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k new_text -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (177 before this task; expect 179 after).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_edit_convert.py
git commit -m "feat: accept new_text elements in POST /tools/edit-pdf"
```

No `Co-Authored-By` trailer — this is a `feat:` commit.

---

## Task 3: Frontend — Add Text mode: placement and inline editor

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `commitElements`, `newElementId`, `pointFromEvent`, `MARKUP_COLORS`, `FAMILY_OPTIONS` (all existing in this file).
- Produces: `textDraft` state (shape: `{id: string|null, x, y, width, height, text, family, bold, italic, underline, size, color, align}`), `commitTextDraft()`, `newTextFontFamilyCss(family)`. Task 4 consumes all three, plus reads/writes `textDraft` to implement double-click re-editing.

Backend is done (Tasks 1-2). This task builds the placement + inline-editor half of the frontend: clicking the canvas in "Add Text" mode drops a box with a live text/style editor; clicking away commits it (or discards it if empty). Selecting, moving, resizing, and re-editing an already-placed box is Task 4 — this task renders placed boxes read-only.

TDD is N/A for this frontend task, per this project's established convention (no automated frontend tests). Verification is `npm run build` plus a manual browser pass at the end of this task's steps.

- [ ] **Step 1: Add new icon imports and the "Add Text" mode entry**

In `web/frontend/src/components/EditPdfCanvas.jsx`, change the import block from:

```js
import {
  CaretLeft,
  CaretRight,
  CursorText,
  PencilSimple,
  Rectangle,
  Highlighter,
  ImageSquare,
  X,
  ArrowUUpLeft,
  ArrowUUpRight,
} from "@phosphor-icons/react";
```

to:

```js
import {
  CaretLeft,
  CaretRight,
  CursorText,
  PencilSimple,
  Rectangle,
  Highlighter,
  ImageSquare,
  TextAa,
  TextB,
  TextItalic,
  TextAUnderline,
  TextAlignLeft,
  TextAlignCenter,
  TextAlignRight,
  X,
  ArrowUUpLeft,
  ArrowUUpRight,
} from "@phosphor-icons/react";
```

Change the `MODES` array from:

```js
const MODES = [
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
];
```

to:

```js
const MODES = [
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
  { id: "new_text", label: "Add Text", icon: TextAa },
];
```

- [ ] **Step 2: Add new-text constants and the font-family CSS helper**

Change:

```js
const FAMILY_OPTIONS = ["helvetica", "times", "courier"];
```

to:

```js
const FAMILY_OPTIONS = ["helvetica", "times", "courier"];

const NEW_TEXT_DEFAULT_WIDTH = 0.25;
const NEW_TEXT_DEFAULT_HEIGHT = 0.08;
const NEW_TEXT_DEFAULTS = {
  family: "helvetica",
  bold: false,
  italic: false,
  underline: false,
  size: 14,
  color: "#1f2937",
  align: "left",
};

function newTextFontFamilyCss(family) {
  if (family === "times") return '"Times New Roman", Times, serif';
  if (family === "courier") return '"Courier New", Courier, monospace';
  return "Helvetica, Arial, sans-serif";
}
```

- [ ] **Step 3: Add `textDraft` state and an autofocus effect**

Change:

```js
  const [highlightColor, setHighlightColor] = useState("#ffd43b");
  const [highlightDragStart, setHighlightDragStart] = useState(null);
  const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
```

to:

```js
  const [highlightColor, setHighlightColor] = useState("#ffd43b");
  const [highlightDragStart, setHighlightDragStart] = useState(null);
  const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
  const [textDraft, setTextDraft] = useState(null);
  const textDraftAreaRef = useRef(null);
```

Then, right after the existing `useEffect(() => { elementsRef.current = elements; }, [elements]);` block, add a new effect that focuses the editor's textarea whenever a draft opens (a brand new placement, or Task 4 opening an existing box for re-editing):

```js
  useEffect(() => {
    if (textDraft) textDraftAreaRef.current?.focus();
  }, [textDraft?.id]);
```

- [ ] **Step 4: Add the placement handler and commit/discard logic**

Add these functions near the other mode handlers (e.g. right after `handleImageFileSelected`, before `startImageDrag`):

```js
  function handleNewTextStageClick(e) {
    if (textDraft) return; // an editor is already open — closing it happens via blur, not another placement in the same click
    const point = pointFromEvent(e);
    if (!point) return;
    const width = NEW_TEXT_DEFAULT_WIDTH;
    const height = NEW_TEXT_DEFAULT_HEIGHT;
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setTextDraft({ id: null, x, y, width, height, text: "", ...NEW_TEXT_DEFAULTS });
  }

  function commitTextDraft() {
    const draft = textDraft;
    setTextDraft(null);
    if (!draft || !draft.text.trim()) return; // empty placements are discarded, not saved
    const { id, ...rest } = draft;
    const newEl = { id: id ?? newElementId(), type: "new_text", page: currentPage, ...rest };
    const next = id ? elements.map((el) => (el.id === id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  function handleTextDraftBlur(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      commitTextDraft();
    }
  }

  function handleTextDraftKeyDown(e) {
    const ctrl = e.ctrlKey || e.metaKey;
    if (!ctrl) return;
    if (e.key === "b" || e.key === "B") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, bold: !d.bold }));
    } else if (e.key === "i" || e.key === "I") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, italic: !d.italic }));
    } else if (e.key === "u" || e.key === "U") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, underline: !d.underline }));
    }
  }
```

- [ ] **Step 5: Wire placement into the stage's mousedown dispatcher**

Change:

```js
  function handleStageMouseDown(e) {
    if (activeMode === "draw") return handleDrawMouseDown(e);
    if (activeMode === "shapes") return handleShapeMouseDown(e);
    if (activeMode === "highlight") return handleHighlightMouseDown(e);
    if (activeMode === "image") return handleImageStageClick(e);
  }
```

to:

```js
  function handleStageMouseDown(e) {
    if (activeMode === "draw") return handleDrawMouseDown(e);
    if (activeMode === "shapes") return handleShapeMouseDown(e);
    if (activeMode === "highlight") return handleHighlightMouseDown(e);
    if (activeMode === "image") return handleImageStageClick(e);
    if (activeMode === "new_text") return handleNewTextStageClick(e);
  }
```

- [ ] **Step 6: Render placed `new_text` elements (read-only) and the active editor**

Add this block inside the `<div ref={stageRef} ...>` stage, after the existing `image` elements block (i.e. right after the `.map((el) => ( ... ))` that renders `edit-pdf-canvas__image-el` closes, and before the `{activeMode === "text" && runs.map(...)}` block):

```jsx
        {elements
          .filter((el) => el.type === "new_text" && el.page === currentPage && el.id !== textDraft?.id)
          .map((el) => (
            <div
              key={el.id}
              className="edit-pdf-canvas__new-text-el"
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
            >
              <p
                style={{
                  fontFamily: newTextFontFamilyCss(el.family),
                  fontWeight: el.bold ? "bold" : "normal",
                  fontStyle: el.italic ? "italic" : "normal",
                  textDecoration: el.underline ? "underline" : "none",
                  color: el.color,
                  fontSize: `${el.size}px`,
                  textAlign: el.align,
                }}
              >
                {el.text}
              </p>
            </div>
          ))}

        {textDraft && (
          <div
            className="edit-pdf-canvas__new-text-editor"
            style={{ left: `${textDraft.x * 100}%`, top: `${textDraft.y * 100}%`, width: `${textDraft.width * 100}%`, height: `${textDraft.height * 100}%` }}
            onMouseDown={(e) => e.stopPropagation()}
            onBlur={handleTextDraftBlur}
          >
            <textarea
              ref={textDraftAreaRef}
              className="edit-pdf-canvas__new-text-textarea"
              value={textDraft.text}
              onChange={(e) => setTextDraft((d) => ({ ...d, text: e.target.value }))}
              onKeyDown={handleTextDraftKeyDown}
              style={{
                fontFamily: newTextFontFamilyCss(textDraft.family),
                fontWeight: textDraft.bold ? "bold" : "normal",
                fontStyle: textDraft.italic ? "italic" : "normal",
                textDecoration: textDraft.underline ? "underline" : "none",
                color: textDraft.color,
                fontSize: `${textDraft.size}px`,
                textAlign: textDraft.align,
              }}
            />
            <div className="edit-pdf-canvas__new-text-style-bar">
              <select
                value={textDraft.family}
                onChange={(e) => setTextDraft((d) => ({ ...d, family: e.target.value }))}
              >
                {FAMILY_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                value={textDraft.size}
                onChange={(e) => setTextDraft((d) => ({ ...d, size: Number(e.target.value) }))}
              />
              <button
                type="button"
                className={textDraft.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, bold: !d.bold }))}
                aria-label="Bold"
              >
                <TextB size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, italic: !d.italic }))}
                aria-label="Italic"
              >
                <TextItalic size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.underline ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, underline: !d.underline }))}
                aria-label="Underline"
              >
                <TextAUnderline size={14} weight="bold" />
              </button>
              {MARKUP_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={c === textDraft.color ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
                  style={{ background: c }}
                  onClick={() => setTextDraft((d) => ({ ...d, color: c }))}
                  aria-label={`Color ${c}`}
                />
              ))}
              <button
                type="button"
                className={textDraft.align === "left" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "left" }))}
                aria-label="Align left"
              >
                <TextAlignLeft size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.align === "center" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "center" }))}
                aria-label="Align center"
              >
                <TextAlignCenter size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.align === "right" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "right" }))}
                aria-label="Align right"
              >
                <TextAlignRight size={14} weight="bold" />
              </button>
            </div>
          </div>
        )}
```

- [ ] **Step 7: Add CSS**

In `web/frontend/src/index.css`, insert this block after `.edit-pdf-canvas__width-button--active` ends and before the `/* ---------- Sign canvas ---------- */` comment:

```css
.edit-pdf-canvas__new-text-el {
  position: absolute;
  overflow: hidden;
  pointer-events: none;
}

.edit-pdf-canvas__new-text-el p {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.2;
}

.edit-pdf-canvas__new-text-editor {
  position: absolute;
  z-index: 3;
  display: flex;
  flex-direction: column;
}

.edit-pdf-canvas__new-text-textarea {
  flex: 1;
  width: 100%;
  height: 100%;
  resize: none;
  border: 1px solid var(--color-accent);
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.9);
  padding: 2px 4px;
  box-sizing: border-box;
  line-height: 1.2;
}

.edit-pdf-canvas__new-text-style-bar {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: var(--space-1);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  white-space: nowrap;
  z-index: 4;
}

.edit-pdf-canvas__new-text-style-bar select,
.edit-pdf-canvas__new-text-style-bar input[type="number"] {
  font-size: 12px;
  padding: 2px 4px;
}

.edit-pdf-canvas__new-text-style-bar input[type="number"] {
  width: 48px;
}
```

- [ ] **Step 8: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 9: Manual browser check**

Start the backend and frontend dev servers, open Edit PDF on any PDF, switch to "Add Text" mode, and verify:
- Clicking the page drops a box with a text area and style bar; typing appears live-styled.
- Toggling family/size/bold/italic/underline/color/align in the style bar visibly updates the textarea's live preview.
- Ctrl+B, Ctrl+I, Ctrl+U while typing toggle the same three states.
- Clicking away with text typed leaves a placed, styled (read-only for now) text box on the page.
- Clicking away with the text area empty discards the placement — nothing is left behind.
- Clicking a style-bar button (e.g. a color swatch) does NOT close/discard the editor.

- [ ] **Step 10: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add Add Text mode placement and inline editor"
```

No `Co-Authored-By` trailer — this is a `feat:` commit.

---

## Task 4: Frontend — select, move, resize, re-edit, and copy/paste for placed text boxes

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `textDraft`/`commitTextDraft`/`newTextFontFamilyCss` (Task 3), the existing `image`-element drag machinery (generalized in this task), `removeElement`, `selectElement`, `historyRef`, `elementsRef`, `onChange` (all existing).
- Produces: a generalized `dragRef`/`startElementDrag(el, mode, e, options)`/`handleElementDragMove`/`handleElementDragEnd` (renamed and widened from the `image`-specific `imageDragRef`/`startImageDrag`/`handleImageDragMove`/`handleImageDragEnd`, now shared by both `image` and `new_text` elements), `openTextDraftForEdit(el)`.

This is the final task of this plan — after this, the feature is complete (no `ToolView.jsx`/`toolConfigs.js` changes are needed anywhere in this plan; `new_text` elements ride along in the `elements` array `EditPdfCanvas` already reports via its existing `onChange` prop).

- [ ] **Step 1: Generalize the image drag machinery to be element-type-agnostic**

The existing `image` element's move/resize drag functions already operate generically on `el.x/y/width/height` — nothing in their logic is actually image-specific except their names and one aspect-ratio-locking behavior that only `image` wants. Rename them and add an opt-in `lockAspect` flag so `new_text` can use the same functions with FREE (non-aspect-locked) resizing — a text box's width and height are independent (unlike an image's), so locking its aspect ratio would fight against reflowing wrapped text as the box is resized.

Change:

```js
  const imageDragRef = useRef(null);
```

to:

```js
  const dragRef = useRef(null);
```

Change:

```js
  function startImageDrag(el, mode, e) {
    e.stopPropagation();
    const point = pointFromEvent(e);
    if (!point) return;
    imageDragRef.current = { id: el.id, mode, start: point, startElement: { ...el }, startElementsSnapshot: elements, moved: false };
    window.addEventListener("mousemove", handleImageDragMove);
    window.addEventListener("mouseup", handleImageDragEnd);
    window.addEventListener("blur", handleImageDragEnd);
  }

  function handleImageDragMove(e) {
    const drag = imageDragRef.current;
    if (!drag) return;
    const point = pointFromEvent(e);
    if (!point) return;
    drag.moved = true;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    const { startElement } = drag;
    let updated;
    if (drag.mode === "move") {
      const x = Math.min(Math.max(startElement.x + dx, 0), 1 - startElement.width);
      const y = Math.min(Math.max(startElement.y + dy, 0), 1 - startElement.height);
      updated = { ...startElement, x, y };
    } else {
      const aspect = startElement.height / startElement.width;
      const widthCap = Math.min(1 - startElement.x, (1 - startElement.y) / aspect);
      const desiredWidth = Math.max(0.05, startElement.width + dx);
      const width = Math.min(desiredWidth, widthCap);
      const height = width * aspect;
      updated = { ...startElement, width, height };
    }
    drag.latestElement = updated;
    setElements((prev) => prev.map((el) => (el.id === drag.id ? updated : el)));
  }

  function handleImageDragEnd() {
    window.removeEventListener("mousemove", handleImageDragMove);
    window.removeEventListener("mouseup", handleImageDragEnd);
    window.removeEventListener("blur", handleImageDragEnd);
    const drag = imageDragRef.current;
    imageDragRef.current = null;
    if (!drag || !drag.moved) return;
    historyRef.current = { undoStack: [...historyRef.current.undoStack, drag.startElementsSnapshot], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    const finalElements = drag.latestElement
      ? elementsRef.current.map((el) => (el.id === drag.id ? drag.latestElement : el))
      : elementsRef.current;
    onChange(finalElements);
  }
```

to:

```js
  function startElementDrag(el, mode, e, options = {}) {
    e.stopPropagation();
    const point = pointFromEvent(e);
    if (!point) return;
    dragRef.current = {
      id: el.id, mode, start: point, startElement: { ...el }, startElementsSnapshot: elements, moved: false,
      lockAspect: options.lockAspect ?? false,
    };
    window.addEventListener("mousemove", handleElementDragMove);
    window.addEventListener("mouseup", handleElementDragEnd);
    window.addEventListener("blur", handleElementDragEnd);
  }

  function handleElementDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(e);
    if (!point) return;
    drag.moved = true;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    const { startElement } = drag;
    let updated;
    if (drag.mode === "move") {
      const x = Math.min(Math.max(startElement.x + dx, 0), 1 - startElement.width);
      const y = Math.min(Math.max(startElement.y + dy, 0), 1 - startElement.height);
      updated = { ...startElement, x, y };
    } else if (drag.lockAspect) {
      const aspect = startElement.height / startElement.width;
      const widthCap = Math.min(1 - startElement.x, (1 - startElement.y) / aspect);
      const desiredWidth = Math.max(0.05, startElement.width + dx);
      const width = Math.min(desiredWidth, widthCap);
      const height = width * aspect;
      updated = { ...startElement, width, height };
    } else {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, width, height };
    }
    drag.latestElement = updated;
    setElements((prev) => prev.map((el) => (el.id === drag.id ? updated : el)));
  }

  function handleElementDragEnd() {
    window.removeEventListener("mousemove", handleElementDragMove);
    window.removeEventListener("mouseup", handleElementDragEnd);
    window.removeEventListener("blur", handleElementDragEnd);
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || !drag.moved) return;
    historyRef.current = { undoStack: [...historyRef.current.undoStack, drag.startElementsSnapshot], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    const finalElements = drag.latestElement
      ? elementsRef.current.map((el) => (el.id === drag.id ? drag.latestElement : el))
      : elementsRef.current;
    onChange(finalElements);
  }
```

Then update the existing `image` element's render block — change:

```jsx
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startImageDrag(el, "move", e);
              }}
              // Selection happens on mousedown here (it starts a drag), but the
              // click that follows would still reach the stage and deselect.
              onClick={(e) => e.stopPropagation()}
            >
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startImageDrag(el, "resize", e)} />
```

to:

```jsx
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(el, "move", e);
              }}
              // Selection happens on mousedown here (it starts a drag), but the
              // click that follows would still reach the stage and deselect.
              onClick={(e) => e.stopPropagation()}
            >
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(el, "resize", e, { lockAspect: true })} />
```

- [ ] **Step 2: Add the double-click-to-reedit helper**

Add near `commitTextDraft` (Task 3):

```js
  function openTextDraftForEdit(el) {
    const { id, page, ...rest } = el;
    setTextDraft({ id, ...rest });
  }
```

- [ ] **Step 3: Replace the read-only `new_text` render block with a fully interactive one**

Replace the block Task 3 added:

```jsx
        {elements
          .filter((el) => el.type === "new_text" && el.page === currentPage && el.id !== textDraft?.id)
          .map((el) => (
            <div
              key={el.id}
              className="edit-pdf-canvas__new-text-el"
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
            >
              <p
                style={{
                  fontFamily: newTextFontFamilyCss(el.family),
                  fontWeight: el.bold ? "bold" : "normal",
                  fontStyle: el.italic ? "italic" : "normal",
                  textDecoration: el.underline ? "underline" : "none",
                  color: el.color,
                  fontSize: `${el.size}px`,
                  textAlign: el.align,
                }}
              >
                {el.text}
              </p>
            </div>
          ))}
```

with:

```jsx
        {elements
          .filter((el) => el.type === "new_text" && el.page === currentPage && el.id !== textDraft?.id)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__new-text-el edit-pdf-canvas__new-text-el--selected"
                  : "edit-pdf-canvas__new-text-el"
              }
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(el, "move", e);
              }}
              onClick={(e) => e.stopPropagation()}
              onDoubleClick={(e) => {
                e.stopPropagation();
                openTextDraftForEdit(el);
              }}
            >
              <p
                style={{
                  fontFamily: newTextFontFamilyCss(el.family),
                  fontWeight: el.bold ? "bold" : "normal",
                  fontStyle: el.italic ? "italic" : "normal",
                  textDecoration: el.underline ? "underline" : "none",
                  color: el.color,
                  fontSize: `${el.size}px`,
                  textAlign: el.align,
                }}
              >
                {el.text}
              </p>
              <div
                className="edit-pdf-canvas__new-text-el-handle"
                onMouseDown={(e) => startElementDrag(el, "resize", e, { lockAspect: false })}
              />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => removeElement(el.id)}
                aria-label="Remove this text box"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}
```

- [ ] **Step 4: Update CSS for selection/interactivity**

In `web/frontend/src/index.css`, change:

```css
.edit-pdf-canvas__new-text-el {
  position: absolute;
  overflow: hidden;
  pointer-events: none;
}
```

to:

```css
.edit-pdf-canvas__new-text-el {
  position: absolute;
  overflow: hidden;
  pointer-events: auto;
  cursor: move;
}

.edit-pdf-canvas__new-text-el--selected {
  outline: 2px solid var(--color-accent);
  outline-offset: 1px;
}

.edit-pdf-canvas__new-text-el-handle {
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

- [ ] **Step 5: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Run the full backend test suite once more**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (179, unaffected by this frontend-only task — confirming nothing else regressed).

- [ ] **Step 7: Manual end-to-end browser verification**

Start the backend and frontend dev servers, open Edit PDF on a PDF with at least 2 pages, and verify the complete feature:
- Place a text box, style it (family/size/bold/italic/underline/color/align), click away — it appears correctly on the page.
- Single click on the placed box selects it (outline appears) without reopening the editor.
- Body-drag repositions it; corner-drag resizes it — width and height move INDEPENDENTLY (not locked to one aspect ratio, unlike Insert Image's resize).
- Double-click reopens the inline editor pre-filled with its current text and styling; editing and clicking away updates it in place.
- The × button removes it.
- Ctrl+C then Ctrl+V (with it selected, and not currently inside any text input) duplicates it, offset slightly, on the current page.
- Ctrl+Z/Ctrl+Y undo/redo placement, edits, moves, and resizes.
- Switching to a different page and back preserves per-page text boxes correctly (only the current page's boxes render).
- Existing modes (Edit Text, Draw, Shapes, Highlight, Insert Image) still work exactly as before — this task renamed shared drag internals, so re-verify Insert Image's move/resize (now via the renamed `startElementDrag`/`handleElementDragMove`/`handleElementDragEnd`) still works and still keeps its aspect ratio locked while resizing.
- Run the tool with a mix of element types including at least one `new_text` box; download the output and confirm (e.g. via a quick PyMuPDF inspection, or just visually) the text box rendered with the right content, font, style, and position.

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: select, move, resize, re-edit, and copy/paste Add Text boxes"
```

No `Co-Authored-By` trailer — this is a `feat:` commit.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (179).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (4 total), in order, on top of `main`'s current tip, none carrying a `Co-Authored-By` trailer (all are `feat:`).
