# PDF Editor Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, offline web app (FastAPI backend + React frontend) that replaces the PySide6 desktop app as the primary way to use PDF Editor — same 10 tools, plus a clickable/draggable page-thumbnail grid (replacing the desktop app's text checklist) and a persistent output history ("Recent Files").

**Architecture:** FastAPI serves a small JSON API wrapping the existing, unchanged `app/core/pdf_ops.py`/`app/core/convert.py`, plus the built React frontend as static files. A launcher script starts the server and opens the browser to it. Everything runs on `127.0.0.1` — no internet connection is used or required.

**Tech Stack:** Python (FastAPI, uvicorn, python-multipart) for the backend; React + Vite + react-router-dom for the frontend.

## Global Constraints

- Reuses `app/core/pdf_ops.py`, `app/core/convert.py`, `app/core/errors.py` **unchanged** — no edits to those files in this plan.
- Backend listens on `127.0.0.1:8756` (both `launch.py` and the frontend's dev-mode Vite proxy use this port).
- Every `PDFError` raised by `app/core/` is turned into an HTTP 422 response with `{"detail": "<message>"}` by one global FastAPI exception handler — route functions should let `PDFError` propagate rather than catching it themselves.
- Output files go to `~/Documents/PDF Editor Output/` (a persistent library, not next to the input file — this is a deliberate change from the desktop app). Every output filename includes a `%Y%m%d-%H%M%S` timestamp to guarantee uniqueness across repeated runs, so the history list is never corrupted by a later run silently overwriting an earlier one's file on disk.
- Because outputs live in a separate directory from uploaded inputs (a temp directory), the desktop app's "output filename could overwrite an input file" class of bug is structurally impossible here — no path-collision check is needed for Merge's filename field.
- Testing policy for this plan: the backend (`web/backend/`) gets full `pytest` + FastAPI `TestClient` coverage, same rigor as `app/core/`'s existing 30 tests. The frontend gets Browser-tool-assisted checks (page loads, no console errors, expected elements present) rather than a JS test framework — full interactive click-through (uploading a real file, clicking thumbnails) is verified either via direct backend API calls from a script (proving the flow works end-to-end) or a manual pass, since headless browser automation in this environment cannot drive native OS file-picker dialogs.
- All new backend tests must isolate file I/O from the user's real filesystem via the `isolate_storage` fixture (Task 1) — no test may write to the real `~/Documents/PDF Editor Output/` or the real system temp directory's shared upload folder.
- Project root is `C:\Users\chinw\Documents\Project\PDF Editor`. This plan's code lives alongside, not instead of, the existing `app/` (PySide6) and `tests/` (its pytest suite) — nothing in this plan deletes or modifies those.

---

## Task 1: Backend scaffolding — storage.py, minimal main.py, test isolation

**Files:**
- Modify: `requirements.txt`
- Create: `web/__init__.py`
- Create: `web/backend/__init__.py`
- Create: `web/backend/storage.py`
- Create: `web/backend/main.py`
- Create: `web/backend/routes/__init__.py`
- Create: `tests/web/__init__.py`
- Create: `tests/web/conftest.py`
- Create: `tests/web/test_storage.py`

**Interfaces:**
- Consumes: `PDFError` from `app.core.errors` (Task 2, already built).
- Produces: `storage.save_upload(filename: str, content: bytes) -> dict` (`{id, filename, path}`); `storage.resolve_file(file_id: str) -> Path` (raises `FileNotFoundError` if unknown); `storage.load_history() -> list[dict]`; `storage.record_output(path: Path, tool: str, source_filenames: list[str]) -> dict`; `storage.delete_output(file_id: str) -> bool`; `storage.output_path_for(stem: str, suffix: str, ext: str = ".pdf") -> Path` (single-file tools); `storage.output_dir_for(stem: str, suffix: str) -> Path` (multi-file tools: Split, PDF→Image — returns a fresh timestamped subdirectory). `storage.UPLOAD_DIR`, `storage.OUTPUT_DIR`, `storage.HISTORY_FILE` are module-level `Path`s, monkeypatchable by tests. `main.app` is the FastAPI instance every route task includes routers into. `tests/web/conftest.py`'s `isolate_storage` autouse fixture is consumed by every later backend test task.

- [ ] **Step 1: Add backend dependencies to `requirements.txt`**

Append to the existing `requirements.txt`:

```
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
httpx>=0.27.0
```

(`httpx` is required by FastAPI's `TestClient`.)

- [ ] **Step 2: Install the new dependencies**

Run: `venv/Scripts/python -m pip install -r requirements.txt`
Expected: installs cleanly, no errors.

- [ ] **Step 3: Create package skeleton**

```bash
mkdir -p web/backend/routes tests/web
touch web/__init__.py web/backend/__init__.py web/backend/routes/__init__.py tests/web/__init__.py
```

- [ ] **Step 4: Write the failing tests for `storage.py`**

`tests/web/conftest.py`:

```python
import pytest

from web.backend import storage


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(storage, "OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr(storage, "HISTORY_FILE", tmp_path / "output" / "history.json")
    storage._uploads.clear()
    yield
    storage._uploads.clear()
```

`tests/web/test_storage.py`:

```python
from pathlib import Path

import pytest

from web.backend import storage


def test_save_upload_creates_file_and_record():
    record = storage.save_upload("report.pdf", b"%PDF-1.4 fake content")

    assert record["filename"] == "report.pdf"
    assert Path(record["path"]).exists()
    assert Path(record["path"]).read_bytes() == b"%PDF-1.4 fake content"
    assert storage.resolve_file(record["id"]) == Path(record["path"])


def test_resolve_file_unknown_id_raises():
    with pytest.raises(FileNotFoundError):
        storage.resolve_file("does-not-exist")


def test_record_output_appends_to_history_newest_first(tmp_path):
    path_a = tmp_path / "a.pdf"
    path_a.write_text("a")
    path_b = tmp_path / "b.pdf"
    path_b.write_text("b")

    storage.record_output(path_a, "Merge PDF", ["x.pdf", "y.pdf"])
    record_b = storage.record_output(path_b, "Compress PDF", ["a.pdf"])

    history = storage.load_history()
    assert len(history) == 2
    assert history[0]["id"] == record_b["id"]
    assert history[0]["tool"] == "Compress PDF"
    assert history[0]["source_filenames"] == ["a.pdf"]
    assert storage.resolve_file(record_b["id"]) == path_b


def test_delete_output_removes_record_and_file(tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    record = storage.record_output(path, "Rotate PDF", ["in.pdf"])

    deleted = storage.delete_output(record["id"])

    assert deleted is True
    assert storage.load_history() == []
    assert not path.exists()


def test_delete_output_unknown_id_returns_false():
    assert storage.delete_output("nope") is False


def test_output_path_for_is_unique_across_calls():
    first = storage.output_path_for("report", "_merged")
    second = storage.output_path_for("report", "_merged")

    assert first != second
    assert first.name.startswith("report_merged_")
    assert first.suffix == ".pdf"


def test_output_dir_for_creates_a_fresh_directory():
    out_dir = storage.output_dir_for("report", "_split")

    assert out_dir.exists()
    assert out_dir.is_dir()
    assert out_dir.name.startswith("report_split_")
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'web.backend.storage'`.

- [ ] **Step 6: Write `web/backend/storage.py`**

```python
import json
import tempfile
import time
import uuid
from pathlib import Path

UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdf_editor_web_uploads"
OUTPUT_DIR = Path.home() / "Documents" / "PDF Editor Output"
HISTORY_FILE = OUTPUT_DIR / "history.json"

_uploads: dict[str, dict] = {}


def save_upload(filename: str, content: bytes) -> dict:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex[:12]
    safe_name = Path(filename).name
    path = UPLOAD_DIR / f"{file_id}_{safe_name}"
    path.write_bytes(content)
    record = {"id": file_id, "filename": safe_name, "path": str(path)}
    _uploads[file_id] = record
    return record


def load_history() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))


def _save_history(records: list[dict]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")


def record_output(path: Path, tool: str, source_filenames: list[str]) -> dict:
    record = {
        "id": uuid.uuid4().hex[:12],
        "filename": path.name,
        "path": str(path),
        "tool": tool,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_filenames": source_filenames,
    }
    records = load_history()
    records.insert(0, record)
    _save_history(records)
    return record


def delete_output(file_id: str) -> bool:
    records = load_history()
    remaining = [r for r in records if r["id"] != file_id]
    if len(remaining) == len(records):
        return False
    deleted = next(r for r in records if r["id"] == file_id)
    _save_history(remaining)
    Path(deleted["path"]).unlink(missing_ok=True)
    return True


def resolve_file(file_id: str) -> Path:
    if file_id in _uploads:
        return Path(_uploads[file_id]["path"])
    for record in load_history():
        if record["id"] == file_id:
            return Path(record["path"])
    raise FileNotFoundError(f"No file found for id '{file_id}'")


def output_path_for(stem: str, suffix: str, ext: str = ".pdf") -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return OUTPUT_DIR / f"{stem}{suffix}_{timestamp}{ext}"


def output_dir_for(stem: str, suffix: str) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / f"{stem}{suffix}_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/test_storage.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 8: Write the minimal `web/backend/main.py`**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.core.errors import PDFError

app = FastAPI(title="PDF Editor")


@app.exception_handler(PDFError)
async def pdf_error_handler(request, exc: PDFError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# Routers are included here as each one is built.

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
```

- [ ] **Step 9: Verify the app imports cleanly**

Run: `venv/Scripts/python -c "from web.backend.main import app; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 10: Run the full test suite to confirm no regressions**

Run: `venv/Scripts/python -m pytest -v`
Expected: all 30 existing tests still PASS, plus the 7 new ones (37 total).

- [ ] **Step 11: Commit**

```bash
git add requirements.txt web/__init__.py web/backend/__init__.py web/backend/storage.py web/backend/main.py web/backend/routes/__init__.py tests/web/__init__.py tests/web/conftest.py tests/web/test_storage.py
git commit -m "feat: web backend scaffolding — storage layer and minimal FastAPI app"
```

---

## Task 2: Backend — file routes (upload, thumbnail, download)

**Files:**
- Create: `web/backend/routes/files.py`
- Modify: `web/backend/main.py`
- Create: `tests/web/test_files.py`

**Interfaces:**
- Consumes: `storage.save_upload`, `storage.resolve_file` (Task 1); `get_page_count`, `render_page_thumbnail` (already built in `app/core/pdf_ops.py`).
- Produces: `files.router` (FastAPI `APIRouter`), included in `main.app` under `/api`. `POST /api/files` → `{id, filename, page_count}`. `GET /api/files/{file_id}/pages/{page_number}/thumbnail` → PNG bytes. `GET /api/files/{file_id}/download` → file attachment.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_files.py`:

```python
import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _make_pdf_bytes(num_pages=2):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def test_upload_returns_id_filename_and_page_count():
    pdf_bytes = _make_pdf_bytes(num_pages=3)

    response = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "sample.pdf"
    assert data["page_count"] == 3
    assert data["id"]


def test_upload_invalid_pdf_returns_422():
    response = client.post(
        "/api/files", files={"file": ("bad.pdf", b"not a pdf", "application/pdf")}
    )

    assert response.status_code == 422
    assert "detail" in response.json()


def test_thumbnail_returns_png():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/pages/1/thumbnail")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/pages/1/thumbnail")
    assert response.status_code == 404


def test_download_returns_file_content():
    pdf_bytes = _make_pdf_bytes(num_pages=1)
    upload = client.post(
        "/api/files", files={"file": ("sample.pdf", pdf_bytes, "application/pdf")}
    ).json()

    response = client.get(f"/api/files/{upload['id']}/download")

    assert response.status_code == 200
    assert response.content == pdf_bytes


def test_download_unknown_file_id_returns_404():
    response = client.get("/api/files/nope/download")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_files.py -v`
Expected: FAIL — `/api/files` returns 404 (no such route yet).

- [ ] **Step 3: Write `web/backend/routes/files.py`**

```python
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from app.core.errors import PDFError
from app.core.pdf_ops import get_page_count, render_page_thumbnail
from web.backend import storage

router = APIRouter()


@router.post("/files")
async def upload_file(file: UploadFile):
    content = await file.read()
    record = storage.save_upload(file.filename, content)
    try:
        page_count = get_page_count(record["path"])
    except PDFError:
        storage.resolve_file(record["id"]).unlink(missing_ok=True)
        raise
    return {"id": record["id"], "filename": record["filename"], "page_count": page_count}


@router.get("/files/{file_id}/pages/{page_number}/thumbnail")
def get_thumbnail(file_id: str, page_number: int):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    thumb_bytes = render_page_thumbnail(str(path), page_number, max_size=220)
    return Response(content=thumb_bytes, media_type="image/png")


@router.get("/files/{file_id}/download")
def download_file(file_id: str):
    try:
        path = storage.resolve_file(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path), filename=path.name)
```

- [ ] **Step 4: Wire the router into `main.py`**

In `web/backend/main.py`, add the import alongside the existing ones and replace the marker comment:

```python
from app.core.errors import PDFError
from web.backend.routes import files
```

```python
from web.backend.routes import files

app.include_router(files.router, prefix="/api")

# Routers are included here as each one is built.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/ -v`
Expected: all tests in `tests/web/` PASS (13 total: 7 storage + 6 files).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/files.py web/backend/main.py tests/web/test_files.py
git commit -m "feat: file upload, thumbnail, and download endpoints"
```

---

## Task 3: Backend — history routes (list, delete)

**Files:**
- Create: `web/backend/routes/history.py`
- Modify: `web/backend/main.py`
- Create: `tests/web/test_history.py`

**Interfaces:**
- Consumes: `storage.load_history`, `storage.delete_output` (Task 1).
- Produces: `history.router`, included under `/api`. `GET /api/history` → `list[dict]`. `DELETE /api/history/{file_id}` → `{"deleted": file_id}` or 404.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_history.py`:

```python
from fastapi.testclient import TestClient

from web.backend import storage
from web.backend.main import app

client = TestClient(app)


def test_history_empty_by_default():
    response = client.get("/api/history")
    assert response.status_code == 200
    assert response.json() == []


def test_history_lists_recorded_outputs(tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    storage.record_output(path, "Compress PDF", ["in.pdf"])

    response = client.get("/api/history")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["tool"] == "Compress PDF"


def test_delete_history_entry_removes_it(tmp_path):
    path = tmp_path / "out.pdf"
    path.write_text("data")
    record = storage.record_output(path, "Rotate PDF", ["in.pdf"])

    response = client.delete(f"/api/history/{record['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": record["id"]}
    assert client.get("/api/history").json() == []


def test_delete_unknown_history_entry_returns_404():
    response = client.delete("/api/history/nope")
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_history.py -v`
Expected: FAIL — 404 on `/api/history` (no such route yet).

- [ ] **Step 3: Write `web/backend/routes/history.py`**

```python
from fastapi import APIRouter, HTTPException

from web.backend import storage

router = APIRouter()


@router.get("/history")
def list_history():
    return storage.load_history()


@router.delete("/history/{file_id}")
def delete_history_entry(file_id: str):
    deleted = storage.delete_output(file_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="History entry not found")
    return {"deleted": file_id}
```

- [ ] **Step 4: Wire the router into `main.py`**

Add `from web.backend.routes import history` alongside the `files` import, and `app.include_router(history.router, prefix="/api")` alongside the `files` include, both before the marker comment.

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/ -v`
Expected: all tests PASS (17 total).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/history.py web/backend/main.py tests/web/test_history.py
git commit -m "feat: history list and delete endpoints"
```

---

## Task 4: Backend — tool routes, Organize group (merge, split, remove/extract/reorder pages)

**Files:**
- Create: `web/backend/routes/tools.py`
- Modify: `web/backend/main.py`
- Create: `tests/web/test_tools_organize.py`

**Interfaces:**
- Consumes: `storage.resolve_file`, `storage.record_output`, `storage.output_path_for`, `storage.output_dir_for`, `storage.OUTPUT_DIR` (Task 1); `merge_pdfs`, `split_pdf`, `get_page_count`, `remove_pages`, `extract_pages`, `reorder_pages` (already built).
- Produces: `tools.router` (prefix `/tools`, itself mounted under `/api` — full paths `/api/tools/...`), included in `main.app`. Shared helper `_output_response(paths, tool, source_filenames) -> dict` returning `{"outputs": [{"id", "filename", "download_url"}, ...]}` — every tool endpoint in this and the next task returns this exact shape. Endpoints: `POST /api/tools/merge`, `/split`, `/remove-pages`, `/extract-pages`, `/reorder-pages`.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_tools_organize.py`:

```python
import fitz
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _upload_pdf(num_pages=3, text_prefix="Page"):
    doc = fitz.open()
    for i in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text_prefix} {i + 1}")
    data = doc.tobytes()
    doc.close()
    return client.post(
        "/api/files", files={"file": ("sample.pdf", data, "application/pdf")}
    ).json()


def test_merge_combines_two_files():
    upload_a = _upload_pdf(num_pages=2, text_prefix="A")
    upload_b = _upload_pdf(num_pages=3, text_prefix="B")

    response = client.post(
        "/api/tools/merge",
        json={"file_ids": [upload_a["id"], upload_b["id"]], "filename": "combined.pdf"},
    )

    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].startswith("combined_")
    download = client.get(outputs[0]["download_url"])
    assert download.status_code == 200


def test_merge_rejects_path_in_filename():
    upload_a = _upload_pdf()
    upload_b = _upload_pdf()

    response = client.post(
        "/api/tools/merge",
        json={"file_ids": [upload_a["id"], upload_b["id"]], "filename": "../evil.pdf"},
    )

    assert response.status_code == 422


def test_split_produces_one_file_per_range():
    upload = _upload_pdf(num_pages=4)

    response = client.post(
        "/api/tools/split", json={"file_id": upload["id"], "pages_per_file": 2}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 2


def test_remove_pages_drops_selected():
    upload = _upload_pdf(num_pages=3)

    response = client.post(
        "/api/tools/remove-pages", json={"file_id": upload["id"], "pages": [2]}
    )

    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1


def test_remove_pages_rejects_empty_selection():
    upload = _upload_pdf()

    response = client.post(
        "/api/tools/remove-pages", json={"file_id": upload["id"], "pages": []}
    )

    assert response.status_code == 422


def test_extract_pages_selects_given_pages():
    upload = _upload_pdf(num_pages=4)

    response = client.post(
        "/api/tools/extract-pages", json={"file_id": upload["id"], "pages": [1, 3]}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_reorder_pages_accepts_new_order():
    upload = _upload_pdf(num_pages=3)

    response = client.post(
        "/api/tools/reorder-pages", json={"file_id": upload["id"], "order": [3, 1, 2]}
    )

    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_organize.py -v`
Expected: FAIL — 404 on `/api/tools/merge` (no such route yet).

- [ ] **Step 3: Write `web/backend/routes/tools.py`**

```python
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.errors import PDFError
from app.core.pdf_ops import (
    extract_pages,
    get_page_count,
    merge_pdfs,
    remove_pages,
    reorder_pages,
    split_pdf,
)
from web.backend import storage

router = APIRouter(prefix="/tools")


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


class MergeRequest(BaseModel):
    file_ids: list[str]
    filename: str


@router.post("/merge")
def merge(req: MergeRequest):
    input_paths = [str(storage.resolve_file(fid)) for fid in req.file_ids]
    filename = req.filename.strip()
    if not filename:
        raise PDFError("Enter an output filename.")
    if any(sep in filename for sep in ("/", "\\", ":")):
        raise PDFError("Output filename must be a plain file name, not a path.")
    if filename.lower().endswith(".pdf"):
        filename = filename[: -len(".pdf")]
    output_path = storage.output_path_for(filename, "")
    merge_pdfs(input_paths, str(output_path))
    source_names = [Path(p).name for p in input_paths]
    return _output_response([output_path], "Merge PDF", source_names)


class SplitRequest(BaseModel):
    file_id: str
    pages_per_file: int


@router.post("/split")
def split(req: SplitRequest):
    input_path = str(storage.resolve_file(req.file_id))
    total = get_page_count(input_path)
    step = req.pages_per_file
    ranges = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
    stem = Path(input_path).stem
    out_dir = storage.output_dir_for(stem, "_split")
    result_paths = split_pdf(input_path, str(out_dir), ranges)
    return _output_response([Path(p) for p in result_paths], "Split PDF", [Path(input_path).name])


class RemovePagesRequest(BaseModel):
    file_id: str
    pages: list[int]


@router.post("/remove-pages")
def remove_pages_route(req: RemovePagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    if not req.pages:
        raise PDFError("Select at least one page to remove.")
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_removed")
    remove_pages(input_path, req.pages, str(output_path))
    return _output_response([output_path], "Remove pages", [Path(input_path).name])


class ExtractPagesRequest(BaseModel):
    file_id: str
    pages: list[int]


@router.post("/extract-pages")
def extract_pages_route(req: ExtractPagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    if not req.pages:
        raise PDFError("Select at least one page to extract.")
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_extracted")
    extract_pages(input_path, req.pages, str(output_path))
    return _output_response([output_path], "Extract pages", [Path(input_path).name])


class ReorderPagesRequest(BaseModel):
    file_id: str
    order: list[int]


@router.post("/reorder-pages")
def reorder_pages_route(req: ReorderPagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_reordered")
    reorder_pages(input_path, req.order, str(output_path))
    return _output_response([output_path], "Reorder pages", [Path(input_path).name])
```

- [ ] **Step 4: Wire the router into `main.py`**

Add `from web.backend.routes import tools` alongside the other route imports, and replace the marker comment with:

```python
app.include_router(tools.router, prefix="/api")
```

(remove the `# Routers are included here...` comment now — this is the last router.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/ -v`
Expected: all tests PASS (24 total: 17 + 7 new).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py web/backend/main.py tests/web/test_tools_organize.py
git commit -m "feat: merge/split/remove/extract/reorder tool endpoints"
```

---

## Task 5: Backend — tool routes, Edit/Optimize/Convert group

**Files:**
- Modify: `web/backend/routes/tools.py`
- Create: `tests/web/test_tools_edit_convert.py`

**Interfaces:**
- Consumes: `_output_response`, `storage` helpers (Task 4); `rotate_pages`, `add_watermark`, `compress_pdf`, `render_to_images`, `convert_to_word` (already built).
- Produces: `POST /api/tools/rotate`, `/watermark`, `/compress`, `/to-images`, `/to-word`, appended to the same `tools.router` from Task 4.

- [ ] **Step 1: Write the failing tests**

`tests/web/test_tools_edit_convert.py`:

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


def test_rotate_returns_one_output():
    upload = _upload_pdf()
    response = client.post("/api/tools/rotate", json={"file_id": upload["id"], "angle": 90})
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_rotate_rejects_non_multiple_of_90():
    upload = _upload_pdf()
    response = client.post("/api/tools/rotate", json={"file_id": upload["id"], "angle": 45})
    assert response.status_code == 422


def test_watermark_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/watermark", json={"file_id": upload["id"], "text": "DRAFT", "opacity": 0.3}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_watermark_rejects_empty_text():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/watermark", json={"file_id": upload["id"], "text": "  ", "opacity": 0.3}
    )
    assert response.status_code == 422


def test_compress_returns_one_output():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/compress", json={"file_id": upload["id"], "image_quality": 50}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 1


def test_to_images_returns_one_output_per_page():
    upload = _upload_pdf(num_pages=3)
    response = client.post(
        "/api/tools/to-images", json={"file_id": upload["id"], "image_format": "png"}
    )
    assert response.status_code == 200
    assert len(response.json()["outputs"]) == 3


def test_to_word_returns_one_output():
    upload = _upload_pdf()
    response = client.post("/api/tools/to-word", json={"file_id": upload["id"]})
    assert response.status_code == 200
    outputs = response.json()["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["filename"].endswith(".docx")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/Scripts/python -m pytest tests/web/test_tools_edit_convert.py -v`
Expected: FAIL — 404 on `/api/tools/rotate` (routes don't exist yet).

- [ ] **Step 3: Append the five endpoints to `web/backend/routes/tools.py`**

Add these imports to the existing import block at the top (merge into the existing `from app.core.pdf_ops import (...)` line):

```python
from app.core.convert import convert_to_word
from app.core.pdf_ops import (
    add_watermark,
    compress_pdf,
    extract_pages,
    get_page_count,
    merge_pdfs,
    remove_pages,
    render_to_images,
    reorder_pages,
    rotate_pages,
    split_pdf,
)
```

Append at the end of the file:

```python
class RotateRequest(BaseModel):
    file_id: str
    angle: int


@router.post("/rotate")
def rotate(req: RotateRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_rotated")
    rotate_pages(input_path, str(output_path), req.angle)
    return _output_response([output_path], "Rotate PDF", [Path(input_path).name])


class WatermarkRequest(BaseModel):
    file_id: str
    text: str
    opacity: float = 0.3


@router.post("/watermark")
def watermark(req: WatermarkRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_watermarked")
    add_watermark(input_path, str(output_path), req.text, opacity=req.opacity)
    return _output_response([output_path], "Add watermark", [Path(input_path).name])


class CompressRequest(BaseModel):
    file_id: str
    image_quality: int = 60


@router.post("/compress")
def compress(req: CompressRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_compressed")
    compress_pdf(input_path, str(output_path), image_quality=req.image_quality)
    return _output_response([output_path], "Compress PDF", [Path(input_path).name])


class ToImagesRequest(BaseModel):
    file_id: str
    image_format: str = "png"


@router.post("/to-images")
def to_images(req: ToImagesRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    out_dir = storage.output_dir_for(stem, "_images")
    result_paths = render_to_images(input_path, str(out_dir), image_format=req.image_format)
    return _output_response([Path(p) for p in result_paths], "PDF to Image", [Path(input_path).name])


class ToWordRequest(BaseModel):
    file_id: str


@router.post("/to-word")
def to_word(req: ToWordRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "", ".docx")
    convert_to_word(input_path, str(output_path))
    return _output_response([output_path], "PDF to Word", [Path(input_path).name])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/Scripts/python -m pytest tests/web/ -v`
Expected: all tests PASS (31 total: 24 + 7 new).

- [ ] **Step 5: Run the full project suite**

Run: `venv/Scripts/python -m pytest -v`
Expected: all 61 tests PASS (30 existing `app/core` + 31 `web`).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_edit_convert.py
git commit -m "feat: rotate/watermark/compress/to-images/to-word tool endpoints"
```

---

## Task 6: Backend — launcher script

**Files:**
- Create: `web/launch.py`

**Interfaces:**
- Consumes: `web.backend.main.app`.
- Produces: a script that starts the server and opens the browser — no importable interface, this is an entry point.

- [ ] **Step 1: Write `web/launch.py`**

```python
import threading
import time
import webbrowser

import uvicorn

from web.backend.main import app

HOST = "127.0.0.1"
PORT = 8756


def _open_browser_when_ready() -> None:
    time.sleep(1.0)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Manual verification**

Run: `venv/Scripts/python -m web.launch` (from the project root, with a short timeout since it's a long-running server — e.g. run it in the background or with a `timeout` wrapper)
Expected: console shows uvicorn startup logs ("Uvicorn running on http://127.0.0.1:8756"); a browser tab opens automatically. Since the frontend isn't built yet (Tasks 7-11), the root URL will 404 — that's expected at this point. Instead confirm the backend itself is alive by fetching `http://127.0.0.1:8756/docs` (FastAPI's automatic Swagger UI) — it should load and list all the routes built in Tasks 2-5 (files, history, tools).

- [ ] **Step 3: Commit**

```bash
git add web/launch.py
git commit -m "feat: local server launcher"
```

---

## Task 7: Frontend scaffolding — Vite + React project, routing shell, API client

**Files:**
- Create: `web/frontend/package.json`
- Create: `web/frontend/vite.config.js`
- Create: `web/frontend/index.html`
- Create: `web/frontend/src/main.jsx`
- Create: `web/frontend/src/App.jsx`
- Create: `web/frontend/src/api.js`
- Create: `web/frontend/src/index.css`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `api.js` exports — `uploadFile(file) -> Promise<{id, filename, page_count}>`, `thumbnailUrl(fileId, pageNumber) -> string`, `downloadUrl(fileId) -> string`, `runTool(toolPath, body) -> Promise<{outputs: [...]}>`, `fetchHistory() -> Promise<list>`, `deleteHistoryEntry(fileId) -> Promise<void>`. These are consumed by every later frontend task. `App.jsx` exports the routing shell later tasks add routes to.

- [ ] **Step 1: Add `node_modules` and the frontend build output to `.gitignore`**

Append to the existing `.gitignore`:

```
web/frontend/node_modules/
web/frontend/dist/
```

- [ ] **Step 2: Write `web/frontend/package.json`**

```json
{
  "name": "pdf-editor-web-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.3.1",
    "vite": "^5.4.0"
  }
}
```

- [ ] **Step 3: Write `web/frontend/vite.config.js`**

```javascript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8756",
    },
  },
  build: {
    outDir: "dist",
  },
});
```

- [ ] **Step 4: Write `web/frontend/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PDF Editor</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 5: Write `web/frontend/src/api.js`**

```javascript
const BASE = "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new Error(detail);
  }
  return res;
}

export async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const res = await request("/files", { method: "POST", body: formData });
  return res.json();
}

export function thumbnailUrl(fileId, pageNumber) {
  return `${BASE}/files/${fileId}/pages/${pageNumber}/thumbnail`;
}

export function downloadUrl(fileId) {
  return `${BASE}/files/${fileId}/download`;
}

export async function runTool(toolPath, body) {
  const res = await request(`/tools/${toolPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function fetchHistory() {
  const res = await request("/history");
  return res.json();
}

export async function deleteHistoryEntry(fileId) {
  await request(`/history/${fileId}`, { method: "DELETE" });
}
```

- [ ] **Step 6: Write `web/frontend/src/index.css`**

```css
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 16px;
  background: #f5f5f7;
  color: #1a1a1a;
}

.app__header {
  padding: 16px 24px;
  background: #202124;
  color: white;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.app__brand {
  color: white;
  text-decoration: none;
  font-size: 20px;
  font-weight: 600;
}

.app__nav a {
  color: #ddd;
  text-decoration: none;
  margin-left: 20px;
  font-size: 15px;
}

.app__main {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 24px;
}

.tool-grid__category {
  margin-bottom: 32px;
}

.tool-grid__category h2 {
  font-size: 18px;
  color: #555;
  margin-bottom: 12px;
}

.tool-grid__buttons {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.tool-grid__buttons button {
  padding: 20px;
  font-size: 16px;
  border-radius: 10px;
  border: 1px solid #ddd;
  background: white;
  cursor: pointer;
  text-align: left;
}

.tool-grid__buttons button:hover {
  border-color: #4a7dff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.page-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
  margin: 24px 0;
}

.page-thumb {
  position: relative;
  border: 2px solid #ddd;
  border-radius: 8px;
  padding: 8px;
  background: white;
}

.page-thumb img {
  width: 100%;
  display: block;
  border-radius: 4px;
}

.page-thumb__label {
  display: block;
  text-align: center;
  font-size: 14px;
  color: #666;
  margin-top: 6px;
}

.page-grid--select .page-thumb,
.page-grid--reorder .page-thumb {
  cursor: pointer;
}

.page-thumb--selected {
  border-color: #4a7dff;
  box-shadow: 0 0 0 3px rgba(74, 125, 255, 0.25);
}

.page-thumb__badge {
  position: absolute;
  top: 4px;
  right: 4px;
  background: #4a7dff;
  color: white;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
}

.field {
  display: block;
  margin: 16px 0;
  font-size: 15px;
}

.field input,
.field select {
  display: block;
  margin-top: 6px;
  padding: 8px;
  font-size: 15px;
  width: 100%;
  max-width: 300px;
}

.banner {
  padding: 12px 16px;
  border-radius: 8px;
  margin: 16px 0;
}

.banner--error {
  background: #fde8e8;
  color: #a11;
}

.result {
  margin-top: 24px;
  padding: 16px;
  background: #e8f7ec;
  border-radius: 8px;
}

.result a {
  display: block;
  margin-top: 8px;
  color: #226;
}

.history-list {
  list-style: none;
  padding: 0;
}

.history-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  border-bottom: 1px solid #eee;
}
```

- [ ] **Step 7: Write `web/frontend/src/App.jsx`** (routing shell — `Home` is a placeholder Task 8 replaces)

```jsx
import { Routes, Route, Link } from "react-router-dom";

function Home() {
  return <h1>PDF Editor</h1>;
}

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<Home />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 8: Write `web/frontend/src/main.jsx`**

```jsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.jsx";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
```

- [ ] **Step 9: Install frontend dependencies**

Run: `cd web/frontend && npm install`
Expected: installs cleanly, creates `node_modules/` and `package-lock.json`.

- [ ] **Step 10: Manual verification with the dev server**

Run: `cd web/frontend && npm run dev` (background it or use a timeout — it's a long-running dev server)
Expected: Vite prints a local URL (typically `http://localhost:5173/`). Load it (e.g. via the Browser tool) and confirm the page shows a dark header reading "PDF Editor" and a main-area heading also reading "PDF Editor", with no console errors.

- [ ] **Step 11: Commit**

```bash
git add .gitignore web/frontend/package.json web/frontend/package-lock.json web/frontend/vite.config.js web/frontend/index.html web/frontend/src
git commit -m "feat: frontend scaffolding — Vite + React, routing shell, API client"
```

---

## Task 8: Frontend — tool configuration and home screen (ToolGrid)

**Files:**
- Create: `web/frontend/src/toolConfigs.js`
- Create: `web/frontend/src/components/ToolGrid.jsx`
- Modify: `web/frontend/src/App.jsx`

**Interfaces:**
- Produces: `TOOL_CONFIGS` — an object keyed by `toolId` (e.g. `"remove-pages"`), each value `{title, category, multiFile, mode, endpoint, fields}` where `mode` is one of `"view" | "select" | "reorder"` and `fields` is a list of `{name, label, type, default, ...}` describing the option form. Consumed by `ToolGrid` (this task) and `ToolView` (Task 10).

- [ ] **Step 1: Write `web/frontend/src/toolConfigs.js`**

```javascript
export const TOOL_CONFIGS = {
  merge: {
    title: "Merge PDF",
    category: "Organize",
    multiFile: true,
    mode: "view",
    endpoint: "merge",
    fields: [{ name: "filename", label: "Output filename", type: "text", default: "" }],
  },
  split: {
    title: "Split PDF",
    category: "Organize",
    multiFile: false,
    mode: "view",
    endpoint: "split",
    fields: [
      { name: "pages_per_file", label: "Pages per output file", type: "number", default: 1, min: 1 },
    ],
  },
  "remove-pages": {
    title: "Remove pages",
    category: "Organize",
    multiFile: false,
    mode: "select",
    endpoint: "remove-pages",
    fields: [],
  },
  "extract-pages": {
    title: "Extract pages",
    category: "Organize",
    multiFile: false,
    mode: "select",
    endpoint: "extract-pages",
    fields: [],
  },
  "reorder-pages": {
    title: "Reorder pages",
    category: "Organize",
    multiFile: false,
    mode: "reorder",
    endpoint: "reorder-pages",
    fields: [],
  },
  rotate: {
    title: "Rotate PDF",
    category: "Edit",
    multiFile: false,
    mode: "view",
    endpoint: "rotate",
    fields: [
      { name: "angle", label: "Rotate by", type: "select", options: [90, 180, 270], default: 90 },
    ],
  },
  watermark: {
    title: "Add watermark",
    category: "Edit",
    multiFile: false,
    mode: "view",
    endpoint: "watermark",
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
  },
  compress: {
    title: "Compress PDF",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    endpoint: "compress",
    fields: [
      { name: "image_quality", label: "Image quality", type: "range", min: 10, max: 100, default: 60 },
    ],
  },
  "to-images": {
    title: "PDF to Image",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "to-images",
    fields: [
      { name: "image_format", label: "Format", type: "select", options: ["jpg", "png"], default: "jpg" },
    ],
  },
  "to-word": {
    title: "PDF to Word",
    category: "Convert",
    multiFile: false,
    mode: "view",
    endpoint: "to-word",
    fields: [],
  },
};
```

- [ ] **Step 2: Write `web/frontend/src/components/ToolGrid.jsx`**

```jsx
import { useNavigate } from "react-router-dom";
import { TOOL_CONFIGS } from "../toolConfigs";

const CATEGORIES = ["Organize", "Edit", "Optimize", "Convert"];

export default function ToolGrid() {
  const navigate = useNavigate();

  return (
    <div className="tool-grid">
      {CATEGORIES.map((category) => {
        const tools = Object.entries(TOOL_CONFIGS).filter(([, cfg]) => cfg.category === category);
        return (
          <div key={category} className="tool-grid__category">
            <h2>{category}</h2>
            <div className="tool-grid__buttons">
              {tools.map(([toolId, cfg]) => (
                <button key={toolId} onClick={() => navigate(`/tool/${toolId}`)}>
                  {cfg.title}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Wire `ToolGrid` into `App.jsx`**

Replace the placeholder `Home` function and its usage:

```jsx
import { Routes, Route, Link } from "react-router-dom";
import ToolGrid from "./components/ToolGrid.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Manual verification**

With `npm run dev` running (from Task 7), reload the page (e.g. via the Browser tool) and confirm four category headings (Organize, Edit, Optimize, Convert) each show their tool buttons — Organize should show 5 buttons (Merge PDF, Split PDF, Remove pages, Extract pages, Reorder pages), Edit 2, Optimize 1, Convert 2 — 10 buttons total, no console errors.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx web/frontend/src/App.jsx
git commit -m "feat: tool configuration data and home screen tool grid"
```

---

## Task 9: Frontend — PageGrid component (click-select / drag-reorder / view-only)

**Files:**
- Create: `web/frontend/src/components/PageGrid.jsx`

**Interfaces:**
- Consumes: `thumbnailUrl` (Task 7).
- Produces: `PageGrid({fileId, pageCount, mode, selected, onToggle, order, onReorder})` — a React component. `mode` is `"view" | "select" | "reorder"`. In `"select"` mode, clicking a thumbnail calls `onToggle(pageNumber)`; the caller owns the `selected: number[]` array. In `"reorder"` mode, dragging a thumbnail to a new position calls `onReorder(newOrderArray)`; the caller owns `order: number[]` (1-indexed page numbers in current visual order). In `"view"` mode there is no interaction — the grid just renders `pageCount` thumbnails in order 1..N. Consumed by `ToolView` (Task 10).

- [ ] **Step 1: Write `web/frontend/src/components/PageGrid.jsx`**

```jsx
import { useState } from "react";
import { thumbnailUrl } from "../api";

export default function PageGrid({ fileId, pageCount, mode = "view", selected, onToggle, order, onReorder }) {
  const [dragIndex, setDragIndex] = useState(null);

  if (!fileId || !pageCount) return null;

  const pages = mode === "reorder" && order ? order : Array.from({ length: pageCount }, (_, i) => i + 1);

  function handleDragStart(index) {
    setDragIndex(index);
  }

  function handleDrop(index) {
    if (dragIndex === null || dragIndex === index) return;
    const next = [...pages];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(index, 0, moved);
    onReorder(next);
    setDragIndex(null);
  }

  return (
    <div className={`page-grid page-grid--${mode}`}>
      {pages.map((pageNumber, index) => {
        const isSelected = mode === "select" && selected?.includes(pageNumber);
        return (
          <div
            key={pageNumber}
            className={`page-thumb ${isSelected ? "page-thumb--selected" : ""}`}
            draggable={mode === "reorder"}
            onDragStart={() => handleDragStart(index)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => handleDrop(index)}
            onClick={() => mode === "select" && onToggle(pageNumber)}
          >
            <img src={thumbnailUrl(fileId, pageNumber)} alt={`Page ${pageNumber}`} loading="lazy" />
            <span className="page-thumb__label">Page {pageNumber}</span>
            {isSelected && <span className="page-thumb__badge">✓</span>}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Verify the frontend still builds with no syntax errors**

Run: `cd web/frontend && npm run build`
Expected: build completes with no errors (this component isn't wired into any route yet, so this only confirms it's syntactically valid — full interactive verification happens in Task 10 once `ToolView` actually renders it).

- [ ] **Step 3: Commit**

```bash
git add web/frontend/src/components/PageGrid.jsx
git commit -m "feat: PageGrid component — click-select, drag-reorder, view-only modes"
```

---

## Task 10: Frontend — ToolView (generic tool page, wired to the backend)

**Files:**
- Create: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/App.jsx`

**Interfaces:**
- Consumes: `TOOL_CONFIGS` (Task 8), `PageGrid` (Task 9), `uploadFile`/`runTool`/`downloadUrl` (Task 7).
- Produces: a route at `/tool/:toolId` rendering the matching tool's full workflow: upload → (page grid, if the tool has one) → options form (driven by `config.fields`) → Run → download links for the result(s).

- [ ] **Step 1: Write `web/frontend/src/components/ToolView.jsx`**

```jsx
import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { TOOL_CONFIGS } from "../toolConfigs";
import { uploadFile, runTool, downloadUrl } from "../api";
import PageGrid from "./PageGrid";

export default function ToolView() {
  const { toolId } = useParams();
  const navigate = useNavigate();
  const config = TOOL_CONFIGS[toolId];

  const [files, setFiles] = useState([]);
  const [fieldValues, setFieldValues] = useState(() =>
    Object.fromEntries((config?.fields ?? []).map((f) => [f.name, f.default]))
  );
  const [selected, setSelected] = useState([]);
  const [order, setOrder] = useState(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!config) {
    return <p>Unknown tool.</p>;
  }

  async function handleFilePick(e) {
    setError("");
    const picked = Array.from(e.target.files);
    try {
      const uploaded = [];
      for (const file of picked) {
        uploaded.push(await uploadFile(file));
      }
      const nextFiles = config.multiFile ? [...files, ...uploaded] : uploaded;
      setFiles(nextFiles);
      const primary = nextFiles[0];
      if (primary) {
        setSelected([]);
        setOrder(Array.from({ length: primary.page_count }, (_, i) => i + 1));
        if (config.fields.some((f) => f.name === "filename") && !fieldValues.filename) {
          setFieldValues((v) => ({
            ...v,
            filename: primary.filename.replace(/\.pdf$/i, "") + "_merged",
          }));
        }
      }
    } catch (err) {
      setError(err.message);
    }
  }

  function updateField(name, value) {
    setFieldValues((v) => ({ ...v, [name]: value }));
  }

  async function handleRun() {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const body = {};
      for (const field of config.fields) {
        const raw = fieldValues[field.name];
        body[field.name] = field.scale ? raw * field.scale : raw;
      }
      if (config.multiFile) {
        body.file_ids = files.map((f) => f.id);
      } else {
        body.file_id = files[0]?.id;
      }
      if (config.mode === "select") body.pages = selected;
      if (config.mode === "reorder") body.order = order;
      const data = await runTool(config.endpoint, body);
      setResult(data.outputs);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const primaryFile = files[0];

  return (
    <div className="tool-view">
      <button onClick={() => navigate("/")}>&larr; Back</button>
      <h1>{config.title}</h1>

      <input type="file" accept=".pdf" multiple={config.multiFile} onChange={handleFilePick} />

      {error && <div className="banner banner--error">{error}</div>}

      {primaryFile && (
        <PageGrid
          fileId={primaryFile.id}
          pageCount={primaryFile.page_count}
          mode={config.mode}
          selected={selected}
          onToggle={(n) => setSelected((s) => (s.includes(n) ? s.filter((p) => p !== n) : [...s, n]))}
          order={order}
          onReorder={setOrder}
        />
      )}

      {config.fields.map((field) => (
        <label key={field.name} className="field">
          {field.label}
          {field.type === "select" ? (
            <select value={fieldValues[field.name]} onChange={(e) => updateField(field.name, e.target.value)}>
              {field.options.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
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
              value={fieldValues[field.name]}
              onChange={(e) => updateField(field.name, Number(e.target.value))}
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

      <button disabled={busy || files.length === 0} onClick={handleRun}>
        {busy ? "Working…" : "Run"}
      </button>

      {result && (
        <div className="result">
          <p>Done — {result.length} file(s) created.</p>
          {result.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire the route into `App.jsx`**

```jsx
import { Routes, Route, Link } from "react-router-dom";
import ToolGrid from "./components/ToolGrid.jsx";
import ToolView from "./components/ToolView.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Manual verification — page rendering**

With `npm run dev` (Task 7) and the backend (`python -m web.launch` or `uvicorn web.backend.main:app --port 8756`, Task 6) both running, navigate to `/tool/remove-pages` (e.g. via the Browser tool) and confirm: the page shows "Remove pages", a file input, and no console errors. Do the same for `/tool/merge` (confirm the "Output filename" field renders) and `/tool/watermark` (confirm text + range fields render).

- [ ] **Step 4: End-to-end verification via a script (covers what browser automation can't — actual file upload)**

Since headless browser automation in this environment cannot drive a native OS file-picker dialog, verify the full upload → run → download flow directly against the running backend using a short throwaway Python script (not part of the committed codebase):

```python
import fitz
import requests

doc = fitz.open()
for i in range(3):
    page = doc.new_page()
    page.insert_text((72, 72), f"Page {i + 1}")
data = doc.tobytes()
doc.close()

upload = requests.post(
    "http://127.0.0.1:8756/api/files",
    files={"file": ("sample.pdf", data, "application/pdf")},
).json()
print("uploaded:", upload)

result = requests.post(
    "http://127.0.0.1:8756/api/tools/remove-pages",
    json={"file_id": upload["id"], "pages": [2]},
).json()
print("result:", result)

download = requests.get(f"http://127.0.0.1:8756{result['outputs'][0]['download_url']}")
print("download status:", download.status_code, "bytes:", len(download.content))
```

Expected: prints a valid upload record, a result with one output, and a successful download with non-zero byte count. This proves the exact flow `ToolView` drives (upload → run tool → download) works end-to-end against the real backend.

- [ ] **Step 5: Commit**

```bash
git add web/frontend/src/components/ToolView.jsx web/frontend/src/App.jsx
git commit -m "feat: ToolView — generic tool page wired to the backend"
```

---

## Task 11: Frontend — Recent Files page

**Files:**
- Create: `web/frontend/src/components/RecentFiles.jsx`
- Modify: `web/frontend/src/App.jsx`

**Interfaces:**
- Consumes: `fetchHistory`, `deleteHistoryEntry`, `downloadUrl` (Task 7).
- Produces: a route at `/recent` listing every output the app has produced, with download and delete actions.

- [ ] **Step 1: Write `web/frontend/src/components/RecentFiles.jsx`**

```jsx
import { useEffect, useState } from "react";
import { fetchHistory, deleteHistoryEntry, downloadUrl } from "../api";

export default function RecentFiles() {
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    load();
  }, []);

  async function load() {
    try {
      setEntries(await fetchHistory());
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleDelete(id) {
    try {
      await deleteHistoryEntry(id);
      setEntries((prev) => prev.filter((e) => e.id !== id));
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <div className="recent-files">
      <h1>Recent Files</h1>
      {error && <div className="banner banner--error">{error}</div>}
      {entries.length === 0 && <p>No files produced yet.</p>}
      <ul className="history-list">
        {entries.map((entry) => (
          <li key={entry.id}>
            <div>
              <strong>{entry.filename}</strong>
              <div>
                {entry.tool} — {entry.created_at}
              </div>
            </div>
            <div>
              <a href={downloadUrl(entry.id)} download>
                Download
              </a>{" "}
              <button onClick={() => handleDelete(entry.id)}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 2: Wire the route and a nav link into `App.jsx`**

```jsx
import { Routes, Route, Link } from "react-router-dom";
import ToolGrid from "./components/ToolGrid.jsx";
import ToolView from "./components/ToolView.jsx";
import RecentFiles from "./components/RecentFiles.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          PDF Editor
        </Link>
        <nav className="app__nav">
          <Link to="/recent">Recent Files</Link>
        </nav>
      </header>
      <main className="app__main">
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
          <Route path="/recent" element={<RecentFiles />} />
        </Routes>
      </main>
    </div>
  );
}
```

- [ ] **Step 3: Manual verification**

With the dev server and backend both running, navigate to `/recent` (e.g. via the Browser tool). If Task 10's verification script has already run, confirm the produced file appears in the list with its tool name and timestamp, and that the Download link and Delete button are present. Click Delete (or verify via a script call to `DELETE /api/history/{id}`) and confirm the entry disappears.

- [ ] **Step 4: Commit**

```bash
git add web/frontend/src/components/RecentFiles.jsx web/frontend/src/App.jsx
git commit -m "feat: Recent Files page"
```

---

## Task 12: Build the frontend, serve it from the backend, end-to-end verification

**Files:**
- No new files — this task builds and verifies the integration of everything from Tasks 1-11.

**Interfaces:**
- Consumes: everything built in Tasks 1-11.
- Produces: `web/frontend/dist/` (built static assets, gitignored, not committed), served by `main.py`'s existing static-mount guard (Task 1) once it exists on disk.

- [ ] **Step 1: Build the frontend**

Run: `cd web/frontend && npm run build`
Expected: completes with no errors, creates `web/frontend/dist/` containing `index.html` and bundled JS/CSS.

- [ ] **Step 2: Launch the full app as an end user would**

Run: `venv/Scripts/python -m web.launch` (from the project root, backgrounded or with a timeout — long-running server)
Expected: uvicorn starts, a browser tab opens automatically to `http://127.0.0.1:8756/`, and — because `web/frontend/dist/` now exists — `main.py`'s static mount serves the real built app (not a 404 like in Task 6's verification).

- [ ] **Step 3: Full click-through verification**

Using the Browser tool against `http://127.0.0.1:8756/`:
- Confirm the home page loads with all 10 tool buttons across 4 categories, and a "Recent Files" link in the header.
- Navigate to each of the 10 `/tool/:toolId` pages and confirm each renders without console errors and shows the fields its config specifies (e.g. Rotate shows a 90/180/270 select, Compress shows a quality slider).
- Re-run the Task 10 Step 4 verification script (upload → run → download) against `http://127.0.0.1:8756` instead of the dev server, for at least Remove Pages, Merge, and PDF to Word, to confirm the same flow works through the production build, not just the dev server.
- Navigate to `/recent` and confirm the files produced by the script appear, with working Download links.

- [ ] **Step 4: Run the full project test suite one more time**

Run: `venv/Scripts/python -m pytest -v`
Expected: all 61 tests pass (30 `app/core` + 31 `web/backend`) — confirms nothing in this task's manual work touched code in a way that broke the automated suite.

- [ ] **Step 5: Report completion**

No commit needed for this task (no new tracked files — `dist/` is gitignored). If any of the verification steps above surface a bug, fix it in the relevant task's file, re-run that task's tests/build, and commit the fix with a message referencing what was fixed (e.g. `fix: <description>`).

---

## Plan complete

At the end of Task 12, PDF Editor Web is a working local app: `python -m web.launch` starts a FastAPI server on `127.0.0.1:8756`, opens a browser to it, and serves a React frontend covering the same 10 tools as the desktop app — with a clickable/draggable page-thumbnail grid instead of a text checklist, thumbnails large enough to actually read, and a persistent Recent Files history. Packaging this into a standalone `.exe` (mirroring the desktop app's PyInstaller build) and the mobile thin-client idea are both explicitly out of scope here, per the design spec — separate future work, not part of this plan.
