# Phase 2 Group B: Images to PDF Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one new tool, "Images to PDF" — combine multiple JPG/PNG image files into a single
PDF, one image per A4 page, with a Fit (show whole image, letterboxed) or Fill (crop to cover the
page) choice and a live preview mocking up each image on an A4 page before running.

**Architecture:** One new core function computes a per-image target rect using standard
contain/cover geometry (verified empirically against this project's actual PyMuPDF version — see
Global Constraints) and inserts each image into a freshly created A4 page (portrait or landscape,
matching that image's own orientation) via `page.insert_image()`. No new upload or thumbnail
routes are needed: PyMuPDF already treats a raw JPG/PNG as a 1-page pseudo-document, so the
existing `/files` upload route and thumbnail route work on images unmodified (verified
empirically). The frontend reuses the Merge tool's multi-file upload pattern and Group A's
`{value, label}` select-option shape, adding a small new non-interactive preview component (no
drag/mouse logic needed, unlike Group A's `CropSelector`).

**Tech Stack:** Python/FastAPI/PyMuPDF backend (unchanged), React/Vite frontend (unchanged).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-02-pdf-editor-phase2-images-to-pdf-design.md` — read it
  first; this plan implements it exactly.
- Supported formats: JPG/JPEG and PNG only.
- One tool, not two — "Images to PDF" replaces both "JPG→PDF" and "Scan to PDF" from the original
  roadmap; there is no camera-capture concept anywhere in this plan.
- Every output page is a standard A4 page: portrait `595×842pt` when the source image is not
  wider than it is tall, landscape `842×595pt` when it is wider than it is tall.
- Fit vs Fill is one setting applied to the whole batch, not per-image. Fit = contain (whole image
  visible, letterboxed). Fill = cover (image scaled to cover the page, overflow clipped at the
  page boundary — verified empirically that `insert_image` clips overflow correctly with no extra
  code, see Task 1).
- **Verified empirically against this project's actual code before this plan was written** (not
  assumed from documentation): `app/core/pdf_ops.py`'s `open_pdf()`/`get_page_count()` and
  `render_page_thumbnail()` already work unmodified on a raw `.jpg`/`.png` file — confirmed by
  running them directly against a real JPG through the actual `app.core.pdf_ops` module. Do not
  add any image-specific branching to those functions or to `web/backend/routes/files.py` — none
  is needed, and adding any would be unrequested scope.
- All user-facing errors raise `app.core.errors.PDFError` — never a raw exception surfaced to the
  API layer.
- Every new backend function/route follows the exact patterns already established in
  `app/core/pdf_ops.py` (read `merge_pdfs` as the closest precedent) and
  `web/backend/routes/tools.py` (read the `merge` route as the closest precedent — multi-file,
  filename sanitization).
- No new frontend automated test infrastructure — frontend behavior is verified by manual browser
  testing at the end, matching every prior UI feature this project has shipped.

---

### Task 1: `images_to_pdf` — core function

**Files:**
- Modify: `app/core/pdf_ops.py`
- Test: `tests/test_pdf_ops.py`

**Interfaces:**
- Produces: `images_to_pdf(image_paths: list[str], output_path: str, fit_mode: str) -> None`,
  raising `PDFError` for an unrecognized `fit_mode` or an empty `image_paths` list.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pdf_ops.py` (add `images_to_pdf` to the existing
`from app.core.pdf_ops import ...` line):

```python
def test_images_to_pdf_single_image_produces_one_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    img_bytes = page.get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    assert result.page_count == 1
    result.close()


def test_images_to_pdf_mixed_orientation_pages(tmp_path):
    doc = fitz.open()
    portrait_bytes = doc.new_page(width=300, height=400).get_pixmap().tobytes("png")
    landscape_bytes = doc.new_page(width=400, height=300).get_pixmap().tobytes("png")
    doc.close()
    portrait_path = tmp_path / "portrait.png"
    landscape_path = tmp_path / "landscape.png"
    portrait_path.write_bytes(portrait_bytes)
    landscape_path.write_bytes(landscape_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(portrait_path), str(landscape_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    assert result.page_count == 2
    assert result[0].rect.width < result[0].rect.height  # portrait image -> portrait page
    assert result[1].rect.width > result[1].rect.height  # landscape image -> landscape page
    result.close()


def test_images_to_pdf_fit_mode_does_not_overflow_page(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=500, height=600).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fit")

    result = fitz.open(str(output_path))
    result_page = result[0]
    bbox = result_page.get_image_bbox(result_page.get_images(full=True)[0])
    assert bbox.width <= result_page.rect.width + 0.01
    assert bbox.height <= result_page.rect.height + 0.01
    result.close()


def test_images_to_pdf_fill_mode_covers_page(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=500, height=600).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    images_to_pdf([str(img_path)], str(output_path), fit_mode="fill")

    result = fitz.open(str(output_path))
    result_page = result[0]
    bbox = result_page.get_image_bbox(result_page.get_images(full=True)[0])
    assert bbox.width >= result_page.rect.width - 0.01
    assert bbox.height >= result_page.rect.height - 0.01
    result.close()


def test_images_to_pdf_rejects_unknown_fit_mode(tmp_path):
    doc = fitz.open()
    img_bytes = doc.new_page(width=400, height=300).get_pixmap().tobytes("png")
    doc.close()
    img_path = tmp_path / "photo.png"
    img_path.write_bytes(img_bytes)

    output_path = tmp_path / "combined.pdf"
    with pytest.raises(PDFError):
        images_to_pdf([str(img_path)], str(output_path), fit_mode="stretch")


def test_images_to_pdf_rejects_empty_list(tmp_path):
    output_path = tmp_path / "combined.pdf"
    with pytest.raises(PDFError):
        images_to_pdf([], str(output_path), fit_mode="fit")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k images_to_pdf -v`
Expected: FAIL — `images_to_pdf` doesn't exist yet.

- [ ] **Step 3: Implement `images_to_pdf`**

Add to `app/core/pdf_ops.py`, after `crop_pdf` and `add_page_numbers` (keep the newest functions
grouped at the end, matching how each Phase 2 addition has been appended so far):

```python
def images_to_pdf(image_paths: list[str], output_path: str, fit_mode: str) -> None:
    if fit_mode not in ("fit", "fill"):
        raise PDFError(f"Unknown fit mode: {fit_mode}")
    if not image_paths:
        raise PDFError("Select at least one image.")
    result = fitz.open()
    try:
        for path in image_paths:
            doc = open_pdf(path)
            try:
                img_rect = doc[0].rect
            finally:
                doc.close()
            img_w, img_h = img_rect.width, img_rect.height
            page_w, page_h = (842, 595) if img_w > img_h else (595, 842)
            page = result.new_page(width=page_w, height=page_h)
            img_aspect = img_w / img_h
            page_aspect = page_w / page_h
            if fit_mode == "fit":
                if img_aspect > page_aspect:
                    target_w, target_h = page_w, page_w / img_aspect
                else:
                    target_h, target_w = page_h, page_h * img_aspect
            else:
                if img_aspect > page_aspect:
                    target_h, target_w = page_h, page_h * img_aspect
                else:
                    target_w, target_h = page_w, page_w / img_aspect
            x0 = (page_w - target_w) / 2
            y0 = (page_h - target_h) / 2
            page.insert_image(fitz.Rect(x0, y0, x0 + target_w, y0 + target_h), filename=path)
        result.save(output_path)
    finally:
        result.close()
```

`open_pdf(path)` already works on a raw `.jpg`/`.png` file — this is verified, not assumed (see
Global Constraints). Do not add any format-detection or image-specific branching here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -k images_to_pdf -v`
Expected: 6 PASS.

- [ ] **Step 5: Run the full core test suite**

Run: `venv/Scripts/python -m pytest tests/test_pdf_ops.py -v`
Expected: all PASS (no regressions).

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_ops.py tests/test_pdf_ops.py
git commit -m "feat: add images_to_pdf core function"
```

---

### Task 2: `/tools/images-to-pdf` route

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `images_to_pdf` from Task 1 (exact signature above).
- Produces: `POST /api/tools/images-to-pdf`, returning
  `{"outputs": [{"id": str, "filename": str, "download_url": str}]}` — the same shape every other
  tool endpoint already returns via `_output_response`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/web/test_tools_edit_convert.py`. This file's existing `_upload_pdf()` helper
only builds PDFs — add a sibling helper for images, and reuse it:

```python
def _upload_image(width=400, height=300, filename="photo.png"):
    doc = fitz.open()
    img_bytes = doc.new_page(width=width, height=height).get_pixmap().tobytes("png")
    doc.close()
    return client.post(
        "/api/files", files={"file": (filename, img_bytes, "image/png")}
    ).json()


def test_images_to_pdf_returns_one_output():
    upload1 = _upload_image(filename="a.png")
    upload2 = _upload_image(filename="b.png")
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload1["id"], upload2["id"]], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].endswith(".pdf")


def test_images_to_pdf_rejects_empty_file_ids():
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [], "filename": "combined", "fit_mode": "fit"},
    )
    assert response.status_code == 422


def test_images_to_pdf_rejects_unknown_fit_mode():
    upload = _upload_image()
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload["id"]], "filename": "combined", "fit_mode": "stretch"},
    )
    assert response.status_code == 422


def test_images_to_pdf_rejects_empty_filename():
    upload = _upload_image()
    response = client.post(
        "/api/tools/images-to-pdf",
        json={"file_ids": [upload["id"]], "filename": "  ", "fit_mode": "fit"},
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -k images_to_pdf -v`
Expected: FAIL with 404 (the route doesn't exist yet).

- [ ] **Step 3: Implement the route**

In `web/backend/routes/tools.py`, add `images_to_pdf` to the existing
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
    remove_pages,
    render_to_images,
    reorder_pages,
    rotate_pages,
    split_pdf,
)
```

Then add, after the `to-word` route (keeping Convert-category tools grouped together at the end
of the file):

```python
class ImagesToPdfRequest(BaseModel):
    file_ids: list[str]
    filename: str
    fit_mode: str


@router.post("/images-to-pdf")
def images_to_pdf_route(req: ImagesToPdfRequest):
    input_paths = [str(storage.resolve_file(fid)) for fid in req.file_ids]
    filename = req.filename.strip()
    if not filename:
        raise PDFError("Enter an output filename.")
    if any(sep in filename for sep in ("/", "\\", ":")):
        raise PDFError("Output filename must be a plain file name, not a path.")
    if filename.lower().endswith(".pdf"):
        filename = filename[: -len(".pdf")]
    output_path = storage.output_path_for(filename, "")
    images_to_pdf(input_paths, str(output_path), fit_mode=req.fit_mode)
    source_names = [Path(p).name for p in input_paths]
    return _output_response([output_path], "Images to PDF", source_names)
```

This is the `merge` route's filename-sanitization logic, copied verbatim — keep it identical, do
not simplify or diverge from it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full test suite**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_edit_convert.py
git commit -m "feat: add /tools/images-to-pdf route"
```

---

### Task 3: Frontend — tool config and shared upload-flow generalization

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolView.jsx`

**Interfaces:**
- Produces: two new optional `toolConfigs.js` fields consumed by `ToolView.jsx` —
  `fileAccept` (a string for the upload `<input accept=...>`, defaulting to `.pdf` when a tool
  doesn't set it) and `fileTypeLabel` (a string used in the upload button's text, defaulting to
  `"PDF"` when a tool doesn't set it).

**This task changes shared code every existing tool also uses — read carefully.** The upload
`<input>`'s `accept` attribute and the upload button's label text are currently hardcoded to
`.pdf` / `"PDF"` in `ToolView.jsx`, and `handleFilePick`'s auto-fill-filename logic strips a
trailing `.pdf` extension via a PDF-specific regex. All three need to become generic so this tool
(the first ever to accept non-PDF uploads) can use them, **without changing behavior for any of
the eleven existing PDF-only tools**, which never set `fileAccept`/`fileTypeLabel` and always
upload files ending in `.pdf`.

- [ ] **Step 1: Add the `images-to-pdf` tool config**

In `web/frontend/src/toolConfigs.js`, add a new entry (category `"Convert"`, alongside
`"to-images"` and `"to-word"`):

```javascript
"images-to-pdf": {
  title: "Images to PDF",
  category: "Convert",
  multiFile: true,
  mode: "view",
  preview: "images-to-pdf",
  endpoint: "images-to-pdf",
  fileAccept: ".jpg,.jpeg,.png",
  fileTypeLabel: "image",
  filenameSuffix: "_combined",
  fields: [
    { name: "filename", label: "Output filename", type: "text", default: "" },
    {
      name: "fit_mode",
      label: "Fit mode",
      type: "select",
      options: [
        { value: "fit", label: "Fit (show the whole image)" },
        { value: "fill", label: "Fill (crop to fill the page)" },
      ],
      default: "fit",
    },
  ],
},
```

- [ ] **Step 2: Generalize the upload `<input>`'s `accept` attribute**

In `web/frontend/src/components/ToolView.jsx`, find:

```jsx
<input type="file" accept=".pdf" multiple={config.multiFile} onChange={handleFilePick} />
```

Replace with:

```jsx
<input
  type="file"
  accept={config.fileAccept ?? ".pdf"}
  multiple={config.multiFile}
  onChange={handleFilePick}
/>
```

- [ ] **Step 3: Generalize the upload button's label text**

Find:

```jsx
{config.multiFile ? "Add PDF file(s)…" : "Choose a PDF file…"}
```

Replace with:

```jsx
{config.multiFile
  ? `Add ${config.fileTypeLabel ?? "PDF"} file(s)…`
  : `Choose a ${config.fileTypeLabel ?? "PDF"} file…`}
```

- [ ] **Step 4: Generalize the filename auto-fill's extension-strip regex**

Find, inside `handleFilePick`:

```javascript
filename: primary.filename.replace(/\.pdf$/i, "") + config.filenameSuffix,
```

Replace with:

```javascript
filename: primary.filename.replace(/\.[^.]+$/, "") + config.filenameSuffix,
```

`\.[^.]+$` strips any trailing extension (a dot followed by one-or-more non-dot characters at the
end of the string) instead of only `.pdf`. For every existing tool, every uploaded file's name
still ends in exactly `.pdf`, so this produces byte-identical results to the old regex for all
eleven existing tools — this is purely additive for this new tool's `.jpg`/`.png` uploads.

- [ ] **Step 5: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors. (There is no `"images-to-pdf"` preview branch yet — Task 4 —
so `renderPreview()` falls through to the default `PageGrid` branch for this tool for now; that's
fine, it isn't wired into a user-facing route change yet from this task's perspective, it's just
config + shared-mechanism plumbing.)

- [ ] **Step 6: Self-review the backward-compatibility claim**

Read back your changes to Steps 2-4 and trace them for one existing tool (e.g. Merge,
`config.fileAccept` and `config.fileTypeLabel` both undefined): confirm
`config.fileAccept ?? ".pdf"` evaluates to `".pdf"`, confirm the label text evaluates to the
exact same string as before (`"Add PDF file(s)…"`), and confirm
`"report.pdf".replace(/\.[^.]+$/, "")` produces `"report"` — identical to the old
`"report.pdf".replace(/\.pdf$/i, "")`.

- [ ] **Step 7: Run the full backend test suite (confirm no regressions)**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS (this task touched no backend code, but confirm nothing else broke).

- [ ] **Step 8: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolView.jsx
git commit -m "feat: add Images to PDF config, generalize upload accept/label/filename-strip"
```

---

### Task 4: Frontend — A4 Fit/Fill preview

**Files:**
- Create: `web/frontend/src/components/ImagePagePreview.jsx`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: `thumbnailUrl(fileId, pageNumber)` from `api.js` (unchanged, 2-argument form — no
  need for the higher-resolution 3-argument form Group A added for Crop, since these thumbnails
  are shown at grid-thumbnail size here, not full preview size).
- Produces: `<ImagePagePreview fileId={string} fitMode={"fit"|"fill"}>` — a single, non-
  interactive preview box for one uploaded image, sized to A4 portrait or landscape (detected
  from the image's own loaded dimensions) with the image fitted or filled inside it via CSS.

- [ ] **Step 1: Create `ImagePagePreview.jsx`**

Create `web/frontend/src/components/ImagePagePreview.jsx`:

```jsx
import { useState } from "react";
import { thumbnailUrl } from "../api";

export default function ImagePagePreview({ fileId, fitMode }) {
  const [orientation, setOrientation] = useState("portrait");

  function handleLoad(e) {
    const { naturalWidth: w, naturalHeight: h } = e.target;
    if (!w || !h) return;
    setOrientation(w > h ? "landscape" : "portrait");
  }

  return (
    <div className={`image-page-preview image-page-preview--${orientation}`}>
      <img
        src={thumbnailUrl(fileId, 1)}
        alt=""
        onLoad={handleLoad}
        style={{ objectFit: fitMode === "fill" ? "cover" : "contain" }}
      />
    </div>
  );
}
```

This is the same natural-size-on-load technique `PageGrid.jsx`'s `handleImageLoad` already uses
for Rotate's fit-scaling (see Global Constraints / the spec's Frontend section) — the box starts
portrait by default and corrects to landscape once the image has actually loaded and its real
dimensions are known.

- [ ] **Step 2: Add the CSS**

In `web/frontend/src/index.css`, add a new section (near the Page Grid / Crop selector sections):

```css
/* ---------- Image page preview (Images to PDF) ---------- */

.image-page-preview {
  width: 220px;
  max-width: 100%;
  margin: 0 auto;
  background: white;
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius);
  overflow: hidden;
}

.image-page-preview--portrait {
  aspect-ratio: 595 / 842;
}

.image-page-preview--landscape {
  aspect-ratio: 842 / 595;
}

.image-page-preview img {
  width: 100%;
  height: 100%;
  display: block;
}
```

- [ ] **Step 3: Add the `images-to-pdf` preview branch**

In `web/frontend/src/components/ToolView.jsx`, add the import near the top:

```javascript
import ImagePagePreview from "./ImagePagePreview";
```

Add a new branch inside `renderPreview()`, directly after the `crop` branch:

```jsx
if (config.preview === "images-to-pdf") {
  if (files.length === 0) return null;
  const fitMode = fieldValues.fit_mode ?? "fit";
  return files.map((f) => (
    <div key={f.id} className="preview-group">
      <div className="preview-group__label">
        <FilePdf size={14} weight="fill" />
        {f.filename}
      </div>
      <ImagePagePreview fileId={f.id} fitMode={fitMode} />
    </div>
  ));
}
```

This reuses the existing `.preview-group`/`.preview-group__label` classes (already used by
Merge's and Split's preview branches) and the already-imported `FilePdf` icon — no new imports
beyond `ImagePagePreview` itself.

- [ ] **Step 4: Build the frontend and check for errors**

Run:
```bash
cd web/frontend
npm run build
cd ../..
```
Expected: clean build, no errors.

- [ ] **Step 5: Run the full backend test suite (confirm no regressions)**

Run: `venv/Scripts/python -m pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add web/frontend/src/components/ImagePagePreview.jsx web/frontend/src/components/ToolView.jsx web/frontend/src/index.css
git commit -m "feat: add A4 Fit/Fill live preview for Images to PDF"
```

---

## Final Verification (done by the controller, not a dispatched task)

After all four tasks land:

1. Run the full test suite once more: `venv/Scripts/python -m pytest -q` — expect all green.
2. Rebuild the frontend (`cd web/frontend && npm run build`) and launch the dev server
   (`venv/Scripts/python -m uvicorn web.backend.main:app --host 127.0.0.1 --port 8756`).
3. Manually verify in the browser: upload 2-3 JPG/PNG images of different sizes and orientations
   (at least one portrait, one landscape), confirm the upload button says "Add image file(s)…"
   (not "Add PDF file(s)…"), confirm each preview box shows the correct A4 orientation and the
   chosen Fit/Fill behavior visually (switch the dropdown and confirm the preview updates), run
   it, download the result, and confirm (via a quick script or PyMuPDF check) the output has the
   right page count, page orientations, and roughly the expected image placement per page.
4. Confirm no existing tool regressed: spot-check Merge or Rotate still shows "Add PDF file(s)…" /
   "Choose a PDF file…" and still only accepts `.pdf` uploads.
5. Rebuild the packaged PyInstaller exe and smoke-test it launches and serves the new tool.
6. Push to `main`.
