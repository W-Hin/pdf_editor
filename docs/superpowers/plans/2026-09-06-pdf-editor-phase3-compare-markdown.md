# Phase 3, Group D: Compare PDF + PDF→Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the first two tools of Phase 3 — Compare PDF (text diff + side-by-side visual pixel-diff overlay, in-app view only) and PDF→Markdown (via `pymupdf4llm`, zipped with extracted images).

**Architecture:** Compare PDF gets a new backend module (`app/core/compare_pdf.py`), a dedicated two-file API route (`web/backend/routes/compare.py`, not `tools.py`'s single-file shape), and a dedicated frontend page (`ComparePdfView.jsx`) that bypasses `ToolView`'s generic upload-then-configure flow entirely. PDF→Markdown fits the existing single-file-in/single-file-out tool pattern completely — one small addition to `pdf_ops.py`, one `tools.py` route, one `toolConfigs.js` entry.

**Tech Stack:** PyMuPDF (`fitz`), `numpy` (moving from a transitive to a direct dependency), `pymupdf4llm` (new), Python stdlib `difflib`/`zipfile`, FastAPI, React + `react-router-dom`.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task's `feat:` commit must **not** carry the trailer.
- No frontend automated tests (established project convention) — `npm run build` plus a specific manual browser checklist per frontend task.
- Backend changes follow TDD with concrete assertions verified empirically before being written into a test — every numeric value in this plan (the pixel-diff tolerance, the grid cell size, exact line/box counts) was independently verified against real generated PDFs before this plan was written, not assumed from documentation.
- Compare PDF writes nothing to `storage.record_output`/history — it produces no downloadable output at all, per the spec's explicit scope decision.
- **Correction to the spec's architecture section, found while reading the current codebase fresh:** the spec said Compare PDF's frontend would reuse "`PageScrollViewer`'s continuous-scroll pattern." Read fresh, `PageScrollViewer.jsx` always renders `<img src={thumbnailUrl(fileId, pageNumber, maxSize)}>` as each page's content internally — `renderPageOverlay` only draws an OVERLAY on top of that single image, it doesn't replace what the page's own content is. Compare PDF's per-page content (a text-diff panel plus TWO independently-fetched diff images with highlight boxes, driven by TWO file ids) doesn't fit that model — there's no single `fileId`/`thumbnailUrl` this component could hand to `PageScrollViewer`. Task 3 below therefore builds `ComparePdfView.jsx`'s own scroll container, reusing the *pattern* `PageScrollViewer` established (`IntersectionObserver`-driven lazy-loading, a directly-editable "Page X of Y" jump box) rather than the component itself.

---

### Task 1: Compare PDF — backend core logic

**Files:**
- Create: `app/core/compare_pdf.py`
- Test: `tests/test_compare_pdf.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `extract_page_texts(path: str) -> list[str]`, `diff_page_text(text_a: str, text_b: str) -> list[dict]` (each dict is `{"op": "equal"|"delete"|"insert", "text": str}`), `diff_page_visual(path_a: str, path_b: str, page_num: int, max_size: int) -> list[dict]` (each dict is `{"x0": float, "y0": float, "x1": float, "y1": float}`, page-fraction coordinates), `render_page_image(path: str, page_num: int, max_size: int) -> bytes` (PNG bytes, for the API route to base64-encode).
- Consumes: `app.core.pdf_ops.open_pdf` (existing, unchanged).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compare_pdf.py`:

```python
from app.core.compare_pdf import diff_page_text, diff_page_visual, extract_page_texts, render_page_image


def _make_pdf(path, rect_pos=None, texts=None):
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    if texts:
        y = 100
        for text in texts:
            page.insert_text((72, y), text, fontsize=14)
            y += 30
    if rect_pos:
        page.draw_rect(fitz.Rect(*rect_pos), color=(0, 0, 1), fill=(0.8, 0.8, 1))
    doc.save(str(path))
    doc.close()


def test_diff_page_text_detects_a_changed_line(tmp_path):
    path_a = tmp_path / "a.pdf"
    path_b = tmp_path / "b.pdf"
    _make_pdf(path_a, texts=["Hello World.", "Second unchanged line."])
    _make_pdf(path_b, texts=["Goodbye World.", "Second unchanged line."])

    texts_a = extract_page_texts(str(path_a))
    texts_b = extract_page_texts(str(path_b))
    result = diff_page_text(texts_a[0], texts_b[0])

    assert result == [
        {"op": "delete", "text": "Hello World."},
        {"op": "insert", "text": "Goodbye World."},
        {"op": "equal", "text": "Second unchanged line."},
    ]


def test_diff_page_visual_detects_a_shape_change_text_diff_misses(tmp_path):
    path_a = tmp_path / "a.pdf"
    path_b = tmp_path / "b.pdf"
    same_text = ["Hello World, this is a test page with some text."]
    _make_pdf(path_a, rect_pos=(100, 200, 300, 350), texts=same_text)
    _make_pdf(path_b, rect_pos=(120, 200, 320, 350), texts=same_text)

    texts_a = extract_page_texts(str(path_a))
    texts_b = extract_page_texts(str(path_b))
    text_result = diff_page_text(texts_a[0], texts_b[0])
    assert all(entry["op"] == "equal" for entry in text_result)

    boxes = diff_page_visual(str(path_a), str(path_b), 1, max_size=1800)
    assert len(boxes) >= 1
    for box in boxes:
        assert 0 <= box["x0"] < box["x1"] <= 1
        assert 0 <= box["y0"] < box["y1"] <= 1


def test_diff_page_visual_ignores_negligible_rendering_noise(tmp_path):
    path = tmp_path / "same.pdf"
    _make_pdf(path, rect_pos=(100, 200, 300, 350), texts=["Some text here."])

    boxes = diff_page_visual(str(path), str(path), 1, max_size=1800)
    assert boxes == []


def test_render_page_image_returns_png_bytes(tmp_path):
    path = tmp_path / "a.pdf"
    _make_pdf(path, texts=["Hello"])
    data = render_page_image(str(path), 1, max_size=200)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_compare_pdf.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.compare_pdf'`.

- [ ] **Step 3: Write `app/core/compare_pdf.py`**

```python
import difflib

import fitz
import numpy as np

from app.core.pdf_ops import open_pdf

# A per-channel difference below this is treated as noise rather than a real
# content change. Verified empirically: rendering the SAME page twice via
# fitz's get_pixmap is bit-exact deterministic (max per-channel diff is 0),
# so this value isn't compensating for observed rendering noise between
# identical renders — it's a conservative margin for real-world cross-file
# comparisons (different PDF producers can rasterize visually-identical
# content with tiny colour/positioning differences this codebase has no way
# to synthesize in a test). Confirmed this value causes no false negatives:
# a genuinely moved 200x150pt rectangle was detected identically at every
# tolerance tested from 0 to 50.
_VISUAL_DIFF_TOLERANCE = 24

# Coarse-grid cell size (px) used to cluster differing pixels into bounding
# boxes. Verified empirically on a real rendered page at max_size 1800: a
# moved rectangle produced two clean ~60x340px boxes at the changed edges —
# neither tiny slivers nor one overly-coarse blob.
_DIFF_GRID_CELL_PX = 20


def extract_page_texts(path: str) -> list[str]:
    doc = open_pdf(path)
    try:
        return [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()


def diff_page_text(text_a: str, text_b: str) -> list[dict]:
    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    result: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            result.extend({"op": "equal", "text": line} for line in lines_a[i1:i2])
        elif op == "delete":
            result.extend({"op": "delete", "text": line} for line in lines_a[i1:i2])
        elif op == "insert":
            result.extend({"op": "insert", "text": line} for line in lines_b[j1:j2])
        elif op == "replace":
            result.extend({"op": "delete", "text": line} for line in lines_a[i1:i2])
            result.extend({"op": "insert", "text": line} for line in lines_b[j1:j2])
    return result


def render_page_image(path: str, page_num: int, max_size: int) -> bytes:
    doc = open_pdf(path)
    try:
        page = doc[page_num - 1]
        rect = page.rect
        scale = max_size / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")
    finally:
        doc.close()


def _render_pixmap_array(path: str, page_num: int, max_size: int) -> np.ndarray:
    doc = open_pdf(path)
    try:
        page = doc[page_num - 1]
        rect = page.rect
        scale = max_size / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    finally:
        doc.close()


def _cluster_diff_boxes(mask: np.ndarray, cell: int = _DIFF_GRID_CELL_PX) -> list[tuple[int, int, int, int]]:
    """Coarse-grid flood-fill: divides `mask` into `cell`x`cell` blocks, flags
    any block containing at least one True pixel, then merges 4-connected
    flagged blocks into pixel-space (x0, y0, x1, y1) bounding boxes. No
    scipy dependency — box-level precision is enough for "here's roughly
    where it changed," not pixel-perfect segmentation.
    """
    h, w = mask.shape
    grid_h, grid_w = (h + cell - 1) // cell, (w + cell - 1) // cell
    grid = np.zeros((grid_h, grid_w), dtype=bool)
    for gy in range(grid_h):
        for gx in range(grid_w):
            block = mask[gy * cell : (gy + 1) * cell, gx * cell : (gx + 1) * cell]
            if block.any():
                grid[gy, gx] = True

    visited = np.zeros_like(grid)
    boxes: list[tuple[int, int, int, int]] = []
    for gy in range(grid_h):
        for gx in range(grid_w):
            if not grid[gy, gx] or visited[gy, gx]:
                continue
            stack = [(gy, gx)]
            visited[gy, gx] = True
            cells = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < grid_h and 0 <= nx < grid_w and grid[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            y0, y1 = min(ys) * cell, min((max(ys) + 1) * cell, h)
            x0, x1 = min(xs) * cell, min((max(xs) + 1) * cell, w)
            boxes.append((x0, y0, x1, y1))
    return boxes


def diff_page_visual(path_a: str, path_b: str, page_num: int, max_size: int) -> list[dict]:
    arr_a = _render_pixmap_array(path_a, page_num, max_size)
    arr_b = _render_pixmap_array(path_b, page_num, max_size)

    # Pad the smaller array to the larger's canvas size (black fill), never
    # stretch — lets pages with different aspect ratios still be diffed
    # pixel-for-pixel without distorting either.
    h = max(arr_a.shape[0], arr_b.shape[0])
    w = max(arr_a.shape[1], arr_b.shape[1])
    n = arr_a.shape[2]

    def pad(arr: np.ndarray) -> np.ndarray:
        if arr.shape[0] == h and arr.shape[1] == w:
            return arr
        canvas = np.zeros((h, w, n), dtype=np.uint8)
        canvas[: arr.shape[0], : arr.shape[1], :] = arr
        return canvas

    arr_a = pad(arr_a)
    arr_b = pad(arr_b)

    per_channel_diff = np.abs(arr_a.astype(int) - arr_b.astype(int))
    mask = (per_channel_diff > _VISUAL_DIFF_TOLERANCE).any(axis=2)
    boxes = _cluster_diff_boxes(mask)
    return [{"x0": x0 / w, "y0": y0 / h, "x1": x1 / w, "y1": y1 / h} for x0, y0, x1, y1 in boxes]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_compare_pdf.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Add `numpy` to `requirements.txt`**

Add a line `numpy>=1.24.0` to `requirements.txt` (it's already installed transitively; this makes it an explicit, pinned direct dependency, matching the spec's stated scope decision).

- [ ] **Step 6: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (187 before this task; 191 expected after — this task's 4 new tests).

- [ ] **Step 7: Commit**

```bash
git add app/core/compare_pdf.py tests/test_compare_pdf.py requirements.txt
git commit -m "feat: add Compare PDF's text-diff and visual pixel-diff core logic"
```

No `Co-Authored-By` trailer.

---

### Task 2: Compare PDF — API routes

**Files:**
- Create: `web/backend/routes/compare.py`
- Modify: `web/backend/main.py`
- Test: `tests/web/test_compare_route.py`

**Interfaces:**
- Consumes: Task 1's `extract_page_texts`, `diff_page_text`, `diff_page_visual`, `render_page_image` (all unchanged); `web.backend.storage.resolve_file` (existing).
- Produces: `POST /api/compare` (body `{"file_id_a": str, "file_id_b": str}`, returns `{"page_count_a": int, "page_count_b": int, "pages": [{"text_diff": [...], "has_counterpart": bool}, ...]}`); `GET /api/compare/{file_id_a}/{file_id_b}/{page_num}/visual` (returns `{"image_a": str, "image_b": str, "boxes": [...]}`, `image_a`/`image_b` are base64-encoded PNG data URIs).

- [ ] **Step 1: Write the failing route tests**

Create `tests/web/test_compare_route.py` (verified fresh against the current
`tests/web/test_tools_edit_convert.py`, which defines the exact `client`/`_upload_pdf`
pattern every route test file in `tests/web/` already follows — copy it into this new
file, don't import it across test modules):

```python
import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_pdf(num_pages=1):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return client.post(
        "/api/files", files={"file": ("sample.pdf", data, "application/pdf")}
    ).json()


def test_compare_reports_trailing_page_as_added():
    # doc_a: 2 pages, doc_b: 3 pages
    upload_a = _upload_pdf(num_pages=2)
    upload_b = _upload_pdf(num_pages=3)
    response = client.post(
        "/api/compare",
        json={"file_id_a": upload_a["id"], "file_id_b": upload_b["id"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["page_count_a"] == 2
    assert data["page_count_b"] == 3
    assert len(data["pages"]) == 3
    assert data["pages"][0]["has_counterpart"] is True
    assert data["pages"][1]["has_counterpart"] is True
    assert data["pages"][2]["has_counterpart"] is False


def test_compare_visual_diff_returns_base64_images_and_boxes():
    upload_a = _upload_pdf(num_pages=1)
    upload_b = _upload_pdf(num_pages=1)
    response = client.get(f"/api/compare/{upload_a['id']}/{upload_b['id']}/1/visual")
    assert response.status_code == 200
    data = response.json()
    assert data["image_a"].startswith("data:image/png;base64,")
    assert data["image_b"].startswith("data:image/png;base64,")
    assert isinstance(data["boxes"], list)
```

`_upload_pdf(page_count=N)` doesn't exist yet in this test file's neighbors as a parameterized helper — check the existing `_upload_pdf()` helper's exact signature in `tests/web/test_tools_edit_convert.py` (or wherever it's defined) and either reuse it as-is if it already accepts a page count, or write a small local helper in this new test file that generates and uploads an N-page PDF via the same upload flow every other route test already uses (`client.post("/api/files", files=...)` with PyMuPDF-generated bytes) — match the exact existing pattern precisely, don't invent a new one.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_compare_route.py -v`
Expected: FAIL — `404 Not Found` (the routes don't exist yet).

- [ ] **Step 3: Write `web/backend/routes/compare.py`**

```python
import base64

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.compare_pdf import diff_page_text, diff_page_visual, extract_page_texts, render_page_image
from web.backend import storage

router = APIRouter()


class CompareRequest(BaseModel):
    file_id_a: str
    file_id_b: str


@router.post("/compare")
def compare_route(req: CompareRequest):
    path_a = str(storage.resolve_file(req.file_id_a))
    path_b = str(storage.resolve_file(req.file_id_b))
    texts_a = extract_page_texts(path_a)
    texts_b = extract_page_texts(path_b)
    page_count_a = len(texts_a)
    page_count_b = len(texts_b)
    total_pages = max(page_count_a, page_count_b)

    pages = []
    for i in range(total_pages):
        has_a = i < page_count_a
        has_b = i < page_count_b
        if has_a and has_b:
            pages.append({"text_diff": diff_page_text(texts_a[i], texts_b[i]), "has_counterpart": True})
        else:
            pages.append({"text_diff": [], "has_counterpart": False})

    return {"page_count_a": page_count_a, "page_count_b": page_count_b, "pages": pages}


@router.get("/compare/{file_id_a}/{file_id_b}/{page_num}/visual")
def compare_visual_route(file_id_a: str, file_id_b: str, page_num: int, max_size: int = 1800):
    path_a = str(storage.resolve_file(file_id_a))
    path_b = str(storage.resolve_file(file_id_b))
    image_a = render_page_image(path_a, page_num, max_size)
    image_b = render_page_image(path_b, page_num, max_size)
    boxes = diff_page_visual(path_a, path_b, page_num, max_size)
    return {
        "image_a": f"data:image/png;base64,{base64.b64encode(image_a).decode('ascii')}",
        "image_b": f"data:image/png;base64,{base64.b64encode(image_b).decode('ascii')}",
        "boxes": boxes,
    }
```

- [ ] **Step 4: Wire the router into `main.py`**

In `web/backend/main.py`, find:

```python
from web.backend.routes import files, history, tools, version
```

Replace with:

```python
from web.backend.routes import compare, files, history, tools, version
```

Find:

```python
app.include_router(files.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(version.router, prefix="/api")
```

Replace with:

```python
app.include_router(compare.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(history.router, prefix="/api")
app.include_router(tools.router, prefix="/api")
app.include_router(version.router, prefix="/api")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_compare_route.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (191 before this task; 193 expected after).

- [ ] **Step 7: Commit**

```bash
git add web/backend/routes/compare.py web/backend/main.py tests/web/test_compare_route.py
git commit -m "feat: add Compare PDF's API routes"
```

No `Co-Authored-By` trailer.

---

### Task 3: Compare PDF — frontend

**Files:**
- Create: `web/frontend/src/components/ComparePdfView.jsx`
- Modify: `web/frontend/src/api.js`
- Modify: `web/frontend/src/App.jsx`
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/components/ToolGrid.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: Task 2's `POST /api/compare` and `GET /api/compare/{a}/{b}/{page}/visual`; `uploadFile` (existing, from `api.js`).
- Produces: `comparePdf(fileIdA, fileIdB)` and `fetchCompareVisual(fileIdA, fileIdB, pageNum)` in `api.js`; a `<Route path="/compare" element={<ComparePdfView />} />` in `App.jsx`.

- [ ] **Step 1: Add API helpers**

In `web/frontend/src/api.js`, add near `runTool`:

```jsx
export async function comparePdf(fileIdA, fileIdB) {
  const res = await request("/compare", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file_id_a: fileIdA, file_id_b: fileIdB }),
  });
  return res.json();
}

export async function fetchCompareVisual(fileIdA, fileIdB, pageNum) {
  const res = await request(`/compare/${fileIdA}/${fileIdB}/${pageNum}/visual`);
  return res.json();
}
```

- [ ] **Step 2: Add the `/compare` route**

In `web/frontend/src/App.jsx`, add the import:

```jsx
import ComparePdfView from "./components/ComparePdfView.jsx";
```

Find:

```jsx
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
```

Replace with:

```jsx
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/compare" element={<ComparePdfView />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
```

- [ ] **Step 3: Add a Compare PDF tile to the grid**

In `web/frontend/src/toolConfigs.js`, add an entry (this is used ONLY to make Compare PDF appear as a normal tile in the grid, driven by the same `TOOL_CONFIGS`-iterating code `ToolGrid.jsx` already has for every other tool — `ToolView.jsx`'s Step 4 below intercepts this specific id before any of `ToolView`'s own generic logic runs, since none of it applies to Compare PDF):

```jsx
  "compare-pdf": {
    title: "Compare PDF",
    category: "Edit",
    fields: [],
  },
```

In `web/frontend/src/components/ToolGrid.jsx`, add an import and a `TOOL_ICONS` entry:

```jsx
import {
  // ...existing icons...
  FileMagnifyingGlass,
} from "@phosphor-icons/react";
```

```jsx
const TOOL_ICONS = {
  // ...existing entries...
  "compare-pdf": FileMagnifyingGlass,
};
```

Read the current icon import list and `TOOL_ICONS` object fresh before editing — the exact insertion point among the existing entries doesn't matter, just add both without disturbing the rest.

- [ ] **Step 4: Intercept `compare-pdf` in `ToolView`**

In `web/frontend/src/components/ToolView.jsx`, add the import:

```jsx
import ComparePdfView from "./ComparePdfView.jsx";
```

Find:

```jsx
export default function ToolView() {
  const { toolId } = useParams();
  const navigate = useNavigate();
  const config = TOOL_CONFIGS[toolId];
```

Replace with:

```jsx
export default function ToolView() {
  const { toolId } = useParams();
  const navigate = useNavigate();
  const config = TOOL_CONFIGS[toolId];

  // Compare PDF's flow (two files, no Run/download step, live inspection
  // only) is different enough from every other tool's "upload → configure →
  // Run → download" shape that it doesn't fit this component's generic
  // rendering at all. It still needs a TOOL_CONFIGS entry so it appears as a
  // normal tile in the grid (ToolGrid.jsx always navigates tiles to
  // `/tool/${toolId}`) — this is the one point where that navigation gets
  // redirected to its own dedicated page instead of this component's own
  // upload/preview/Run logic below.
  if (toolId === "compare-pdf") {
    return <ComparePdfView />;
  }
```

(The rest of the component — every hook, `renderPreview`, the return JSX — is unchanged. Placing the redirect AFTER the `useParams`/`useNavigate`/`config` lines but BEFORE any `useState` call would violate the Rules of Hooks if `config` were ever null for a different reason; since `compare-pdf` always has a `config` entry from Step 3, and this check returns before any `useState` call in the current function, this is safe — confirm by reading the current file's exact hook order before inserting, since a later edit to this file could have moved things.)

- [ ] **Step 5: Write `ComparePdfView.jsx`**

```jsx
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { uploadFile, comparePdf, fetchCompareVisual } from "../api";

export default function ComparePdfView() {
  const navigate = useNavigate();
  const [fileA, setFileA] = useState(null);
  const [fileB, setFileB] = useState(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // { page_count_a, page_count_b, pages }
  const [visualByPage, setVisualByPage] = useState({}); // pageNum -> data | "loading"
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const containerRefsRef = useRef([]);
  const visibilityRef = useRef(new Map());
  const fetchedRef = useRef(new Set());

  async function handlePick(which, e) {
    setError("");
    const file = e.target.files[0];
    if (!file) return;
    try {
      const uploaded = await uploadFile(file);
      if (which === "a") setFileA(uploaded);
      else setFileB(uploaded);
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleCompare() {
    setError("");
    setResult(null);
    setVisualByPage({});
    fetchedRef.current = new Set();
    try {
      const data = await comparePdf(fileA.id, fileB.id);
      setResult(data);
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  useEffect(() => {
    if (!result) return;
    const totalPages = result.pages.length;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const pageNumber = Number(entry.target.dataset.pageNumber);
          visibilityRef.current.set(pageNumber, entry.isIntersecting ? entry.intersectionRatio : 0);
          if (entry.isIntersecting && !fetchedRef.current.has(pageNumber)) {
            const page = result.pages[pageNumber - 1];
            if (page.has_counterpart) {
              fetchedRef.current.add(pageNumber);
              setVisualByPage((v) => ({ ...v, [pageNumber]: "loading" }));
              fetchCompareVisual(fileA.id, fileB.id, pageNumber)
                .then((data) => setVisualByPage((v) => ({ ...v, [pageNumber]: data })))
                .catch((err) => setVisualByPage((v) => ({ ...v, [pageNumber]: { error: err.message } })));
            }
          }
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
    containerRefsRef.current.slice(0, totalPages).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [result, fileA, fileB]);

  function jumpToPage(n) {
    if (!result) return;
    const clamped = Math.min(Math.max(1, n), result.pages.length);
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

  function renderTextDiff(entries) {
    return (
      <div className="compare-pdf__text-diff">
        {entries.map((entry, i) => (
          <div key={i} className={`compare-pdf__diff-line compare-pdf__diff-line--${entry.op}`}>
            {entry.text || " "}
          </div>
        ))}
      </div>
    );
  }

  function renderVisual(pageNumber) {
    const data = visualByPage[pageNumber];
    if (!data) return null;
    if (data === "loading") return <p className="compare-pdf__visual-status">Loading visual diff…</p>;
    if (data.error) return <p className="compare-pdf__visual-status">{data.error}</p>;
    return (
      <div className="compare-pdf__visual-pair">
        {[data.image_a, data.image_b].map((src, i) => (
          <div key={i} className="compare-pdf__visual-image-wrap">
            <img src={src} alt={`Page ${pageNumber}, document ${i === 0 ? "A" : "B"}`} />
            {data.boxes.map((box, bi) => (
              <div
                key={bi}
                className="compare-pdf__diff-box"
                style={{
                  left: `${box.x0 * 100}%`,
                  top: `${box.y0 * 100}%`,
                  width: `${(box.x1 - box.x0) * 100}%`,
                  height: `${(box.y1 - box.y0) * 100}%`,
                }}
              />
            ))}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="compare-pdf">
      <button className="tool-view__back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} weight="bold" />
        Back
      </button>
      <h1>Compare PDF</h1>

      <div className="compare-pdf__pickers">
        <label className="tool-view__upload">
          <UploadSimple size={18} weight="regular" />
          {fileA ? fileA.filename : "Choose the first PDF…"}
          <input type="file" accept=".pdf" onChange={(e) => handlePick("a", e)} />
        </label>
        <label className="tool-view__upload">
          <UploadSimple size={18} weight="regular" />
          {fileB ? fileB.filename : "Choose the second PDF…"}
          <input type="file" accept=".pdf" onChange={(e) => handlePick("b", e)} />
        </label>
        <button className="run-button" disabled={!fileA || !fileB} onClick={handleCompare}>
          Compare
        </button>
      </div>

      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      {result && (
        <div className="compare-pdf__viewer">
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
            of {result.pages.length}
          </div>
          <div className="page-scroll-viewer__scroll">
            {result.pages.map((page, i) => {
              const pageNumber = i + 1;
              return (
                <div
                  key={pageNumber}
                  ref={(el) => {
                    containerRefsRef.current[pageNumber - 1] = el;
                  }}
                  data-page-number={pageNumber}
                  className="page-scroll-viewer__page compare-pdf__page"
                >
                  {page.has_counterpart ? (
                    <>
                      {renderTextDiff(page.text_diff)}
                      {renderVisual(pageNumber)}
                    </>
                  ) : (
                    <p className="compare-pdf__added-removed">
                      {pageNumber <= result.page_count_a && pageNumber > result.page_count_b
                        ? "Page removed (only in the first document)"
                        : "Page added (only in the second document)"}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Add CSS**

In `web/frontend/src/index.css`, add:

```css
.compare-pdf__pickers {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}

.compare-pdf__page {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
}

.compare-pdf__text-diff {
  font-family: monospace;
  font-size: 13px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  background: var(--color-card);
}

.compare-pdf__diff-line {
  white-space: pre-wrap;
}

.compare-pdf__diff-line--insert {
  background: rgba(47, 158, 68, 0.15);
  color: #2f9e44;
}

.compare-pdf__diff-line--delete {
  background: rgba(224, 49, 49, 0.15);
  color: #e03131;
  text-decoration: line-through;
}

.compare-pdf__visual-pair {
  display: flex;
  gap: var(--space-3);
}

.compare-pdf__visual-image-wrap {
  position: relative;
  flex: 1;
}

.compare-pdf__visual-image-wrap img {
  width: 100%;
  display: block;
}

.compare-pdf__diff-box {
  position: absolute;
  border: 2px solid #e03131;
  background: rgba(224, 49, 49, 0.15);
  pointer-events: none;
}

.compare-pdf__added-removed {
  font-style: italic;
  color: var(--color-muted-foreground);
  text-align: center;
  padding: var(--space-6);
}

.compare-pdf__visual-status {
  color: var(--color-muted-foreground);
  font-size: 13px;
}
```

- [ ] **Step 7: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 8: Manual browser check**

- The tool grid shows a "Compare PDF" tile under Edit; clicking it navigates to `/compare` and shows the dedicated two-file picker, not the generic `ToolView` layout.
- Upload two different PDFs, click Compare — each page shows a text-diff panel (added lines green, removed lines red/struck-through, unchanged plain) and, once scrolled into view, a side-by-side visual panel with red highlight boxes over the actually-differing regions.
- Upload two PDFs with different page counts — the trailing page(s) show the correct "Page added"/"Page removed" message with no visual panel.
- The "Page X of Y" box updates as you scroll, and typing a page number and pressing Enter jumps to it.
- Confirm no output appears in Recent Files after using this tool — nothing is written to history.

- [ ] **Step 9: Commit**

```bash
git add web/frontend/src/components/ComparePdfView.jsx web/frontend/src/api.js web/frontend/src/App.jsx web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx web/frontend/src/components/ToolGrid.jsx web/frontend/src/index.css
git commit -m "feat: add the Compare PDF frontend"
```

No `Co-Authored-By` trailer.

---

### Task 4: PDF→Markdown

**Files:**
- Modify: `app/core/pdf_ops.py`
- Modify: `web/backend/routes/tools.py`
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolGrid.jsx`
- Modify: `requirements.txt`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `pdf_to_markdown_zip(input_path: str, output_path: str) -> None` in `pdf_ops.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pdf_ops.py`, near the other conversion-style tests:

```python
def test_pdf_to_markdown_zip_contains_markdown_and_extracted_image(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 72), "My Heading", fontsize=24)
    page.insert_text((72, 120), "A paragraph of body text follows here.", fontsize=12)
    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    img_pix.set_rect(img_pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(72, 400, 172, 500), pixmap=img_pix)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.zip"
    pdf_to_markdown_zip(str(input_path), str(output_path))

    assert output_path.exists()
    with zipfile.ZipFile(output_path) as zf:
        names = zf.namelist()
        md_names = [n for n in names if n.endswith(".md")]
        image_names = [n for n in names if n.lower().endswith((".png", ".jpg", ".jpeg"))]
        assert len(md_names) == 1
        assert len(image_names) >= 1
        md_text = zf.read(md_names[0]).decode("utf-8")
        assert "My Heading" in md_text
        assert "A paragraph of body text follows here." in md_text
```

Add `import zipfile` to the top of `tests/test_pdf_ops.py` if it isn't already imported (check the current imports first).

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k pdf_to_markdown -v`
Expected: FAIL — `ImportError` (`pdf_to_markdown_zip` doesn't exist yet).

- [ ] **Step 3: Add `pdf_to_markdown_zip` to `pdf_ops.py`**

Add near the top of `app/core/pdf_ops.py`, with the other imports:

```python
import tempfile
import zipfile

import pymupdf4llm
```

Add the function (anywhere reasonable among the other top-level, non-`_`-prefixed conversion functions — e.g. near `render_page_thumbnail`):

```python
def pdf_to_markdown_zip(input_path: str, output_path: str) -> None:
    with tempfile.TemporaryDirectory() as image_dir:
        markdown_text = pymupdf4llm.to_markdown(input_path, write_images=True, image_path=image_dir)
        # pymupdf4llm embeds each image reference as an ABSOLUTE filesystem
        # path into image_dir (verified empirically: "![](C:/Users/.../
        # tmpXXXX/images/input.pdf-0001-01.png)") — meaningless once this zip
        # is extracted anywhere else. Images are stored FLAT at the zip's own
        # root, next to document.md, so rewriting each reference down to just
        # its filename makes the link correctly relative once extracted.
        image_dir_prefix = Path(image_dir).as_posix() + "/"
        markdown_text = markdown_text.replace(image_dir_prefix, "")
        with zipfile.ZipFile(output_path, "w") as zf:
            zf.writestr("document.md", markdown_text)
            for image_path in Path(image_dir).iterdir():
                zf.write(image_path, arcname=image_path.name)
```

(`Path` is already imported at the top of `pdf_ops.py` — confirm this before adding the function; if it's imported under a different alias, adjust accordingly.)

Also add a dedicated test asserting this rewrite actually happened — a separate test function from the one written in Step 1:

```python
def test_pdf_to_markdown_zip_rewrites_image_paths_as_relative(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    img_pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    img_pix.set_rect(img_pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(72, 400, 172, 500), pixmap=img_pix)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.zip"
    pdf_to_markdown_zip(str(input_path), str(output_path))

    with zipfile.ZipFile(output_path) as zf:
        md_names = [n for n in zf.namelist() if n.endswith(".md")]
        image_names = [n for n in zf.namelist() if n.lower().endswith((".png", ".jpg", ".jpeg"))]
        md_text = zf.read(md_names[0]).decode("utf-8")
        assert len(image_names) >= 1
        # The markdown's image reference must be exactly the bare filename of
        # an image actually present in this same zip — not an absolute path
        # pointing at a temp directory that no longer exists once extracted.
        image_name = image_names[0]
        assert f"]({image_name})" in md_text
        assert ":" not in md_text.split("![")[1].split(")")[0]  # no drive letter / absolute path leaked through
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_ops.py -k pdf_to_markdown -v`
Expected: PASS.

- [ ] **Step 5: Add the route**

In `web/backend/routes/tools.py`, find the imports from `app.core.pdf_ops` at the top and add
`pdf_to_markdown_zip` to that import list. This codebase's convention (confirmed by reading the
current file: `ToWordRequest`, `CompressRequest`, etc.) is one dedicated Pydantic model per route,
even when the shape is identical to another route's — no shared "single file" base model exists.
Follow that convention. Add near `ToWordRequest`/`to_word`:

```python
class PdfToMarkdownRequest(BaseModel):
    file_id: str


@router.post("/pdf-to-markdown")
def pdf_to_markdown_route(req: PdfToMarkdownRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_markdown", ext=".zip")
    pdf_to_markdown_zip(input_path, str(output_path))
    return _output_response([output_path], "PDF to Markdown", [Path(input_path).name])
```

- [ ] **Step 6: Register the frontend tool**

In `web/frontend/src/toolConfigs.js`, add:

```jsx
  "pdf-to-markdown": {
    title: "PDF to Markdown",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "pdf-to-markdown",
    previewNote: "PDF to Markdown extracts text and images — the result can't be previewed as a PDF page.",
    fields: [],
  },
```

In `web/frontend/src/components/ToolGrid.jsx`, add a `TOOL_ICONS` entry (reuse an already-imported icon suited to markdown/text export, e.g. `FileText` — check what's already imported from `@phosphor-icons/react` in this file first and either reuse an existing import or add one, matching the exact pattern the other entries already follow):

```jsx
const TOOL_ICONS = {
  // ...existing entries...
  "pdf-to-markdown": FileText,
};
```

- [ ] **Step 7: Add `pymupdf4llm` to `requirements.txt`**

Add a line `pymupdf4llm>=0.0.17` to `requirements.txt`.

Note (verified empirically while dispatching this task, not previously known when the spec/plan
were written): `pymupdf4llm` pulls in `pymupdf_layout`, `onnxruntime`, `protobuf`, and `networkx`
as transitive dependencies — a noticeably heavier install than the spec's "pure-Python wheel"
framing implied, though still no EXTERNAL system binary (everything is pip-installable). This
doesn't change this task's scope or the Phase 3 queue ordering (it's still lighter than a bundled
Tesseract/LibreOffice/Ghostscript), but is worth being aware of for the eventual PyInstaller
packaging step — `onnxruntime` in particular is a large wheel and may need an explicit
`--collect-all` entry when this app is eventually bundled, the same way `uvicorn`/`fastapi`/
`starlette` already are in `.github/workflows/release.yml`. Not this task's job to fix — just
flagging it in the report as a real installed-footprint change.

- [ ] **Step 8: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (194 before this task — 191 from Tasks 1-2 plus 3 from Task 3's frontend-only work not adding backend tests, so still 194 carried over; 196 expected after this task's 2 new tests).

- [ ] **Step 9: Verify the frontend build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 10: Manual browser check**

- The tool grid shows a "PDF to Markdown" tile under Convert.
- Upload a PDF with a heading, a paragraph, and an embedded image; Run; download the `.zip`.
- Open the downloaded `.zip` — confirm it contains a readable `.md` file whose text matches the source PDF's headings/paragraphs, and at least one image file.

- [ ] **Step 11: Commit**

```bash
git add app/core/pdf_ops.py web/backend/routes/tools.py web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx requirements.txt tests/test_pdf_ops.py
git commit -m "feat: add PDF to Markdown conversion"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (196).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (4 total), in order, none carrying a `Co-Authored-By` trailer (all are `feat:`).
- [ ] Confirm the "Compare PDF" and "PDF to Markdown" tiles both appear correctly in the tool grid, under the right categories, with real (non-fallback) icons.
