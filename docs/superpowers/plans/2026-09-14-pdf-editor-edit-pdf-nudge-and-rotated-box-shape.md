# Edit PDF: Arrow-Key Nudge for Text Edits + Rotated-Page Box Shape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a selected `text_edit` element be nudged with the arrow keys like every other draggable element, and make a moved `text_edit` element's on-screen box shape match the orientation its replacement text actually gets drawn in on a rotated page.

**Architecture:** A new backend helper exposes a page's rotation degree through the existing text-runs API. The frontend stores that per page and threads it into the existing `textEditBoxRect` helper, which both the nudge fix and the box's rendering already go through — so fixing `textEditBoxRect` once fixes both the rendering shape and gives nudge the real dimensions it needs to avoid the NaN trap the previous exclusion was protecting against.

**Tech Stack:** Python (FastAPI backend, PyMuPDF/`fitz`), React (frontend), pytest.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Both tasks in this plan ship new, intentional behavior — their commits are `feat:` and must **not** carry the trailer.
- The box does not resize based on the actual length of the replacement content — only its orientation (width/height swap) changes on a rotated page, once moved. This mirrors the existing, already-accepted "move only" limitation for non-rotated pages.
- The narrow first-drag-near-edge overflow edge case (see Task 2) is accepted and documented, not fixed — do not add extra clamp-reconciliation logic for it.
- No frontend automated tests (established project convention for frontend-only work) — manual browser verification instead, including checking the actual exported/downloaded PDF's content for the box-shape scenario.

---

### Task 1: Backend — expose a page's rotation degree

**Files:**
- Modify: `app/core/pdf_ops.py` (add `get_page_rotation` right after `get_page_count`, currently lines 31-36)
- Modify: `web/backend/routes/files.py` (its `get_text_runs` route, currently lines 38-45, and its import line, currently line 5)
- Test: `tests/test_pdf_ops.py` (new tests near `test_get_page_count`, currently at line 22; add `get_page_rotation` to the import line, currently line 7)
- Test: `tests/web/test_tools_edit_convert.py` (extend `test_get_text_runs_returns_runs`, currently at line 296)

**Interfaces:**
- Produces: `get_page_rotation(path: str, page_number: int) -> int` in `app/core/pdf_ops.py`, raising `PDFError` for an out-of-range page (matching `extract_text_runs`'s own validation). The `/files/{file_id}/pages/{page_number}/text-runs` route's JSON response gains a top-level `"rotation": <int>` field alongside its existing `"runs"` field. Task 2 consumes this field directly from `fetchTextRuns`'s response (`web/frontend/src/api.js`'s `fetchTextRuns` already returns the full parsed body — no change needed there).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pdf_ops.py`, directly after `test_get_page_count` (currently ending at line 24):

```python
def test_get_page_rotation_returns_zero_for_unrotated_page(make_pdf):
    path = make_pdf(num_pages=1)
    assert get_page_rotation(path, 1) == 0


def test_get_page_rotation_returns_the_rotation_degree(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.set_rotation(90)
    path = tmp_path / "rotated.pdf"
    doc.save(str(path))
    doc.close()
    assert get_page_rotation(str(path), 1) == 90


def test_get_page_rotation_rejects_out_of_range_page(make_pdf):
    path = make_pdf(num_pages=1)
    with pytest.raises(PDFError):
        get_page_rotation(path, 2)
```

Add `get_page_rotation` to the existing import line (currently line 7):

```python
from app.core.pdf_ops import open_pdf, get_page_count, get_page_rotation, merge_pdfs, extract_pages, remove_pages, reorder_pages, split_pdf, rotate_pages, add_watermark, crop_pdf, add_page_numbers, images_to_pdf, redact_pdf, extract_text_runs, edit_pdf, extract_form_fields, fill_form, pdf_to_markdown_zip
```

Also extend the existing route test in `tests/web/test_tools_edit_convert.py` (currently lines 296-302):

```python
def test_get_text_runs_returns_runs():
    upload = _upload_pdf()
    response = client.get(f"/api/files/{upload['id']}/pages/1/text-runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["text"] == "Page 1"
    assert body["rotation"] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pdf_ops.py -k get_page_rotation -v`
Expected: FAIL with `ImportError`/`NameError` — `get_page_rotation` doesn't exist yet.

Run: `pytest tests/web/test_tools_edit_convert.py -k test_get_text_runs_returns_runs -v`
Expected: FAIL — `body["rotation"]` raises `KeyError` (the route doesn't return that key yet).

- [ ] **Step 3: Implement `get_page_rotation`**

In `app/core/pdf_ops.py`, add directly after `get_page_count` (currently lines 31-36):

```python
def get_page_rotation(path: str, page_number: int) -> int:
    doc = open_pdf(path)
    try:
        if page_number < 1 or page_number > doc.page_count:
            raise PDFError(f"Page {page_number} does not exist in this document ({doc.page_count} pages).")
        return doc[page_number - 1].rotation
    finally:
        doc.close()
```

- [ ] **Step 4: Wire it into the text-runs route**

In `web/backend/routes/files.py`, change the import line (currently line 5):

```python
from app.core.pdf_ops import extract_form_fields, extract_text_runs, get_page_count, get_page_rotation, render_page_thumbnail
```

And change `get_text_runs` (currently lines 38-45):

```python
@router.get("/files/{file_id}/pages/{page_number}/text-runs")
def get_text_runs(file_id: str, page_number: int):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    runs = extract_text_runs(str(path), page_number)
    rotation = get_page_rotation(str(path), page_number)
    return {"runs": runs, "rotation": rotation}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_pdf_ops.py -k get_page_rotation -v`
Expected: PASS (3 tests).

Run: `pytest tests/web/test_tools_edit_convert.py -v`
Expected: PASS (all tests in this file, including the extended `test_get_text_runs_returns_runs`).

Run the full backend suite to confirm no regressions: `pytest -q`
Expected: PASS, same total count as before plus 3.

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py web/backend/routes/files.py tests/test_pdf_ops.py tests/web/test_tools_edit_convert.py
git commit -m "feat: expose a page's rotation degree from the text-runs API"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: Frontend — nudge for text_edit, and rotated-page box orientation

This task is one cohesive unit, not split further: nudge's fix depends on
the exact same `textEditBoxRect` change the box-shape fix needs (nudge
reuses it to get real dimensions before calling `moveElement`) — splitting
them would leave an awkward intermediate state where one half references a
function signature the other half hasn't added yet.

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx` (see exact regions below)

**Interfaces:**
- Consumes: Task 1's `"rotation"` field in the text-runs API response (via the existing `fetchTextRuns`, unchanged).
- Produces: nothing consumed by a later task (this is the last task in the plan).

- [ ] **Step 1: Add `pageRotations` state**

Add directly after the existing `const [runs, setRuns] = useState([]);` line (currently line 269):

```javascript
  const [pageRotations, setPageRotations] = useState({}); // { [pageNumber]: rotationDegrees }
```

- [ ] **Step 2: Populate it alongside `runs`**

Replace the `loadRuns` effect (currently lines 376-397):

```javascript
  useEffect(() => {
    if (!fileId || !pageCount) return;
    let cancelled = false;
    async function loadRuns() {
      const perPage = await Promise.all(
        Array.from({ length: pageCount }, (_, i) => i + 1).map((pageNumber) =>
          fetchTextRuns(fileId, pageNumber)
            .then((data) => data.runs.map((r) => ({ ...r, page: pageNumber })))
            .catch((err) => {
              console.error(`Failed to load text runs for page ${pageNumber}:`, err);
              return [];
            })
        )
      );
      if (!cancelled) setRuns(perPage.flat());
    }
    loadRuns();
    setRunEditor(null);
    return () => {
      cancelled = true;
    };
  }, [fileId, pageCount]);
```

with:

```javascript
  useEffect(() => {
    if (!fileId || !pageCount) return;
    let cancelled = false;
    async function loadRuns() {
      const perPage = await Promise.all(
        Array.from({ length: pageCount }, (_, i) => i + 1).map((pageNumber) =>
          fetchTextRuns(fileId, pageNumber)
            .then((data) => ({
              page: pageNumber,
              runs: data.runs.map((r) => ({ ...r, page: pageNumber })),
              rotation: data.rotation,
            }))
            .catch((err) => {
              console.error(`Failed to load text runs for page ${pageNumber}:`, err);
              return { page: pageNumber, runs: [], rotation: 0 };
            })
        )
      );
      if (!cancelled) {
        setRuns(perPage.flatMap((p) => p.runs));
        setPageRotations(Object.fromEntries(perPage.map((p) => [p.page, p.rotation])));
      }
    }
    loadRuns();
    setRunEditor(null);
    return () => {
      cancelled = true;
    };
  }, [fileId, pageCount]);
```

- [ ] **Step 3: Update `textEditBoxRect` to swap axes once moved on a rotated page**

Replace `textEditBoxRect` and its leading comment (currently lines 1003-1014):

```javascript
  // The box a text_edit element (or its live editor overlay) occupies: the
  // original run's own detected size always (per this feature's "move only,
  // never resize" scope decision), positioned at the element's moved x/y
  // once it has one, falling back to the run's own top-left when it hasn't
  // been moved yet (or no pending edit exists at all).
  function textEditBoxRect(run, pending) {
    const width = 1 - run.bbox.left - run.bbox.right;
    const height = 1 - run.bbox.top - run.bbox.bottom;
    const left = pending?.x ?? run.bbox.left;
    const top = pending?.y ?? run.bbox.top;
    return { left, top, width, height };
  }
```

with:

```javascript
  // The box a text_edit element (or its live editor overlay) occupies: the
  // original run's own detected size always (per this feature's "move only,
  // never resize" scope decision), positioned at the element's moved x/y
  // once it has one, falling back to the run's own top-left when it hasn't
  // been moved yet (or no pending edit exists at all).
  //
  // On a 90/270-rotated page, once actually moved, width/height are
  // transposed: the backend draws the replacement with rotate=page.rotation
  // once an override is active (_apply_text_edit's override_xy branch) so it
  // reads upright to the viewer, which transposes its actual extent relative
  // to the ORIGINAL run's own (possibly sideways) orientation. Swapping here
  // keeps the box's on-screen shape matching what will actually export —
  // but only once moved, since an un-moved element still draws (and must
  // still be shown) in the original run's own unrotated orientation.
  //
  // Known, accepted limitation: this swap is keyed off the CURRENT pending
  // element's x/y, so it only takes effect starting from the render right
  // after a move commits. A drag gesture's own clamp bound (moveElement, via
  // the `positioned` snapshot captured once at drag-start) is computed
  // against PRE-swap dimensions for an element's very FIRST-ever move — so
  // dropping it very close to a page edge on that first drag can show a
  // small overflow past that edge. Dragging it again uses the now-current
  // (already-swapped) dimensions and is correctly bounded. Deliberately not
  // closed: doing so would mean reconciling two different clamp bases
  // mid-gesture, real complexity for a cosmetic, self-fixing edge case.
  function textEditBoxRect(run, pending, pageRotations) {
    let width = 1 - run.bbox.left - run.bbox.right;
    let height = 1 - run.bbox.top - run.bbox.bottom;
    const moved = pending?.x !== undefined && pending?.y !== undefined;
    const rotation = pageRotations[run.page] ?? 0;
    if (moved && (rotation === 90 || rotation === 270)) {
      [width, height] = [height, width];
    }
    const left = pending?.x ?? run.bbox.left;
    const top = pending?.y ?? run.bbox.top;
    return { left, top, width, height };
  }
```

- [ ] **Step 4: Pass `pageRotations` through all three existing call sites**

In `renderTextEditElement` (currently around line 1426):

```javascript
    const box = textEditBoxRect(run, el);
```

becomes:

```javascript
    const box = textEditBoxRect(run, el, pageRotations);
```

In `renderRunStyleOverlay` (currently around line 1582):

```javascript
    const box = textEditBoxRect(run, pending);
```

becomes:

```javascript
    const box = textEditBoxRect(run, pending, pageRotations);
```

In `renderRunEditorOverlay` (currently around line 1677):

```javascript
    const box = textEditBoxRect(run, pendingTextEditFor(run));
```

becomes:

```javascript
    const box = textEditBoxRect(run, pendingTextEditFor(run), pageRotations);
```

- [ ] **Step 5: Enable arrow-key nudge for `text_edit` elements**

In `handleKeyDown`'s arrow-key branch (currently lines 465-477):

```javascript
        } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) && selectedId) {
          const el = elements.find((item) => item.id === selectedId);
          if (el && el.type !== "text_edit") {
            e.preventDefault();
            const step = e.shiftKey ? NUDGE_BIG_STEP : NUDGE_SMALL_STEP;
            let dx = 0;
            let dy = 0;
            if (e.key === "ArrowLeft") dx = -step;
            else if (e.key === "ArrowRight") dx = step;
            else if (e.key === "ArrowUp") dy = -step;
            else dy = step;
            commitElements(elements.map((item) => (item.id === selectedId ? moveElement(item, dx, dy) : item)));
          }
        }
```

becomes:

```javascript
        } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) && selectedId) {
          const el = elements.find((item) => item.id === selectedId);
          if (el) {
            let target = el;
            if (el.type === "text_edit") {
              // A stored text_edit element never has width/height (its size
              // always comes from its own run) - moveElement's text_edit
              // branch needs those to clamp correctly, so build the same
              // dimension-carrying object renderTextEditElement's drag start
              // already builds via textEditBoxRect, instead of handing it
              // the raw stored element (which would read undefined -> NaN).
              const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
              if (!run) return; // runs haven't loaded yet - nothing to nudge against safely
              const box = textEditBoxRect(run, el, pageRotations);
              target = { ...el, x: box.left, y: box.top, width: box.width, height: box.height };
            }
            e.preventDefault();
            const step = e.shiftKey ? NUDGE_BIG_STEP : NUDGE_SMALL_STEP;
            let dx = 0;
            let dy = 0;
            if (e.key === "ArrowLeft") dx = -step;
            else if (e.key === "ArrowRight") dx = step;
            else if (e.key === "ArrowUp") dy = -step;
            else dy = step;
            const moved = moveElement(target, dx, dy);
            commitElements(elements.map((item) => (item.id === selectedId ? moved : item)));
          }
        }
```

- [ ] **Step 6: Keep `handleKeyDown`'s closure fresh over the new state**

`handleKeyDown` is defined inside a `useEffect` whose dependency array
currently reads (search for `document.addEventListener("keydown", handleKeyDown);` a few lines below `handleKeyDown`'s closing brace):

```javascript
  }, [elements, selectedId, textDraft, runEditor]);
```

`runs` and `pageRotations` are now referenced inside this same closure (Step
5) — add them so the listener re-registers with fresh values once either
loads, rather than reading a stale (possibly empty) snapshot from whenever
this effect last ran:

```javascript
  }, [elements, selectedId, textDraft, runEditor, runs, pageRotations]);
```

- [ ] **Step 7: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: builds with no errors.

Start the dev server and manually verify, using a PDF with existing text —
ideally one rotated page and one non-rotated page in the same document, so
both paths are exercised in one session:

1. Double-click an existing text run on a **non-rotated** page, type a
   replacement, select it (don't drag it), then press an arrow key — the
   box moves in the correct direction; Shift+Arrow moves it further.
2. Same on a **rotated** page: select an un-moved `text_edit` box and press
   an arrow key — it nudges correctly (this exercises the `moved === false`
   path through `textEditBoxRect`, i.e. no swap yet, matching the original
   run's own orientation).
3. On the rotated page, drag the box once (any small move), then nudge it
   with arrow keys — it continues to move correctly using the now-swapped
   dimensions, and stays within the page bounds under repeated nudging in
   every direction including toward each edge.
4. Confirm nudging while nothing is selected, or while a non-`text_edit`
   element is selected, is unaffected (still works exactly as before this
   change).
5. On the rotated page: double-click an existing run, commit a replacement
   without moving it — the box's shape still matches the *original* run's
   own (un-swapped) orientation. Then drag it — the box visibly transposes
   to a wide/short shape matching how the replacement will actually read.
6. Export/download the PDF after moving a `text_edit` element on the
   rotated page, and inspect the downloaded file with a quick PyMuPDF
   script (`page.get_text("dict")`, checking the resulting span's bbox) to
   confirm the exported text's actual extent is wide/short — matching what
   the on-screen (post-swap) box shape showed, not the original run's
   tall/narrow shape.

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx
git commit -m "feat: nudge text edits with arrow keys and match their box shape to rotated replacement text"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.
