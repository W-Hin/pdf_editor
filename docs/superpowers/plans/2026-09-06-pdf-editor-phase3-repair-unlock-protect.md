# Phase 3, Group 2: Repair + Unlock + Protect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three `pikepdf`-based tools — Repair (structural recovery with a healthy/recovered summary), Unlock (decrypt with a password), Protect (encrypt with a password) — the second sub-project of Phase 3.

**Architecture:** A new `app/core/pdf_repair.py` module holds all three tools' core logic. Repair and Protect fit the app's existing single-file-in/single-file-out route pattern exactly (`tools.py`). Unlock is fundamentally different — the app's normal upload step rejects any encrypted file before a password field could ever be reached — so it gets its own combined multipart file+password route and its own dedicated frontend page (`/unlock`), following the same "dedicated route, not a `ToolView` special case" pattern Compare PDF's own final fix wave established.

**Tech Stack:** `pikepdf` (new dependency, prebuilt wheel, no external binary — verified installed and working in this dev environment), FastAPI (`File`/`Form`/`UploadFile` for Unlock's multipart route), React.

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Every task's `feat:` commit must **not** carry the trailer.
- No frontend automated tests (established project convention) — `npm run build` plus a specific manual browser checklist per frontend task.
- Backend changes follow TDD with concrete assertions verified empirically before being written into a test. Every truncation percentage / recovered-page-count / warning-count number in this plan was independently verified against a real generated PDF before this plan was written (see Task 1) — not assumed from documentation.
- **Correction to the spec, found while reading the current codebase fresh:** the spec's Repair section says Repair's healthy/recovered summary is added to "`_output_response`'s existing per-tool result-summary convention." Read fresh, no such convention exists — every one of the 17 current call sites of `_output_response` returns the exact same `{"outputs": [...]}` shape, with no message/summary field anywhere, and `ToolView.jsx`'s result state currently stores only `data.outputs` (discarding the rest of the response). Task 2 below adds a new optional `message` parameter to `_output_response` (default `None`, so all 17 existing call sites are completely unaffected) and a small, corresponding frontend change so `ToolView.jsx` can display it when present — this is new plumbing this plan introduces, not something that already existed.
- **A small, justified frontend addition**: `ToolView.jsx`'s generic field renderer has no masked/password input type — no prior tool has ever needed one. Task 4 adds a `field.type === "password"` branch (rendering `<input type="password">`) alongside the existing `select`/`range`/`number`/text branches, used by Protect's password field.

---

### Task 1: Backend core logic

**Files:**
- Create: `app/core/pdf_repair.py`
- Test: `tests/test_pdf_repair.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `repair_pdf(input_path: str, output_path: str) -> dict` (returns `{"page_count": int, "warnings_count": int}`), `unlock_pdf(input_path: str, output_path: str, password: str) -> None`, `protect_pdf(input_path: str, output_path: str, password: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pdf_repair.py`:

```python
import fitz
import pikepdf
import pytest

from app.core.errors import PDFError
from app.core.pdf_repair import protect_pdf, repair_pdf, unlock_pdf


def _make_pdf(path, num_pages=5):
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page(width=595, height=842)
    doc.save(str(path))
    doc.close()


def test_repair_pdf_reports_healthy_file_with_no_warnings(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)

    output_path = tmp_path / "output.pdf"
    result = repair_pdf(str(input_path), str(output_path))

    assert result == {"page_count": 5, "warnings_count": 0}
    assert output_path.exists()


def test_repair_pdf_recovers_a_truncated_file(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)
    data = input_path.read_bytes()

    # Verified empirically: truncating this exact 5-page fixture to 50% of
    # its byte length is recoverable by pikepdf/qpdf, salvaging exactly 3 of
    # the 5 original pages with exactly 8 structural warnings — not an
    # assumed "original" page count, the actual number pikepdf reports at
    # this truncation level for this exact fixture shape.
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.5)])

    output_path = tmp_path / "output.pdf"
    result = repair_pdf(str(truncated_path), str(output_path))

    assert result == {"page_count": 3, "warnings_count": 8}
    assert output_path.exists()


def test_repair_pdf_raises_on_unrecoverable_file(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=5)
    data = input_path.read_bytes()

    # Verified empirically: truncating to 20% of the byte length is past the
    # point even qpdf's recovery can salvage anything — pikepdf.open() itself
    # raises PdfError("...unable to find any pages while recovering damaged
    # file...").
    truncated_path = tmp_path / "truncated.pdf"
    truncated_path.write_bytes(data[: int(len(data) * 0.2)])

    output_path = tmp_path / "output.pdf"
    with pytest.raises(PDFError):
        repair_pdf(str(truncated_path), str(output_path))
    assert not output_path.exists()


def test_unlock_pdf_decrypts_with_correct_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    output_path = tmp_path / "unlocked.pdf"
    unlock_pdf(str(encrypted_path), str(output_path), "secret123")

    result = fitz.open(str(output_path))
    assert result.is_encrypted is False
    assert result.page_count == 3
    result.close()


def test_unlock_pdf_rejects_wrong_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    encrypted_path = tmp_path / "encrypted.pdf"
    pdf = pikepdf.open(str(input_path))
    pdf.save(str(encrypted_path), encryption=pikepdf.Encryption(user="secret123", owner="secret123", R=6))
    pdf.close()

    output_path = tmp_path / "unlocked.pdf"
    with pytest.raises(PDFError) as exc_info:
        unlock_pdf(str(encrypted_path), str(output_path), "wrong")
    # The underlying pikepdf.PasswordError's message includes the raw temp
    # file path — must never leak into the user-facing error.
    assert str(encrypted_path) not in str(exc_info.value)
    assert not output_path.exists()


def test_protect_pdf_encrypts_with_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    protect_pdf(str(input_path), str(output_path), "mypassword")

    result = fitz.open(str(output_path))
    assert result.is_encrypted is True
    result.close()
    # Confirm the exact password given actually works.
    reopened = fitz.open(str(output_path))
    reopened.authenticate("mypassword")
    assert reopened.page_count == 3
    reopened.close()


def test_protect_pdf_rejects_empty_password(tmp_path):
    input_path = tmp_path / "input.pdf"
    _make_pdf(input_path, num_pages=3)

    output_path = tmp_path / "protected.pdf"
    with pytest.raises(PDFError):
        protect_pdf(str(input_path), str(output_path), "")
    assert not output_path.exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_repair.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.pdf_repair'`.

- [ ] **Step 3: Write `app/core/pdf_repair.py`**

```python
import pikepdf

from app.core.errors import PDFError


def repair_pdf(input_path: str, output_path: str) -> dict:
    try:
        pdf = pikepdf.open(input_path)
    except pikepdf.PdfError as exc:
        raise PDFError("This file is too damaged to be repaired.") from exc
    try:
        page_count = len(pdf.pages)
        warnings_count = len(pdf.get_warnings())
        pdf.save(output_path)
    finally:
        pdf.close()
    return {"page_count": page_count, "warnings_count": warnings_count}


def unlock_pdf(input_path: str, output_path: str, password: str) -> None:
    try:
        pdf = pikepdf.open(input_path, password=password)
    except pikepdf.PasswordError as exc:
        raise PDFError("Incorrect password.") from exc
    try:
        pdf.save(output_path)
    finally:
        pdf.close()


def protect_pdf(input_path: str, output_path: str, password: str) -> None:
    if not password.strip():
        raise PDFError("Enter a password.")
    pdf = pikepdf.open(input_path)
    try:
        pdf.save(output_path, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    finally:
        pdf.close()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_pdf_repair.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Add `pikepdf` to `requirements.txt`**

Add a line `pikepdf>=9.0.0` to `requirements.txt` (already installed in this dev environment from earlier feasibility verification; this makes it an explicit, pinned direct dependency).

- [ ] **Step 6: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (196 before this task; 203 expected after — this task's 7 new tests).

- [ ] **Step 7: Commit**

```bash
git add app/core/pdf_repair.py tests/test_pdf_repair.py requirements.txt
git commit -m "feat: add Repair, Unlock, and Protect's pikepdf-based core logic"
```

No `Co-Authored-By` trailer.

---

### Task 2: Repair and Protect — API routes

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_tools_repair_protect.py`

**Interfaces:**
- Consumes: Task 1's `repair_pdf`, `protect_pdf`.
- Produces: `POST /api/tools/repair` (`{file_id}` → the normal `_output_response` shape, now with a `message` field); `POST /api/tools/protect` (`{file_id, password}` → the normal `_output_response` shape). `_output_response(paths, tool, source_filenames, message: str | None = None) -> dict` — the new optional 4th parameter, backward compatible with all 17 existing call sites.

- [ ] **Step 1: Write the failing route tests**

Create `tests/web/test_tools_repair_protect.py` (following the exact `client`/`_upload_pdf` pattern already established in `tests/web/test_tools_edit_convert.py` and `tests/web/test_compare_route.py`):

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


def test_repair_reports_healthy_message():
    upload = _upload_pdf(num_pages=3)
    response = client.post("/api/tools/repair", json={"file_id": upload["id"]})
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1
    assert "healthy" in data["message"].lower()
    assert "3" in data["message"]


def test_protect_encrypts_with_password():
    upload = _upload_pdf()
    response = client.post(
        "/api/tools/protect", json={"file_id": upload["id"], "password": "mypassword"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1


def test_protect_rejects_empty_password():
    upload = _upload_pdf()
    response = client.post("/api/tools/protect", json={"file_id": upload["id"], "password": ""})
    assert response.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_repair_protect.py -v`
Expected: FAIL — `404 Not Found` (the routes don't exist yet).

- [ ] **Step 3: Add the `message` parameter to `_output_response`**

In `web/backend/routes/tools.py`, find:

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

Replace with:

```python
def _output_response(paths: list[Path], tool: str, source_filenames: list[str], message: str | None = None) -> dict:
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
    return {"outputs": outputs, "message": message}
```

Every existing call site passes only 3 positional arguments, so `message` defaults to `None` for all of them — no other route needs to change.

- [ ] **Step 4: Add the Repair and Protect routes**

In `web/backend/routes/tools.py`, add `repair_pdf`, `protect_pdf` to the `from app.core.pdf_repair import (...)` import (a new import line — `pdf_repair` is a separate module from `pdf_ops`, so this is a new `from app.core.pdf_repair import protect_pdf, repair_pdf` line, not an addition to the existing `pdf_ops` import list). Add near the other single-file-in/single-file-out routes (e.g. near `compress`):

```python
class RepairRequest(BaseModel):
    file_id: str


@router.post("/repair")
def repair_route(req: RepairRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_repaired")
    result = repair_pdf(input_path, str(output_path))
    if result["warnings_count"] == 0:
        message = f"File is healthy — {result['page_count']} page{'s' if result['page_count'] != 1 else ''}."
    else:
        message = (
            f"Recovered {result['page_count']} page{'s' if result['page_count'] != 1 else ''} "
            f"after {result['warnings_count']} structural issue{'s' if result['warnings_count'] != 1 else ''} found."
        )
    return _output_response([output_path], "Repair PDF", [Path(input_path).name], message=message)


class ProtectRequest(BaseModel):
    file_id: str
    password: str


@router.post("/protect")
def protect_route(req: ProtectRequest):
    input_path = str(storage.resolve_file(req.file_id))
    stem = Path(input_path).stem
    output_path = storage.output_path_for(stem, "_protected")
    protect_pdf(input_path, str(output_path), req.password)
    return _output_response([output_path], "Protect PDF", [Path(input_path).name])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_tools_repair_protect.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (203 before this task; 206 expected after).

- [ ] **Step 7: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_tools_repair_protect.py
git commit -m "feat: add Repair and Protect API routes"
```

No `Co-Authored-By` trailer.

---

### Task 3: Unlock — combined file+password API route

**Files:**
- Modify: `web/backend/routes/tools.py`
- Test: `tests/web/test_unlock_route.py`

**Interfaces:**
- Consumes: Task 1's `unlock_pdf`.
- Produces: `POST /api/tools/unlock` — multipart form data (`file`, `password`), NOT a `file_id`-referencing JSON body like every other route. Returns the normal `_output_response` shape on success.

- [ ] **Step 1: Write the failing route tests**

Create `tests/web/test_unlock_route.py`:

```python
import fitz
import pikepdf
from fastapi.testclient import TestClient

from web.backend.main import app

client = TestClient(app)


def _make_encrypted_pdf_bytes(password="secret123", num_pages=3):
    doc = fitz.open()
    for _ in range(num_pages):
        doc.new_page()
    plain_bytes = doc.tobytes()
    doc.close()

    import io

    pdf = pikepdf.open(io.BytesIO(plain_bytes))
    buf = io.BytesIO()
    pdf.save(buf, encryption=pikepdf.Encryption(user=password, owner=password, R=6))
    pdf.close()
    return buf.getvalue()


def test_unlock_with_correct_password_succeeds():
    encrypted_bytes = _make_encrypted_pdf_bytes(password="secret123", num_pages=3)
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("locked.pdf", encrypted_bytes, "application/pdf")},
        data={"password": "secret123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1


def test_unlock_with_wrong_password_fails():
    encrypted_bytes = _make_encrypted_pdf_bytes(password="secret123", num_pages=3)
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("locked.pdf", encrypted_bytes, "application/pdf")},
        data={"password": "wrong"},
    )
    assert response.status_code == 422
    assert "path" not in response.json()["detail"].lower()


def test_unlock_with_non_encrypted_file_passes_through_cleanly():
    doc = fitz.open()
    doc.new_page()
    plain_bytes = doc.tobytes()
    doc.close()
    response = client.post(
        "/api/tools/unlock",
        files={"file": ("plain.pdf", plain_bytes, "application/pdf")},
        data={"password": "irrelevant"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["outputs"]) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_unlock_route.py -v`
Expected: FAIL — `404 Not Found`.

- [ ] **Step 3: Add the Unlock route**

In `web/backend/routes/tools.py`, add `File`, `Form`, `UploadFile` to the `from fastapi import APIRouter` line (becomes `from fastapi import APIRouter, File, Form, UploadFile`), add `import tempfile` near the top with the other stdlib imports, and add `unlock_pdf` to the `from app.core.pdf_repair import (...)` line added in Task 2 (becomes `from app.core.pdf_repair import protect_pdf, repair_pdf, unlock_pdf`). Add near the Repair/Protect routes:

```python
@router.post("/unlock")
async def unlock_route(file: UploadFile = File(...), password: str = Form(...)):
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        input_path = tmp.name
    try:
        stem = Path(file.filename or "unlocked").stem
        output_path = storage.output_path_for(stem, "_unlocked")
        unlock_pdf(input_path, str(output_path), password)
        return _output_response([output_path], "Unlock PDF", [file.filename or "unlocked.pdf"])
    finally:
        Path(input_path).unlink(missing_ok=True)
```

This deliberately does NOT go through `storage.save_upload`/`storage.resolve_file` for the INPUT file (unlike every other route) — the encrypted upload only needs to exist long enough for `unlock_pdf` to read it, and never needs its own independently-downloadable `file_id`; only the decrypted OUTPUT does, via the normal `_output_response`/`storage.output_path_for` path every other tool already uses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/web/test_unlock_route.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full backend test suite**

Run: `./venv/Scripts/python.exe -m pytest tests/ -v`
Expected: all passing (206 before this task; 209 expected after).

- [ ] **Step 6: Commit**

```bash
git add web/backend/routes/tools.py tests/web/test_unlock_route.py
git commit -m "feat: add Unlock's combined file-and-password API route"
```

No `Co-Authored-By` trailer.

---

### Task 4: Frontend — Repair, Protect (generic flow) and Unlock (dedicated page)

**Files:**
- Modify: `web/frontend/src/toolConfigs.js`
- Modify: `web/frontend/src/components/ToolGrid.jsx`
- Modify: `web/frontend/src/components/ToolView.jsx`
- Modify: `web/frontend/src/App.jsx`
- Modify: `web/frontend/src/api.js`
- Create: `web/frontend/src/components/UnlockPdfView.jsx`
- Modify: `web/frontend/src/index.css`

**Interfaces:**
- Consumes: Task 2's `POST /api/tools/repair`/`POST /api/tools/protect` (generic `runTool` flow); Task 3's `POST /api/tools/unlock`.
- Produces: `unlockPdf(file, password)` in `api.js`; a `DEDICATED_ROUTES` lookup in `ToolGrid.jsx` (generalizing the single-entry special case Compare PDF's own final fix wave introduced, now with a second entry); `field.type === "password"` support in `ToolView.jsx`'s generic field renderer; a `result.message` display in `ToolView.jsx`'s result block.

- [ ] **Step 1: Register Repair and Protect in `toolConfigs.js`**

Add:

```jsx
  repair: {
    title: "Repair PDF",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    endpoint: "repair",
    previewNote: "Repair fixes the file's internal structure, not its visual content — there's nothing meaningful to preview before running.",
    fields: [],
  },
  protect: {
    title: "Protect PDF",
    category: "Optimize",
    multiFile: false,
    mode: "view",
    endpoint: "protect",
    fields: [{ name: "password", label: "Password", type: "password", default: "" }],
  },
```

- [ ] **Step 2: Add `field.type === "password"` support to `ToolView.jsx`'s generic field renderer**

Find (inside the `config.fields.map(...)` block):

```jsx
          ) : field.type === "number" ? (
            <input
              type="number"
              min={field.min}
              step={1}
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
```

Replace with:

```jsx
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
```

- [ ] **Step 3: Show `result.message` in `ToolView.jsx`'s result block**

Find:

```jsx
      if (config.preview === "fill-form") {
        body.values = formValues;
      }
      const data = await runTool(config.endpoint, body);
      setResult(data.outputs);
```

Replace with:

```jsx
      if (config.preview === "fill-form") {
        body.values = formValues;
      }
      const data = await runTool(config.endpoint, body);
      setResult(data);
```

Find the result-rendering block:

```jsx
      {result && (
        <div className="result">
          <p className="result__title">
            <CheckCircle size={18} weight="fill" />
            Done — {result.length} file{result.length === 1 ? "" : "s"} created.
          </p>
          {result.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              <DownloadSimple size={16} weight="regular" />
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
```

Replace with:

```jsx
      {result && (
        <div className="result">
          <p className="result__title">
            <CheckCircle size={18} weight="fill" />
            Done — {result.outputs.length} file{result.outputs.length === 1 ? "" : "s"} created.
          </p>
          {result.message && <p className="result__message">{result.message}</p>}
          {result.outputs.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              <DownloadSimple size={16} weight="regular" />
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
```

Read the current file fresh before making this change — `result` is used ONLY in these two places in the current file (`setResult(data.outputs)` and this one JSX block); confirm this is still true before editing, so no other reference is missed.

- [ ] **Step 4: Add `unlockPdf` to `api.js`**

```jsx
export async function unlockPdf(file, password) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("password", password);
  const res = await request("/tools/unlock", { method: "POST", body: formData });
  return res.json();
}
```

- [ ] **Step 5: Generalize `ToolGrid.jsx`'s dedicated-route navigation**

Find:

```jsx
                  return (
                    <button
                      key={toolId}
                      onClick={() => navigate(toolId === "compare-pdf" ? "/compare" : `/tool/${toolId}`)}
                    >
```

Replace with:

```jsx
                  return (
                    <button key={toolId} onClick={() => navigate(DEDICATED_ROUTES[toolId] ?? `/tool/${toolId}`)}>
```

Add near `TOOL_ICONS` (before the component, at module scope):

```jsx
// Tools whose interaction model differs enough from the standard "pick
// file(s) → configure → Run → download" flow that they render their own
// dedicated page instead of going through ToolView's generic flow.
const DEDICATED_ROUTES = {
  "compare-pdf": "/compare",
  "unlock-pdf": "/unlock",
};
```

Add a minimal `TOOL_CONFIGS["unlock-pdf"]` entry in `toolConfigs.js` (needed only so the grid tile renders with a title — nothing else about this entry is consumed, since `unlock-pdf` never reaches `ToolView`'s generic flow):

```jsx
  "unlock-pdf": {
    title: "Unlock PDF",
    category: "Optimize",
    fields: [],
  },
```

Add `TOOL_ICONS` entries in `ToolGrid.jsx` for all three new tools — `repair`/`protect` also need real icons here (easy to miss, since Step 1 only registered them in `toolConfigs.js`; without a `TOOL_ICONS` entry each would silently fall back to the generic `File` icon and trigger the existing dev-time `console.error` warning). Verified these three icon names exist in the installed `@phosphor-icons/react` package: `Wrench`, `Lock`, `LockOpen`. Check what's already imported from `@phosphor-icons/react` in this file and add these three to that same import statement, then add the entries:

```jsx
const TOOL_ICONS = {
  // ...existing entries...
  repair: Wrench,
  protect: Lock,
  "unlock-pdf": LockOpen,
};
```

- [ ] **Step 6: Add the `/unlock` route**

In `web/frontend/src/App.jsx`, add the import:

```jsx
import UnlockPdfView from "./components/UnlockPdfView.jsx";
```

Find:

```jsx
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/compare" element={<ComparePdfView />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
```

Replace with:

```jsx
        <Routes>
          <Route path="/" element={<ToolGrid />} />
          <Route path="/compare" element={<ComparePdfView />} />
          <Route path="/unlock" element={<UnlockPdfView />} />
          <Route path="/tool/:toolId" element={<ToolView />} />
        </Routes>
```

- [ ] **Step 7: Write `UnlockPdfView.jsx`**

```jsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  UploadSimple,
  Play,
  CircleNotch,
  WarningCircle,
  CheckCircle,
  DownloadSimple,
} from "@phosphor-icons/react";
import { unlockPdf, downloadUrl } from "../api";

export default function UnlockPdfView() {
  const navigate = useNavigate();
  const [file, setFile] = useState(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  function handlePick(e) {
    setError("");
    setResult(null);
    setFile(e.target.files[0] ?? null);
  }

  async function handleUnlock() {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const data = await unlockPdf(file, password);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="tool-view">
      <button className="tool-view__back" onClick={() => navigate("/")}>
        <ArrowLeft size={16} weight="bold" />
        Back
      </button>
      <h1>Unlock PDF</h1>

      <label className="tool-view__upload">
        <UploadSimple size={18} weight="regular" />
        {file ? file.name : "Choose a password-protected PDF file…"}
        <input type="file" accept=".pdf" onChange={handlePick} />
      </label>

      <label className="field">
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </label>

      {error && (
        <div className="banner banner--error">
          <WarningCircle size={18} weight="fill" />
          {error}
        </div>
      )}

      <button className="run-button" disabled={busy || !file || !password} onClick={handleUnlock}>
        {busy ? <CircleNotch size={17} weight="bold" className="spin" /> : <Play size={16} weight="fill" />}
        {busy ? "Working…" : "Unlock"}
      </button>

      {result && (
        <div className="result">
          <p className="result__title">
            <CheckCircle size={18} weight="fill" />
            Done — {result.outputs.length} file{result.outputs.length === 1 ? "" : "s"} created.
          </p>
          {result.outputs.map((out) => (
            <a key={out.id} href={downloadUrl(out.id)} download>
              <DownloadSimple size={16} weight="regular" />
              Download {out.filename}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8: Add CSS**

`.result__message` is new (everything else reuses existing classes — `.tool-view`, `.tool-view__back`, `.tool-view__upload`, `.field`, `.banner`, `.run-button`, `.result`, `.result__title`, all already defined in `index.css`). Add:

```css
.result__message {
  font-size: 13px;
  color: var(--color-muted-foreground);
  margin: 0 0 var(--space-2);
}
```

- [ ] **Step 9: Verify the build**

Run: `cd web/frontend && npm run build`
Expected: builds successfully.

- [ ] **Step 10: Manual browser check**

- **Repair**: the tool grid shows a "Repair PDF" tile under Optimize with a real icon; running it on a normal, healthy PDF shows "File is healthy — N pages." alongside the download link; running it on a genuinely truncated/damaged PDF (construct one the same way the backend test does — truncate a real generated PDF's bytes) shows "Recovered N pages after M structural issues found."
- **Protect**: the tool grid shows a "Protect PDF" tile under Optimize; the password field is masked (dots/asterisks, not plaintext); running it produces a downloadable file that genuinely requires the password to open in a DIFFERENT PDF viewer, not just within this app.
- **Unlock**: the tool grid shows an "Unlock PDF" tile under Optimize with a real (non-fallback) icon; clicking it navigates to `/unlock`, not `/tool/unlock-pdf`; uploading a password-protected PDF with the correct password succeeds and produces a downloadable, genuinely-decrypted file; the wrong password shows a clear error with no raw exception/path text; uploading a PDF that isn't actually encrypted (with any password typed in) succeeds and passes through cleanly, not erroring.
- Confirm every OTHER existing tool (e.g. Watermark) still shows its normal result (no message line appears, since `result.message` is `null`/`undefined` for those routes) — no regression from the `ToolView.jsx` result-shape change.

- [ ] **Step 11: Commit**

```bash
git add web/frontend/src/toolConfigs.js web/frontend/src/components/ToolGrid.jsx web/frontend/src/components/ToolView.jsx web/frontend/src/App.jsx web/frontend/src/api.js web/frontend/src/components/UnlockPdfView.jsx web/frontend/src/index.css
git commit -m "feat: add the Repair, Protect, and Unlock frontend"
```

No `Co-Authored-By` trailer.

---

## Final check

- [ ] Run the full backend test suite once more: `./venv/Scripts/python.exe -m pytest tests/ -v` — all passing (209).
- [ ] Run `cd web/frontend && npm run build` once more — clean build.
- [ ] Confirm `git log --oneline` shows one commit per task above (4 total), in order, none carrying a `Co-Authored-By` trailer (all are `feat:`).
- [ ] Confirm "Repair PDF", "Protect PDF", and "Unlock PDF" all appear correctly in the tool grid under Optimize, each with a real (non-fallback) icon.
- [ ] Confirm no OTHER existing tool's result display regressed (the `ToolView.jsx` result-shape change from `data.outputs` to `data` is backward compatible — spot-check at least one other tool, e.g. Merge or Watermark, still works end-to-end).
