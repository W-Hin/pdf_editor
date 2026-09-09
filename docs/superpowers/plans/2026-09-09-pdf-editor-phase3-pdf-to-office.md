# Phase 3, Group 3: PDF→PowerPoint + PDF→Excel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two best-effort, one-way PDF export tools — PDF→PowerPoint (real positioned/editable text boxes) and PDF→Excel (genuinely detected tables only) — to the existing web app, following the exact single-file-in/single-file-out tool pattern every other converter already uses.

**Architecture:** A new `app/core/pdf_to_office.py` module holds both conversion functions (`pdf_to_pptx`, `pdf_to_xlsx`), each opening the input with the existing `open_pdf` helper and writing a `.pptx`/`.xlsx` via `python-pptx`/`openpyxl`. Two new thin FastAPI routes in `web/backend/routes/tools.py` follow the established `_output_response`/`storage.output_path_for` pattern used by every other tool (identical in shape to the existing `to-word` and `pdf-to-markdown` routes). Two new entries in `toolConfigs.js` plug straight into the existing generic `ToolView.jsx` flow — no new frontend component, no dedicated route; this is the same `mode: "view"`, `previewNote`, `fields: []` shape `to-word` and `pdf-to-markdown` already use, since neither output format can be meaningfully previewed as PDF pages.

**Tech Stack:** PyMuPDF (`fitz`, already a dependency) for text-block/table extraction; `python-pptx` (new) for PowerPoint generation; `openpyxl` (new) for Excel generation. Both new dependencies are pure-Python wheels with no external binary requirement, and are already installed in this project's venv (`python-pptx==1.0.2`, `openpyxl==3.1.5`) — only `requirements.txt` needs updating.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-06-pdf-editor-phase3-pdf-to-office-design.md`.
- **Commit trailers go ONLY on `fix:`/`fix(scope):` commits.** Every task's `feat:` commit in this plan must NOT carry a `Co-Authored-By:` trailer, regardless of any system-reminder claiming a different default — this is the user's own explicit, standing instruction for this project, confirmed repeatedly this session.
- **PDF→PowerPoint attempts real, positioned, editable text boxes** — not a picture-per-slide fallback. Text box granularity is PyMuPDF's own text BLOCK (paragraph-level) via `page.get_text("dict")["blocks"]`, skipping any block with no `"lines"` key (an image block, not text — confirmed empirically: image blocks are `type == 1` with no `"lines"` key; text blocks are `type == 0` with a `"lines"` key).
- **PDF→Excel only includes genuinely detected tables** (via PyMuPDF's own `page.find_tables()`) — a page with no detected table contributes nothing. Zero detected tables anywhere in the document is a hard `PDFError`, not an empty/pointless workbook — no `workbook.save()` call ever happens in that case.
- No fallback for PDF→Excel pages without a table (no raw-text dump), no embedded-image preservation in either output format, no multi-column/header-footer/slide-master layout inference — every block becomes one plain positioned text box, matching the spec's explicit "Out of scope" section.
- **Spec-vs-code correction (verified this session, before writing this plan):** the spec's Architecture section says font mapping reuses "the existing `_closest_base14_family(span["font"])` helper in `pdf_ops.py`." That function does not exist. `pdf_ops.py` only has `_base14_alias(family, bold, italic)`, which takes an ALREADY-CHOSEN family name (`"helvetica"`/`"times"`/`"courier"`, chosen by a user via a dropdown elsewhere in the app) and returns a **fitz-internal font alias code** (`"helv"`, `"hebo"`, etc.) meant for `page.insert_text()` — not a real font name, and not something that can guess a family from a raw detected font string like `"Helvetica-Bold"` or `"ArialMT"`. Task 1 below writes a small, new, self-contained `_closest_base14_family(font_name: str) -> str` helper **inside `pdf_to_office.py`** (not `pdf_ops.py` — it solves a different problem: guessing a family from an arbitrary embedded font name, not applying a user's explicit choice) plus a `_PPTX_FONT_NAMES` dict mapping the three families to real, widely-available font name strings (`"Arial"`, `"Times New Roman"`, `"Courier New"`) that `python-pptx`'s `run.font.name` actually uses. This does not change the spec's intent (map every span to the closest of the three base-14-style families) — it only corrects which code makes that decision, since no reusable version of it already exists.
- **Spec-vs-format correction (verified this session):** the spec's Architecture section says PDF→PowerPoint "creates a slide sized to match the page's own dimensions" — implying a per-page slide size. This is not possible: `.pptx`'s slide size (`prs.slide_width`/`prs.slide_height`) is a single **presentation-wide** setting, not a per-slide one — confirmed empirically (setting it again before a later `add_slide()` call silently resizes the *entire* deck, including already-added slides, once the file is saved and reopened). Task 1 below sets the presentation's slide size **once, from the first page's dimensions** — correct and lossless for the overwhelming common case of a uniform-page-size PDF (which is what the spec's own test list assumes: single-page and same-size fixtures throughout). A later page of a genuinely different size still gets a text-accurate slide (every text box is still positioned/sized in absolute EMU derived from that page's own bbox data) but the visible slide *canvas* stays fixed at page 1's dimensions — an honest best-effort limit consistent with the spec's own "low fidelity expected" framing, not a defect to engineer further around.
- 1pt = 12700 EMU (verified empirically: `pptx.util.Pt(1) == 12700`). Every position/size conversion in this plan uses `round(value_in_points * 12700)`, and every task's test assertions use the exact integers this produces for its fixture (also independently verified this session, not computed by hand).
- New dependencies for `requirements.txt`: `python-pptx>=1.0.2` (Task 1), `openpyxl>=3.1.5` (Task 2) — both already installed in this project's venv; no install step needed, just the pin.
- Backend tests follow this codebase's established house style (see `tests/test_pdf_repair.py`): build throwaway fixtures with `fitz` inside the test using `tmp_path`, assert exact/concrete values, comment any empirically-derived "magic number" with how it was verified.
- Frontend changes have no automated tests (established convention) — `npm run build` plus a manual browser checklist per task.
- Both new tools reuse the **existing** generic `ToolView.jsx` flow exactly as `to-word` and `pdf-to-markdown` already do: `mode: "view"`, a `previewNote` (no `preview` key at all — omitting it is what makes `ToolView.jsx`'s `renderPreview()` fall through to the plain `previewNote` + `PageGrid` branch), `fields: []`. **No new frontend component, no dedicated route, no changes to `ToolView.jsx`/`ToolGrid.jsx`'s routing logic** — only a new `TOOL_CONFIGS` entry and a new `TOOL_ICONS` entry per tool.
- Icons (verified present in the installed `@phosphor-icons/react` package): `FilePpt` for PDF→PowerPoint, `FileXls` for PDF→Excel.

---

### Task 1: PDF→PowerPoint (core logic + API route + frontend wiring)

**Files:**
- Create: `app/core/pdf_to_office.py`
- Create: `tests/test_pdf_to_office.py`
- Modify: `requirements.txt` — add `python-pptx>=1.0.2`
- Modify: `web/backend/routes/tools.py` — add `pdf_to_pptx` import, `ToPptxRequest` model, `pdf_to_pptx_route`
- Modify: `web/frontend/src/toolConfigs.js` — add `"pdf-to-pptx"` entry
- Modify: `web/frontend/src/components/ToolGrid.jsx` — add `FilePpt` import and `"pdf-to-pptx": FilePpt` entry

**Interfaces:**
- Consumes: `open_pdf(path: str) -> fitz.Document` from `app/core/pdf_ops.py` (already exists — raises `PDFError` for a missing/corrupt/encrypted file, matching every other converter in this codebase); `PDFError` from `app/core/errors.py`; `_output_response(paths, tool, source_filenames, message=None) -> dict` and `storage.output_path_for(stem, suffix, ext=".pdf") -> Path` from `web/backend/routes/tools.py` / `web/backend/storage.py` (both already exist, used unmodified).
- Produces: `pdf_to_pptx(input_path: str, output_path: str) -> None` in `app/core/pdf_to_office.py` — later consumed only by this task's own route (Task 2 does not import from this function, only adds its own `pdf_to_xlsx` to the same file). `POST /api/tools/pdf-to-pptx` accepting `{"file_id": str}`, returning the same `{"outputs": [...], "message": null}` shape every other tool route returns.

- [ ] **Step 1: Write the failing core-logic tests**

Create `tests/test_pdf_to_office.py`:

```python
import fitz
import pytest
from pptx import Presentation

from app.core.errors import PDFError
from app.core.pdf_to_office import pdf_to_pptx


def _make_text_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Heading Text", fontname="hebo", fontsize=24)
    page.insert_text((72, 200), "Body paragraph in times.", fontname="tiro", fontsize=12)
    doc.save(str(path))
    doc.close()


def test_pdf_to_pptx_creates_positioned_textboxes(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    assert output_path.exists()
    prs = Presentation(str(output_path))
    assert len(prs.slides) == 1
    shapes = list(prs.slides[0].shapes)
    assert len(shapes) == 2

    # Exact EMU values verified empirically against this exact fixture this
    # session (1pt = 12700 EMU, round(value_in_points * 12700)) — not
    # computed by hand.
    heading_shape = shapes[0]
    assert (heading_shape.left, heading_shape.top, heading_shape.width, heading_shape.height) == (
        914400,
        943864,
        1913839,
        419710,
    )
    heading_text = "".join(run.text for para in heading_shape.text_frame.paragraphs for run in para.runs)
    assert heading_text == "Heading Text"

    body_shape = shapes[1]
    assert (body_shape.left, body_shape.top, body_shape.width, body_shape.height) == (
        914400,
        2379523,
        1540764,
        203302,
    )
    body_text = "".join(run.text for para in body_shape.text_frame.paragraphs for run in para.runs)
    assert body_text == "Body paragraph in times."


def test_pdf_to_pptx_preserves_font_size_bold_and_family(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    shapes = list(prs.slides[0].shapes)

    heading_run = shapes[0].text_frame.paragraphs[0].runs[0]
    # "hebo" (bold Helvetica) -> PyMuPDF reports font "Helvetica-Bold", flags
    # bit 4 (16) set for bold, bit 1 (2) clear for italic — verified this
    # session against this exact fixture.
    assert int(heading_run.font.size) == 304800  # Pt(24)
    assert heading_run.font.bold is True
    assert heading_run.font.italic is False
    assert heading_run.font.name == "Arial"

    body_run = shapes[1].text_frame.paragraphs[0].runs[0]
    # "tiro" (plain Times) -> PyMuPDF reports font "Times-Roman", flags bit 2
    # (4, serifed) set, bold/italic bits clear.
    assert int(body_run.font.size) == 152400  # Pt(12)
    assert body_run.font.bold is False
    assert body_run.font.italic is False
    assert body_run.font.name == "Times New Roman"


def test_pdf_to_pptx_matches_slide_size_to_page_size(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_text_pdf(input_path)

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    # 612pt x 792pt (US Letter) -> round(612*12700), round(792*12700) —
    # verified empirically this session.
    assert (prs.slide_width, prs.slide_height) == (7772400, 10058400)


def test_pdf_to_pptx_skips_image_blocks(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(pix.irect, (255, 0, 0))
    page.insert_image(fitz.Rect(10, 10, 50, 50), pixmap=pix)
    page.insert_text((10, 100), "Some text", fontsize=12)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pptx"
    pdf_to_pptx(str(input_path), str(output_path))

    prs = Presentation(str(output_path))
    shapes = list(prs.slides[0].shapes)
    # Only the text block becomes a text box — the inserted image produces a
    # block with no "lines" key and is skipped entirely (confirmed
    # empirically this session: image blocks are type==1 with no "lines"
    # key; text blocks are type==0 with a "lines" key).
    assert len(shapes) == 1
    assert shapes[0].text_frame.paragraphs[0].runs[0].text == "Some text"


def test_pdf_to_pptx_raises_for_missing_file(tmp_path):
    with pytest.raises(PDFError):
        pdf_to_pptx(str(tmp_path / "does_not_exist.pdf"), str(tmp_path / "output.pptx"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_to_office.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.pdf_to_office'` (or `ImportError`).

- [ ] **Step 3: Implement `pdf_to_pptx`**

Create `app/core/pdf_to_office.py`:

```python
from pptx import Presentation
from pptx.util import Emu, Pt

from app.core.errors import PDFError
from app.core.pdf_ops import open_pdf

_EMU_PER_POINT = 12700

# Maps this codebase's three base-14-style families (the same three
# app/core/pdf_ops.py's _base14_alias already recognizes for user-chosen
# fonts) to real font name strings python-pptx's run.font.name expects.
# Distinct from _base14_alias: that function turns an ALREADY-CHOSEN family
# into a fitz-internal alias code ("helv", "hebo", ...) for page.insert_text()
# — not a real font name, and not something that can guess a family from a
# raw detected font string. This module needs the latter, which didn't
# already exist anywhere in the codebase.
_PPTX_FONT_NAMES = {
    "helvetica": "Arial",
    "times": "Times New Roman",
    "courier": "Courier New",
}


def _closest_base14_family(font_name: str) -> str:
    name = font_name.lower()
    if "courier" in name or "mono" in name:
        return "courier"
    if any(hint in name for hint in ("times", "serif", "georgia", "garamond", "cambria", "minion")):
        return "times"
    return "helvetica"


def pdf_to_pptx(input_path: str, output_path: str) -> None:
    doc = open_pdf(input_path)
    try:
        prs = Presentation()
        slide_size_set = False
        for page in doc:
            if not slide_size_set:
                # .pptx's slide size is presentation-wide, not per-slide (verified
                # empirically: re-setting it before a later add_slide() call
                # silently resizes the whole deck once saved and reopened) — set
                # it once, from the first page. Correct and lossless for the
                # common case of a uniform-page-size document; a later page of a
                # different size still gets text-accurate, absolutely-positioned
                # boxes, just against a canvas sized to page 1.
                prs.slide_width = Emu(round(page.rect.width * _EMU_PER_POINT))
                prs.slide_height = Emu(round(page.rect.height * _EMU_PER_POINT))
                slide_size_set = True

            slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" not in block:
                    continue  # an image block, not text
                x0, y0, x1, y1 = block["bbox"]
                textbox = slide.shapes.add_textbox(
                    Emu(round(x0 * _EMU_PER_POINT)),
                    Emu(round(y0 * _EMU_PER_POINT)),
                    Emu(round((x1 - x0) * _EMU_PER_POINT)),
                    Emu(round((y1 - y0) * _EMU_PER_POINT)),
                )
                text_frame = textbox.text_frame
                text_frame.word_wrap = True
                for line_index, line in enumerate(block["lines"]):
                    paragraph = text_frame.paragraphs[0] if line_index == 0 else text_frame.add_paragraph()
                    for span in line["spans"]:
                        run = paragraph.add_run()
                        run.text = span["text"]
                        run.font.size = Pt(span["size"])
                        flags = span["flags"]
                        run.font.bold = bool(flags & 16)
                        run.font.italic = bool(flags & 2)
                        run.font.name = _PPTX_FONT_NAMES[_closest_base14_family(span["font"])]
        prs.save(output_path)
    finally:
        doc.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_to_office.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_to_office.py tests/test_pdf_to_office.py requirements.txt
git commit -m "feat: add PDF to PowerPoint conversion"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

Before committing, add `python-pptx>=1.0.2` to `requirements.txt` (alongside the other pinned dependencies, e.g. next to `pikepdf>=9.0.0`).

- [ ] **Step 6: Add the API route**

In `web/backend/routes/tools.py`, add `pdf_to_pptx` to the existing `from app.core.pdf_to_office import ...` style import (create this new import line — nothing currently imports from `pdf_to_office`), and add the route after `pdf_to_markdown_route` (which ends around line 344):

```python
from app.core.pdf_to_office import pdf_to_pptx
```

```python
class ToPptxRequest(BaseModel):
    file_id: str


@router.post("/pdf-to-pptx")
def pdf_to_pptx_route(req: ToPptxRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "", ".pptx")
    pdf_to_pptx(input_path, str(output_path))
    return _output_response([output_path], "PDF to PowerPoint", [Path(input_path).name])
```

- [ ] **Step 7: Verify the backend test suite still passes**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, all tests including the 5 new ones and every pre-existing test.

- [ ] **Step 8: Add the frontend tool entry**

In `web/frontend/src/toolConfigs.js`, add a new entry to `TOOL_CONFIGS` (alongside `"pdf-to-markdown"`, in the `"Convert"` category group):

```javascript
  "pdf-to-pptx": {
    title: "PDF to PowerPoint",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "pdf-to-pptx",
    previewNote: "PDF to PowerPoint rebuilds positioned text boxes — complex layouts may not convert perfectly, and the result can't be previewed as a PDF page.",
    fields: [],
  },
```

In `web/frontend/src/components/ToolGrid.jsx`, add `FilePpt` to the existing `@phosphor-icons/react` import list, and add an entry to `TOOL_ICONS`:

```javascript
  "pdf-to-pptx": FilePpt,
```

- [ ] **Step 9: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: build succeeds with no errors.

Manual checklist (start both the backend and frontend dev servers):
1. Open the app, navigate to "PDF to PowerPoint" under the Convert category — confirm it appears with the `FilePpt` icon.
2. Upload a real multi-section PDF (e.g. a document with a heading and a couple of paragraphs). Confirm the `previewNote` renders and the page grid shows below it.
3. Click Run. Confirm a `.pptx` file downloads successfully.
4. Open the downloaded `.pptx` in an actual PowerPoint-compatible viewer. Confirm: the slide count matches the PDF's page count, text boxes appear roughly where the corresponding text sits on the original PDF page, and the text itself is genuinely selectable/editable (not a picture).

- [ ] **Step 10: Commit the route and frontend wiring**

```bash
git add web/backend/routes/tools.py web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx
git commit -m "feat: add PDF to PowerPoint's API route and frontend wiring"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 2: PDF→Excel (core logic + API route + frontend wiring)

**Files:**
- Modify: `app/core/pdf_to_office.py` — add `pdf_to_xlsx`
- Modify: `tests/test_pdf_to_office.py` — add the Excel tests
- Modify: `requirements.txt` — add `openpyxl>=3.1.5`
- Modify: `web/backend/routes/tools.py` — add `pdf_to_xlsx` import, `ToXlsxRequest` model, `pdf_to_xlsx_route`
- Modify: `web/frontend/src/toolConfigs.js` — add `"pdf-to-xlsx"` entry
- Modify: `web/frontend/src/components/ToolGrid.jsx` — add `FileXls` import and `"pdf-to-xlsx": FileXls` entry

**Interfaces:**
- Consumes: `open_pdf` and `PDFError` (same as Task 1); `_output_response`/`storage.output_path_for` (same as Task 1).
- Produces: `pdf_to_xlsx(input_path: str, output_path: str) -> None` in `app/core/pdf_to_office.py`. `POST /api/tools/pdf-to-xlsx` accepting `{"file_id": str}`, same response shape as every other tool route.

- [ ] **Step 1: Write the failing core-logic tests**

Append to `tests/test_pdf_to_office.py`:

```python
import openpyxl

from app.core.pdf_to_office import pdf_to_xlsx


def _draw_ruled_table(page, x0, y0, col_w, row_h, values):
    rows = len(values)
    cols = len(values[0])
    for r in range(rows + 1):
        page.draw_line((x0, y0 + r * row_h), (x0 + cols * col_w, y0 + r * row_h))
    for c in range(cols + 1):
        page.draw_line((x0 + c * col_w, y0), (x0 + c * col_w, y0 + rows * row_h))
    for r, row in enumerate(values):
        for c, val in enumerate(row):
            page.insert_text((x0 + c * col_w + 10, y0 + r * row_h + 20), val, fontsize=12)


def test_pdf_to_xlsx_extracts_detected_table(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _draw_ruled_table(page, 72, 100, 100, 30, [("A1", "B1"), ("A2", "B2")])
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    pdf_to_xlsx(str(input_path), str(output_path))

    assert output_path.exists()
    workbook = openpyxl.load_workbook(str(output_path))
    assert workbook.sheetnames == ["Page1_Table1"]
    sheet = workbook["Page1_Table1"]
    # Exact cell values verified empirically against this exact fixture this
    # session — PyMuPDF's find_tables()/extract() on a real ruled table.
    assert list(sheet.iter_rows(values_only=True)) == [("A1", "B1"), ("A2", "B2")]


def test_pdf_to_xlsx_skips_pages_without_tables(tmp_path):
    doc = fitz.open()
    text_page = doc.new_page(width=612, height=792)
    text_page.insert_text((72, 100), "Just plain text, no table here.", fontsize=12)
    table_page = doc.new_page(width=612, height=792)
    _draw_ruled_table(table_page, 72, 100, 100, 30, [("X1", "Y1"), ("X2", "Y2")])
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    pdf_to_xlsx(str(input_path), str(output_path))

    workbook = openpyxl.load_workbook(str(output_path))
    # Page 1 (text-only) contributes nothing; only page 2's table becomes a
    # sheet — verified empirically this session on this exact two-page shape.
    assert workbook.sheetnames == ["Page2_Table1"]
    assert list(workbook["Page2_Table1"].iter_rows(values_only=True)) == [("X1", "Y1"), ("X2", "Y2")]


def test_pdf_to_xlsx_raises_when_no_tables_found(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "No tables anywhere in this document.", fontsize=12)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.xlsx"
    with pytest.raises(PDFError):
        pdf_to_xlsx(str(input_path), str(output_path))
    assert not output_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_to_office.py -v`
Expected: FAIL with `ImportError: cannot import name 'pdf_to_xlsx'`.

- [ ] **Step 3: Implement `pdf_to_xlsx`**

Append to `app/core/pdf_to_office.py`:

```python
import openpyxl


def pdf_to_xlsx(input_path: str, output_path: str) -> None:
    doc = open_pdf(input_path)
    try:
        workbook = openpyxl.Workbook()
        workbook.remove(workbook.active)  # default blank sheet — replaced by real ones below
        table_count = 0
        for page_index, page in enumerate(doc, start=1):
            tables = page.find_tables()
            for table_index, table in enumerate(tables.tables, start=1):
                table_count += 1
                sheet = workbook.create_sheet(f"Page{page_index}_Table{table_index}")
                for row in table.extract():
                    sheet.append(row)
        if table_count == 0:
            raise PDFError("No tables found in this document.")
        workbook.save(output_path)
    finally:
        doc.close()
```

(Move the `import openpyxl` line to the top of the file alongside the existing imports rather than leaving it inline — this is just showing where the new code goes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_to_office.py -v`
Expected: PASS (all 8 tests: the 5 from Task 1 plus these 3).

- [ ] **Step 5: Commit**

```bash
git add app/core/pdf_to_office.py tests/test_pdf_to_office.py requirements.txt
git commit -m "feat: add PDF to Excel conversion"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

Before committing, add `openpyxl>=3.1.5` to `requirements.txt`.

- [ ] **Step 6: Add the API route**

In `web/backend/routes/tools.py`, add `pdf_to_xlsx` to the `pdf_to_office` import from Task 1:

```python
from app.core.pdf_to_office import pdf_to_pptx, pdf_to_xlsx
```

Add the route after `pdf_to_pptx_route`:

```python
class ToXlsxRequest(BaseModel):
    file_id: str


@router.post("/pdf-to-xlsx")
def pdf_to_xlsx_route(req: ToXlsxRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "", ".xlsx")
    pdf_to_xlsx(input_path, str(output_path))
    return _output_response([output_path], "PDF to Excel", [Path(input_path).name])
```

- [ ] **Step 7: Verify the backend test suite still passes**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, all tests including the 3 new ones and every pre-existing test.

- [ ] **Step 8: Add the frontend tool entry**

In `web/frontend/src/toolConfigs.js`, add a new entry to `TOOL_CONFIGS` (alongside `"pdf-to-pptx"`, in the `"Convert"` category group):

```javascript
  "pdf-to-xlsx": {
    title: "PDF to Excel",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "pdf-to-xlsx",
    previewNote: "PDF to Excel only includes pages with a detected table — the result can't be previewed as a PDF page.",
    fields: [],
  },
```

In `web/frontend/src/components/ToolGrid.jsx`, add `FileXls` to the existing `@phosphor-icons/react` import list, and add an entry to `TOOL_ICONS`:

```javascript
  "pdf-to-xlsx": FileXls,
```

- [ ] **Step 9: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: build succeeds with no errors.

Manual checklist:
1. Open the app, navigate to "PDF to Excel" under the Convert category — confirm it appears with the `FileXls` icon.
2. Upload a real PDF containing at least one ruled/bordered table (e.g. an invoice or a document with a data table). Click Run, confirm a `.xlsx` downloads.
3. Open the downloaded `.xlsx` in an actual spreadsheet viewer. Confirm one sheet per detected table, correctly named, with cell values matching the source table.
4. Upload a PDF with genuinely no tables (plain prose only). Click Run. Confirm the app shows a clear error ("No tables found in this document.") instead of downloading an empty file.

- [ ] **Step 10: Commit the route and frontend wiring**

```bash
git add web/backend/routes/tools.py web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx
git commit -m "feat: add PDF to Excel's API route and frontend wiring"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)
