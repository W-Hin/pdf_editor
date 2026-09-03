# Sign (Phase 2 Group D1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a "Sign PDF" tool — draw or upload a signature (optionally saved for reuse), place it on any number of pages with drag-to-move and resize, then Run.

**Architecture:** Zero new backend code — signature placements are `image`-type elements submitted to the already-shipped `edit_pdf`/`POST /tools/edit-pdf` endpoint, identical in shape to Edit PDF's Insert Image mode. One new frontend component, `SignCanvas.jsx`, built from Insert Image mode's placement/resize/drag code plus a new signature-source panel (draw pad, upload, `localStorage`-backed reuse).

**Tech Stack:** React frontend only. No new dependencies — uses the native `<canvas>` 2D API for the drawing pad and `localStorage` for persistence.

**Spec:** `docs/superpowers/specs/2026-09-03-pdf-editor-phase2-sign-design.md` — read it before starting.

## Global Constraints

- Backend: **no new code.** Every placement is submitted as `{type: "image", page, file_id, x, y, width, height}` inside the existing `elements` array to `POST /tools/edit-pdf` — the exact same request shape Edit PDF's Insert Image mode already produces and the backend already validates/applies/tests.
- `x`/`y` are the top-left corner as fractions of the page's displayed dimensions; `width`/`height` are size as fractions. Same convention as every other element type in this app.
- No undo/redo, no selection, no clipboard for this tool — the spec doesn't call for them, and Sign's element set is homogeneous (always exactly one signature `file_id`, referenced by every placement), so there's nothing to select-and-copy between different element types the way Edit PDF has.
- No new automated frontend tests — this project's established convention for interactive canvas components is manual browser verification at the end of implementation.
- One saved signature, overwritable — not a signature library. Drawing or uploading a new one replaces whatever was saved.
- No background removal — an uploaded/drawn signature's background renders as-is. Stated as a known limitation in the spec, not something to silently "fix."
- Web app only — no desktop (PySide6) app changes.

---

## Task 1: `SignCanvas.jsx` — signature source panel + basic placement

**Files:**
- Create: `web/frontend/src/components/SignCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `uploadFile(file)` (existing, `api.js`, returns `{id, filename, page_count}`), `thumbnailUrl(fileId, pageNumber, maxSize)` (existing, `api.js`).
- Produces: default export `SignCanvas({ fileId, pageCount, onChange })`, matching `EditPdfCanvas`'s exact prop shape. Internally: `placements` state (array of `{id, type: "image", page, file_id, x, y, width, height}`), synced to the parent via a `useEffect` that calls `onChange(placements)` on every change — this task establishes that sync mechanism; Task 2's drag code relies on `setPlacements` alone (never manual `onChange` calls) to get the sync for free.

- [ ] **Step 1: Create the component**

```jsx
import { useEffect, useRef, useState } from "react";
import { CaretLeft, CaretRight, PencilSimple, UploadSimple, X } from "@phosphor-icons/react";
import { thumbnailUrl, uploadFile } from "../api";

const PREVIEW_MAX_SIZE = 700;
const PAD_WIDTH = 400;
const PAD_HEIGHT = 150;
const SIGNATURE_STORAGE_KEY = "pdf-editor-saved-signature";
const DEFAULT_WIDTH_FRACTION = 0.25;
const MAX_HEIGHT_FRACTION = 0.9;

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function dataUrlToFile(dataUrl, filename) {
  const res = await fetch(dataUrl);
  const blob = await res.blob();
  return new File([blob], filename, { type: blob.type || "image/png" });
}

function loadImageNaturalSizeFromDataUrl(dataUrl) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
    img.src = dataUrl;
  });
}

export default function SignCanvas({ fileId, pageCount, onChange }) {
  const stageRef = useRef(null);
  const padCanvasRef = useRef(null);
  const isDrawingRef = useRef(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [placements, setPlacements] = useState([]);
  const [signatureFileId, setSignatureFileId] = useState(null);
  const [signatureNaturalSize, setSignatureNaturalSize] = useState(null);
  const [signaturePreviewSrc, setSignaturePreviewSrc] = useState(null);
  const [savedSignature, setSavedSignature] = useState(null);
  const [drawing, setDrawing] = useState(false);
  const [padHasDrawing, setPadHasDrawing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    onChange(placements);
  }, [placements]);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SIGNATURE_STORAGE_KEY);
      if (saved) setSavedSignature(saved);
    } catch {
      // localStorage unavailable (quota, private browsing) — just don't offer reuse.
    }
  }, []);

  useEffect(() => {
    if (drawing) initPad();
  }, [drawing]);

  if (!fileId || !pageCount) return null;

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

  async function useSignature(dataUrl, { persist }) {
    setError("");
    try {
      const file = await dataUrlToFile(dataUrl, "signature.png");
      const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSizeFromDataUrl(dataUrl)]);
      setSignatureFileId(uploaded.id);
      setSignatureNaturalSize(naturalSize);
      setSignaturePreviewSrc(dataUrl);
      if (persist) {
        try {
          localStorage.setItem(SIGNATURE_STORAGE_KEY, dataUrl);
          setSavedSignature(dataUrl);
        } catch {
          // localStorage unavailable/quota exceeded — signature still works this session.
        }
      }
    } catch (err) {
      setError("Could not use this signature: " + err.message);
    }
  }

  async function handleUploadFileSelected(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const dataUrl = await readFileAsDataUrl(file);
      await useSignature(dataUrl, { persist: true });
    } catch (err) {
      setError("Could not read this image: " + err.message);
    }
  }

  function initPad() {
    const canvas = padCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = "#000000";
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
  }

  function padPointFromEvent(e) {
    const canvas = padCanvasRef.current;
    const rect = canvas.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * canvas.width,
      y: ((e.clientY - rect.top) / rect.height) * canvas.height,
    };
  }

  function handlePadMouseDown(e) {
    isDrawingRef.current = true;
    setPadHasDrawing(true);
    const ctx = padCanvasRef.current.getContext("2d");
    const { x, y } = padPointFromEvent(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
  }

  function handlePadMouseMove(e) {
    if (!isDrawingRef.current) return;
    const ctx = padCanvasRef.current.getContext("2d");
    const { x, y } = padPointFromEvent(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  function handlePadMouseUp() {
    isDrawingRef.current = false;
  }

  function handlePadClear() {
    initPad();
    setPadHasDrawing(false);
  }

  async function handlePadSave() {
    if (!padHasDrawing) {
      setError("Draw a signature first.");
      return;
    }
    const dataUrl = padCanvasRef.current.toDataURL("image/png");
    await useSignature(dataUrl, { persist: true });
    setDrawing(false);
  }

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

  function removePlacement(id) {
    setPlacements((prev) => prev.filter((p) => p.id !== id));
  }

  function useDifferentSignature() {
    setSignatureFileId(null);
    setSignatureNaturalSize(null);
    setSignaturePreviewSrc(null);
    setPlacements([]);
  }

  const markedPageCount = new Set(placements.map((p) => p.page)).size;

  return (
    <div className="sign-canvas">
      {error && <p className="sign-canvas__error">{error}</p>}

      {!signatureFileId && (
        <div className="sign-canvas__source-panel">
          {savedSignature && (
            <div className="sign-canvas__saved">
              <img src={savedSignature} alt="Saved signature" className="sign-canvas__saved-preview" />
              <button type="button" onClick={() => useSignature(savedSignature, { persist: false })}>
                Use saved signature
              </button>
            </div>
          )}
          <div className="sign-canvas__source-actions">
            <button type="button" onClick={() => setDrawing((d) => !d)}>
              <PencilSimple size={16} weight="regular" />
              Draw new
            </button>
            <label className="sign-canvas__upload">
              <UploadSimple size={16} weight="regular" />
              Upload new
              <input type="file" accept="image/png,image/jpeg" onChange={handleUploadFileSelected} style={{ display: "none" }} />
            </label>
          </div>
          {drawing && (
            <div className="sign-canvas__pad">
              <canvas
                ref={padCanvasRef}
                width={PAD_WIDTH}
                height={PAD_HEIGHT}
                className="sign-canvas__pad-canvas"
                onMouseDown={handlePadMouseDown}
                onMouseMove={handlePadMouseMove}
                onMouseUp={handlePadMouseUp}
                onMouseLeave={handlePadMouseUp}
              />
              <div className="sign-canvas__pad-actions">
                <button type="button" onClick={handlePadClear}>
                  Clear
                </button>
                <button type="button" onClick={handlePadSave}>
                  Save signature
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {signatureFileId && (
        <>
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
                  onMouseDown={(e) => e.stopPropagation()}
                >
                  <img src={signaturePreviewSrc} className="sign-canvas__placement-image" alt="Placed signature" draggable={false} />
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

          <button type="button" className="sign-canvas__different" onClick={useDifferentSignature}>
            Use a different signature
          </button>
        </>
      )}
    </div>
  );
}
```

Note: this step's placement `<div>` stops propagation on its own `onMouseDown` (so a click landing on an already-placed signature doesn't also place a new one via the stage's handler) but has no drag/resize interaction yet — Task 2 adds that by attaching a real handler to that `onMouseDown` instead of just stopping propagation, and adding a resize handle.

- [ ] **Step 2: Add CSS**

Add to `web/frontend/src/index.css`, after the Edit PDF canvas block:

```css
/* ---------- Sign canvas ---------- */

.sign-canvas {
  margin: var(--space-5) 0;
}

.sign-canvas__error {
  color: var(--color-destructive, #dc2626);
  font-size: 13px;
  margin: 0 0 var(--space-3) 0;
}

.sign-canvas__source-panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  max-width: 460px;
}

.sign-canvas__saved {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.sign-canvas__saved-preview {
  max-width: 120px;
  max-height: 60px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: #fff;
}

.sign-canvas__source-actions {
  display: flex;
  gap: var(--space-2);
}

.sign-canvas__source-actions button,
.sign-canvas__upload {
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

.sign-canvas__pad-canvas {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  cursor: crosshair;
  touch-action: none;
  max-width: 100%;
}

.sign-canvas__pad-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.sign-canvas__pad-actions button {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
}

.sign-canvas__nav {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  font-size: 14px;
  color: var(--color-muted-foreground);
}

.sign-canvas__nav button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
}

.sign-canvas__nav button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.sign-canvas__stage {
  position: relative;
  display: inline-block;
  max-width: 100%;
  user-select: none;
}

.sign-canvas__image {
  display: block;
  max-width: 100%;
  border-radius: var(--radius-sm);
  pointer-events: none;
}

.sign-canvas__placement {
  position: absolute;
  border: 1px dashed var(--color-accent);
  cursor: move;
}

.sign-canvas__placement-image {
  width: 100%;
  height: 100%;
  display: block;
  pointer-events: none;
}

.sign-canvas__placement-remove {
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
}

.sign-canvas__different {
  margin-top: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-card);
  cursor: pointer;
  font-size: 13px;
}
```

- [ ] **Step 3: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully with no errors. (`SignCanvas` isn't wired into the app yet — Task 3 does that — so there's nothing to manually click through until then.)

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/SignCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add SignCanvas signature source panel and basic placement

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 2: Drag-to-move and resize

**Files:**
- Modify: `web/frontend/src/components/SignCanvas.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `placements`/`setPlacements`, `pointFromEvent`, `stageRef` (Task 1).
- Produces: dragging a placement's body repositions it; dragging its corner handle resizes it (aspect-ratio locked). Both stay clamped within `[0, 1 - width/height]` on both axes — the same page-bounds invariant `_validate_image_element` (backend, already shipped) enforces, so a drag can never produce a placement the Run would reject.

- [ ] **Step 1: Add drag state and handlers**

Add a ref near the other refs in `SignCanvas.jsx`:

```js
const dragRef = useRef(null);
```

Add these functions (anywhere among the other handler functions, before the `return`):

```js
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
  const dx = point.x - drag.start.x;
  const dy = point.y - drag.start.y;
  const { startPlacement } = drag;
  let updated;
  if (drag.mode === "move") {
    const x = Math.min(Math.max(startPlacement.x + dx, 0), 1 - startPlacement.width);
    const y = Math.min(Math.max(startPlacement.y + dy, 0), 1 - startPlacement.height);
    updated = { ...startPlacement, x, y };
  } else {
    const aspect = startPlacement.height / startPlacement.width;
    const widthCap = Math.min(1 - startPlacement.x, (1 - startPlacement.y) / aspect);
    const desiredWidth = Math.max(0.05, startPlacement.width + dx);
    const width = Math.min(desiredWidth, widthCap);
    const height = width * aspect;
    updated = { ...startPlacement, width, height };
  }
  setPlacements((prev) => prev.map((p) => (p.id === drag.id ? updated : p)));
}

function handleDragEnd() {
  window.removeEventListener("mousemove", handleDragMove);
  window.removeEventListener("mouseup", handleDragEnd);
  window.removeEventListener("blur", handleDragEnd);
  dragRef.current = null;
}
```

This is Insert Image mode's exact resize/move math (`web/frontend/src/components/EditPdfCanvas.jsx`'s `handleImageDragMove`), minus the undo-history bookkeeping and the `moved`/`elementsRef` machinery that existed there specifically to make one drag gesture count as a single undo step and to avoid a React 18 StrictMode double-invoke on a `setElements` updater with side effects inside it. Neither concern applies here: this tool has no undo/redo, and `handleDragEnd` here has no side effects at all beyond removing its own listeners — the `useEffect(() => onChange(placements), [placements])` from Task 1 already picks up every `setPlacements` call, including the live updates from `handleDragMove`, with no stale-closure risk (it always reads the current `placements` from React's own render cycle, not from a listener's closure).

- [ ] **Step 2: Wire the handlers into the placement and add a resize handle**

Replace the placement `<div>` from Task 1's Step 1 (the one that currently only does `onMouseDown={(e) => e.stopPropagation()}`) with:

```jsx
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
```

- [ ] **Step 3: Add the resize handle's CSS**

Add to `web/frontend/src/index.css`, after `.sign-canvas__placement-remove`:

```css
.sign-canvas__placement-handle {
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

- [ ] **Step 4: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully with no errors.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/SignCanvas.jsx web/frontend/src/index.css
git commit -m "feat: add drag-to-move and resize to signature placements

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Task 3: Wire "Sign PDF" into ToolView

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/components/ToolGrid.jsx`

**Interfaces:**
- Consumes: `SignCanvas` (Task 2, final form), `TOOL_CONFIGS` (existing).

- [ ] **Step 1: Add the `toolConfigs.js` entry**

Add to `TOOL_CONFIGS` in `web/frontend/src/toolConfigs.js`, alongside `edit-pdf`:

```js
sign: {
  title: "Sign PDF",
  category: "Edit",
  multiFile: false,
  mode: "view",
  preview: "sign",
  endpoint: "edit-pdf",
  fields: [],
},
```

(`endpoint: "edit-pdf"` is deliberate — Sign submits the same `elements` shape Edit PDF does, so it reuses that endpoint directly rather than needing its own.)

- [ ] **Step 2: Wire `ToolView.jsx`**

Add the import: `import SignCanvas from "./SignCanvas";`

`ToolView.jsx` already has an `elements` state variable (added for `edit-pdf`) and already resets it to `[]` in `handleFilePick`. Sign reuses that same state — no new state variable needed, since only one tool's preview is ever mounted at a time and a fresh file pick already clears it for every tool.

In `handleRun`, add a precondition guard next to the existing `edit-pdf` guard:

```js
if (config.preview === "sign" && elements.length === 0) {
  setError("Place at least one signature on the page preview before running.");
  return;
}
```

The body assembly already handles this case for free: the existing `if (config.preview === "edit-pdf") { body.elements = elements.map(({ id, ...rest }) => rest); }` line needs a sibling condition. Change it to:

```js
if (config.preview === "edit-pdf" || config.preview === "sign") {
  body.elements = elements.map(({ id, ...rest }) => rest);
}
```

Add a preview branch in `renderPreview()`, next to the existing `edit-pdf` branch:

```jsx
if (config.preview === "sign") {
  if (!primaryFile) return null;
  return (
    // key={primaryFile.id}: same file-switch remount fix every selector-style
    // component in this app uses — discards SignCanvas's internal placements/
    // signature state on file switch instead of applying stale placements to
    // a newly-loaded document.
    <SignCanvas key={primaryFile.id} fileId={primaryFile.id} pageCount={primaryFile.page_count} onChange={setElements} />
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
  (config.preview === "edit-pdf" && elements.length === 0) ||
  (config.preview === "sign" && elements.length === 0)
}
```

- [ ] **Step 3: Add the tool-grid icon**

In `ToolGrid.jsx`, add `Signature` to the icon import line, and add to `TOOL_ICONS`:

```js
sign: Signature,
```

- [ ] **Step 4: Build and manually verify end-to-end**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

Then start the dev server and the backend, open the app, navigate to Sign PDF, upload a multi-page PDF, and manually verify:
- No saved signature yet: only "Draw new" / "Upload new" are offered (no "Use saved signature").
- Draw: click "Draw new," draw something in the pad, click "Save signature" — confirm it switches to the placement view with page nav and the stage visible.
- Place: click the page preview, confirm a signature-image placement appears there at a reasonable default size.
- Resize: drag the corner handle, confirm it resizes while preserving aspect ratio and staying on-page.
- Move: drag the placement's body, confirm it repositions and stays on-page.
- Multi-page: navigate to page 2, place another signature there; confirm the nav label says "2 pages signed."
- Remove: click a placement's × button, confirm it's removed and doesn't also start a drag.
- Reload the tool (upload a fresh file, or reopen Sign PDF) — confirm "Use saved signature" now offers the just-drawn signature as a thumbnail, and clicking it goes straight to the placement view without re-drawing.
- Upload path: use "Upload new" with an image file, confirm it also becomes the new saved signature (overwriting the drawn one).
- File switch: load file A, place a signature, load file B, confirm the tool resets to the source panel with zero stale placements (the file-switch remount fix).
- Run the tool and confirm the downloaded output actually shows the signature(s) placed where expected.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx web/frontend/src/components/ToolGrid.jsx
git commit -m "feat: wire Sign PDF tool into ToolView

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Final check

- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Run `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (this plan touches no backend code, so this is a pure regression check).
- [ ] Confirm `git log --oneline` shows one commit per task above, in order, on top of `main`'s current tip.
