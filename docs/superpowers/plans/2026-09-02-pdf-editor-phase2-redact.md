# Phase 2 Group C1: Redact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Redact PDF" tool — draw one or more boxes across any pages of a document to
permanently remove the content underneath (not just visually cover it) and replace it with a
solid black fill.

**Architecture:** One new core function reuses Crop's exact fraction-to-rect conversion and
validation bound (verified against the actual shipped `crop_pdf`), but per-box instead of
per-document-uniform, and uses PyMuPDF's real redaction API (`add_redact_annot` +
`apply_redactions`, empirically verified against this project's actual PyMuPDF version to
genuinely strip content, not just paint over it — see Global Constraints). The frontend gets a new
`RedactSelector` component that extends `CropSelector`'s proven drag-to-rectangle technique for
multi-page navigation and multiple boxes per page, each removable via a small × button.

**Tech Stack:** Python/FastAPI/PyMuPDF backend (unchanged), React/Vite frontend (unchanged).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-redact-design.md` — read it first;
  this plan implements it exactly.
- **Verified empirically against this project's actual PyMuPDF version before this plan was
  written** (not assumed from documentation): `add_redact_annot(rect, fill=(0,0,0))` followed by
  `apply_redactions()` genuinely removes the underlying text (confirmed via `get_text()` before
  and after), renders a solid black fill (confirmed by sampling a rendered pixel), and correctly
  scopes each page's removal to only that page's own annotations when multiple pages have
  annotations queued (confirmed with a 2-page document where only specific lines/pages were
  redacted and everything else remained exactly intact).
- Each redaction box's four fractions must be validated `0 <= value < 1` per edge, plus
  `left + right < 1` and `top + bottom < 1` — this is the exact bound `crop_pdf` already uses
  (confirmed present in the current `app/core/pdf_ops.py`); do not re-derive a different bound.
- A page number in a redaction entry is 1-indexed and must be validated against the document's
  actual page count before any page is modified.
- All user-facing errors raise `app.core.errors.PDFError` — never a raw exception surfaced to the
  API layer.
- The `RedactRequest` Pydantic model uses an explicit nested `RedactionBox` model — not a raw
  `list[dict]` — matching every other route in `web/backend/routes/tools.py`
  (`CropRequest`/`AddPageNumbersRequest`/etc. all use explicit typed fields). `app/core/pdf_ops.py`
  stays framework-agnostic — the route converts each validated `RedactionBox` to a plain dict
  (`.model_dump()`, confirmed correct for this project's installed Pydantic 2.13.5) before calling
  the core function.
- No new frontend automated test infrastructure — frontend behavior is verified by manual browser
  testing at the end, matching every prior UI feature this project has shipped.

---

### Task 1: `redact_pdf` — core function

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `redact_pdf(input_path: str, output_path: str, redactions: list[dict]) -> None`, where
  each dict has keys `page` (int, 1-indexed), `top`, `right`, `bottom`, `left` (float, 0-1
  fractions). Raises `PDFError` for an empty list, an out-of-range `page`, or a fraction outside
  the valid bound.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py` (add `redact_pdf` to the existing
`from app.core.pdf_ops import ...` line):

```python
def test_redact_pdf_removes_covered_text(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "REMOVE THIS")
    page.insert_text((72, 150), "KEEP THIS")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    assert "REMOVE THIS" not in text
    assert "KEEP THIS" in text
    result.close()


def test_redact_pdf_multiple_boxes_same_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "FIRST SECRET")
    page.insert_text((72, 150), "SECOND SECRET")
    page.insert_text((72, 250), "KEPT TEXT")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
        {"page": 1, "top": 0.13, "right": 0.35, "bottom": 0.77, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    text = result[0].get_text()
    assert "FIRST SECRET" not in text
    assert "SECOND SECRET" not in text
    assert "KEPT TEXT" in text
    result.close()


def test_redact_pdf_multiple_pages(tmp_path):
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((72, 72), "PAGE ONE SECRET")
    p2 = doc.new_page(width=595, height=842)
    p2.insert_text((72, 72), "PAGE TWO SECRET")
    p2.insert_text((72, 150), "PAGE TWO KEPT")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    redact_pdf(str(input_path), str(output_path), [
        {"page": 1, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
        {"page": 2, "top": 0.05, "right": 0.4, "bottom": 0.85, "left": 0.1},
    ])

    result = fitz.open(str(output_path))
    assert "PAGE ONE SECRET" not in result[0].get_text()
    assert "PAGE TWO SECRET" not in result[1].get_text()
    assert "PAGE TWO KEPT" in result[1].get_text()
    result.close()


def test_redact_pdf_rejects_empty_list(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [])


def test_redact_pdf_rejects_out_of_range_page(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [
            {"page": 2, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1},
        ])


def test_redact_pdf_rejects_invalid_fraction(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "redacted.pdf"
    with pytest.raises(PDFError):
        redact_pdf(str(input_path), str(output_path), [
            {"page": 1, "top": 1.0, "right": 0.1, "bottom": 0.1, "left": 0.1},
        ])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k redact_pdf -v`
Expected: FAIL — `redact_pdf` doesn't exist yet.

- [ ] **Step 3: Implement `redact_pdf`**

Add to `app/core/pdf_ops.py`, after `images_to_pdf` (keep the newest functions grouped at the
end, matching how each Phase 2 addition has been appended so far):

```python
def redact_pdf(input_path: str, output_path: str, redactions: list[dict]) -> None:
    if not redactions:
        raise PDFError("Select at least one area to redact.")
    doc = open_pdf(input_path)
    try:
        for r in redactions:
            page_num = r["page"]
            if page_num < 1 or page_num > doc.page_count:
                raise PDFError(f"Page {page_num} does not exist in this document ({doc.page_count} pages).")
        for r in redactions:
            for name in ("top", "right", "bottom", "left"):
                value = r[name]
                if not (0 <= value < 1):
                    raise PDFError(f"Redaction '{name}' must be between 0 and 1 (got {value}).")
            if r["left"] + r["right"] >= 1 or r["top"] + r["bottom"] >= 1:
                raise PDFError("Each redaction area must have a positive width and height.")
        pages_with_annots = set()
        for r in redactions:
            page = doc[r["page"] - 1]
            rect = page.rect
            redact_rect = fitz.Rect(
                rect.x0 + r["left"] * rect.width,
                rect.y0 + r["top"] * rect.height,
                rect.x1 - r["right"] * rect.width,
                rect.y1 - r["bottom"] * rect.height,
            )
            page.add_redact_annot(redact_rect, fill=(0, 0, 0))
            pages_with_annots.add(r["page"])
        for page_num in pages_with_annots:
            doc[page_num - 1].apply_redactions()
        doc.save(output_path)
    finally:
        doc.close()
```

Note the three separate passes: validate every page number first, then validate every fraction,
*then* mutate — this guarantees a bad entry anywhere in the list fails before any page is
touched, leaving no partially-redacted output. `open_pdf(path)` already works unmodified here;
do not add any redaction-specific branching to it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k redact_pdf -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the full core test suite**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add redact_pdf core function"
```

---

### Task 2: `/tools/redact` route

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `redact_pdf` from Task 1 (exact signature above).
- Produces: `POST /api/tools/redact`, returning
  `{"outputs": [{"id": str, "filename": str, "download_url": str}]}` — the same shape every other
  tool endpoint already returns via `_output_response`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_tools_edit_convert.py` (reuse the existing `_upload_pdf()` helper — do
not redefine it):

```python
def test_redact_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/redact",
        json={
            "file_id": upload["id"],
            "redactions": [{"page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1}],
        },
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_redact_rejects_empty_redactions():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/redact",
        json={"file_id": upload["id"], "redactions": []},
    )
    assert response.status_code == 422


def test_redact_unknown_file_id_returns_404():
    response = client.post(
        "/api/tools/redact",
        json={
            "file_id": "nope",
            "redactions": [{"page": 1, "top": 0.1, "right": 0.1, "bottom": 0.1, "left": 0.1}],
        },
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -k redact -v`
Expected: FAIL with 404 (the route doesn't exist yet — note `test_redact_unknown_file_id_returns_404`
will coincidentally also expect 404 but for the wrong reason at this stage; that's fine, it's
still red for a different reason than intended, which Step 4 resolves for real).

- [ ] **Step 3: Implement the route**

In `web/backend/routes/tools.py`, add `redact_pdf` to the existing
`from app.core.pdf_ops import (...)` block, keeping it alphabetically sorted:

```python
from app.core.pdf_ops import (
    add_page_numbers,
    add_watermark,
    compress_pdf,
    crop_pdf,
    extract_pages,
    get_page_count,
    images_to_pdf,
    merge_pdfs,
    redact_pdf,
    remove_pages,
    render_to_images,
    reorder_pages,
    rotate_pages,
    split_pdf,
)
```

Then add, after the `crop`/`add-page-numbers` routes (keeping Edit-category tools grouped
together):

```python
class RedactionBox(BaseModel):
    page: int
    top: float
    right: float
    bottom: float
    left: float


class RedactRequest(BaseModel):
    file_id: str
    redactions: list[RedactionBox]


@router.post("/redact")
def redact(req: RedactRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_redacted")
    redactions = [r.model_dump() for r in req.redactions]
    redact_pdf(input_path, str(output_path), redactions)
    return _output_response([output_path], "Redact PDF", [Path(input_path).name])
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
git commit -m "feat: add /tools/redact route"
```

---

### Task 3: Frontend — `RedactSelector` component and tool config

**Files:**
- Create: `web/frontend/src/components/RedactSelector.jsx`
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Produces: `<RedactSelector fileId={string} pageCount={number} onChange={(redactions) => void}>`
  — a self-contained component that owns its own page-navigation and box state internally, and
  calls `onChange` with the full current array of `{page, top, right, bottom, left}` objects
  every time a box is added or removed. `pageCount` is a new required prop this component
  introduces (unlike `CropSelector`, which only ever showed page 1 and didn't need it).

- [ ] **Step 1: Add the `redact` tool config**

In `web/frontend/src/toolConfigs.js`, add (category `"Edit"`, alongside `rotate`, `watermark`,
`add-page-numbers`, `crop`):

```javascript
redact: {
  title: "Redact PDF",
  category: "Edit",
  multiFile: false,
  mode: "view",
  preview: "redact",
  endpoint: "redact",
  fields: [],
},
```

- [ ] **Step 2: Create `RedactSelector.jsx`**

Create `web/frontend/src/components/RedactSelector.jsx`:

```jsx
import { useRef, useState } from "react";
import { CaretLeft, CaretRight, X } from "@phosphor-icons/react";
import { thumbnailUrl } from "../api";

const PREVIEW_MAX_SIZE = 700;
const MIN_DRAG_FRACTION = 0.02;

export default function RedactSelector({ fileId, pageCount, onChange }) {
  const containerRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [redactions, setRedactions] = useState([]);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);

  if (!fileId || !pageCount) return null;

  function pointFromEvent(e) {
    const rect = containerRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(e) {
    if (!dragStart) return;
    const point = pointFromEvent(e);
    if (!point) return;
    setDragCurrent(point);
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
      return; // too small to be a deliberate drag
    }
    const next = [...redactions, { page: currentPage, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 }];
    setRedactions(next);
    onChange(next);
  }

  function removeBox(index) {
    const next = redactions.filter((_, i) => i !== index);
    setRedactions(next);
    onChange(next);
  }

  const activeDragBox =
    dragStart && dragCurrent
      ? {
          x0: Math.min(dragStart.x, dragCurrent.x),
          y0: Math.min(dragStart.y, dragCurrent.y),
          x1: Math.max(dragStart.x, dragCurrent.x),
          y1: Math.max(dragStart.y, dragCurrent.y),
        }
      : null;

  const pageBoxes = redactions
    .map((r, index) => ({ ...r, index }))
    .filter((r) => r.page === currentPage);
  const markedPageCount = new Set(redactions.map((r) => r.page)).size;

  return (
    <div className="redact-selector">
      <div className="redact-selector__nav">
        <button
          type="button"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={currentPage === 1}
        >
          <CaretLeft size={14} weight="bold" />
          Previous
        </button>
        <span>
          Page {currentPage} of {pageCount} ({markedPageCount} page{markedPageCount === 1 ? "" : "s"} marked)
        </span>
        <button
          type="button"
          onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))}
          disabled={currentPage === pageCount}
        >
          Next
          <CaretRight size={14} weight="bold" />
        </button>
      </div>
      <div
        ref={containerRef}
        className="redact-selector__canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img
          className="redact-selector__image"
          src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
          alt={`Page ${currentPage} preview — drag to mark an area for redaction`}
          draggable={false}
        />
        {pageBoxes.map((box) => (
          <div
            key={box.index}
            className="redact-selector__box"
            style={{
              left: `${box.left * 100}%`,
              top: `${box.top * 100}%`,
              width: `${(1 - box.left - box.right) * 100}%`,
              height: `${(1 - box.top - box.bottom) * 100}%`,
            }}
          >
            <button
              type="button"
              className="redact-selector__box-remove"
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => removeBox(box.index)}
              aria-label="Remove this redaction area"
            >
              <X size={12} weight="bold" />
            </button>
          </div>
        ))}
        {activeDragBox && (
          <div
            className="redact-selector__box redact-selector__box--dragging"
            style={{
              left: `${activeDragBox.x0 * 100}%`,
              top: `${activeDragBox.y0 * 100}%`,
              width: `${(activeDragBox.x1 - activeDragBox.x0) * 100}%`,
              height: `${(activeDragBox.y1 - activeDragBox.y0) * 100}%`,
            }}
          />
        )}
      </div>
    </div>
  );
}
```

The box's `left`/`top` CSS position and `width`/`height` are derived from the stored margin
fractions: `1 - box.left - box.right` recovers the width fraction (`x1 - x0`) without storing
`x0`/`x1` directly — this is the same `{top, left, right, bottom}` margin-fraction shape
`CropSelector` already uses and the backend already expects, so no conversion is needed anywhere
in the data flow from drag to API body.

- [ ] **Step 3: Add the CSS**

In `web/frontend/src/index.css`, add a new section (near the Crop selector section):

```css
/* ---------- Redact selector ---------- */

.redact-selector {
  margin: var(--space-5) 0;
}

.redact-selector__nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  font-size: 14px;
  color: var(--color-muted-foreground);
}

.redact-selector__nav button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
}

.redact-selector__nav button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.redact-selector__canvas {
  position: relative;
  display: inline-block;
  max-width: 100%;
  cursor: crosshair;
  user-select: none;
}

.redact-selector__image {
  display: block;
  max-width: 100%;
  border-radius: var(--radius-sm);
  pointer-events: none;
}

.redact-selector__box {
  position: absolute;
  background: rgba(0, 0, 0, 0.85);
  pointer-events: auto;
}

.redact-selector__box--dragging {
  background: rgba(0, 0, 0, 0.5);
  pointer-events: none;
}

.redact-selector__box-remove {
  position: absolute;
  top: -8px;
  right: -8px;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-accent);
  color: white;
  border: 2px solid var(--color-background);
  border-radius: 50%;
  cursor: pointer;
  padding: 0;
}
```

- [ ] **Step 4: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors. (`RedactSelector` isn't wired into `ToolView` yet — Task 4 —
so this just confirms the new file and CSS compile cleanly on their own.)

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/RedactSelector.jsx web/frontend/src/toolConfigs.js web/frontend/src/index.css
git commit -m "feat: add RedactSelector multi-page multi-box drag component"
```

---

### Task 4: Frontend — wire Redact into `ToolView`

**Files:**
- Modify: `web/frontend/src/components/ToolView.jsx`

**Interfaces:**
- Consumes: `RedactSelector` from Task 3, `POST /tools/redact` from Task 2.

**This task changes shared code every existing tool also uses** — the same category of change as
wiring Crop in (Group A, Task 7) and Images-to-PDF's config-driven upload generalization (Group
B, Task 3). The new guard/body-merge/disabled-clause additions must be strict no-ops for every
tool other than Redact.

- [ ] **Step 1: Import `RedactSelector` and add `redactions` state**

In `web/frontend/src/components/ToolView.jsx`, add the import near the top, alongside the
existing `CropSelector`/`ImagePagePreview` imports:

```javascript
import RedactSelector from "./RedactSelector";
```

Add a new piece of state alongside the existing `cropRect` state:

```javascript
const [redactions, setRedactions] = useState([]);
```

- [ ] **Step 2: Reset `redactions` on a new file pick**

In `handleFilePick`, find this block:

```javascript
if (primary) {
  setSelected([]);
  setCropRect(null);
  setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
```

Add `setRedactions([]);` right after `setCropRect(null);`:

```javascript
if (primary) {
  setSelected([]);
  setCropRect(null);
  setRedactions([]);
  setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
```

- [ ] **Step 3: Add the `redact` preview branch**

In `renderPreview()`, add a new branch directly after the `images-to-pdf` branch:

```jsx
if (config.preview === "redact") {
  if (!primaryFile) return null;
  return (
    <RedactSelector fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setRedactions} />
  );
}
```

- [ ] **Step 4: Guard `handleRun` and include the redactions array in the request body**

In `handleRun`, find this existing guard:

```javascript
if (config.preview === "crop" && !cropRect) {
  setError("Drag a box on the page preview to select the area to keep.");
  return;
}
```

Add a new guard directly after it:

```javascript
if (config.preview === "redact" && redactions.length === 0) {
  setError("Draw at least one box on the page preview to mark an area for redaction.");
  return;
}
```

Then, inside the `try` block, find this existing line:

```javascript
if (config.preview === "crop") Object.assign(body, cropRect);
```

Add directly after it:

```javascript
if (config.preview === "redact") body.redactions = redactions;
```

- [ ] **Step 5: Disable Run until at least one box is drawn**

Find the Run button's `disabled` expression:

```jsx
disabled={busy || files.length === 0 || (config.preview === "crop" && !cropRect)}
```

Extend it:

```jsx
disabled={
  busy ||
  files.length === 0 ||
  (config.preview === "crop" && !cropRect) ||
  (config.preview === "redact" && redactions.length === 0)
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
Expected: all PASS.

- [ ] **Step 8: Self-review the no-op claim**

Trace the four new additions (state, guard, body-merge, disabled-clause) for one non-Redact tool
(e.g. Merge, or Rotate): confirm every new `config.preview === "redact"` condition evaluates to
`false` for it, so none of the new code contributes anything to its behavior. This mirrors the
exact trace done for Crop's equivalent wiring in Group A.

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/components/ToolView.jsx
git commit -m "feat: wire Redact tool into ToolView with multi-page box selector"
```

---

## Final Verification (done by the controller, not a dispatched task)

After all four tasks land:

1. Run the full test suite once more: `venv/Scripts/python -m pytest -q` — expect all green.
2. Rebuild the frontend (`cd web/frontend && npm run build`) and launch the dev server
   (`venv/Scripts/python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8756`).
3. Manually verify in the browser: upload a multi-page PDF, draw multiple boxes on the first
   page, navigate to a later page with Next and draw a box there too, confirm the
   "Page X of N (K pages marked)" label updates correctly, remove one box with its × button and
   confirm it disappears, navigate back to the first page and confirm its remaining boxes are
   still there, confirm Run is disabled until at least one box exists, run it, download the
   result, and confirm (via a quick script or PyMuPDF check) the redacted regions' text is
   genuinely gone from the output while unredacted content on the same pages remains intact.
4. Confirm no existing tool regressed: spot-check Crop (a tool with its own similar Run-disable
   precondition) still works exactly as before.
5. Rebuild the packaged PyInstaller exe and smoke-test it launches and serves the new tool.
6. Push to `main`.
