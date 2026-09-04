# Page-Scroll Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the duplicated single-page-plus-Previous/Next pattern in four existing tools (Redact, Sign, PDF Forms, Edit PDF) and add a new Recent Files preview, all built on one shared `PageScrollViewer` component: continuous vertical scroll, scroll-tracked "Page X of Y" with a directly-editable jump-to-page, a wider/sharper dedicated container, and (for the four interactive tools) an interaction model where "which page" comes from where you click or drag, not a pre-selected page.

**Architecture:** One new component, `PageScrollViewer.jsx`, renders every page of a document stacked vertically and calls a `renderPageOverlay(pageNumber, pageRef)` render prop once per mounted page for interactive consumers (omitted entirely for the read-only Recent Files case). All pages mount eagerly and stay mounted for the component's lifetime — no virtualization — which is what makes per-page `ref`s stable for the whole gesture lifecycle of a drag, even for handlers that continue via `window` listeners after the drag starts.

**Tech Stack:** React (no new dependencies) — `IntersectionObserver` for scroll-tracking.

## Global Constraints

- All pages render eagerly; no virtualization in this pass (explicit spec scope boundary).
- The wider container (`~1400px`) and bumped thumbnail resolution (`max_size=1400`, up from `700`) apply only to `PageScrollViewer` consumers — the app-wide `.app__main` cap (`1080px`) and every other page are untouched.
- "Page X of Y": `X` auto-tracks scroll position via `IntersectionObserver` and is directly editable (type a number, Enter scrolls there).
- **Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go ONLY on commits whose subject starts with `fix:`/`fix(scope):`.** Every task's initial implementation commit in this plan is a `feat:` commit and must NOT carry that trailer. Standing project policy — state this explicitly in every task dispatch.

---

## Task 1: `PageScrollViewer` component + migrate Redact (proves the design end-to-end)

**Files:**
- Create: `web/frontend/src/components/PageScrollViewer.jsx`
- Modify: `web/frontend/src/components/RedactSelector.jsx` (full rewrite of its nav/stage section)
- Modify: `web/frontend/src/index.css` (new `.page-scroll-viewer*` rules; `.redact-selector__canvas`/`.redact-selector__nav` rules become unused and are removed)

**Interfaces:**
- Produces: `PageScrollViewer({ fileId, pageCount, maxSize = 1400, renderPageOverlay, className })` — `renderPageOverlay`, if given, is called as `renderPageOverlay(pageNumber, pageRef)` once per mounted page and its return value is rendered absolutely-positioned over that page's image; `pageRef` is a stable ref object (`{ current: HTMLElement | null }`) pointing at that page's own container, for computing click/drag fractions relative to that specific page. Omit `renderPageOverlay` for a read-only viewer.
- Consumes (Redact migration): nothing new — `RedactSelector`'s existing `redactions` state/shape and `onChange` contract are unchanged; only how pages are displayed changes.

Redact is the simplest interactive consumer (one drag-a-box interaction, no in-progress state beyond the drag itself), so migrating it alongside building `PageScrollViewer` is what actually proves the render-prop API works, not just compiles.

- [ ] **Step 1: Create `PageScrollViewer.jsx`**

```jsx
import { useEffect, useRef, useState } from "react";
import { thumbnailUrl } from "../api";

const DEFAULT_MAX_SIZE = 1400;

export default function PageScrollViewer({ fileId, pageCount, maxSize = DEFAULT_MAX_SIZE, renderPageOverlay, className = "" }) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const pageRefsRef = useRef([]); // stable per-page ref objects, index 0 = page 1
  const containerRefsRef = useRef([]); // the page wrapper DOM nodes, for IntersectionObserver
  const visibilityRef = useRef(new Map()); // pageNumber -> intersection ratio

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  useEffect(() => {
    if (!pageCount) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const pageNumber = Number(entry.target.dataset.pageNumber);
          visibilityRef.current.set(pageNumber, entry.isIntersecting ? entry.intersectionRatio : 0);
        }
        let bestPage = null;
        let bestRatio = 0;
        for (const [pageNumber, ratio] of visibilityRef.current) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestPage = pageNumber;
          }
        }
        if (bestPage) setCurrentPage(bestPage);
      },
      { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] }
    );
    containerRefsRef.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [fileId, pageCount]);

  if (!fileId || !pageCount) return null;

  function jumpToPage(n) {
    const clamped = Math.min(Math.max(1, n), pageCount);
    const el = containerRefsRef.current[clamped - 1];
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setCurrentPage(clamped);
  }

  function handlePageInputKeyDown(e) {
    if (e.key !== "Enter") return;
    const n = parseInt(pageInput, 10);
    if (!Number.isNaN(n)) jumpToPage(n);
    else setPageInput(String(currentPage));
  }

  const pages = Array.from({ length: pageCount }, (_, i) => i + 1);

  return (
    <div className={`page-scroll-viewer ${className}`}>
      <div className="page-scroll-viewer__header">
        Page{" "}
        <input
          type="text"
          inputMode="numeric"
          className="page-scroll-viewer__page-input"
          value={pageInput}
          onChange={(e) => setPageInput(e.target.value)}
          onKeyDown={handlePageInputKeyDown}
          onBlur={() => setPageInput(String(currentPage))}
        />{" "}
        of {pageCount}
      </div>
      <div className="page-scroll-viewer__scroll">
        {pages.map((pageNumber) => {
          if (!pageRefsRef.current[pageNumber - 1]) pageRefsRef.current[pageNumber - 1] = { current: null };
          const pageRef = pageRefsRef.current[pageNumber - 1];
          return (
            <div
              key={pageNumber}
              ref={(el) => {
                containerRefsRef.current[pageNumber - 1] = el;
              }}
              data-page-number={pageNumber}
              className="page-scroll-viewer__page"
            >
              <div
                ref={(el) => {
                  pageRef.current = el;
                }}
                className="page-scroll-viewer__page-inner"
              >
                <img
                  className="page-scroll-viewer__image"
                  src={thumbnailUrl(fileId, pageNumber, maxSize)}
                  alt={`Page ${pageNumber} preview`}
                  draggable={false}
                />
                {renderPageOverlay && renderPageOverlay(pageNumber, pageRef)}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Add CSS**

In `web/frontend/src/index.css`, insert this block right after the `/* ---------- Update banner ---------- */` section's closing rule (or any top-level location — it doesn't depend on ordering relative to other rules):

```css
/* ---------- Page scroll viewer ---------- */

.page-scroll-viewer {
  max-width: 1400px;
  width: 100%;
  margin: 0 auto;
}

.page-scroll-viewer__header {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
  font-size: 14px;
  color: var(--color-muted-foreground);
}

.page-scroll-viewer__page-input {
  width: 48px;
  text-align: center;
  padding: 2px 4px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  font-size: 14px;
}

.page-scroll-viewer__scroll {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-5);
  max-height: 80vh;
  overflow-y: auto;
  padding: var(--space-2);
}

.page-scroll-viewer__page {
  width: 100%;
  display: flex;
  justify-content: center;
}

.page-scroll-viewer__page-inner {
  position: relative;
  display: inline-block;
  max-width: 100%;
}

.page-scroll-viewer__image {
  display: block;
  max-width: 100%;
  border-radius: var(--radius-sm);
  pointer-events: none;
}
```

- [ ] **Step 3: Rewrite `RedactSelector.jsx` to use `PageScrollViewer`**

Replace the entire file with:

```jsx
import { X } from "@phosphor-icons/react";
import { useState } from "react";
import PageScrollViewer from "./PageScrollViewer";

const MIN_DRAG_FRACTION = 0.02;

export default function RedactSelector({ fileId, pageCount, onChange }) {
  const [redactions, setRedactions] = useState([]);
  const [dragStart, setDragStart] = useState(null);
  const [dragCurrent, setDragCurrent] = useState(null);
  const [dragPage, setDragPage] = useState(null);

  function pointFromEvent(pageRef, e) {
    const rect = pageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setDragPage(pageNumber);
    setDragStart(point);
    setDragCurrent(point);
  }

  function handleMouseMove(pageRef, e) {
    if (!dragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setDragCurrent(point);
  }

  function handleMouseUp() {
    if (!dragStart || !dragCurrent) return;
    const x0 = Math.min(dragStart.x, dragCurrent.x);
    const x1 = Math.max(dragStart.x, dragCurrent.x);
    const y0 = Math.min(dragStart.y, dragCurrent.y);
    const y1 = Math.max(dragStart.y, dragCurrent.y);
    const page = dragPage;
    setDragStart(null);
    setDragCurrent(null);
    setDragPage(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) {
      return; // too small to be a deliberate drag
    }
    const next = [...redactions, { page, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1 }];
    setRedactions(next);
    onChange(next);
  }

  function removeBox(index) {
    const next = redactions.filter((_, i) => i !== index);
    setRedactions(next);
    onChange(next);
  }

  if (!fileId || !pageCount) return null;

  function renderPageOverlay(pageNumber, pageRef) {
    const pageBoxes = redactions.map((r, index) => ({ ...r, index })).filter((r) => r.page === pageNumber);
    const activeDragBox =
      dragPage === pageNumber && dragStart && dragCurrent
        ? {
            x0: Math.min(dragStart.x, dragCurrent.x),
            y0: Math.min(dragStart.y, dragCurrent.y),
            x1: Math.max(dragStart.x, dragCurrent.x),
            y1: Math.max(dragStart.y, dragCurrent.y),
          }
        : null;
    return (
      <div
        className="redact-selector__canvas"
        onMouseDown={(e) => handleMouseDown(pageNumber, pageRef, e)}
        onMouseMove={(e) => handleMouseMove(pageRef, e)}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
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
    );
  }

  return <PageScrollViewer fileId={fileId} pageCount={pageCount} renderPageOverlay={renderPageOverlay} className="redact-selector" />;
}
```

Note: `.redact-selector__canvas` needs `position: absolute; inset: 0;` now (it used to size itself via its own `<img>` sibling — that image is gone, `PageScrollViewer` owns it now, and this overlay just fills the same `.page-scroll-viewer__page-inner` box). Update its CSS rule — find:

```css
.redact-selector__canvas {
  position: relative;
  display: inline-block;
  max-width: 100%;
  cursor: crosshair;
  user-select: none;
}
```

and change to:

```css
.redact-selector__canvas {
  position: absolute;
  inset: 0;
  cursor: crosshair;
  user-select: none;
}
```

Delete the now-unused `.redact-selector__nav` and `.redact-selector__nav button` and `.redact-selector__nav button:disabled` rules, and delete the `.redact-selector__image` rule (that `<img>` no longer exists in this component — `PageScrollViewer` renders it).

- [ ] **Step 4: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 5: Manual browser check**

Start the backend and frontend dev servers, open Redact PDF on a multi-page PDF, and verify:
- Every page renders stacked vertically, sharp (not blurry) at the new resolution, in a visibly wider container than before.
- "Page X of Y" updates as you scroll.
- Typing a page number and pressing Enter scrolls to that page.
- Dragging a redaction box on ANY visible page (not just "the current page") works and stays attached to that specific page — scroll away and back, the box is still there, on the right page.
- Removing a box, then running the tool, produces correct output (existing Redact backend is untouched by this task).

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/components/PageScrollViewer.jsx web/frontend/src/components/RedactSelector.jsx web/frontend/src/index.css
git commit -m "feat: add PageScrollViewer and migrate Redact to it"
```

No `Co-Authored-By` trailer — this is a `feat:` commit.

---

## Task 2: Migrate `SignCanvas` to `PageScrollViewer`

**Files:**
- Modify: `web/frontend/src/components/SignCanvas.jsx`
- Modify: `web/frontend/src/index.css` (`.sign-canvas__stage`/`.sign-canvas__nav` rules removed/adjusted)

**Interfaces:**
- Consumes: `PageScrollViewer` (Task 1).
- No change to `SignCanvas`'s own props (`fileId`, `pageCount`, `onChange`) or the `placements` element shape it emits.

- [ ] **Step 1: Rewrite `SignCanvas.jsx`'s page-nav/stage section**

The signature-source panel (upload/draw/saved-signature UI, lines 1–311 of the current file) is unchanged — only the "page nav + stage + placements" section changes. Replace:

```jsx
  const stageRef = useRef(null);
```

with (removing the single shared stage ref — each page now gets its own via the render prop):

```jsx
  // (stageRef removed — PageScrollViewer gives a per-page ref to renderPageOverlay instead)
```

Replace:

```jsx
  function pointFromEvent(e) {
    const rect = stageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }
```

with:

```jsx
  function pointFromEvent(pageRef, e) {
    const rect = pageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }
```

Replace:

```jsx
  function handleStagePlace(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    const width = DEFAULT_WIDTH_FRACTION;
    const height = Math.min(MAX_HEIGHT_FRACTION, width * (signatureNaturalSize.height / signatureNaturalSize.width));
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setPlacements((prev) => [
      ...prev,
      { id: newElementId(), type: "image", page: currentPage, file_id: signatureFileId, x, y, width, height },
    ]);
  }
```

with:

```jsx
  function handleStagePlace(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    const width = DEFAULT_WIDTH_FRACTION;
    const height = Math.min(MAX_HEIGHT_FRACTION, width * (signatureNaturalSize.height / signatureNaturalSize.width));
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setPlacements((prev) => [
      ...prev,
      { id: newElementId(), type: "image", page: pageNumber, file_id: signatureFileId, x, y, width, height },
    ]);
  }
```

Replace:

```jsx
  function startDrag(placement, mode, e) {
    e.stopPropagation();
    const point = pointFromEvent(e);
    if (!point) return;
    dragRef.current = { id: placement.id, mode, start: point, startPlacement: { ...placement } };
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
    window.addEventListener("blur", handleDragEnd);
  }

  function handleDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(e);
    if (!point) return;
```

with:

```jsx
  function startDrag(pageRef, placement, mode, e) {
    e.stopPropagation();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    dragRef.current = { id: placement.id, mode, start: point, startPlacement: { ...placement }, pageRef };
    window.addEventListener("mousemove", handleDragMove);
    window.addEventListener("mouseup", handleDragEnd);
    window.addEventListener("blur", handleDragEnd);
  }

  function handleDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
    if (!point) return;
```

Replace the whole "page nav + stage" JSX block:

```jsx
          <div className="sign-canvas__nav">
            <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}>
              <CaretLeft size={14} weight="bold" />
              Previous
            </button>
            <span>
              Page {currentPage} of {pageCount} ({markedPageCount} page{markedPageCount === 1 ? "" : "s"} signed)
            </span>
            <button type="button" onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))} disabled={currentPage === pageCount}>
              Next
              <CaretRight size={14} weight="bold" />
            </button>
          </div>

          <div ref={stageRef} className="sign-canvas__stage" onMouseDown={handleStagePlace}>
            <img
              className="sign-canvas__image"
              src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
              alt={`Page ${currentPage} preview — click to place your signature`}
              draggable={false}
            />
            {placements
              .filter((p) => p.page === currentPage)
              .map((p) => (
                <div
                  key={p.id}
                  className="sign-canvas__placement"
                  style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%`, width: `${p.width * 100}%`, height: `${p.height * 100}%` }}
                  onMouseDown={(e) => startDrag(p, "move", e)}
                >
                  <img src={signaturePreviewSrc} className="sign-canvas__placement-image" alt="Placed signature" draggable={false} />
                  <div className="sign-canvas__placement-handle" onMouseDown={(e) => startDrag(p, "resize", e)} />
                  <button
                    type="button"
                    className="sign-canvas__placement-remove"
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={() => removePlacement(p.id)}
                    aria-label="Remove this signature"
                  >
                    <X size={12} weight="bold" />
                  </button>
                </div>
              ))}
          </div>
```

with:

```jsx
          <PageScrollViewer
            fileId={fileId}
            pageCount={pageCount}
            className="sign-canvas__viewer"
            renderPageOverlay={(pageNumber, pageRef) => (
              <div
                className="sign-canvas__stage"
                onMouseDown={(e) => handleStagePlace(pageNumber, pageRef, e)}
              >
                {placements
                  .filter((p) => p.page === pageNumber)
                  .map((p) => (
                    <div
                      key={p.id}
                      className="sign-canvas__placement"
                      style={{ left: `${p.x * 100}%`, top: `${p.y * 100}%`, width: `${p.width * 100}%`, height: `${p.height * 100}%` }}
                      onMouseDown={(e) => startDrag(pageRef, p, "move", e)}
                    >
                      <img src={signaturePreviewSrc} className="sign-canvas__placement-image" alt="Placed signature" draggable={false} />
                      <div className="sign-canvas__placement-handle" onMouseDown={(e) => startDrag(pageRef, p, "resize", e)} />
                      <button
                        type="button"
                        className="sign-canvas__placement-remove"
                        onMouseDown={(e) => e.stopPropagation()}
                        onClick={() => removePlacement(p.id)}
                        aria-label="Remove this signature"
                      >
                        <X size={12} weight="bold" />
                      </button>
                    </div>
                  ))}
              </div>
            )}
          />
```

Remove the now-unused "Page X of Y ... signed" label's `markedPageCount` computation is still used elsewhere? Check: it's only referenced in the JSX just replaced — remove the `const markedPageCount = new Set(placements.map((p) => p.page)).size;` line too, since `PageScrollViewer`'s own header no longer shows a per-tool "K pages signed" count (matches Task 1's `PageScrollViewer` design, which only shows "Page X of Y" — this per-tool marked-count label is dropped, consistent with Redact's migration in Task 1 also dropping its "K pages marked" text).

Add the import: change

```jsx
import { thumbnailUrl, uploadFile } from "../api";
```

to

```jsx
import { uploadFile } from "../api";
import PageScrollViewer from "./PageScrollViewer";
```

(`thumbnailUrl` is no longer used directly in this file — `PageScrollViewer` calls it internally.)

- [ ] **Step 2: Update CSS**

`.sign-canvas__stage` needs to become an absolutely-positioned overlay instead of the image-containing stage it was. Find:

```css
.sign-canvas__stage {
```

and view the existing rule (read the file to see its current declarations), then change its `position`/sizing declarations so it's `position: absolute; inset: 0;` instead of whatever made it the `<img>`-containing box before (it no longer contains an `<img>` — `PageScrollViewer` does). Remove any rule that specifically styled `.sign-canvas__image` (that class no longer exists in this component). Delete `.sign-canvas__nav` and its child rules (no longer used, same reasoning as Task 1's Redact nav removal).

- [ ] **Step 3: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 4: Manual browser check**

Start the backend and frontend dev servers, open Sign PDF, place a signature, and verify:
- Every page renders stacked, sharp, in the wider container.
- Placing a signature on any visible page works and stays attached to that page.
- Dragging to move/resize a placed signature works correctly (verify the drag stays relative to the CORRECT page even if you drag near a page boundary).
- "Page X of Y" scroll-tracking and jump-to-page work.
- Running the tool produces correct output.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/SignCanvas.jsx web/frontend/src/index.css
git commit -m "feat: migrate SignCanvas to PageScrollViewer"
```

No `Co-Authored-By` trailer.

---

## Task 3: Migrate `FormFillCanvas` to `PageScrollViewer`

**Files:**
- Modify: `web/frontend/src/components/FormFillCanvas.jsx`
- Modify: `web/frontend/src/index.css` (`.form-fill-canvas__stage`/`.form-fill-canvas__nav` rules removed/adjusted)

**Interfaces:**
- Consumes: `PageScrollViewer` (Task 1).
- No change to `FormFillCanvas`'s props or the `{page, index, value}` change-tracking contract it emits.

This is the simplest of the four interactive migrations — there's no "in-progress placement" concept at all, just per-page filtered controls.

- [ ] **Step 1: Rewrite the render section**

Replace:

```jsx
import { CaretLeft, CaretRight } from "@phosphor-icons/react";
import { thumbnailUrl, fetchFormFields } from "../api";

const PREVIEW_MAX_SIZE = 700;
```

with:

```jsx
import { fetchFormFields } from "../api";
import PageScrollViewer from "./PageScrollViewer";
```

Remove `const [currentPage, setCurrentPage] = useState(1);` — there's no single current page anymore.

Replace the whole return block:

```jsx
  const pageFields = fields.filter((f) => f.page === currentPage);
  const changedCount = fields.filter((f) => values[fieldKey(f)] !== initialValues[fieldKey(f)]).length;

  return (
    <div className="form-fill-canvas">
      <div className="form-fill-canvas__nav">
        <button type="button" onClick={() => setCurrentPage((p) => Math.max(1, p - 1))} disabled={currentPage === 1}>
          <CaretLeft size={14} weight="bold" />
          Previous
        </button>
        <span>
          Page {currentPage} of {pageCount} ({changedCount} field{changedCount === 1 ? "" : "s"} changed)
        </span>
        <button type="button" onClick={() => setCurrentPage((p) => Math.min(pageCount, p + 1))} disabled={currentPage === pageCount}>
          Next
          <CaretRight size={14} weight="bold" />
        </button>
      </div>

      <div className="form-fill-canvas__stage">
        <img
          className="form-fill-canvas__image"
          src={thumbnailUrl(fileId, currentPage, PREVIEW_MAX_SIZE)}
          alt={`Page ${currentPage} preview`}
          draggable={false}
        />
        {pageFields.map((field) => {
          const key = fieldKey(field);
          const style = {
            left: `${field.rect.left * 100}%`,
            top: `${field.rect.top * 100}%`,
            width: `${(1 - field.rect.left - field.rect.right) * 100}%`,
            height: `${(1 - field.rect.top - field.rect.bottom) * 100}%`,
          };
          if (field.type === "text") {
            return (
              <input
                key={key}
                type="text"
                className="form-fill-canvas__field"
                style={style}
                value={values[key] ?? ""}
                onChange={(e) => setFieldValue(field, e.target.value)}
                title={field.label}
              />
            );
          }
          if (field.type === "checkbox") {
            return (
              <input
                key={key}
                type="checkbox"
                className="form-fill-canvas__field"
                style={style}
                checked={Boolean(values[key])}
                onChange={(e) => setFieldValue(field, e.target.checked)}
                title={field.label}
              />
            );
          }
          return (
            <select
              key={key}
              className="form-fill-canvas__field"
              style={style}
              value={values[key] ?? ""}
              onChange={(e) => setFieldValue(field, e.target.value)}
              title={field.label}
            >
              <option value="" disabled>
                — Select —
              </option>
              {(field.choices ?? []).map((choice) => (
                <option key={choice} value={choice}>
                  {choice}
                </option>
              ))}
            </select>
          );
        })}
      </div>
    </div>
  );
```

with:

```jsx
  function renderField(field) {
    const key = fieldKey(field);
    const style = {
      left: `${field.rect.left * 100}%`,
      top: `${field.rect.top * 100}%`,
      width: `${(1 - field.rect.left - field.rect.right) * 100}%`,
      height: `${(1 - field.rect.top - field.rect.bottom) * 100}%`,
    };
    if (field.type === "text") {
      return (
        <input
          key={key}
          type="text"
          className="form-fill-canvas__field"
          style={style}
          value={values[key] ?? ""}
          onChange={(e) => setFieldValue(field, e.target.value)}
          title={field.label}
        />
      );
    }
    if (field.type === "checkbox") {
      return (
        <input
          key={key}
          type="checkbox"
          className="form-fill-canvas__field"
          style={style}
          checked={Boolean(values[key])}
          onChange={(e) => setFieldValue(field, e.target.checked)}
          title={field.label}
        />
      );
    }
    return (
      <select
        key={key}
        className="form-fill-canvas__field"
        style={style}
        value={values[key] ?? ""}
        onChange={(e) => setFieldValue(field, e.target.value)}
        title={field.label}
      >
        <option value="" disabled>
          — Select —
        </option>
        {(field.choices ?? []).map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }

  return (
    <div className="form-fill-canvas">
      <PageScrollViewer
        fileId={fileId}
        pageCount={pageCount}
        className="form-fill-canvas__viewer"
        renderPageOverlay={(pageNumber) => (
          <div className="form-fill-canvas__stage">
            {fields.filter((f) => f.page === pageNumber).map(renderField)}
          </div>
        )}
      />
    </div>
  );
```

(The "changed field count" label is dropped from the header, consistent with Task 1/2's migrations — `PageScrollViewer`'s own "Page X of Y" is the only header now. If you want to preserve a changed-count indicator, that's fine to add as a small separate line above `PageScrollViewer` — e.g. `<p>{changedCount} field{changedCount === 1 ? "" : "s"} changed</p>` — using the existing `changedCount` computation, just relocated above the viewer instead of inside its old nav bar.)

- [ ] **Step 2: Update CSS**

`.form-fill-canvas__stage` needs `position: absolute; inset: 0;` instead of whatever positioned it relative to its old sibling `<img>` (which no longer exists in this component). Delete `.form-fill-canvas__image`, `.form-fill-canvas__nav`, and its child rules.

- [ ] **Step 3: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 4: Manual browser check**

Open PDF Forms on a multi-page fillable form, verify:
- Every page's fields render at the right position, on the right page, scrolling correctly.
- Filling fields on any page updates the changed set correctly.
- Running the tool produces correct output.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/FormFillCanvas.jsx web/frontend/src/index.css
git commit -m "feat: migrate FormFillCanvas to PageScrollViewer"
```

No `Co-Authored-By` trailer.

---

## Task 4: Migrate `EditPdfCanvas` to `PageScrollViewer` (the complex one) + centered toolbar

**Files:**
- Modify: `web/frontend/src/components/EditPdfCanvas.jsx` (substantial rewrite — see below)
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `PageScrollViewer` (Task 1).
- No change to the `elements` array shape this component emits via `onChange` — only how pages are displayed and how in-progress interaction state is tracked changes.

This is the most complex of the five migrations: six modes, and — per the design spec — every one of them switches from "acts on a pre-selected `currentPage`" to "acts on whichever page the gesture started on." Read the CURRENT state of `EditPdfCanvas.jsx` fresh before starting (it has grown since this plan was written and Tasks 1-3 didn't touch it, but confirm nothing else has). The rewrite below is scoped to: removing `stageRef`/`currentPage`; making every "in-progress" piece of state carry its own page; parameterizing every mode-handler function to take `(pageNumber, pageRef, e)` (or a subset, depending on what it needs) instead of closing over a single page/ref; and rendering through `PageScrollViewer`'s `renderPageOverlay` instead of one shared stage.

- [ ] **Step 1: Remove `stageRef` and `currentPage`, add per-page-aware in-progress state**

Change:

```jsx
export default function EditPdfCanvas({ fileId, pageCount, onChange }) {
  const stageRef = useRef(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [activeMode, setActiveMode] = useState("text");
```

to:

```jsx
export default function EditPdfCanvas({ fileId, pageCount, onChange }) {
  const [activeMode, setActiveMode] = useState("text");
```

Change:

```jsx
  const [activeStroke, setActiveStroke] = useState(null);
  const [shapeType, setShapeType] = useState("rectangle");
  const [shapeColor, setShapeColor] = useState(MARKUP_COLORS[0]);
  const [shapeWidth, setShapeWidth] = useState("medium");
  const [shapeFilled, setShapeFilled] = useState(false);
  const [shapeDragStart, setShapeDragStart] = useState(null);
  const [shapeDragCurrent, setShapeDragCurrent] = useState(null);
  const [highlightColor, setHighlightColor] = useState("#ffd43b");
  const [highlightDragStart, setHighlightDragStart] = useState(null);
  const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
```

to:

```jsx
  const [activeStroke, setActiveStroke] = useState(null); // { page, points } | null
  const [shapeType, setShapeType] = useState("rectangle");
  const [shapeColor, setShapeColor] = useState(MARKUP_COLORS[0]);
  const [shapeWidth, setShapeWidth] = useState("medium");
  const [shapeFilled, setShapeFilled] = useState(false);
  const [shapeDragPage, setShapeDragPage] = useState(null);
  const [shapeDragStart, setShapeDragStart] = useState(null);
  const [shapeDragCurrent, setShapeDragCurrent] = useState(null);
  const [highlightColor, setHighlightColor] = useState("#ffd43b");
  const [highlightDragPage, setHighlightDragPage] = useState(null);
  const [highlightDragStart, setHighlightDragStart] = useState(null);
  const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
```

`textDraft` already becomes page-aware in Step 3 below (it gains a `page` field directly, since it's already a rich object). `pendingImageDropRef` gains a page field in Step 4.

- [ ] **Step 2: Rewrite `pointFromEvent` and every mode's mousedown/mousemove/mouseup handler**

Change:

```jsx
  function pointFromEvent(e) {
    const rect = stageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  // Stubs — replaced (body only) by later tasks. Kept here so the stage's
  // dispatcher below never needs to change as modes are filled in.
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
    // Clear FIRST, unconditionally. handleDrawMouseMove is gated only on
    // activeStroke being non-null, not on a button actually being held, so
    // leaving a 1-point stroke armed after a plain click makes a line follow
    // the cursor and commit a phantom stroke on the next mouseup/mouseleave.
    const stroke = activeStroke;
    setActiveStroke(null);
    if (!stroke || stroke.length < 2) return;
    // A point count is not a size: a click with a pixel of jitter still yields
    // two points. Measure the actual extent instead, as Highlight mode does.
    const xs = stroke.map((p) => p.x);
    const ys = stroke.map((p) => p.y);
    if (
      Math.max(...xs) - Math.min(...xs) < MIN_DRAG_FRACTION &&
      Math.max(...ys) - Math.min(...ys) < MIN_DRAG_FRACTION
    ) {
      return;
    }
    const next = [
      ...elements,
      { id: newElementId(), type: "stroke", page: currentPage, points: stroke, color: drawColor, width: STROKE_WIDTHS[drawWidth] },
    ];
    commitElements(next);
  }
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
    // Check both axes independently, as Highlight mode does. A perfectly
    // horizontal or vertical drag is not "stationary", but it still produces a
    // zero-dimension rectangle/ellipse that _validate_shape rejects at Run time
    // with an error pointing at nothing visible on screen.
    if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION || Math.abs(y1 - y0) < MIN_DRAG_FRACTION) {
      if (shapeType === "rectangle" || shapeType === "ellipse") return;
      // A line or arrow only needs two distinct points, so only a drag that is
      // degenerate on BOTH axes is unusable.
      if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION && Math.abs(y1 - y0) < MIN_DRAG_FRACTION) return;
    }
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
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) return;
    const next = [
      ...elements,
      { id: newElementId(), type: "highlight", page: currentPage, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1, color: highlightColor },
    ];
    commitElements(next);
  }
  function handleImageStageClick(e) {
    const point = pointFromEvent(e);
    if (!point) return;
    pendingImageDropRef.current = point;
    imageFileInputRef.current?.click();
  }
```

to:

```jsx
  function pointFromEvent(pageRef, e) {
    const rect = pageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleDrawMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setActiveStroke({ page: pageNumber, points: [point] });
  }

  function handleDrawMouseMove(pageRef, e) {
    if (!activeStroke) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setActiveStroke((s) => ({ ...s, points: [...s.points, point] }));
  }

  function handleDrawMouseUp() {
    // Clear FIRST, unconditionally. handleDrawMouseMove is gated only on
    // activeStroke being non-null, not on a button actually being held, so
    // leaving a 1-point stroke armed after a plain click makes a line follow
    // the cursor and commit a phantom stroke on the next mouseup/mouseleave.
    const stroke = activeStroke;
    setActiveStroke(null);
    if (!stroke || stroke.points.length < 2) return;
    // A point count is not a size: a click with a pixel of jitter still yields
    // two points. Measure the actual extent instead, as Highlight mode does.
    const xs = stroke.points.map((p) => p.x);
    const ys = stroke.points.map((p) => p.y);
    if (
      Math.max(...xs) - Math.min(...xs) < MIN_DRAG_FRACTION &&
      Math.max(...ys) - Math.min(...ys) < MIN_DRAG_FRACTION
    ) {
      return;
    }
    const next = [
      ...elements,
      { id: newElementId(), type: "stroke", page: stroke.page, points: stroke.points, color: drawColor, width: STROKE_WIDTHS[drawWidth] },
    ];
    commitElements(next);
  }
  function handleShapeMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setShapeDragPage(pageNumber);
    setShapeDragStart(point);
    setShapeDragCurrent(point);
  }

  function handleShapeMouseMove(pageRef, e) {
    if (!shapeDragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setShapeDragCurrent(point);
  }

  function handleShapeMouseUp() {
    if (!shapeDragStart || !shapeDragCurrent) return;
    const { x: x0, y: y0 } = shapeDragStart;
    const { x: x1, y: y1 } = shapeDragCurrent;
    const page = shapeDragPage;
    setShapeDragPage(null);
    setShapeDragStart(null);
    setShapeDragCurrent(null);
    // Check both axes independently, as Highlight mode does. A perfectly
    // horizontal or vertical drag is not "stationary", but it still produces a
    // zero-dimension rectangle/ellipse that _validate_shape rejects at Run time
    // with an error pointing at nothing visible on screen.
    if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION || Math.abs(y1 - y0) < MIN_DRAG_FRACTION) {
      if (shapeType === "rectangle" || shapeType === "ellipse") return;
      // A line or arrow only needs two distinct points, so only a drag that is
      // degenerate on BOTH axes is unusable.
      if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION && Math.abs(y1 - y0) < MIN_DRAG_FRACTION) return;
    }
    const next = [
      ...elements,
      {
        id: newElementId(),
        type: "shape",
        page,
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
  function handleHighlightMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setHighlightDragPage(pageNumber);
    setHighlightDragStart(point);
    setHighlightDragCurrent(point);
  }

  function handleHighlightMouseMove(pageRef, e) {
    if (!highlightDragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setHighlightDragCurrent(point);
  }

  function handleHighlightMouseUp() {
    if (!highlightDragStart || !highlightDragCurrent) return;
    const x0 = Math.min(highlightDragStart.x, highlightDragCurrent.x);
    const x1 = Math.max(highlightDragStart.x, highlightDragCurrent.x);
    const y0 = Math.min(highlightDragStart.y, highlightDragCurrent.y);
    const y1 = Math.max(highlightDragStart.y, highlightDragCurrent.y);
    const page = highlightDragPage;
    setHighlightDragPage(null);
    setHighlightDragStart(null);
    setHighlightDragCurrent(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) return;
    const next = [
      ...elements,
      { id: newElementId(), type: "highlight", page, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1, color: highlightColor },
    ];
    commitElements(next);
  }
  function handleImageStageClick(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    pendingImageDropRef.current = { page: pageNumber, point };
    imageFileInputRef.current?.click();
  }
```

- [ ] **Step 3: Update image upload, Add Text placement/edit, and the drag machinery for page-awareness**

Change:

```jsx
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

  function handleNewTextStageClick(e) {
    if (textDraft) return; // an editor is already open — closing it happens via blur, not another placement in the same click
    // The browser's own mousedown default action clears focus shortly after
    // this handler returns (since the stage div itself isn't focusable),
    // racing the effect below that focuses the new textarea and winning —
    // the textarea gets focus then loses it a fraction of a millisecond
    // later, firing the wrapper's onBlur and discarding the just-placed,
    // still-empty draft before the user can type. Suppressing the default
    // action here stops the browser from clearing focus so the effect's
    // focus() call sticks.
    e.preventDefault();
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

  function openTextDraftForEdit(el) {
    const { id, page, ...rest } = el;
    setTextDraft({ id, ...rest });
  }
```

to:

```jsx
  async function handleImageFileSelected(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const drop = pendingImageDropRef.current ?? { page: 1, point: { x: 0.375, y: 0.375 } };
    const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSize(file)]);
    const width = 0.25;
    const height = Math.min(0.9, width * (naturalSize.height / naturalSize.width));
    const x = Math.min(Math.max(drop.point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(drop.point.y - height / 2, 0), 1 - height);
    commitElements([...elements, { id: newElementId(), type: "image", page: drop.page, file_id: uploaded.id, x, y, width, height }]);
  }

  function handleNewTextStageClick(pageNumber, pageRef, e) {
    if (textDraft) return; // an editor is already open — closing it happens via blur, not another placement in the same click
    // The browser's own mousedown default action clears focus shortly after
    // this handler returns (since the stage div itself isn't focusable),
    // racing the effect below that focuses the new textarea and winning —
    // the textarea gets focus then loses it a fraction of a millisecond
    // later, firing the wrapper's onBlur and discarding the just-placed,
    // still-empty draft before the user can type. Suppressing the default
    // action here stops the browser from clearing focus so the effect's
    // focus() call sticks.
    e.preventDefault();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    const width = NEW_TEXT_DEFAULT_WIDTH;
    const height = NEW_TEXT_DEFAULT_HEIGHT;
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setTextDraft({ id: null, page: pageNumber, x, y, width, height, text: "", ...NEW_TEXT_DEFAULTS });
  }

  function commitTextDraft() {
    const draft = textDraft;
    setTextDraft(null);
    if (!draft || !draft.text.trim()) return; // empty placements are discarded, not saved
    const { id, ...rest } = draft;
    const newEl = { id: id ?? newElementId(), type: "new_text", ...rest };
    const next = id ? elements.map((el) => (el.id === id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  function openTextDraftForEdit(el) {
    const { id, ...rest } = el;
    setTextDraft({ id, ...rest });
  }
```

Change:

```jsx
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
```

to:

```jsx
  function startElementDrag(pageRef, el, mode, e, options = {}) {
    e.stopPropagation();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    dragRef.current = {
      id: el.id, mode, start: point, startElement: { ...el }, startElementsSnapshot: elements, moved: false,
      lockAspect: options.lockAspect ?? false, pageRef,
    };
    window.addEventListener("mousemove", handleElementDragMove);
    window.addEventListener("mouseup", handleElementDragEnd);
    window.addEventListener("blur", handleElementDragEnd);
  }

  function handleElementDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
    if (!point) return;
```

- [ ] **Step 4: Replace the mousedown/mousemove/mouseup dispatchers**

Change:

```jsx
  function handleStageMouseDown(e) {
    if (activeMode === "draw") return handleDrawMouseDown(e);
    if (activeMode === "shapes") return handleShapeMouseDown(e);
    if (activeMode === "highlight") return handleHighlightMouseDown(e);
    if (activeMode === "image") return handleImageStageClick(e);
    if (activeMode === "new_text") return handleNewTextStageClick(e);
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
```

to:

```jsx
  function handleStageMouseDown(pageNumber, pageRef, e) {
    if (activeMode === "draw") return handleDrawMouseDown(pageNumber, pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseDown(pageNumber, pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseDown(pageNumber, pageRef, e);
    if (activeMode === "image") return handleImageStageClick(pageNumber, pageRef, e);
    if (activeMode === "new_text") return handleNewTextStageClick(pageNumber, pageRef, e);
  }

  function handleStageMouseMove(pageRef, e) {
    if (activeMode === "draw") return handleDrawMouseMove(pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseMove(pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseMove(pageRef, e);
  }

  function handleStageMouseUp(e) {
    if (activeMode === "draw") return handleDrawMouseUp(e);
    if (activeMode === "shapes") return handleShapeMouseUp(e);
    if (activeMode === "highlight") return handleHighlightMouseUp(e);
  }
```

- [ ] **Step 5: Replace the whole render section with a `renderPageOverlay`-based one**

Change the import line from:

```jsx
import { thumbnailUrl, fetchTextRuns, uploadFile } from "../api";
```

to:

```jsx
import { fetchTextRuns, uploadFile } from "../api";
import PageScrollViewer from "./PageScrollViewer";
```

Replace the entire `return (...)` block (everything from `return (` to the final closing `);` before the function's closing `}`) with:

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
        <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none">
          {elements
            .filter((el) => el.type === "stroke" && el.page === pageNumber)
            .map((el) => (
              <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
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
          {activeStroke && activeStroke.page === pageNumber && (
            <polyline
              points={activeStroke.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={drawColor}
              strokeWidth={STROKE_WIDTHS[drawWidth] / 3}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

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

        <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ zIndex: 2 }}>
          {elements
            .filter((el) => el.type === "shape" && el.page === pageNumber)
            .map((el) => {
              const stroke = el.color;
              const fill = el.filled ? el.color : "none";
              const commonProps = {
                stroke,
                fill,
                strokeWidth: el.width / 3,
                vectorEffect: "non-scaling-stroke",
                className: el.id === selectedId ? "edit-pdf-canvas__shape edit-pdf-canvas__shape--selected" : "edit-pdf-canvas__shape",
              };
              if (el.shape === "rectangle") {
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <rect
                      {...commonProps}
                      x={Math.min(el.x0, el.x1) * 100}
                      y={Math.min(el.y0, el.y1) * 100}
                      width={Math.abs(el.x1 - el.x0) * 100}
                      height={Math.abs(el.y1 - el.y0) * 100}
                    />
                  </g>
                );
              }
              if (el.shape === "ellipse") {
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <ellipse
                      {...commonProps}
                      cx={((el.x0 + el.x1) / 2) * 100}
                      cy={((el.y0 + el.y1) / 2) * 100}
                      rx={(Math.abs(el.x1 - el.x0) / 2) * 100}
                      ry={(Math.abs(el.y1 - el.y0) / 2) * 100}
                    />
                  </g>
                );
              }
              // line and arrow both render as a line preview; the real arrowhead is
              // drawn server-side by edit_pdf — this is close enough for the queue preview.
              return (
                <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                  <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
                </g>
              );
            })}
          {shapeDragPage === pageNumber && shapeDragStart && shapeDragCurrent && (
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

        {elements
          .filter((el) => el.type === "image" && el.page === pageNumber)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__image-el edit-pdf-canvas__image-el--selected"
                  : "edit-pdf-canvas__image-el"
              }
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(pageRef, el, "move", e);
              }}
              // Selection happens on mousedown here (it starts a drag), but the
              // click that follows would still reach the stage and deselect.
              onClick={(e) => e.stopPropagation()}
            >
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: true })} />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => removeElement(el.id)}
                aria-label="Remove this image"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}

        {elements
          .filter((el) => el.type === "new_text" && el.page === pageNumber && el.id !== textDraft?.id)
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
                startElementDrag(pageRef, el, "move", e);
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
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: false })}
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

        {textDraft && textDraft.page === pageNumber && (
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

        {activeMode === "text" &&
          runs
            .filter((r) => r.page === pageNumber)
            .map((run) => {
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
                  onClick={() => openRunEditor(pageNumber, run)}
                />
              );
            })}
      </div>
    );
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

      <PageScrollViewer fileId={fileId} pageCount={pageCount} className="edit-pdf-canvas__viewer" renderPageOverlay={renderPageOverlay} />

      <input
        ref={imageFileInputRef}
        type="file"
        accept="image/png,image/jpeg"
        style={{ display: "none" }}
        onChange={handleImageFileSelected}
      />

      {activeMode === "text" && editingRunIndex !== null && (
        <div className="edit-pdf-canvas__run-editor">
          {(() => {
            const run = runs.find((r) => r.index === editingRunIndex && r.page === editingRunPage);
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
                  <select
                    value={draftOverride.family}
                    onChange={(e) => {
                      setDraftFamilyTouched(true);
                      setDraftOverride((o) => ({ ...o, family: e.target.value }));
                    }}
                  >
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

**Important note on Edit Text mode's `runs` fetching (a real, load-bearing gap this rewrite must not leave unaddressed):** the pre-migration code fetched text runs for only the single `currentPage` (`useEffect(() => { fetchTextRuns(fileId, currentPage)... }, [fileId, currentPage])`). With every page now mounted at once, Edit Text mode needs runs for EVERY page, not just one. Change the runs-loading effect — find:

```jsx
  useEffect(() => {
    if (!fileId) return;
    async function loadRuns() {
      try {
        const data = await fetchTextRuns(fileId, currentPage);
        setRuns(data.runs);
      } catch (err) {
        console.error("Failed to load text runs:", err);
        setRuns([]);
      }
    }
    loadRuns();
    setEditingRunIndex(null);
  }, [fileId, currentPage]);
```

to fetch every page's runs once, tagging each run with its own page number (the existing `fetchTextRuns(fileId, pageNumber)` API already returns per-page run indices — `run.index` is only unique WITHIN a page, so each run object needs a `page` field added so cross-page runs don't collide when flattened into one array):

```jsx
  useEffect(() => {
    if (!fileId || !pageCount) return;
    let cancelled = false;
    async function loadRuns() {
      try {
        const perPage = await Promise.all(
          Array.from({ length: pageCount }, (_, i) => i + 1).map((pageNumber) =>
            fetchTextRuns(fileId, pageNumber).then((data) => data.runs.map((r) => ({ ...r, page: pageNumber })))
          )
        );
        if (!cancelled) setRuns(perPage.flat());
      } catch (err) {
        console.error("Failed to load text runs:", err);
        if (!cancelled) setRuns([]);
      }
    }
    loadRuns();
    setEditingRunIndex(null);
    return () => {
      cancelled = true;
    };
  }, [fileId, pageCount]);
```

Then update every place that filtered/matched runs by an implicit "current page" to filter by each run's own new `page` field instead:

- `pendingTextEditFor(run)`: change `elements.find((el) => el.type === "text_edit" && el.page === currentPage && el.run_index === run.index)` to `elements.find((el) => el.type === "text_edit" && el.page === run.page && el.run_index === run.index)`.
- The runs-rendering block in `renderPageOverlay` (Step 5, above) already filters by `runs.filter((r) => r.page === pageNumber)` — no further change needed there.
- `openRunEditor(run)` (called as `openRunEditor(pageNumber, run)` from the render block above) needs a `page` parameter threaded through to `submitRunEditor`, since `submitRunEditor` currently builds its new element with `page: currentPage`. Change `openRunEditor`/`submitRunEditor`'s signatures:

```jsx
  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    setEditingRunIndex(run.index);
    setEditingRunPage(pageNumber);
    setDraftText(pending ? pending.text : run.text);
    setDraftFamilyTouched(Boolean(pending?.font_override));
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
      draftFamilyTouched || draftOverride.bold !== run.bold || draftOverride.italic !== run.italic || draftOverride.size !== run.size;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editingRunPage,
      run_index: run.index,
      text: draftText,
      font_override: overrideChanged ? draftOverride : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
    setEditingRunIndex(null);
  }
```

Add the new `editingRunPage` state alongside `editingRunIndex`:

```jsx
  const [editingRunIndex, setEditingRunIndex] = useState(null);
  const [editingRunPage, setEditingRunPage] = useState(null);
```

(`editingRunIndex` alone is no longer sufficient to identify a unique run across the whole document, now that every page's runs share the same index range starting from 0 — the combination of `editingRunPage` + `editingRunIndex` is, which is why the bottom edit form's run lookup in Step 5's code above already filters by both.)

- [ ] **Step 6: Update CSS**

`.edit-pdf-canvas__stage` needs `position: absolute; inset: 0;` (it no longer contains its own `<img>` — `PageScrollViewer` does). Delete `.edit-pdf-canvas__image` and `.edit-pdf-canvas__nav`/`.edit-pdf-canvas__nav button`/`.edit-pdf-canvas__nav button:disabled` (no longer used).

Center the mode toolbar — find:

```css
.edit-pdf-canvas__modes {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
```

and change to:

```css
.edit-pdf-canvas__modes {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  flex-wrap: wrap;
}
```

Also center `.edit-pdf-canvas__history-bar` and each mode's `.edit-pdf-canvas__style-bar` the same way (add `justify-content: center;` to each of those existing rules), so the whole toolbar area reads centered in the new wider layout, not just the mode buttons.

- [ ] **Step 7: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 8: Thorough manual browser check**

Start the backend and frontend dev servers, open Edit PDF on a multi-page PDF with actual text on more than one page, and verify EVERY mode still works correctly under the new per-page model:

- Every page renders stacked, sharp, in the wider, centered-toolbar layout.
- **Edit Text**: click a run on page 1 — edits page 1's run. Click a DIFFERENT run on page 2 — edits page 2's run, independently. Both pending edits coexist correctly (verify via the "K pages have edits" — actually check whether this label still exists/is accurate, or was dropped per the header simplification noted in earlier tasks; if dropped, verify via Undo becoming enabled and via running the tool).
- **Draw**: draw a stroke on page 1, then a different stroke on page 2 — both persist correctly, each on its own page, after scrolling away and back.
- **Shapes**: draw a rectangle on page 1 and an arrow on page 2 — both land on the correct page.
- **Highlight**: same check, two different pages.
- **Insert Image**: place an image on page 1 — appears there, not elsewhere.
- **Add Text**: place a text box on page 2 while page 1 is also visible — verify it appears only on page 2, editing/re-editing it (double-click) still works, and the focus-race-fix (`preventDefault()`) still functions correctly (typing immediately after clicking to place still works, matching Add Text's own prior verification).
- Select, move, resize, remove, copy/cut/paste, undo/redo — spot-check each still works for at least the image and new_text element types across DIFFERENT pages.
- Run the tool with a mix of elements across multiple pages, download, and confirm the output matches what the editor showed on each page.

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/components/EditPdfCanvas.jsx web/frontend/src/index.css
git commit -m "feat: migrate EditPdfCanvas to PageScrollViewer, center its toolbar"
```

No `Co-Authored-By` trailer.

---

## Task 5: Recent Files read-only preview

**Files:**
- Modify: `web/backend/storage.py` (`record_output` gains a `page_count` field)
- Modify: `web/backend/routes/tools.py` (`_output_response` computes and passes `page_count` for PDF outputs)
- Modify: `web/frontend/src/components/RecentFiles.jsx` (add an inline expand-to-preview per entry)
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `PageScrollViewer` (Task 1).
- Produces: `fetchHistory()`'s entries gain an optional `page_count: number | null` field (`null`/absent for non-PDF outputs like PDF-to-Word or PDF-to-Image, and for any history entry recorded before this change).

- [ ] **Step 1: Add `page_count` to recorded output history**

In `web/backend/storage.py`, change:

```python
def record_output(path: Path, tool: str, source_filenames: list[str]) -> dict:
    record = {
        "id": uuid.uuid4().hex[:12],
        "filename": path.name,
        "path": str(path),
        "tool": tool,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_filenames": source_filenames,
    }
```

to:

```python
def record_output(path: Path, tool: str, source_filenames: list[str], page_count: int | None = None) -> dict:
    record = {
        "id": uuid.uuid4().hex[:12],
        "filename": path.name,
        "path": str(path),
        "tool": tool,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_filenames": source_filenames,
        "page_count": page_count,
    }
```

In `web/backend/routes/tools.py`, find `_output_response`:

```python
def _output_response(paths: list[Path], tool: str, source_filenames: list[str]) -> dict:
    outputs = []
    for path in paths:
        record = storage.record_output(path, tool, source_filenames)
        outputs.append(
            {
                "id": record["id"],
                "filename": record["filename"],
                "download_url": f"/api/files/{record['id']}/download",
            }
        )
    return {"outputs": outputs}
```

and change to:

```python
def _output_response(paths: list[Path], tool: str, source_filenames: list[str]) -> dict:
    outputs = []
    for path in paths:
        page_count = get_page_count(str(path)) if path.suffix.lower() == ".pdf" else None
        record = storage.record_output(path, tool, source_filenames, page_count=page_count)
        outputs.append(
            {
                "id": record["id"],
                "filename": record["filename"],
                "download_url": f"/api/files/{record['id']}/download",
            }
        )
    return {"outputs": outputs}
```

`get_page_count` is already imported into this file (used elsewhere for other routes) — confirm this import exists at the top of `web/backend/routes/tools.py`; if it's missing, add `get_page_count` to the existing `from app.core.pdf_ops import (...)` block.

**Note on existing history entries:** entries recorded before this change simply won't have a `page_count` key in the stored JSON — `record.get("page_count")` (or plain dict access via `.get`, since `load_history()` returns raw dicts) returns `None` for those, which the frontend treats identically to "not a previewable PDF." No migration of `history.json` is needed.

- [ ] **Step 2: Test the backend change**

Run the full backend suite to confirm nothing regressed:

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (180 currently — this task doesn't add new backend tests, since `_output_response`/`record_output` are exercised indirectly by every existing tool-route test already; a genuinely new, dedicated test isn't warranted for a one-field addition to an already-covered code path, but if any EXISTING test asserts on the exact shape of a history record or `_output_response`'s return value in a way this breaks, fix it here).

- [ ] **Step 3: Add the inline preview to `RecentFiles.jsx`**

Add the import:

```jsx
import PageScrollViewer from "./PageScrollViewer";
```

Add state for which entry (if any) is expanded:

```jsx
  const [expandedId, setExpandedId] = useState(null);
```

In the `<li>` for each entry, add a "Preview" toggle button (only when `entry.page_count` is truthy) to the existing `history-list__actions` div, and render `PageScrollViewer` inline when that entry is expanded. Change:

```jsx
              <div className="history-list__actions">
                <a className="icon-button" href={downloadUrl(entry.id)} download>
                  <DownloadSimple size={15} weight="regular" />
                  Download
                </a>
                <button className="icon-button icon-button--danger" onClick={() => handleDelete(entry.id)}>
                  <Trash size={15} weight="regular" />
                  Delete
                </button>
              </div>
            </li>
```

to:

```jsx
              <div className="history-list__actions">
                {entry.page_count ? (
                  <button
                    className="icon-button"
                    onClick={() => setExpandedId((id) => (id === entry.id ? null : entry.id))}
                  >
                    <Eye size={15} weight="regular" />
                    {expandedId === entry.id ? "Hide preview" : "Preview"}
                  </button>
                ) : null}
                <a className="icon-button" href={downloadUrl(entry.id)} download>
                  <DownloadSimple size={15} weight="regular" />
                  Download
                </a>
                <button className="icon-button icon-button--danger" onClick={() => handleDelete(entry.id)}>
                  <Trash size={15} weight="regular" />
                  Delete
                </button>
              </div>
              {expandedId === entry.id && entry.page_count && (
                <div className="history-list__preview">
                  <PageScrollViewer fileId={entry.id} pageCount={entry.page_count} />
                </div>
              )}
            </li>
```

Add `Eye` to the icon import — change:

```jsx
import { ClockCounterClockwise, FilePdf, FileDoc, FileImage, DownloadSimple, Trash, WarningCircle } from "@phosphor-icons/react";
```

to:

```jsx
import { ClockCounterClockwise, FilePdf, FileDoc, FileImage, DownloadSimple, Trash, WarningCircle, Eye } from "@phosphor-icons/react";
```

- [ ] **Step 4: Add CSS**

Add to `web/frontend/src/index.css`, near the existing `.history-list` rules:

```css
.history-list__preview {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}
```

- [ ] **Step 5: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 6: Manual browser check**

Run a couple of tools to produce fresh PDF outputs (so Recent Files has entries with a real `page_count`), then:
- Confirm a "Preview" button appears for PDF entries and does NOT appear for non-PDF outputs (e.g. run PDF to Word, confirm no Preview button on that entry).
- Click "Preview" — a scrollable, multi-page, sharp preview expands inline below that entry, with working "Page X of Y" and jump-to-page.
- Click "Hide preview" (or click Preview again) — it collapses.
- Opening a different entry's preview closes the previously-open one (only one open at a time).
- An entry from BEFORE this change (if any exist in your local history) shows no Preview button and doesn't error.

- [ ] **Step 7: Commit**

```bash
git add web/backend/storage.py web/backend/routes/tools.py web/frontend/src/components/RecentFiles.jsx web/frontend/src/index.css
git commit -m "feat: add scrollable multi-page preview to Recent Files"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (180).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (5 total), in order, on top of `main`'s current tip, none carrying a `Co-Authored-By` trailer (all are `feat:`).
- [ ] Confirm every one of the five `PageScrollViewer` consumers (Redact, Sign, PDF Forms, Edit PDF, Recent Files) actually uses the shared component — no leftover duplicated pagination code anywhere.
