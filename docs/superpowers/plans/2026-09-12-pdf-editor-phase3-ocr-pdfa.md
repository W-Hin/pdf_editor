# Phase 3, Group 4: OCR + PDF-to-PDF/A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new tools to the web app — OCR PDF (make a scanned/image-only PDF searchable) and PDF to PDF/A (convert to the archival-standard format) — both implemented via the `ocrmypdf` library, with Tesseract and Ghostscript vendored directly into the app so no separate install is required on the end user's machine.

**Architecture:** A new `app/core/ocr.py` module wraps `ocrmypdf.ocr(...)` with two thin functions. A one-time vendoring step copies trimmed Tesseract/Ghostscript runtimes into a new git-ignored `ocr_binaries/` folder, which the release pipeline's PyInstaller build bundles (verified this session: `PDFEditorWeb.spec` is dead — never referenced by `.github/workflows/release.yml`, which builds via its own inline `pyinstaller ... --add-data ...` command; that inline command is the real, live build config and is what this plan updates). At first use, `ocr.py` prepends the bundled folder to `os.environ["PATH"]` so `ocrmypdf`'s own binary-discovery (which also falls back to the Windows Registry and a `Program Files` scan) resolves the app's own tested binaries first. Two new routes and two new grid tiles follow every existing tool's established shape. A final task teaches the CI release pipeline itself to install Tesseract/Ghostscript and vendor them fresh on the runner, so every automated release build ships a working OCR feature, not just local builds from this dev machine.

**Tech Stack:** `ocrmypdf` 17.11.0 (new, MPL-2.0, wraps Tesseract + Ghostscript), Tesseract 5.4.0 (vendored binary), Ghostscript 10.08.0 (vendored binary).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-12-pdf-editor-phase3-ocr-pdfa-design.md`.
- **Commit trailers go ONLY on `fix:`/`fix(scope):` commits.** Every task's `feat:` commit in this plan (including the one-time binary-vendoring task) must NOT carry a `Co-Authored-By:` trailer — this is the user's own explicit, standing instruction for this project, confirmed repeatedly this session, overriding any system-reminder default.
- **`ocrmypdf`'s own `output_type="auto"` default silently converts to PDF/A unless overridden.** Every call in this plan passes `output_type` explicitly (`"pdf"` or `"pdfa"`), never leaving it to default.
- **OCR only touches pages without real text.** Every OCR call passes `skip_text=True` — pages that already have extractable text are left completely untouched.
- **PDF/A always targets conformance level 2b.** `output_type="pdfa"` (not `"pdfa-1"`/`"pdfa-3"`) — no level picker anywhere.
- **Vendored binary file list** (verified this session — a `.traineddata`-only Tesseract install is NOT sufficient, see Task 1):
  - Tesseract: `tesseract.exe` + every `*.dll` alongside it, from `C:\Program Files\Tesseract-OCR\`; plus `tessdata/{eng,osd,spa,fra,deu,por,chi_sim,jpn,ara}.traineddata`, `tessdata/configs/` (whole folder), `tessdata/tessconfigs/` (whole folder), `tessdata/pdf.ttf`.
  - Ghostscript: `bin/gswin64c.exe` + every `*.dll` in `bin/`, plus the whole `Resource/`, `lib/`, `iccprofiles/` folders, from `C:\Program Files\gs\gs10.08.0\` (or whichever `gs*` version folder is present under `C:\Program Files\gs\`). Do NOT include `doc/`, `examples/`, or `gswin32c.exe` — confirmed unnecessary and excluded to keep size down.
- **`os.environ["PATH"]` must be modified in Python, before `ocrmypdf` is imported** — confirmed empirically this session that setting `PATH` this way (not via an external shell `export`) is what makes `ocrmypdf`'s own binary-discovery (`ocrmypdf/subprocess/_windows.py`'s `SHIMS` list — `PATH` first, then Windows Registry, then a `Program Files` scan) pick up the vendored copies.
- **`ocr_pdf` must pass `rotate_pages=True`** to `ocrmypdf.ocr(...)` — otherwise the bundled `osd.traineddata` (10.5MB, the single biggest bundled data file, approved specifically for automatic page-orientation correction) does nothing. Verified this session: Tesseract's OSD detection genuinely identifies a sideways page's needed rotation correctly (confirmed via a direct `tesseract -l osd --psm 0` call), and `ocrmypdf`'s pipeline correctly applies it (confirmed via its own debug log: `"page is facing ⇦ ... will rotate"`, and the resulting PDF page carries a real, correctly-embedded, properly-referenced searchable text layer — a genuine Form XObject with an embedded font and `ToUnicode` map, confirmed by inspecting the raw PDF object structure). **One known testing gotcha, not a product defect**: `page.get_text()` (PyMuPDF) does not reliably surface text from an OCR'd page that ALSO carries a `PDF /Rotate` attribute — confirmed this only affects pages that got auto-rotated by this feature, not general OCR (a plain page with `/Rotate` and ordinary visible text extracts correctly with `get_text()`; the empty-result behavior is specific to the combination of a `/Rotate`-attributed page and ocrmypdf's Form-XObject-wrapped invisible text layer). Because of this, **no automated test in this plan exercises rotation-correction specifically** (the spec's own Testing section never required one) — Task 5's manual checklist covers it instead. This is a deliberate, informed scope decision, not an oversight — confirmed with the user directly.
- Backend tests follow this codebase's established house style (see `tests/test_pdf_repair.py`, `tests/test_pdf_to_office.py`): `tmp_path`-based fixtures built with `fitz`, real assertions, empirically-verified numbers, no mocking.
- Frontend changes have no automated tests (established convention) — `npm run build` plus a manual browser checklist per task.
- New dependency for `requirements.txt`: `ocrmypdf>=17.11.0` (already installed and verified in this project's venv).
- Icons (verified present in the installed `@phosphor-icons/react` package): `Scan` for OCR PDF, `Archive` for PDF to PDF/A.

---

### Task 1: Vendor the OCR binaries

**Files:**
- Create: `scripts/vendor_ocr_binaries.py`
- Create (git-ignored, generated by the script — not committed): `ocr_binaries/tesseract/`, `ocr_binaries/ghostscript/`
- Modify: `.gitignore` — add `ocr_binaries/`
- Modify: `.github/workflows/release.yml` — add `--add-data "ocr_binaries;ocr_binaries"` to the PyInstaller build step's inline command (Task 6 adds the separate step that populates `ocr_binaries/` on the CI runner itself — this task only wires the already-populated folder into the build once it exists)
- Test: `tests/test_ocr_binaries_vendored.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the first task).
- Produces: the on-disk `ocr_binaries/tesseract/tesseract.exe` and `ocr_binaries/ghostscript/bin/gswin64c.exe` paths that Task 2's `app/core/ocr.py` will resolve at runtime. The exact folder shape Task 2 depends on:
  ```
  ocr_binaries/
    tesseract/
      tesseract.exe
      *.dll
      tessdata/
        eng.traineddata, osd.traineddata, spa.traineddata, fra.traineddata,
        deu.traineddata, por.traineddata, chi_sim.traineddata, jpn.traineddata, ara.traineddata
        configs/   (whole folder, copied as-is)
        tessconfigs/   (whole folder, copied as-is)
        pdf.ttf
    ghostscript/
      bin/
        gswin64c.exe
        *.dll
      Resource/   (whole folder, copied as-is)
      lib/   (whole folder, copied as-is)
      iccprofiles/   (whole folder, copied as-is)
  ```

This task is a one-time file-vendoring operation from software already installed on this dev
machine, not a pip/npm dependency — there's no "write a failing test, then make it pass" cycle for
a file-copy script in the traditional sense. Instead: write the test FIRST (it will fail because
`ocr_binaries/` doesn't exist yet), then write and run the vendoring script to make it pass.

- [ ] **Step 1: Write the failing verification test**

Create `tests/test_ocr_binaries_vendored.py`:

```python
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TESSERACT_DIR = REPO_ROOT / "ocr_binaries" / "tesseract"
GHOSTSCRIPT_BIN_DIR = REPO_ROOT / "ocr_binaries" / "ghostscript" / "bin"


def test_vendored_tesseract_and_ghostscript_exist():
    assert (TESSERACT_DIR / "tesseract.exe").exists(), "Run scripts/vendor_ocr_binaries.py first."
    assert (GHOSTSCRIPT_BIN_DIR / "gswin64c.exe").exists(), "Run scripts/vendor_ocr_binaries.py first."
    assert (TESSERACT_DIR / "tessdata" / "eng.traineddata").exists()
    assert (TESSERACT_DIR / "tessdata" / "configs").is_dir()
    assert (TESSERACT_DIR / "tessdata" / "tessconfigs").is_dir()
    assert (TESSERACT_DIR / "tessdata" / "pdf.ttf").exists()


def test_vendored_binaries_run_standalone_with_isolated_path():
    # Prove the vendored copies are self-sufficient: run each with PATH set
    # to ONLY that binary's own folder (plus bare Windows system dirs needed
    # for basic DLL loading) - not the real system-wide installs.
    isolated_path = os.pathsep.join([str(TESSERACT_DIR), r"C:\Windows\system32", r"C:\Windows"])
    result = subprocess.run(
        [str(TESSERACT_DIR / "tesseract.exe"), "--version"],
        env={**os.environ, "PATH": isolated_path},
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "tesseract" in result.stdout.lower()

    isolated_path = os.pathsep.join([str(GHOSTSCRIPT_BIN_DIR), r"C:\Windows\system32", r"C:\Windows"])
    result = subprocess.run(
        [str(GHOSTSCRIPT_BIN_DIR / "gswin64c.exe"), "-dNODISPLAY", "-c", "quit"],
        env={**os.environ, "PATH": isolated_path},
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_vendored_ocrmypdf_end_to_end_with_isolated_path(tmp_path):
    # The definitive proof: ocrmypdf itself, with PATH pointing ONLY at the
    # vendored copies (set before ocrmypdf's own import, matching real app
    # startup order), produces correct OCR'd + PDF/A output using nothing
    # but the vendored binaries.
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Vendored binary isolation test.", fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    input_path = tmp_path / "input.pdf"
    scanned.save(str(input_path))
    scanned.close()
    doc.close()

    isolated_path = os.pathsep.join([
        str(TESSERACT_DIR), str(GHOSTSCRIPT_BIN_DIR), r"C:\Windows\system32", r"C:\Windows",
    ])
    output_path = tmp_path / "output.pdf"
    script = (
        "import os, sys\n"
        f"os.environ['PATH'] = {isolated_path!r}\n"
        "import ocrmypdf\n"
        f"ocrmypdf.ocr({str(input_path)!r}, {str(output_path)!r}, "
        "skip_text=True, output_type='pdfa', progress_bar=False)\n"
    )
    result = subprocess.run(["python", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert output_path.exists()

    check = fitz.open(str(output_path))
    assert "Vendored binary isolation test." in check[0].get_text()
    check.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_binaries_vendored.py -v`
Expected: FAIL — `ocr_binaries/tesseract/tesseract.exe` does not exist yet.

- [ ] **Step 3: Write the vendoring script**

Create `scripts/vendor_ocr_binaries.py`:

```python
"""One-time script to vendor trimmed Tesseract + Ghostscript runtimes into
ocr_binaries/ (git-ignored) for bundling into the PyInstaller build.

Run this once on a machine with Tesseract and Ghostscript installed via
their official installers (winget: UB-Mannheim.TesseractOCR; official
Artifex GitHub releases for Ghostscript). Re-run after bumping either
dependency's installed version.

Source locations expected (Windows default install paths):
  Tesseract:  C:\\Program Files\\Tesseract-OCR\\
  Ghostscript: C:\\Program Files\\gs\\gs<version>\\ (auto-detected by glob)
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST = REPO_ROOT / "ocr_binaries"

TESSERACT_SRC = Path(r"C:\Program Files\Tesseract-OCR")
TESSDATA_LANGUAGES = ["eng", "osd", "spa", "fra", "deu", "por", "chi_sim", "jpn", "ara"]

GS_ROOT = Path(r"C:\Program Files\gs")


def find_ghostscript_src() -> Path:
    candidates = sorted(GS_ROOT.glob("gs*"))
    if not candidates:
        sys.exit(f"No Ghostscript install found under {GS_ROOT} — install it first.")
    if len(candidates) > 1:
        print(f"Multiple Ghostscript versions found, using the last one: {candidates[-1]}")
    return candidates[-1]


def vendor_tesseract() -> None:
    if not TESSERACT_SRC.exists():
        sys.exit(f"Tesseract not found at {TESSERACT_SRC} — install it first (winget install UB-Mannheim.TesseractOCR).")
    dest = DEST / "tesseract"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    shutil.copy2(TESSERACT_SRC / "tesseract.exe", dest / "tesseract.exe")
    for dll in TESSERACT_SRC.glob("*.dll"):
        shutil.copy2(dll, dest / dll.name)

    tessdata_dest = dest / "tessdata"
    tessdata_dest.mkdir()
    for lang in TESSDATA_LANGUAGES:
        src_file = TESSERACT_SRC / "tessdata" / f"{lang}.traineddata"
        if not src_file.exists():
            sys.exit(f"Missing trained-data file: {src_file}")
        shutil.copy2(src_file, tessdata_dest / src_file.name)
    shutil.copytree(TESSERACT_SRC / "tessdata" / "configs", tessdata_dest / "configs")
    shutil.copytree(TESSERACT_SRC / "tessdata" / "tessconfigs", tessdata_dest / "tessconfigs")
    shutil.copy2(TESSERACT_SRC / "tessdata" / "pdf.ttf", tessdata_dest / "pdf.ttf")
    print(f"Vendored Tesseract -> {dest}")


def vendor_ghostscript() -> None:
    src = find_ghostscript_src()
    dest = DEST / "ghostscript"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    bin_dest = dest / "bin"
    bin_dest.mkdir()
    shutil.copy2(src / "bin" / "gswin64c.exe", bin_dest / "gswin64c.exe")
    for dll in (src / "bin").glob("*.dll"):
        shutil.copy2(dll, bin_dest / dll.name)

    shutil.copytree(src / "Resource", dest / "Resource")
    shutil.copytree(src / "lib", dest / "lib")
    shutil.copytree(src / "iccprofiles", dest / "iccprofiles")
    print(f"Vendored Ghostscript ({src.name}) -> {dest}")


if __name__ == "__main__":
    vendor_tesseract()
    vendor_ghostscript()
```

- [ ] **Step 4: Run the script**

Run: `./venv/Scripts/python.exe scripts/vendor_ocr_binaries.py`
Expected: prints `Vendored Tesseract -> ...` and `Vendored Ghostscript (gs10.08.0) -> ...`, and `ocr_binaries/` now contains both subfolders.

- [ ] **Step 5: Run the test to verify it passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_binaries_vendored.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 6: Add the `.gitignore` entry and wire the release build to include `ocr_binaries/`**

In `.gitignore`, add a line:
```
ocr_binaries/
```

In `.github/workflows/release.yml`, the `Build the standalone exe (PyInstaller)` step currently reads:
```yaml
      - name: Build the standalone exe (PyInstaller)
        run: >
          pyinstaller --name PDFEditorWeb --onedir --console
          --collect-all uvicorn --collect-all fastapi --collect-all starlette
          --add-data "web/frontend/dist;frontend/dist"
          --add-data "VERSION;."
          -y web/launch.py
```
Add one more `--add-data` line for the vendored OCR binaries, matching the existing two:
```yaml
      - name: Build the standalone exe (PyInstaller)
        run: >
          pyinstaller --name PDFEditorWeb --onedir --console
          --collect-all uvicorn --collect-all fastapi --collect-all starlette
          --add-data "web/frontend/dist;frontend/dist"
          --add-data "VERSION;."
          --add-data "ocr_binaries;ocr_binaries"
          -y web/launch.py
```
(Note: `PDFEditorWeb.spec` in the repo root is dead code — confirmed this session it's referenced nowhere, including not by this workflow, which builds via this inline command instead. This task does not touch that file. Task 6 adds the CI step that populates `ocr_binaries/` on the runner before this build step runs — without Task 6, this `--add-data` flag would point at a folder that doesn't exist on a fresh CI checkout, so both changes are needed together for a working release, though they're being made in separate tasks here since Task 6 also needs its own review as a meaningfully separate, CI-specific change.)

- [ ] **Step 7: Commit**

```bash
git add scripts/vendor_ocr_binaries.py tests/test_ocr_binaries_vendored.py .gitignore .github/workflows/release.yml
git commit -m "feat: vendor trimmed Tesseract and Ghostscript runtimes for OCR/PDF-A"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit. Note: `ocr_binaries/` itself is git-ignored and NOT part of this commit — only the script, test, and config changes are tracked; each machine that builds the installer runs the vendoring script itself, and Task 6 makes the CI runner do the same.)

---

### Task 2: `ocr_pdf` core logic

**Files:**
- Create: `app/core/ocr.py`
- Test: `tests/test_ocr.py`
- Modify: `requirements.txt` — add `ocrmypdf>=17.11.0`

**Interfaces:**
- Consumes: `ocr_binaries/tesseract/tesseract.exe` and `ocr_binaries/ghostscript/bin/gswin64c.exe` (Task 1's output, at the exact paths documented in Task 1's Interfaces). `PDFError` from `app/core/errors.py`.
- Produces: `_ensure_ocr_binaries_on_path() -> None` (module-private helper, prepends the resolved `ocr_binaries/` subfolders to `os.environ["PATH"]`, memoized so it only runs once per process) and `ocr_pdf(input_path: str, output_path: str, languages: list[str], convert_to_pdfa: bool) -> dict` (returns `{"pages_ocred": int, "pages_skipped": int}`) — both consumed by Task 3 (reuses `_ensure_ocr_binaries_on_path`) and Task 4 (calls `ocr_pdf`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ocr.py`:

```python
import os

import fitz
import pytest

from app.core.errors import PDFError
from app.core.ocr import ocr_pdf


def _make_image_only_pdf(path, text="This is a scanned-looking test page for OCR verification."):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    scanned.save(str(path))
    scanned.close()
    doc.close()


def test_ocr_pdf_adds_searchable_text_to_image_only_page(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    before = fitz.open(str(input_path))
    assert before[0].get_text().strip() == ""
    before.close()

    output_path = tmp_path / "output.pdf"
    result = ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert result == {"pages_ocred": 1, "pages_skipped": 0}
    after = fitz.open(str(output_path))
    assert "This is a scanned-looking test page for OCR verification." in after[0].get_text()
    after.close()


def test_ocr_pdf_skips_pages_that_already_have_text(tmp_path):
    image_page_pdf = tmp_path / "image_page.pdf"
    _make_image_only_pdf(image_page_pdf, text="Image page content.")

    doc = fitz.open()
    text_page = doc.new_page(width=612, height=792)
    text_page.insert_text((72, 100), "Already has real text.", fontsize=14)
    image_src = fitz.open(str(image_page_pdf))
    doc.insert_pdf(image_src)
    image_src.close()
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    result = ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert result == {"pages_ocred": 1, "pages_skipped": 1}
    after = fitz.open(str(output_path))
    assert "Already has real text." in after[0].get_text()
    assert "Image page content." in after[1].get_text()
    after.close()


def _has_pdfa_identifier(path: str) -> bool:
    # Verified this session: EVERY ocrmypdf output carries some XMP metadata,
    # even with output_type="pdf" — the presence of a /Metadata key alone
    # does NOT distinguish PDF/A from plain output. The genuine PDF/A marker
    # is the pdfaid:part/pdfaid:conformance fields inside that XMP stream,
    # confirmed present only in output_type="pdfa" output and absent from
    # output_type="pdf" output on the same input.
    doc = fitz.open(path)
    try:
        xml_metadata = doc.xref_get_key(doc.pdf_catalog(), "Metadata")
        if xml_metadata[0] == "null":
            return False
        meta_xref = int(xml_metadata[1].split()[0])
        content = doc.xref_stream(meta_xref)
        return b"pdfaid:part" in content
    finally:
        doc.close()


def test_ocr_pdf_with_pdfa_checkbox_produces_pdfa_metadata(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    output_path = tmp_path / "output.pdf"
    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=True)

    assert _has_pdfa_identifier(str(output_path))


def test_ocr_pdf_without_pdfa_checkbox_produces_plain_pdf(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    output_path = tmp_path / "output.pdf"
    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    assert not _has_pdfa_identifier(str(output_path))


def test_ocr_pdf_rejects_empty_language_list(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)

    with pytest.raises(PDFError):
        ocr_pdf(str(input_path), str(tmp_path / "output.pdf"), languages=[], convert_to_pdfa=False)


def test_ocr_pdf_uses_only_vendored_binaries(tmp_path, monkeypatch):
    # Prove the app's own PATH-prepending is what makes ocrmypdf use the
    # vendored binaries, not a lucky fallback to whatever's on this dev
    # machine's system-wide PATH/Registry/Program Files.
    import app.core.ocr as ocr_module

    ocr_module._binaries_ensured = False  # reset the memoization for this test
    monkeypatch.setenv("PATH", r"C:\Windows\system32;C:\Windows")

    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path)
    output_path = tmp_path / "output.pdf"

    ocr_pdf(str(input_path), str(output_path), languages=["eng"], convert_to_pdfa=False)

    after = fitz.open(str(output_path))
    assert "This is a scanned-looking test page for OCR verification." in after[0].get_text()
    after.close()
    assert str((__import__("pathlib").Path(__file__).resolve().parent.parent / "ocr_binaries" / "tesseract")) in os.environ["PATH"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.ocr'`.

- [ ] **Step 3: Implement `app/core/ocr.py`**

```python
import os
from pathlib import Path

import ocrmypdf
import ocrmypdf.exceptions

from app.core.errors import PDFError

_binaries_ensured = False


def _ocr_binaries_dir() -> Path:
    import sys

    if hasattr(sys, "_MEIPASS"):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent.parent.parent
    return base_dir / "ocr_binaries"


def _ensure_ocr_binaries_on_path() -> None:
    global _binaries_ensured
    if _binaries_ensured:
        return
    binaries_dir = _ocr_binaries_dir()
    tesseract_dir = binaries_dir / "tesseract"
    ghostscript_bin_dir = binaries_dir / "ghostscript" / "bin"
    if not (tesseract_dir / "tesseract.exe").exists() or not (ghostscript_bin_dir / "gswin64c.exe").exists():
        raise PDFError(
            "OCR is unavailable — required files are missing from this installation. "
            "Try reinstalling the app."
        )
    os.environ["PATH"] = os.pathsep.join([str(tesseract_dir), str(ghostscript_bin_dir), os.environ.get("PATH", "")])
    _binaries_ensured = True


def _count_pages_with_text(path: str) -> int:
    import fitz

    doc = fitz.open(path)
    try:
        return sum(1 for page in doc if page.get_text().strip())
    finally:
        doc.close()


def ocr_pdf(input_path: str, output_path: str, languages: list[str], convert_to_pdfa: bool) -> dict:
    if not languages:
        raise PDFError("Select at least one language.")
    _ensure_ocr_binaries_on_path()

    pages_with_text_before = _count_pages_with_text(input_path)
    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            language="+".join(languages),
            skip_text=True,
            rotate_pages=True,
            output_type="pdfa" if convert_to_pdfa else "pdf",
            progress_bar=False,
        )
    except ocrmypdf.exceptions.ExitCodeException as exc:
        raise PDFError(f"OCR failed: {exc}") from exc

    import fitz

    total_pages = fitz.open(input_path).page_count
    pages_skipped = pages_with_text_before
    pages_ocred = total_pages - pages_skipped
    return {"pages_ocred": pages_ocred, "pages_skipped": pages_skipped}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, all pre-existing tests plus the new ones.

- [ ] **Step 6: Commit**

Before committing, add `ocrmypdf>=17.11.0` to `requirements.txt` (alongside the other pinned dependencies).

```bash
git add app/core/ocr.py tests/test_ocr.py requirements.txt
git commit -m "feat: add OCR PDF core logic"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 3: `pdf_to_pdfa` core logic

**Files:**
- Modify: `app/core/ocr.py` — add `pdf_to_pdfa`
- Modify: `tests/test_ocr.py` — add the PDF/A-only tests

**Interfaces:**
- Consumes: `_ensure_ocr_binaries_on_path()` and `PDFError` (Task 2). Also reuses the `_has_pdfa_identifier(path: str) -> bool` test helper Task 2 already added to `tests/test_ocr.py` — since Task 3 appends to the same file, this helper is already in scope, no new import needed.
- Produces: `pdf_to_pdfa(input_path: str, output_path: str) -> None`, consumed by Task 4's `/pdf-to-pdfa` route.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ocr.py`:

```python
from app.core.ocr import pdf_to_pdfa


def test_pdf_to_pdfa_converts_text_only_document_without_ocr(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "This document already has real text.", fontsize=14)
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    output_path = tmp_path / "output.pdf"
    pdf_to_pdfa(str(input_path), str(output_path))

    assert output_path.exists()
    after = fitz.open(str(output_path))
    assert "This document already has real text." in after[0].get_text()
    after.close()
    assert _has_pdfa_identifier(str(output_path))


def test_pdf_to_pdfa_on_image_only_document_does_not_ocr(tmp_path):
    # pdf_to_pdfa is a pure format conversion - it must NOT add a text layer,
    # even to a page that has none (that's ocr_pdf's job, not this one's).
    input_path = tmp_path / "input.pdf"
    _make_image_only_pdf(input_path, text="Should not be OCR'd by pdf_to_pdfa.")

    output_path = tmp_path / "output.pdf"
    pdf_to_pdfa(str(input_path), str(output_path))

    after = fitz.open(str(output_path))
    assert after[0].get_text().strip() == ""
    after.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr.py -v`
Expected: FAIL — `ImportError: cannot import name 'pdf_to_pdfa'`.

- [ ] **Step 3: Implement `pdf_to_pdfa`**

Append to `app/core/ocr.py`:

```python
def pdf_to_pdfa(input_path: str, output_path: str) -> None:
    _ensure_ocr_binaries_on_path()
    try:
        ocrmypdf.ocr(
            input_path,
            output_path,
            skip_text=True,
            output_type="pdfa",
            progress_bar=False,
        )
    except ocrmypdf.exceptions.ExitCodeException as exc:
        raise PDFError(f"PDF/A conversion failed: {exc}") from exc
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr.py -v`
Expected: PASS (all 8 tests).

- [ ] **Step 5: Run the full suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/core/ocr.py tests/test_ocr.py
git commit -m "feat: add PDF to PDF/A conversion"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 4: API routes

**Files:**
- Modify: `web/backend/routes/tools.py` — add `ocr_pdf`/`pdf_to_pdfa` import, `OcrRequest`/`ocr_route`, `PdfToPdfaRequest`/`pdf_to_pdfa_route`

**Interfaces:**
- Consumes: `ocr_pdf(input_path, output_path, languages, convert_to_pdfa) -> dict` and `pdf_to_pdfa(input_path, output_path) -> None` (Tasks 2-3); `_output_response(paths, tool, source_filenames, message=None) -> dict` and `storage.output_path_for(stem, suffix, ext=".pdf") -> Path` (already exist, used unmodified).
- Produces: `POST /api/tools/ocr` and `POST /api/tools/pdf-to-pdfa`, consumed by Task 5's frontend wiring.

- [ ] **Step 1: Add the import**

In `web/backend/routes/tools.py`, add:
```python
from app.core.ocr import ocr_pdf, pdf_to_pdfa
```

- [ ] **Step 2: Add the OCR route**

Add after `pdf_to_xlsx_route` (or the last existing route):

```python
class OcrRequest(BaseModel):
    file_id: str
    languages: list[str]
    convert_to_pdfa: bool = False


@router.post("/ocr")
def ocr_route(req: OcrRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_ocr")
    result = ocr_pdf(input_path, str(output_path), req.languages, req.convert_to_pdfa)
    if result["pages_skipped"] == 0:
        message = f"OCR'd all {result['pages_ocred']} page{'s' if result['pages_ocred'] != 1 else ''}."
    else:
        message = (
            f"OCR'd {result['pages_ocred']} of {result['pages_ocred'] + result['pages_skipped']} pages "
            f"— {result['pages_skipped']} already had text."
        )
    return _output_response([output_path], "OCR PDF", [Path(input_path).name], message=message)
```

- [ ] **Step 3: Add the PDF-to-PDF/A route**

```python
class PdfToPdfaRequest(BaseModel):
    file_id: str


@router.post("/pdf-to-pdfa")
def pdf_to_pdfa_route(req: PdfToPdfaRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_pdfa")
    pdf_to_pdfa(input_path, str(output_path))
    return _output_response([output_path], "PDF to PDF/A", [Path(input_path).name])
```

- [ ] **Step 4: Add a route-level test**

Create `tests/web/test_ocr_routes.py` (matching the existing pattern in `tests/web/test_unlock_route.py` — a `TestClient` against the real FastAPI app):

```python
import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_image_only_pdf(text="Route test OCR content."):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=14)
    zoom = 300 / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    scanned = fitz.open()
    scanned_page = scanned.new_page(width=612, height=792)
    scanned_page.insert_image(scanned_page.rect, pixmap=pix)
    pdf_bytes = scanned.tobytes()
    scanned.close()
    doc.close()
    response = client.post("/api/files", files={"file": ("scan.pdf", pdf_bytes, "application/pdf")})
    return response.json()["id"]


def test_ocr_route_returns_success_message():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/ocr", json={"file_id": file_id, "languages": ["eng"], "convert_to_pdfa": False})
    assert response.status_code == 200
    data = response.json()
    assert "OCR'd" in data["message"]
    assert len(data["outputs"]) == 1


def test_ocr_route_rejects_empty_languages():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/ocr", json={"file_id": file_id, "languages": [], "convert_to_pdfa": False})
    assert response.status_code == 422


def test_pdf_to_pdfa_route_succeeds():
    file_id = _upload_image_only_pdf()
    response = client.post("/api/tools/pdf-to-pdfa", json={"file_id": file_id})
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1
```

- [ ] **Step 5: Run the new tests and the full suite**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_ocr_routes.py -v`
Expected: PASS (all 3 tests).

Run: `./venv/Scripts/python.exe -m pytest tests/ -q`
Expected: PASS, no regressions.

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_ocr_routes.py
git commit -m "feat: add OCR and PDF-to-PDF/A API routes"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 5: Frontend — two new field types + tool entries

**Files:**
- Modify: `web/frontend/src/components/ToolView.jsx` — add `"checkbox-group"` and `"checkbox"` field-type branches to the field-rendering `switch`, plus a generalized required-field check on the Run button
- Modify: `web/frontend/src/toolConfigs.js` — add `ocr` and `pdf-to-pdfa` entries
- Modify: `web/frontend/src/components/ToolGrid.jsx` — add `Scan`/`Archive` imports and `TOOL_ICONS` entries

**Interfaces:**
- Consumes: `POST /api/tools/ocr` and `POST /api/tools/pdf-to-pdfa` (Task 4).
- Produces: nothing further consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Add the two new tool configs**

In `web/frontend/src/toolConfigs.js`, add (alongside `protect`, in the `"Optimize"` category group):

```javascript
  ocr: {
    title: "OCR PDF",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    endpoint: "ocr",
    previewNote: "OCR adds an invisible, searchable text layer to scanned pages — the page's appearance doesn't change, so there's nothing meaningful to preview before running.",
    fields: [
      {
        name: "languages",
        label: "Language(s)",
        type: "checkbox-group",
        required: true,
        options: [
          { value: "eng", label: "English" },
          { value: "spa", label: "Spanish" },
          { value: "fra", label: "French" },
          { value: "deu", label: "German" },
          { value: "por", label: "Portuguese" },
          { value: "chi_sim", label: "Chinese (Simplified)" },
          { value: "jpn", label: "Japanese" },
          { value: "ara", label: "Arabic" },
        ],
        default: ["eng"],
      },
      {
        name: "convert_to_pdfa",
        label: "Also convert to PDF/A",
        type: "checkbox",
        tooltip: "PDF/A is a locked-down archival format designed for long-term storage — every font is embedded and nothing depends on external files, so the document is guaranteed to open identically in the future. Useful for legal, medical, or government records; not needed for everyday use.",
        default: false,
      },
    ],
  },
  "pdf-to-pdfa": {
    title: "PDF to PDF/A",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    endpoint: "pdf-to-pdfa",
    previewNote: "PDF/A converts the file's internal format for long-term archiving — it doesn't change how pages look, so there's nothing meaningful to preview before running.",
    fields: [],
  },
```

- [ ] **Step 2: Add the two new field-rendering branches to `ToolView.jsx`**

Replace the ENTIRE field-rendering block (from `{config.fields.map((field) => (` through the matching `))}`) — the current, complete block is:

```javascript
      {config.fields.map((field) => (
        <label key={field.name} className="field">
          {field.label}
          {field.type === "select" ? (
            <select
              value={fieldValues[field.name]}
              onChange={(e) => {
                const raw = e.target.value;
                updateField(field.name, typeof field.default === "number" ? Number(raw) : raw);
              }}
            >
              {field.options.map((opt) => {
                const optValue = typeof opt === "object" ? opt.value : opt;
                const optLabel = typeof opt === "object" ? opt.label : opt;
                return (
                  <option key={optValue} value={optValue}>
                    {optLabel}
                  </option>
                );
              })}
            </select>
          ) : field.type === "range" ? (
            <input
              type="range"
              min={field.min}
              max={field.max}
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, Number(e.target.value))}
            />
          ) : field.type === "number" ? (
            <input
              type="number"
              min={field.min}
              step={1}
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, Number(e.target.value))}
            />
          ) : field.type === "password" ? (
            <input
              type="password"
              maxLength={field.maxLength}
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, e.target.value)}
            />
          ) : (
            <input
              type="text"
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, e.target.value)}
            />
          )}
        </label>
      ))}
```

Replace it with this complete block (the `select`/`range`/`number`/`password`/text chain is unchanged, just re-homed as the third branch of a new outer ternary — note the closing at the very end: `)}` closes the inner select/range/etc. ternary, `</label>` closes the third branch's label, then a bare `)` closes that branch, then `)}` closes `.map()` and the JSX expression container):

```javascript
      {config.fields.map((field) =>
        field.type === "checkbox-group" ? (
          <div key={field.name} className="field field--checkbox-group">
            <span className="field__label">{field.label}</span>
            {field.options.map((opt) => (
              <label key={opt.value} className="field__checkbox-option">
                <input
                  type="checkbox"
                  checked={fieldValues[field.name].includes(opt.value)}
                  onChange={(e) => {
                    const current = fieldValues[field.name];
                    const next = e.target.checked
                      ? [...current, opt.value]
                      : current.filter((v) => v !== opt.value);
                    updateField(field.name, next);
                  }}
                />
                {opt.label}
              </label>
            ))}
          </div>
        ) : field.type === "checkbox" ? (
          <label key={field.name} className="field field--checkbox">
            <input
              type="checkbox"
              checked={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, e.target.checked)}
            />
            {field.label}
            {field.tooltip && (
              <span className="field__tooltip" title={field.tooltip}>
                <Info size={14} weight="regular" />
              </span>
            )}
          </label>
        ) : (
          <label key={field.name} className="field">
            {field.label}
            {field.type === "select" ? (
              <select
                value={fieldValues[field.name]}
                onChange={(e) => {
                  const raw = e.target.value;
                  updateField(field.name, typeof field.default === "number" ? Number(raw) : raw);
                }}
              >
                {field.options.map((opt) => {
                  const optValue = typeof opt === "object" ? opt.value : opt;
                  const optLabel = typeof opt === "object" ? opt.label : opt;
                  return (
                    <option key={optValue} value={optValue}>
                      {optLabel}
                    </option>
                  );
                })}
              </select>
            ) : field.type === "range" ? (
              <input
                type="range"
                min={field.min}
                max={field.max}
                value={fieldValues[field.name]}
                onChange={(e) => updateField(field.name, Number(e.target.value))}
              />
            ) : field.type === "number" ? (
              <input
                type="number"
                min={field.min}
                step={1}
                value={fieldValues[field.name]}
                onChange={(e) => updateField(field.name, Number(e.target.value))}
              />
            ) : field.type === "password" ? (
              <input
                type="password"
                maxLength={field.maxLength}
                value={fieldValues[field.name]}
                onChange={(e) => updateField(field.name, e.target.value)}
              />
            ) : (
              <input
                type="text"
                value={fieldValues[field.name]}
                onChange={(e) => updateField(field.name, e.target.value)}
              />
            )}
          </label>
        )
      )}
```

`Info` is already imported at the top of `ToolView.jsx` (used by the `previewNote` rendering) — no new import needed for the tooltip icon.

- [ ] **Step 3: Generalize the Run button's disabled check for required checkbox-group fields**

In the `run-button`'s `disabled` prop, add one more clause to the existing list:

```javascript
        disabled={
          busy ||
          files.length === 0 ||
          (config.preview === "crop" && !cropRect) ||
          (config.preview === "redact" && redactions.length === 0) ||
          (config.preview === "edit-pdf" && elements.length === 0) ||
          (config.preview === "sign" && elements.length === 0) ||
          (config.preview === "fill-form" && formValues.length === 0) ||
          config.fields.some((f) => f.required && fieldValues[f.name].length === 0)
        }
```

- [ ] **Step 4: Add the CSS for the new field shapes**

`.field--checkbox` already exists in `web/frontend/src/index.css` (used by Edit PDF's shape "filled" toggle) — reused as-is for the "Also convert to PDF/A" checkbox, no changes needed there. Only `.field--checkbox-group`, `.field__checkbox-option`, and `.field__tooltip` are new. Add these rules directly after the existing `.field--checkbox input[type="checkbox"]` rule (the one setting `margin: 0; accent-color: var(--color-accent);`):

```css
.field--checkbox-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin: var(--space-4) 0;
  font-size: 14px;
  font-weight: 500;
  color: var(--color-foreground);
}

.field__checkbox-option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 400;
}

.field__checkbox-option input[type="checkbox"] {
  margin: 0;
  accent-color: var(--color-accent);
}

.field__tooltip {
  display: inline-flex;
  align-items: center;
  color: var(--color-muted-foreground);
  cursor: help;
}
```

- [ ] **Step 5: Add the icons to `ToolGrid.jsx`**

Add `Scan` and `Archive` to the existing `@phosphor-icons/react` import list, and add two entries to `TOOL_ICONS`:

```javascript
  ocr: Scan,
  "pdf-to-pdfa": Archive,
```

- [ ] **Step 6: Build and manually verify**

Run: `cd web/frontend && npm run build`
Expected: build succeeds with no errors.

Manual checklist (start both the backend and frontend dev servers):
1. Open the app, confirm "OCR PDF" and "PDF to PDF/A" both appear under the Optimize category with their respective icons.
2. Open OCR PDF: confirm the language checkboxes render with English pre-checked, and the "Also convert to PDF/A" checkbox with its (i) tooltip renders (hover to confirm the tooltip text shows).
3. Uncheck all languages — confirm the Run button becomes disabled.
4. Upload a real scanned-looking PDF (or any image-only PDF), check English, run without PDF/A — confirm the downloaded file's text is now selectable/searchable in a PDF viewer, and the success message reports pages OCR'd.
5. Repeat with the PDF/A checkbox checked — confirm the message still reports correctly and the file downloads.
6. Open PDF to PDF/A, run it on any PDF, confirm it downloads successfully with no fields to configure.
7. Scan (or simulate) a sideways or upside-down page and run OCR on it — confirm the resulting text is searchable/selectable despite the original orientation. This is the one behavior this plan's automated tests don't cover (see Global Constraints — a real, verified PyMuPDF text-extraction quirk specific to rotated OCR'd pages, not a gap in the feature itself), so this manual check is the actual verification for it.

- [ ] **Step 7: Commit**

```bash
git add web/frontend/src/components/ToolView.jsx web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx web/frontend/src/index.css
git commit -m "feat: add OCR PDF and PDF to PDF/A frontend wiring"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

---

### Task 6: Wire OCR binaries into the release CI pipeline

**Files:**
- Modify: `.github/workflows/release.yml` — add a step that installs Tesseract/Ghostscript on the CI runner and runs the vendoring script, before the test and build steps

**Interfaces:**
- Consumes: `scripts/vendor_ocr_binaries.py` (Task 1) — this task makes the CI runner execute it, the same script a local developer would run, with no changes to the script itself.
- Produces: nothing further consumed by other tasks — this is the last task in the plan.

**Context:** verified this session — the release pipeline (`.github/workflows/release.yml`, triggered on `git push` of a version tag) builds on a fresh `windows-latest` GitHub Actions runner that has neither Tesseract nor Ghostscript installed, and `ocr_binaries/` is deliberately git-ignored (not committed — ~230MB of vendored binaries has no business living in git history). Without this task, every future automated release build would either fail outright (Tasks 2-4's tests can't find `ocr_binaries/`) or, worse, silently ship an installer missing the OCR feature entirely if the build step doesn't also fail loudly. This task makes the release pipeline install and vendor the binaries fresh on every run, the same way it already installs Python packages and Node modules fresh every run — no manual staging step for the developer.

`winget` is not confirmed present on GitHub's `windows-latest` runner image (checked the official runner-images documentation — it isn't listed). Chocolatey IS confirmed present and already used by this exact workflow (the existing `choco install innosetup` fallback in the "Build the installer" step) — both `tesseract` (5.5.0.20241111) and `Ghostscript` (10.8.0 — matching the version already verified on the dev machine used to write this plan) exist as real, current Chocolatey packages, confirmed via Chocolatey's own package API this session.

- [ ] **Step 1: Add the install-and-vendor step**

In `.github/workflows/release.yml`, add a new step immediately after `Install Python dependencies` and before `Run the test suite` (both the test suite and the later PyInstaller build step need `ocr_binaries/` to already exist):

```yaml
      - name: Install and vendor OCR binaries
        run: |
          choco install tesseract ghostscript -y --no-progress
          python scripts/vendor_ocr_binaries.py
```

The full step order in the `build-installer` job becomes: checkout → derive version → set up Python → set up Node → install Python dependencies → **install and vendor OCR binaries (new)** → run the test suite → build the frontend → build the standalone exe → build the installer → publish the release.

- [ ] **Step 2: Self-check the YAML is well-formed**

Run (locally, no GitHub account needed — just checks the file parses as valid YAML with the expected step present):
```bash
python -c "import yaml; d = yaml.safe_load(open('.github/workflows/release.yml')); steps = d['jobs']['build-installer']['steps']; names = [s.get('name') for s in steps]; print(names); assert 'Install and vendor OCR binaries' in names; assert names.index('Install and vendor OCR binaries') < names.index('Run the test suite')"
```
Expected: prints the full step name list, no assertion error (confirms the new step exists and runs before the test suite).

If `yaml` isn't installed in the venv, install it first: `./venv/Scripts/python.exe -m pip install pyyaml` (a one-off check tool, not a project dependency — do not add it to `requirements.txt`).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "feat: install and vendor OCR binaries in the release CI pipeline"
```

(No `Co-Authored-By:` trailer — this is a `feat:` commit.)

**Note for whoever ships the next release after this plan merges:** the first real-world test of this task is the next `git push` of a version tag. If Chocolatey's `tesseract`/`ghostscript` packages install to different default paths than `scripts/vendor_ocr_binaries.py` assumes (`C:\Program Files\Tesseract-OCR`, `C:\Program Files\gs\gs*`), the release build will fail loudly at the vendoring step with a clear "not found" error (per Task 1's script) rather than silently shipping a broken installer — if that happens, the fix is updating the script's hardcoded source paths to match wherever Chocolatey actually installed them on that run (visible in the failed step's own log output), not a sign anything else in this plan is wrong.
