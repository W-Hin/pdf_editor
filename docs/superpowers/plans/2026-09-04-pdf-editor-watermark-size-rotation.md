# Watermark Size & Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users control Add Watermark's font size and rotation angle (any angle 0-360°, not just 90° multiples), with both reflected live in the existing preview.

**Architecture:** `add_watermark` switches from `page.insert_textbox(..., rotate=angle)` (which only accepts 90° multiples) to `page.insert_text()` with a `morph=(center, fitz.Matrix(angle))` transform, verified empirically to support arbitrary angles. `WatermarkRequest` exposes the core function's already-existing `font_size`/`rotate` parameters (currently accepted by the Python function but not reachable via the API). The frontend adds two range sliders and extends the existing CSS-only preview overlay with a matching `transform: rotate()` and scaled `font-size`.

**Tech Stack:** PyMuPDF (`fitz`) 1.28.2, FastAPI/Pydantic, React (no new dependencies).

## Global Constraints

- Rotation is a continuous slider, 0-360°, not preset-angle buttons.
- Font size is a slider, 10-120pt, default 40 (matching the core function's existing default).
- Watermark text stays single-line — this is a deliberate consequence of moving off `insert_textbox` (which auto-wrapped) to `insert_text` (which doesn't); the existing text field is already a single-line `<input>`, so this is not a behavior anyone currently relies on.
- One angle/size setting applies to every page (matches current behavior — no per-page watermark config).
- **Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go ONLY on commits whose subject starts with `fix:`/`fix(scope):`.** Both tasks' initial commits in this plan are `feat:` commits and must NOT carry that trailer.

---

## Task 1: Backend — arbitrary-angle rotation, expose `font_size`/`rotate`

**Files:**
- Modify: `app/core/pdf_ops.py:121-149` (`add_watermark`)
- Modify: `web/backend/routes/tools.py:155-169` (`WatermarkRequest`, the `watermark` route)
- Test: `tests/test_pdf_ops.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Produces: `add_watermark(input_path, output_path, text, opacity=0.3, font_size=40, rotate=0)` — `font_size`/`rotate` now both `float` (were `int`), `rotate` no longer restricted to 90° multiples. `WatermarkRequest` gains `font_size: float = 40` and `rotate: float = 0`, both passed through to `add_watermark`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ops.py`, near the existing `test_add_watermark_*` tests (search for `test_add_watermark_inserts_text`):

```python
def test_add_watermark_rotates_at_arbitrary_angle(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    out_path = str(tmp_path / "wm45.pdf")

    add_watermark(path, out_path, "DRAFT", opacity=0.5, font_size=60, rotate=45)

    result = fitz.open(out_path)
    pix = result[0].get_pixmap()
    cx, cy = pix.width // 2, pix.height // 2
    center_pixel = pix.pixel(cx, cy)[:3]
    corner_pixel = pix.pixel(20, 20)[:3]
    result.close()
    # A 45-degree-rotated watermark passes through the page's exact center
    # (the rotation pivot) — verified empirically: center pixel (208,208,208),
    # a visible gray, not pure white. A far corner has no ink at all.
    assert center_pixel != (255, 255, 255)
    assert corner_pixel == (255, 255, 255)


def test_add_watermark_font_size_scales_rendered_text(make_pdf, tmp_path):
    path = make_pdf(num_pages=1)
    small_path = str(tmp_path / "small.pdf")
    large_path = str(tmp_path / "large.pdf")

    add_watermark(path, small_path, "DRAFT", opacity=0.5, font_size=20, rotate=0)
    add_watermark(path, large_path, "DRAFT", opacity=0.5, font_size=80, rotate=0)

    def ink_width(p):
        doc = fitz.open(p)
        d = doc[0].get_text("dict")
        doc.close()
        spans = [s for b in d["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        return spans[0]["bbox"][2] - spans[0]["bbox"][0]

    small_w = ink_width(small_path)
    large_w = ink_width(large_path)
    # 80pt vs 20pt is a 4x fontsize ratio — verified empirically: 266.6 vs 66.7,
    # i.e. genuinely ~4x, not a coincidence of rounding.
    assert large_w > small_w * 3
```

Add to `tests/web/test_tools_edit_convert.py`, near the existing `test_watermark_*` tests:

```python
def test_watermark_accepts_font_size_and_rotate():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/watermark",
        json={"file_id": upload["id"], "text": "DRAFT", "opacity": 0.3, "font_size": 60, "rotate": 45},
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k watermark -v`
Expected: `test_add_watermark_rotates_at_arbitrary_angle` FAILS — the current code raises `PDFError("Watermark rotation must be 0, 90, 180, or 270 degrees.")` for `rotate=45`. `test_add_watermark_font_size_scales_rendered_text` currently PASSES already (the existing `insert_textbox` call already respects `font_size`) — that's fine, it's a regression guard for Step 3's rewrite, not a new-behavior test.

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k watermark -v`
Expected: `test_watermark_accepts_font_size_and_rotate` FAILS — `WatermarkRequest` doesn't have `font_size`/`rotate` fields yet, so Pydantic silently ignores them and the request reaches `add_watermark` with `rotate=0` (default) instead of `45`... actually since `WatermarkRequest` doesn't define those fields, FastAPI/Pydantic ignores unknown JSON keys by default rather than erroring — so this test will actually return 200 already. Confirm this by running it: if it unexpectedly passes already, that's fine (it becomes a regression guard once font_size/rotate are wired through for real in Step 3) — don't force a RED result that isn't genuinely there.

- [ ] **Step 3: Rewrite `add_watermark` for arbitrary-angle rotation**

In `app/core/pdf_ops.py`, replace:

```python
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

with:

```python
def add_watermark(
    input_path: str,
    output_path: str,
    text: str,
    opacity: float = 0.3,
    font_size: float = 40,
    rotate: float = 0,
) -> None:
    if not text.strip():
        raise PDFError("Watermark text cannot be empty.")
    doc = open_pdf(input_path)
    try:
        for page in doc:
            # insert_textbox()'s own `rotate` parameter only accepts multiples of
            # 90 — verified empirically (raises "rotate must be multiple of 90").
            # insert_text() with a morph=(pivot, matrix) transform supports any
            # angle instead: the watermark is centered on the page via a computed
            # origin, then rotated around that same center point. This also means
            # the watermark no longer auto-wraps across multiple lines the way
            # insert_textbox() did — a deliberate, documented change (see this
            # plan's Global Constraints), matching the existing single-line text
            # field.
            width = fitz.get_text_length(text, fontname="helv", fontsize=font_size)
            center = fitz.Point(page.rect.width / 2, page.rect.height / 2)
            origin = fitz.Point(center.x - width / 2, center.y + font_size / 3)
            page.insert_text(
                origin,
                text,
                fontsize=font_size,
                fontname="helv",
                color=(0.5, 0.5, 0.5),
                fill_opacity=opacity,
                morph=(center, fitz.Matrix(rotate)),
            )
        doc.save(output_path)
    finally:
        doc.close()
```

- [ ] **Step 4: Wire `font_size`/`rotate` into `WatermarkRequest` and the route**

In `web/backend/routes/tools.py`, replace:

```python
class WatermarkRequest(BaseModel):
    file_id: str
    text: str
    opacity: float = 0.3


@router.post("/watermark")
def watermark(req: WatermarkRequest):
    if not req.text.strip():
        raise PDFError("Watermark text cannot be empty.")
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_watermarked")
    add_watermark(input_path, str(output_path), req.text, opacity=req.opacity)
    return _output_response([output_path], "Add watermark", [Path(input_path).name])
```

with:

```python
class WatermarkRequest(BaseModel):
    file_id: str
    text: str
    opacity: float = 0.3
    font_size: float = 40
    rotate: float = 0


@router.post("/watermark")
def watermark(req: WatermarkRequest):
    if not req.text.strip():
        raise PDFError("Watermark text cannot be empty.")
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_watermarked")
    add_watermark(input_path, str(output_path), req.text, opacity=req.opacity, font_size=req.font_size, rotate=req.rotate)
    return _output_response([output_path], "Add watermark", [Path(input_path).name])
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k watermark -v`
Expected: 4 passed (2 pre-existing + 2 new).

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_edit_convert.py -k watermark -v`
Expected: 3 passed (2 pre-existing + 1 new).

- [ ] **Step 6: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (180 before this task; expect 183 after).

- [ ] **Step 7: Commit**

```bash
git add app/core/pdf_ops.py web/backend/routes/tools.py tests/test_pdf_ops.py tests/web/test_tools_edit_convert.py
git commit -m "feat: support arbitrary-angle watermark rotation and font size"
```

No `Co-Authored-By` trailer — this is a `feat:` commit (see Global Constraints).

---

## Task 2: Frontend — size/rotation sliders with a live-updating preview

**Files:**
- Modify: `web/frontend/src/toolConfigs.js:58-77` (`watermark` entry)
- Modify: `web/frontend/src/components/ToolView.jsx:217-237` (the `config.preview === "watermark"` branch)
- Modify: `web/frontend/src/index.css` (`.page-thumb__watermark-preview`)

**Interfaces:**
- Consumes: `add_watermark`/`WatermarkRequest` (Task 1, already accepting `font_size`/`rotate`).
- No new components — this rides entirely on the existing `PageGrid` + `overlay` prop mechanism `config.preview === "watermark"` already uses.

Backend is done (Task 1). This task is pure frontend: two new range-slider fields, and extending the existing CSS-only preview overlay to reflect them live. `type: "range"` fields already render as a generic `<input type="range">` and already flow into the request body automatically (`ToolView.jsx`'s field-to-body loop applies to every field in `config.fields` uniformly) — no new plumbing needed there, only the two new field definitions and the preview's own rendering.

TDD is N/A for this task, per this project's established convention (no automated frontend tests). Verification is `npm run build` plus a manual browser pass.

- [ ] **Step 1: Add the two new fields to `toolConfigs.js`**

In `web/frontend/src/toolConfigs.js`, change the `watermark` entry's `fields` array from:

```js
    fields: [
      { name: "text", label: "Watermark text", type: "text", default: "" },
      {
        name: "opacity",
        label: "Opacity (%)",
        type: "range",
        min: 10,
        max: 100,
        default: 30,
        scale: 0.01,
      },
    ],
```

to:

```js
    fields: [
      { name: "text", label: "Watermark text", type: "text", default: "" },
      {
        name: "opacity",
        label: "Opacity (%)",
        type: "range",
        min: 10,
        max: 100,
        default: 30,
        scale: 0.01,
      },
      {
        name: "font_size",
        label: "Font size (pt)",
        type: "range",
        min: 10,
        max: 120,
        default: 40,
      },
      {
        name: "rotate",
        label: "Rotation (degrees)",
        type: "range",
        min: 0,
        max: 360,
        default: 0,
      },
    ],
```

- [ ] **Step 2: Extend the preview to reflect size and rotation live**

In `web/frontend/src/components/ToolView.jsx`, change the `config.preview === "watermark"` branch from:

```jsx
    if (config.preview === "watermark") {
      if (!primaryFile) return null;
      const text = fieldValues.text?.trim();
      const opacity = fieldValues.opacity ?? 30;
      return (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode="view"
          overlay={
            text
              ? () => (
                  <span className="page-thumb__watermark-preview" style={{ opacity: opacity / 100 }}>
                    {text}
                  </span>
                )
              : undefined
          }
        />
      );
    }
```

to:

```jsx
    if (config.preview === "watermark") {
      if (!primaryFile) return null;
      const text = fieldValues.text?.trim();
      const opacity = fieldValues.opacity ?? 30;
      const fontSize = fieldValues.font_size ?? 40;
      const rotate = fieldValues.rotate ?? 0;
      return (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode="view"
          overlay={
            text
              ? () => (
                  <span
                    className="page-thumb__watermark-preview"
                    style={{ opacity: opacity / 100, fontSize: `${fontSize}px`, transform: `rotate(${rotate}deg)` }}
                  >
                    {text}
                  </span>
                )
              : undefined
          }
        />
      );
    }
```

(The overlay's wrapping `.page-thumb__overlay` element is already `display: flex; align-items: center; justify-content: center;` with no `overlayPosition` passed for watermark, so it's already centered — `transform: rotate()` on the `<span>` itself rotates around its own center by default, matching how the backend rotates around the page's center.)

- [ ] **Step 3: Remove the fixed `font-size` from the CSS class**

In `web/frontend/src/index.css`, find:

```css
.page-thumb__watermark-preview {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--color-secondary);
  word-break: break-word;
}
```

and remove the `font-size: 11px;` line (it's now set inline per Step 2, driven by the slider) — change to:

```css
.page-thumb__watermark-preview {
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: var(--color-secondary);
  word-break: break-word;
}
```

- [ ] **Step 4: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 5: Manual browser check**

Start the backend and frontend dev servers, open Add Watermark on any PDF, type watermark text, and verify:
- Two new sliders appear: "Font size (pt)" (10-120) and "Rotation (degrees)" (0-360).
- Dragging the font-size slider visibly grows/shrinks the preview text on every page thumbnail, live.
- Dragging the rotation slider visibly rotates the preview text, live, at ANY angle (not just 0/90/180/270 — check e.g. 45° and 200° specifically).
- Running the tool and downloading the output shows a genuinely rotated, correctly-sized watermark matching what the preview showed.

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx web/frontend/src/index.css
git commit -m "feat: add live-updating size and rotation controls to watermark preview"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (183).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (2 total), in order, on top of `main`'s current tip, none carrying a `Co-Authored-By` trailer (both are `feat:`).
