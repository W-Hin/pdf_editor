# Edit PDF Shape/Image Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Edit PDF element type click-anywhere-selectable and movable (shapes/highlights also resizable), let a selected element's style be edited live, add z-order controls, fix Insert Image's missing preview/wrong-proportions/aspect-locked-only resize, add Add Text's minimum-size validation, and make Line visually distinct from Arrow in the live editor.

**Architecture:** Builds entirely on the generalized `startElementDrag`/`handleElementDragMove`/`handleElementDragEnd` drag machinery and the per-page `renderPageOverlay(pageNumber, pageRef)` rendering `EditPdfCanvas.jsx` already has (from the already-shipped PageScrollViewer migration) — extending it with new resize sub-modes, a shared bounding-box hit-test overlay pattern, one interleaved per-page render list (for z-order), and a small number of backend changes (`keep_proportion=False` for images, a min-size check for Add Text using the same wrap logic `_apply_new_text` already has).

**Tech Stack:** React, PyMuPDF (`fitz`) 1.28.2, FastAPI/Pydantic.

## Global Constraints

- Click-anywhere-to-select and drag-to-move apply to every element type (stroke/shape/highlight/image/new_text). Resize applies to every type EXCEPT strokes (move+select only — freehand ink has no natural resize affordance).
- Real-time restyling: when an element is selected, that mode's existing style-bar controls (color/width for Draw+Shapes, fill toggle for Rectangle/Ellipse, color for Highlight) read from and write to that element's own style; with nothing selected, they keep setting the default for the next new element (unchanged).
- Z-order (bring to front / send to back / forward / backward) requires rendering to become one interleaved list per page in `elements` array order, instead of grouped-by-type blocks. No backend change — `edit_pdf` already applies `other_elements` in array order.
- Insert Image: a visible `<img>` inside the box; default size corrected to use the actual rendered page's aspect ratio (not an assumed-square-page formula); three resize handles (corner = proportional, right-edge = width-only, bottom-edge = height-only); backend switches to `keep_proportion=False` so the export always matches exactly what the box shows.
- Add Text: the resize handle can't shrink the box below what its current text needs at its current font size/wrapping.
- Line vs Arrow must look visually distinct while drawing/queued, not just after export.
- Multi-select is out of scope — one element selected/restyled/reordered at a time.
- **Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go ONLY on commits whose subject starts with `fix:`/`fix(scope):`.** Every task's initial commit in this plan is a `feat:` commit and must NOT carry that trailer.

---

## Task 1: Unified select/move/resize for strokes/shapes/highlights + Line/Arrow visual distinction

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: existing `startElementDrag(pageRef, el, mode, e, options)`/`handleElementDragMove`/`handleElementDragEnd`, `selectElement`, `removeElement`.
- Produces: every stroke/shape/highlight gets a transparent hit-test overlay div (bounding box computed per type) wired to select-on-click and move-on-drag; shapes and highlights additionally get a resize handle. Strokes translate as a whole on move (every point shifts by the same delta).

Currently, strokes/shapes/highlights render inside shared `<svg>`/`<div>` blocks with only an `onClick` for selection — no drag-to-move, and (for shapes specifically) clicking only responds to the SVG shape's own painted area (an unfilled rectangle's interior doesn't receive clicks). This task adds a sibling hit-test overlay per element, positioned by a computed bounding box, reusing the existing drag machinery.

- [ ] **Step 1: Generalize `handleElementDragMove` with two new resize sub-modes and a whole-stroke move**

The existing move branch already works generically on any element with `x`/`y`/`width`/`height` — strokes don't have those fields (they have `points`), so moving a stroke needs its own branch. Change:

```jsx
  function handleElementDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
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
```

to:

```jsx
  function handleElementDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
    if (!point) return;
    drag.moved = true;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    const { startElement } = drag;
    let updated;
    if (drag.mode === "move") {
      updated = moveElement(startElement, dx, dy);
    } else if (drag.mode === "resize-width") {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      updated = { ...startElement, width };
    } else if (drag.mode === "resize-height") {
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, height };
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

  // Moving translates the element by (dx, dy), clamped so it stays on the
  // page. Each element type keeps its own coordinates within bounds, so the
  // clamp differs by shape: x/y/width/height types clamp directly; x0/x1 and
  // left/right/top/bottom types clamp the pair together; points translate as
  // a whole group, clamped by their own min/max extent.
  function moveElement(el, dx, dy) {
    if ("x0" in el) {
      const width = Math.abs(el.x1 - el.x0);
      const height = Math.abs(el.y1 - el.y0);
      const minX = Math.min(el.x0, el.x1);
      const minY = Math.min(el.y0, el.y1);
      const clampedDx = Math.min(Math.max(dx, -minX), 1 - width - minX);
      const clampedDy = Math.min(Math.max(dy, -minY), 1 - height - minY);
      return { ...el, x0: el.x0 + clampedDx, x1: el.x1 + clampedDx, y0: el.y0 + clampedDy, y1: el.y1 + clampedDy };
    }
    if ("left" in el) {
      const width = 1 - el.left - el.right;
      const height = 1 - el.top - el.bottom;
      const clampedDx = Math.min(Math.max(dx, -el.left), el.right);
      const clampedDy = Math.min(Math.max(dy, -el.top), el.bottom);
      return { ...el, left: el.left + clampedDx, right: el.right - clampedDx, top: el.top + clampedDy, bottom: el.bottom - clampedDy };
    }
    if ("points" in el) {
      const xs = el.points.map((p) => p.x);
      const ys = el.points.map((p) => p.y);
      const clampedDx = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
      const clampedDy = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
      return { ...el, points: el.points.map((p) => ({ x: p.x + clampedDx, y: p.y + clampedDy })) };
    }
    // x/y/width/height (image, new_text)
    const x = Math.min(Math.max(el.x + dx, 0), 1 - el.width);
    const y = Math.min(Math.max(el.y + dy, 0), 1 - el.height);
    return { ...el, x, y };
  }
```

- [ ] **Step 2: Add resize sub-mode for shapes**

Shapes resize by dragging their `x1`/`y1` corner (the drag-created endpoint). Add a shape-specific resize branch — change `handleElementDragMove`'s dispatch again, this time adding a `resize-corner-xy` mode used only by shapes (which have `x0/y0/x1/y1`, not `width`/`height`, so the existing `lockAspect`/else branches don't apply to them). Find the `else if (drag.lockAspect)` / final `else` pair from Step 1 and add a new branch immediately before them:

```jsx
    } else if (drag.mode === "resize-corner-xy") {
      const x1 = Math.min(Math.max(startElement.x1 + dx, 0), 1);
      const y1 = Math.min(Math.max(startElement.y1 + dy, 0), 1);
      updated = { ...startElement, x1, y1 };
    } else if (drag.lockAspect) {
```

- [ ] **Step 3: Add per-element bounding-box + hit-test-overlay rendering for strokes**

In `renderPageOverlay`, find the stroke remove-button block:

```jsx
        {elements
          .filter((el) => el.type === "stroke" && el.page === pageNumber)
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
                onClick={() => removeElement(el.id)}
                aria-label="Remove this stroke"
              >
                <X size={12} weight="bold" />
              </button>
            );
          })}
```

and replace it with a hit-test overlay (sized to the stroke's bounding box, draggable to move) plus the same remove button:

```jsx
        {elements
          .filter((el) => el.type === "stroke" && el.page === pageNumber)
          .map((el) => {
            const xs = el.points.map((p) => p.x);
            const ys = el.points.map((p) => p.y);
            const left = Math.min(...xs);
            const top = Math.min(...ys);
            const width = Math.max(...xs) - left;
            const height = Math.max(...ys) - top;
            return (
              <div key={`${el.id}-hit`}>
                <div
                  className="edit-pdf-canvas__hit-overlay"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }}
                  onMouseDown={(e) => {
                    setSelectedId(el.id);
                    startElementDrag(pageRef, el, "move", e);
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="button"
                  className="edit-pdf-canvas__element-remove"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => removeElement(el.id)}
                  aria-label="Remove this stroke"
                >
                  <X size={12} weight="bold" />
                </button>
              </div>
            );
          })}
```

- [ ] **Step 4: Add hit-test overlay + resize handle for shapes**

Find the shape remove-button block:

```jsx
        {elements
          .filter((el) => el.type === "shape" && el.page === pageNumber)
          .map((el) => (
            <button
              key={`${el.id}-remove`}
              type="button"
              className="edit-pdf-canvas__element-remove"
              style={{ left: `${Math.min(el.x0, el.x1) * 100}%`, top: `${Math.min(el.y0, el.y1) * 100}%` }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={() => removeElement(el.id)}
              aria-label="Remove this shape"
            >
              <X size={12} weight="bold" />
            </button>
          ))}
```

and replace it with:

```jsx
        {elements
          .filter((el) => el.type === "shape" && el.page === pageNumber)
          .map((el) => {
            const left = Math.min(el.x0, el.x1);
            const top = Math.min(el.y0, el.y1);
            const width = Math.abs(el.x1 - el.x0);
            const height = Math.abs(el.y1 - el.y0);
            return (
              <div key={`${el.id}-hit`}>
                <div
                  className="edit-pdf-canvas__hit-overlay"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }}
                  onMouseDown={(e) => {
                    setSelectedId(el.id);
                    startElementDrag(pageRef, el, "move", e);
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div
                    className="edit-pdf-canvas__shape-resize-handle"
                    onMouseDown={(e) => startElementDrag(pageRef, el, "resize-corner-xy", e)}
                  />
                </div>
                <button
                  type="button"
                  className="edit-pdf-canvas__element-remove"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => removeElement(el.id)}
                  aria-label="Remove this shape"
                >
                  <X size={12} weight="bold" />
                </button>
              </div>
            );
          })}
```

(The resize handle sits at the hit-overlay's own bottom-right corner via CSS, dragging `x1`/`y1` — see Step 6's CSS.)

- [ ] **Step 5: Add move + resize to highlights**

Find the highlight's `onClick={(e) => selectElement(el.id, e)}` and its surrounding `<div>`:

```jsx
        {elements
          .filter((el) => el.type === "highlight" && el.page === pageNumber)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__highlight edit-pdf-canvas__highlight--selected"
                  : "edit-pdf-canvas__highlight"
              }
              style={{
                left: `${el.left * 100}%`,
                top: `${el.top * 100}%`,
                width: `${(1 - el.left - el.right) * 100}%`,
                height: `${(1 - el.top - el.bottom) * 100}%`,
                background: `${el.color}${HIGHLIGHT_ALPHA_HEX}`,
              }}
              onClick={(e) => selectElement(el.id, e)}
            >
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  removeElement(el.id);
                }}
                aria-label="Remove this highlight"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}
```

to:

```jsx
        {elements
          .filter((el) => el.type === "highlight" && el.page === pageNumber)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__highlight edit-pdf-canvas__highlight--selected"
                  : "edit-pdf-canvas__highlight"
              }
              style={{
                left: `${el.left * 100}%`,
                top: `${el.top * 100}%`,
                width: `${(1 - el.left - el.right) * 100}%`,
                height: `${(1 - el.top - el.bottom) * 100}%`,
                background: `${el.color}${HIGHLIGHT_ALPHA_HEX}`,
              }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(pageRef, el, "move", e);
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div
                className="edit-pdf-canvas__shape-resize-handle"
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: false })}
              />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  removeElement(el.id);
                }}
                aria-label="Remove this highlight"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}
```

(Highlight already has `x`/`y`-equivalent fields via `left`/`top`/`right`/`bottom`, but NOT literal `width`/`height` fields the existing `resize` mode's `else` branch expects — so this needs its OWN resize handling. Highlight's shape doesn't fit the generic `else` branch as-is (it has no `width`/`height` keys), so add a highlight-specific case: in `handleElementDragMove`, add this branch right after the `resize-width`/`resize-height` checks from Step 1, before the `lockAspect` check:

```jsx
    } else if (drag.mode === "resize" && "left" in startElement) {
      const width = Math.max(0.02, 1 - startElement.left - startElement.right + dx);
      const height = Math.max(0.02, 1 - startElement.top - startElement.bottom + dy);
      const right = Math.max(0, 1 - startElement.left - width);
      const bottom = Math.max(0, 1 - startElement.top - height);
      updated = { ...startElement, right, bottom };
    } else if (drag.lockAspect) {
```

- [ ] **Step 6: Add CSS for the new hit-overlay and resize handles**

In `web/frontend/src/index.css`, add after `.edit-pdf-canvas__box-remove`'s existing rules (or any sensible location near the other `edit-pdf-canvas__` element rules):

```css
.edit-pdf-canvas__hit-overlay {
  position: absolute;
  cursor: move;
  background: transparent;
}

.edit-pdf-canvas__shape-resize-handle {
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

- [ ] **Step 7: Line vs Arrow visual distinction in the live preview**

Find the shapes SVG's line/arrow rendering:

```jsx
              // line and arrow both render as a line preview; the real arrowhead is
              // drawn server-side by edit_pdf — this is close enough for the queue preview.
              return (
                <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                  <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
                </g>
              );
```

and replace it with a version that draws the same triangular arrowhead geometry `_draw_arrow` uses server-side (angle-based, at the line's endpoint), only for `arrow`:

```jsx
              if (el.shape === "arrow") {
                const x1p = el.x0 * 100, y1p = el.y0 * 100, x2p = el.x1 * 100, y2p = el.y1 * 100;
                const angle = Math.atan2(y2p - y1p, x2p - x1p);
                const headLen = Math.max(2, el.width);
                const headAngle = (25 * Math.PI) / 180;
                const hx1 = x2p - headLen * Math.cos(angle - headAngle);
                const hy1 = y2p - headLen * Math.sin(angle - headAngle);
                const hx2 = x2p - headLen * Math.cos(angle + headAngle);
                const hy2 = y2p - headLen * Math.sin(angle + headAngle);
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <line {...commonProps} x1={x1p} y1={y1p} x2={x2p} y2={y2p} />
                    <polygon
                      points={`${hx1},${hy1} ${x2p},${y2p} ${hx2},${hy2}`}
                      fill={el.color}
                      stroke={el.color}
                    />
                  </g>
                );
              }
              // line renders as a plain line — the arrow branch above is what
              // now makes it visually distinct from Arrow in the live preview.
              return (
                <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                  <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
                </g>
              );
```

- [ ] **Step 8: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 9: Thorough manual browser check**

Open Edit PDF on a multi-page PDF and verify:
- Draw a stroke — clicking ANYWHERE within its bounding box (not just precisely on the line) selects it; dragging from within that box moves the whole stroke.
- Draw a rectangle (filled and unfilled) — clicking anywhere INSIDE it (not just the outline) selects it; dragging moves it; the corner handle resizes it.
- Draw an ellipse, line, arrow — same select/move/resize checks. Confirm Line and Arrow now look visually different while queued (Arrow shows a triangular head, Line doesn't) — not just after Run.
- Draw a highlight — click anywhere inside selects it; drag moves it; a resize handle appears and works.
- Every element stays within page bounds while being moved/resized (can't drag it off the edge).
- Undo/redo works for every new move/resize interaction.
- Run the tool with a mix of moved/resized elements; confirm the output matches what the editor showed.

- [ ] **Step 10: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add click-anywhere select, move, and resize to strokes, shapes, and highlights"
```

No `Co-Authored-By` trailer.

---

## Task 2: Real-time restyling on selection

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`

**Interfaces:**
- Consumes: `selectedId`, `elements`, `commitElements` (all existing).
- Produces: `updateSelectedElementStyle(patch)` — applies a style patch to the currently-selected element (if any) and commits it; each mode's style-bar controls call this when something is selected, falling back to their existing default-setting behavior when nothing is.

Currently, Draw/Shapes/Highlight's color/width/fill controls only ever set the "next new element" default (`drawColor`, `shapeColor`, `shapeWidth`, `shapeFilled`, `highlightColor`). This task gives them a second behavior: when an element is selected, the SAME controls edit that element's live style instead.

- [ ] **Step 1: Add the shared restyling helper**

Add near `commitElements`:

```jsx
  function updateSelectedElementStyle(patch) {
    if (!selectedId) return false; // nothing selected — caller should fall back to its default-setting behavior
    const el = elements.find((e) => e.id === selectedId);
    if (!el) return false;
    commitElements(elements.map((e) => (e.id === selectedId ? { ...e, ...patch } : e)));
    return true;
  }
```

- [ ] **Step 2: Wire Draw's color/width controls**

Find the Draw mode's color swatches:

```jsx
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
```

(this is inside `{activeMode === "draw" && (...)}`) and change the two `onClick` handlers to:

```jsx
              onClick={() => {
                if (!updateSelectedElementStyle({ color: c })) setDrawColor(c);
              }}
```

and:

```jsx
              onClick={() => {
                if (!updateSelectedElementStyle({ width: STROKE_WIDTHS[w] })) setDrawWidth(w);
              }}
```

Also make the ACTIVE-state highlighting reflect the selected stroke's own style when one is selected — change the `className` expressions for both controls. For the color swatch:

```jsx
              className={
                (selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.color === c : c === drawColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
```

For the width button:

```jsx
              className={
                (selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.width === STROKE_WIDTHS[w] : w === drawWidth)
                  ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active"
                  : "edit-pdf-canvas__width-button"
              }
```

Add the `selectedElementForStyle` lookup once, near the top of the component body (after `elements`/`selectedId` state, before the `return`):

```jsx
  const selectedElementForStyle = elements.find((e) => e.id === selectedId) ?? null;
```

- [ ] **Step 3: Wire Shapes' color/width/fill controls**

Find the Shapes mode's color/width/fill controls (color swatches, width buttons, and the Fill checkbox) and apply the same pattern:

- Color swatch `onClick`: `onClick={() => { if (!updateSelectedElementStyle({ color: c })) setShapeColor(c); }}`, active-class condition: `(selectedElementForStyle?.type === "shape" ? selectedElementForStyle.color === c : c === shapeColor)`.
- Width button `onClick`: `onClick={() => { if (!updateSelectedElementStyle({ width: STROKE_WIDTHS[w] })) setShapeWidth(w); }}`, active-class condition: `(selectedElementForStyle?.type === "shape" ? selectedElementForStyle.width === STROKE_WIDTHS[w] : w === shapeWidth)`.
- Fill checkbox: find `<input type="checkbox" checked={shapeFilled} onChange={(e) => setShapeFilled(e.target.checked)} />` and change to:

```jsx
              <input
                type="checkbox"
                checked={selectedElementForStyle?.type === "shape" ? selectedElementForStyle.filled : shapeFilled}
                onChange={(e) => {
                  if (!updateSelectedElementStyle({ filled: e.target.checked })) setShapeFilled(e.target.checked);
                }}
              />
```

Do NOT change the shape TYPE buttons (rectangle/ellipse/line/arrow) — changing an already-placed shape's fundamental type is out of scope; those buttons keep setting `shapeType` only, for the next NEW shape.

- [ ] **Step 4: Wire Highlight's color control**

Find Highlight mode's color swatches and apply the same pattern: `onClick={() => { if (!updateSelectedElementStyle({ color: c })) setHighlightColor(c); }}`, active-class condition: `(selectedElementForStyle?.type === "highlight" ? selectedElementForStyle.color === c : c === highlightColor)`.

- [ ] **Step 5: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Manual browser check**

- Draw a stroke, select it (per Task 1), click a different color swatch in the Draw style bar — the SELECTED stroke changes color live; the swatch shows as active for that stroke's actual current color.
- Deselect (click empty canvas or Escape), click a different color — now a NEW stroke drawn afterward uses that color, the previously-selected stroke is unaffected.
- Repeat for Shapes' color/width/fill and Highlight's color.
- Undo/redo works for a restyle.

- [ ] **Step 7: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx
git commit -m "feat: let selecting an element restyle it live via the existing style-bar controls"
```

No `Co-Authored-By` trailer.

---

## Task 3: Z-order — bring to front / send to back / forward / backward

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `elements`, `selectedId`, `commitElements` (existing).
- Produces: `reorderSelected(direction)` where `direction` is `"front" | "back" | "forward" | "backward"`; four new toolbar buttons.

No backend change — `edit_pdf` already applies `other_elements` in the order they appear in the `elements` array (verified: its apply loop is `for el in other_elements: ...`, filtered from `elements` preserving original order). The only reason z-order doesn't currently work is that the FRONTEND renders elements grouped by type into separate SVG/div blocks (all strokes together, then all shapes, etc.) instead of one interleaved list — so an element's actual array position has no visible effect on what's drawn on top of what. This task restructures rendering to fix that, and adds the reorder buttons.

- [ ] **Step 1: Add the reorder function**

Add near `updateSelectedElementStyle`:

```jsx
  function reorderSelected(direction) {
    if (!selectedId) return;
    const index = elements.findIndex((e) => e.id === selectedId);
    if (index === -1) return;
    const next = [...elements];
    const [el] = next.splice(index, 1);
    if (direction === "front") {
      next.push(el);
    } else if (direction === "back") {
      next.unshift(el);
    } else if (direction === "forward") {
      next.splice(Math.min(index + 1, next.length), 0, el);
    } else if (direction === "backward") {
      next.splice(Math.max(index - 1, 0), 0, el);
    }
    commitElements(next);
  }
```

- [ ] **Step 2: Restructure `renderPageOverlay` into one interleaved list**

This is the core change. Replace the ENTIRE body of `renderPageOverlay` (from the opening `<div className="edit-pdf-canvas__stage" ...>` through its matching closing `</div>`, i.e. everything currently inside it — the strokes SVG block, stroke remove buttons, shapes SVG block, shape remove buttons, highlight blocks, image blocks, new_text blocks, textDraft editor, and the Edit Text runs block) with a version that renders elements as ONE list, in `elements` array order, each dispatched to its own render function by type. Read the CURRENT state of `renderPageOverlay` fresh (Task 1 already modified the stroke/shape/highlight blocks — build on top of THAT code, not the pre-Task-1 version) and restructure it as follows — the exact JSX for each element type's rendering stays the same as what Task 1 left it as, just reorganized into per-type render FUNCTIONS called from one ordered `.map()`, instead of separate `elements.filter(...).map(...)` blocks per type:

```jsx
  function renderElement(el, pageNumber, pageRef) {
    if (el.type === "stroke") return renderStroke(el, pageRef);
    if (el.type === "shape") return renderShape(el, pageRef);
    if (el.type === "highlight") return renderHighlight(el, pageRef);
    if (el.type === "image") return renderImageElement(el, pageRef);
    if (el.type === "new_text") return renderNewTextElement(el, pageRef);
    return null;
  }
```

Move each element type's existing JSX (as left by Task 1) into its own function taking `(el, pageRef)` and returning that one element's markup (drop the `.filter().map()` wrapper — the caller now iterates once over the whole page's elements). For strokes and shapes, since they were rendered via a shared `<svg>` for the "committed" strokes/shapes plus a SEPARATE `<svg>` for in-progress drag previews, split each into: (a) `renderStroke(el, pageRef)` returning ONE `<svg>` containing just that stroke's `<polyline>` plus its hit-overlay and remove button, wrapped together so it moves in z-order as one unit; (b) same for `renderShape`. This means each stroke/shape now gets its OWN small `<svg>` element (viewBox `"0 0 100 100"`, sized via CSS to fill its parent exactly like the shared ones did) instead of sharing one page-wide `<svg>` — necessary so each one can independently take its place in the interleaved z-order list. Give each such per-element `<svg>` the same `edit-pdf-canvas__strokes`/`edit-pdf-canvas__shapes` class plus `style={{ position: "absolute", inset: 0 }}` so it still overlays the whole page area for coordinate purposes while the actual drawn content is still that one element.

The in-progress drag previews (`activeStroke`, `shapeDragStart`/`shapeDragCurrent`, `highlightDragStart`/`highlightDragCurrent`) are NOT elements yet (no `id`, not in the `elements` array) — render them separately, OUTSIDE the interleaved list, always on top (after it), exactly as before.

The final `renderPageOverlay` body:

```jsx
  function renderPageOverlay(pageNumber, pageRef) {
    return (
      <div
        className="edit-pdf-canvas__stage"
        onMouseDown={(e) => handleStageMouseDown(pageNumber, pageRef, e)}
        onMouseMove={(e) => handleStageMouseMove(pageRef, e)}
        onMouseUp={handleStageMouseUp}
        onMouseLeave={handleStageMouseUp}
        onClick={handleStageClick}
      >
        {elements
          .filter((el) => el.page === pageNumber && el.type !== "text_edit" && el.id !== textDraft?.id)
          .map((el) => (
            <div key={el.id} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              <div style={{ pointerEvents: "auto" }}>{renderElement(el, pageNumber, pageRef)}</div>
            </div>
          ))}

        {activeStroke && activeStroke.page === pageNumber && (
          <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
            <polyline
              points={activeStroke.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={drawColor}
              strokeWidth={STROKE_WIDTHS[drawWidth] / 3}
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}
        {shapeDragPage === pageNumber && shapeDragStart && shapeDragCurrent && (
          <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
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
          </svg>
        )}
        {highlightDragPage === pageNumber && highlightDragStart && highlightDragCurrent && (
          <div
            className="edit-pdf-canvas__highlight edit-pdf-canvas__highlight--dragging"
            style={{
              left: `${Math.min(highlightDragStart.x, highlightDragCurrent.x) * 100}%`,
              top: `${Math.min(highlightDragStart.y, highlightDragCurrent.y) * 100}%`,
              width: `${Math.abs(highlightDragCurrent.x - highlightDragStart.x) * 100}%`,
              height: `${Math.abs(highlightDragCurrent.y - highlightDragStart.y) * 100}%`,
              background: `${highlightColor}${HIGHLIGHT_ALPHA_HEX}`,
            }}
          />
        )}

        {textDraft && textDraft.page === pageNumber && (
          /* unchanged — the exact textDraft editor JSX Task-4-of-PageScrollViewer already produced, moved here verbatim */
          <>{renderTextDraftEditor(pageRef)}</>
        )}

        {activeMode === "text" &&
          runs.filter((r) => r.page === pageNumber).map((run) => renderTextRun(run, pageNumber))}
      </div>
    );
  }
```

Extract the existing `textDraft` editor JSX into its own `renderTextDraftEditor(pageRef)` function (same content, unchanged, just wrapped in a named function instead of being inlined) and the Edit Text run overlay JSX into `renderTextRun(run, pageNumber)` (same content, unchanged). This is purely mechanical extraction — no behavior changes for either.

**Note on `pointerEvents`:** the outer `position:absolute; inset:0; pointerEvents:"none"` wrapper per element exists so that EMPTY areas of one element's full-page-sized wrapper don't block clicks intended for an element rendered UNDER it in z-order (e.g. a later, higher-z-order stroke's transparent SVG background shouldn't swallow clicks meant for a highlight underneath it) — only the actual rendered content (`pointerEvents: "auto"` on the inner div) is interactive. This preserves today's "click lands on whatever's visually on top" expectation without breaking clicks reaching lower elements through empty space.

- [ ] **Step 3: Add the four toolbar buttons**

Add near the Undo/Redo history bar (`edit-pdf-canvas__history-bar`), only enabled when something is selected:

```jsx
      <div className="edit-pdf-canvas__zorder-bar">
        <button type="button" onClick={() => reorderSelected("back")} disabled={!selectedId}>
          Send to back
        </button>
        <button type="button" onClick={() => reorderSelected("backward")} disabled={!selectedId}>
          Backward
        </button>
        <button type="button" onClick={() => reorderSelected("forward")} disabled={!selectedId}>
          Forward
        </button>
        <button type="button" onClick={() => reorderSelected("front")} disabled={!selectedId}>
          Bring to front
        </button>
      </div>
```

- [ ] **Step 4: Add CSS**

```css
.edit-pdf-canvas__zorder-bar {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.edit-pdf-canvas__zorder-bar button {
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
  font-size: 12px;
}

.edit-pdf-canvas__zorder-bar button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
```

- [ ] **Step 5: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Manual browser check**

- Every existing interaction from Task 1/2 (select, move, resize, restyle, remove, copy/paste, undo/redo) still works correctly after this rendering restructure — re-verify at least one check per element type.
- Draw two overlapping shapes; select the BACK one; click "Bring to front" — it now renders on top, visibly covering the other.
- Select the front one; click "Send to back" — it goes behind again.
- "Forward"/"Backward" move an element exactly one position past its immediate neighbor.
- Run the tool with overlapping elements in a specific order; confirm the DOWNLOADED output's paint order matches what the editor showed (e.g. a highlight placed AFTER a shape, then moved BEHIND it via "Send to back", should show the shape drawn on top in the output).

- [ ] **Step 7: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add bring-to-front, send-to-back, forward, and backward z-order controls"
```

No `Co-Authored-By` trailer.

---

## Task 4: Insert Image fixes — visible preview, correct proportions, independent resize

**Files:**
- Modify: `app/core/pdf_ops.py:715-734` (`_apply_image`)
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`
- Modify: `web/frontend/src/index.css`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `_apply_image` now calls `insert_image(..., keep_proportion=False)`.
- No change to the `image` element's shape (`{id, type, page, file_id, x, y, width, height}`) or `ImageElement`/the route.

Three bugs, bundled since they're all "Insert Image is broken":
1. The image element's box never rendered the actual picture — just an empty dashed placeholder.
2. The default-size computation assumed a square page, distorting proportions on any real (non-square) page.
3. Resize was always proportional (aspect-locked); the backend's `insert_image()` default (`keep_proportion=True`) then auto-fit the TRUE-proportioned image within whatever box it was given, which could silently disagree with an already-distorted box from bug #2.

- [ ] **Step 1: Write the failing backend test**

Add to `tests/test_pdf_ops.py`, near `test_edit_pdf_image_inserts_into_page`:

```python
def test_edit_pdf_image_stretches_to_exact_non_proportional_box(tmp_path):
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 50), False)  # 2:1 image
    img_pix.set_rect(img_pix.irect, (0, 0, 255))
    img_path = tmp_path / "wide.png"
    img_pix.save(str(img_path))

    output_path = tmp_path / "output.pdf"
    # A tall box (not matching the image's own 2:1 proportions) — with
    # keep_proportion=False the image must STRETCH to fill it exactly,
    # not letterbox/center within it.
    edit_pdf(
        str(input_path),
        str(output_path),
        [{"type": "image", "page": 1, "file_id": "stamp", "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.4}],
        {"stamp": str(img_path)},
    )

    result = fitz.open(str(output_path))
    pix = result[0].get_pixmap()
    result.close()
    # Box: x[59.5,178.5] y[84.2,420.8] (595*0.1..0.3, 842*0.1..0.5). Sample
    # near the TOP and BOTTOM of that box — both must be blue if the image
    # genuinely stretched to fill the full height, not just letterboxed
    # around its own 2:1 proportions near the vertical center.
    top = pix.pixel(119, 90)[:3]
    bottom = pix.pixel(119, 415)[:3]
    assert top[2] > 150 and top[0] < 100 and top[1] < 100  # blue
    assert bottom[2] > 150 and bottom[0] < 100 and bottom[1] < 100  # blue
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k image_stretches -v`
Expected: FAIL — with the current `keep_proportion=True` default, the 2:1 image only fills a 2:1-proportioned sub-region of the tall box, centered vertically; the sampled top/bottom points (near the box's own edges, well outside where a letterboxed 2:1 image would actually land) are white/blank, not blue.

- [ ] **Step 3: Pass `keep_proportion=False` in `_apply_image`**

In `app/core/pdf_ops.py`, change:

```python
        page.insert_image(raw, filename=image_path, rotate=page.rotation % 360)
```

to:

```python
        # keep_proportion defaults to True, which auto-fits the image's TRUE
        # proportions within whatever rect it's given (silently overriding a
        # non-proportional resize the user made deliberately via an edge
        # handle). False makes the export always match exactly what the
        # editor's box showed — the frontend is responsible for starting the
        # box correctly proportioned (Step 6/7 below) and the user opts into
        # distortion explicitly via the width-only/height-only handles.
        page.insert_image(raw, filename=image_path, rotate=page.rotation % 360, keep_proportion=False)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k image -v`
Expected: all image tests pass, including the new one and the pre-existing `test_edit_pdf_image_inserts_into_page`/`test_edit_pdf_markup_elements_handle_rotated_page` (both use proportional boxes already, so `keep_proportion=False` doesn't change their result — a square/matching-ratio box stretches to the same result as a proportional fit).

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (184 before this task; expect 185 after).

- [ ] **Step 6: Add a visible `<img>` and correct the default-size math**

In `web/frontend/src/components/EditPdfCanvas.jsx`, add the import:

```jsx
import { downloadUrl, fetchTextRuns, uploadFile } from "../api";
```

(replacing the current `import { fetchTextRuns, uploadFile } from "../api";`).

Change `handleImageStageClick` and `handleImageFileSelected` to capture and use the clicked page's own actual pixel aspect ratio:

```jsx
  function handleImageStageClick(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    const rect = pageRef.current?.getBoundingClientRect();
    const pageAspect = rect && rect.width ? rect.height / rect.width : 1; // fallback: assume square if unmeasurable
    pendingImageDropRef.current = { page: pageNumber, point, pageAspect };
    imageFileInputRef.current?.click();
  }
```

```jsx
  async function handleImageFileSelected(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const drop = pendingImageDropRef.current ?? { page: 1, point: { x: 0.375, y: 0.375 }, pageAspect: 1 };
    const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSize(file)]);
    const width = 0.25;
    // The image's own pixel aspect ratio, converted into a HEIGHT FRACTION
    // OF THE PAGE, must account for the page's own (non-square) aspect
    // ratio — dividing by pageAspect (the rendered page container's actual
    // height/width ratio) converts "fraction of page width" into "fraction
    // of page height" correctly, instead of assuming they're the same unit.
    const height = Math.min(0.9, (width * (naturalSize.height / naturalSize.width)) / drop.pageAspect);
    const x = Math.min(Math.max(drop.point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(drop.point.y - height / 2, 0), 1 - height);
    commitElements([...elements, { id: newElementId(), type: "image", page: drop.page, file_id: uploaded.id, x, y, width, height }]);
  }
```

- [ ] **Step 7: Render the actual image inside the box**

Find the image element's rendering (as left by Task 1/3's restructuring — likely now inside a `renderImageElement(el, pageRef)` function). Add an `<img>` as the box's first child, right after the opening `<div ...>` that has `className={... "edit-pdf-canvas__image-el" ...}`:

```jsx
              <img src={downloadUrl(el.file_id)} alt="" className="edit-pdf-canvas__image-el-preview" draggable={false} />
```

- [ ] **Step 8: Add the two new resize handles**

Find the image element's existing resize handle:

```jsx
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: true })} />
```

and add two more right after it:

```jsx
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: true })} />
              <div
                className="edit-pdf-canvas__image-el-handle edit-pdf-canvas__image-el-handle--width"
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize-width", e)}
              />
              <div
                className="edit-pdf-canvas__image-el-handle edit-pdf-canvas__image-el-handle--height"
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize-height", e)}
              />
```

- [ ] **Step 9: Add CSS**

```css
.edit-pdf-canvas__image-el-preview {
  width: 100%;
  height: 100%;
  object-fit: fill;
  display: block;
  pointer-events: none;
}

.edit-pdf-canvas__image-el-handle--width {
  right: -6px;
  bottom: 50%;
  transform: translateY(50%);
  cursor: ew-resize;
}

.edit-pdf-canvas__image-el-handle--height {
  right: 50%;
  bottom: -6px;
  transform: translateX(50%);
  cursor: ns-resize;
}
```

(`object-fit: fill` on the preview `<img>` matches the backend's `keep_proportion=False` — the preview stretches to exactly fill the box, the same way the export does, so what you see is what you get.)

- [ ] **Step 10: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 11: Manual browser check**

- Insert Image now shows the actual picture immediately on placement, not a blank box.
- The initial placed box's proportions visually match the source image (not stretched/squashed) — try both a landscape and a portrait source image.
- Drag the CORNER handle — resizes proportionally (image stays undistorted).
- Drag the RIGHT-EDGE handle — width changes, height doesn't (image stretches horizontally).
- Drag the BOTTOM-EDGE handle — height changes, width doesn't (image stretches vertically).
- Run the tool; confirm the downloaded output's image matches exactly what the editor's box showed, for both a proportionally-resized and an independently-stretched image.

- [ ] **Step 12: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: show a live image preview, fix its default proportions, and add independent resize handles"
```

No `Co-Authored-By` trailer.

---

## Task 5: Add Text minimum-size validation

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx`

**Interfaces:**
- Consumes: nothing new from the backend — this is a frontend-only guard mirroring `_wrap_text_lines`'s existing logic in JS, so the check happens before the user even attempts to shrink below what the text needs (no new backend validation, since `_apply_new_text` already just stops drawing past the box — this task's job is purely UX: don't let the box get smaller than useful in the first place).

- [ ] **Step 1: Add a JS word-wrap measurement matching `_wrap_text_lines`**

There's no way to call PyMuPDF's `fitz.get_text_length` from the browser, so this needs a JS approximation. Add near `newTextFontFamilyCss`:

```jsx
// Rough width-per-character estimate for the three base-14 families this
// tool supports, used only to enforce a REASONABLE minimum box size client-
// side — the backend's own _wrap_text_lines (using the real font metrics)
// is still what actually determines final layout at Run time. This doesn't
// need to be exact, just conservative enough that the box the user is
// allowed to shrink to always fits what they typed.
const AVG_CHAR_WIDTH_FACTOR = { helvetica: 0.55, times: 0.5, courier: 0.6 };

function estimateMinTextBoxSize(text, family, size) {
  const charWidth = size * (AVG_CHAR_WIDTH_FACTOR[family] ?? 0.55);
  const lines = text.split("\n").flatMap((paragraph) => {
    const words = paragraph.split(" ");
    // Longest single word sets the minimum WIDTH (a box narrower than its
    // longest word can't usefully wrap at all); count of words roughly
    // approximates how many lines a very narrow box would need.
    return words;
  });
  const longestWordChars = Math.max(1, ...lines.map((w) => w.length));
  const minWidthPx = longestWordChars * charWidth;
  const lineHeight = size * 1.2;
  const paragraphCount = text.split("\n").length;
  const minHeightPx = Math.max(lineHeight, paragraphCount * lineHeight);
  return { minWidthPx, minHeightPx };
}
```

- [ ] **Step 2: Enforce the minimum in the resize drag for `new_text` elements**

In `handleElementDragMove`'s `resize-width`/`resize-height`/`lockAspect`-false branches, the box can currently shrink to a fixed floor (`0.05`/`0.03`, in page-fraction units) regardless of element type. For `new_text` specifically, floor it at whatever the text actually needs instead. Change the three relevant branches — find:

```jsx
    } else if (drag.mode === "resize-width") {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      updated = { ...startElement, width };
    } else if (drag.mode === "resize-height") {
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, height };
```

(these are the two Task 1 added — Add Text elements don't currently use `resize-width`/`resize-height`, only plain `resize` with `lockAspect: false`, so the relevant branch to change is actually the final `else` — find it:)

```jsx
    } else {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, width, height };
    }
```

and change to:

```jsx
    } else {
      let minWidth = 0.05;
      let minHeight = 0.03;
      if (startElement.type === "new_text") {
        // Convert the estimated pixel minimums into page fractions using
        // this drag's own page container size, so the floor is genuinely
        // "big enough for this text" regardless of the page's own physical
        // dimensions.
        const rect = drag.pageRef.current?.getBoundingClientRect();
        if (rect && rect.width && rect.height) {
          const { minWidthPx, minHeightPx } = estimateMinTextBoxSize(startElement.text, startElement.family, startElement.size);
          minWidth = Math.max(0.05, minWidthPx / rect.width);
          minHeight = Math.max(0.03, minHeightPx / rect.height);
        }
      }
      const width = Math.min(Math.max(minWidth, startElement.width + dx), 1 - startElement.x);
      const height = Math.min(Math.max(minHeight, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, width, height };
    }
```

- [ ] **Step 3: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 4: Manual browser check**

- Place an Add Text box with a longer sentence, at a reasonably large font size (e.g. 30pt).
- Try to drag its resize handle down to a tiny size — it should stop shrinking once it reaches roughly the space the text needs, not go arbitrarily small.
- Confirm this doesn't affect OTHER element types (an image or shape can still shrink to the existing small floor).
- Run the tool with a text box at its enforced minimum size; confirm the output still renders the text without excessive truncation (some overflow at the very floor is acceptable — this is a "reasonable minimum," not a byte-for-byte layout guarantee, matching `_apply_new_text`'s own approximate wrap logic).

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx
git commit -m "feat: prevent Add Text boxes from shrinking below what their text needs"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (185).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (5 total), in order, on top of `main`'s current tip, none carrying a `Co-Authored-By` trailer (all are `feat:`).
- [ ] Confirm every element type (stroke/shape/highlight/image/new_text) is consistently select/move-able, and every type except stroke is also resize-able, per the Global Constraints.
