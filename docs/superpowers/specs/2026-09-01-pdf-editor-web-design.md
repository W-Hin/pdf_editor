# PDF Editor Web — Design Spec

Date: 2026-09-01
Status: Approved for planning

## Purpose

Replace the primary way of using PDF Editor from the PySide6 desktop app to a
local, offline web app (FastAPI backend + React frontend), driven by two
concrete complaints about the desktop app:

1. **Remove Pages (and Extract Pages) are not usable** — the page list is
   text-only ("Page 1", "Page 2", ...), so removing a specific page means
   counting through the document rather than looking at it.
2. **The UI, especially page previews, is too small to read.**

A React-based web UI, backed by the already-built and already-tested
`app/core/` PDF logic, solves both: a properly-sized, clickable thumbnail
grid replaces the text checklist, and web layout gives far more room than a
fixed-size Qt dialog.

A third feature was added during design: a persistent **output history**
("Recent Files"), since the app currently has no single place to find files
it has produced.

## Relationship to the existing desktop app

The PySide6 app (`app/`) is **not deleted or modified**. It's fully built,
tested, and shipped (see `docs/superpowers/plans/2026-09-01-pdf-editor-v1.md`).
The web app is new, separate code that reuses `app/core/pdf_ops.py` and
`app/core/convert.py` as-is (both are already pure Python with zero Qt
dependency, by original design) — no changes needed there. Going forward,
the web app is the primary/recommended way to use PDF Editor; the desktop
app remains as a working fallback.

## Architecture

- **Backend**: FastAPI, running locally via `uvicorn`. Wraps the existing
  `app/core/` functions behind a small HTTP API — no PDF logic lives in the
  backend layer itself, only request/response plumbing and file I/O.
- **Frontend**: React + Vite, a single-page app served as static files by
  the same FastAPI process (no separate frontend server, no CDN
  dependencies — this must work fully offline).
- **Launch**: a Python launcher script starts the FastAPI/uvicorn server on
  `127.0.0.1:<port>` and opens the system's default browser to it via
  `webbrowser.open()`. The Desktop shortcut (from the original build) gets
  repointed at this launcher instead of the old `.exe`. Packaging this
  launcher + backend + built frontend into a standalone `.exe` (mirroring
  the desktop app's PyInstaller build) is a later step — the app must work
  correctly first.
- **Everything runs on localhost.** No data leaves the machine, no internet
  connection is required at any point.

## Components

```
web/
  backend/
    __init__.py
    main.py              — FastAPI app: mounts routers, serves built frontend static files
    storage.py            — upload/session temp-file handling + output library + history.json read/write
    routes/
      __init__.py
      files.py             — upload, thumbnail, download endpoints
      tools.py             — one endpoint per tool (merge, split, remove-pages, ...)
      history.py           — list/delete output history
  frontend/
    package.json, vite.config.js, index.html
    src/
      main.jsx
      App.jsx              — routing: tool grid / tool view / recent files
      api.js                — fetch wrappers for backend endpoints
      components/
        ToolGrid.jsx         — home screen, categorized tool buttons
        PageGrid.jsx          — reusable thumbnail grid: click-select mode, drag-reorder mode, view-only mode
        RecentFiles.jsx       — output history list, download + delete
        tool views (one per tool, reusing PageGrid + an options form)
  launch.py                — starts uvicorn, opens the browser
tests/
  web/
    test_files.py           — upload, thumbnail, download endpoints
    test_tools.py            — one or more tests per tool endpoint
    test_history.py          — history list/delete
```

## Page-selection interaction

This is the feature that directly answers the original complaint.

- **Remove Pages / Extract Pages**: `PageGrid` renders one real page
  thumbnail per page (not text), large enough to actually read. Clicking a
  thumbnail toggles its selected state — a highlighted border plus a
  checkmark badge when selected, click again to deselect. A selected-count
  indicator and the Run button sit above/below the grid.
- **Reorder Pages**: same `PageGrid`, drag-and-drop (native HTML5 drag
  events — no extra dependency) to reorder thumbnails; the visual order at
  Run time becomes the new page order.
- **Every other tool** (Rotate, Watermark, Compress, PDF→JPG, PDF→Word,
  Merge, Split): `PageGrid` in view-only mode shows the input's pages as
  context, with no click/drag interaction — same idea as the desktop app's
  thumbnail strip, just far larger and clearer.

## Output storage & history ("Recent Files")

- Every successful operation writes its output to a dedicated library
  folder: `~/Documents/PDF Editor Output/` (this **replaces** the desktop
  app's convention of writing next to the input file — outputs scattered
  across arbitrary input folders would defeat the point of a unified
  history).
- Each write appends one record to `history.json` in that same folder:
  `{id, filename, path, tool, created_at, source_filenames}`.
- A **Recent Files** page (`GET /api/history`, newest first) lists every
  produced file with the tool that made it, when, and a download button.
- A delete action (`DELETE /api/history/{id}`) removes both the history
  entry and the underlying file — one action, no orphaned state either
  direction.
- Scope, confirmed during design: **outputs only**. Uploaded/input files
  are not tracked in history — only what the app produces.

## Data flow

1. Launch → server starts on localhost → browser opens to the tool grid.
2. Pick a tool → drop/select an input file → `POST /api/files` (multipart
   upload) → backend saves it to a temp upload area, returns a file ID and
   page count.
3. Frontend renders `PageGrid` using
   `GET /api/files/{id}/pages/{n}/thumbnail` (real PNG per page, browser
   handles loading/caching naturally — no base64/JSON wrapping).
4. User selects pages / sets options (per the interaction rules above) →
   Run → `POST` to the tool-specific endpoint with the file ID(s) and
   params.
5. Backend runs the matching `app/core/` function, writes the result into
   the output library folder, appends a `history.json` record, returns the
   new output's file ID.
6. Frontend shows a "Done" state with a download link
   (`GET /api/files/{id}/download`) — the browser's native download flow
   handles the actual save. The file now also appears in Recent Files.

## Error handling

Backend `PDFError`s (encrypted file, invalid PDF, bad page range, etc. —
the same exceptions already raised by `app/core/`) are returned as a
structured error response (HTTP 422 with the message in the JSON body),
not an unhandled 500. The frontend shows these as a plain-language
toast/banner — the same messages the desktop app already surfaces, just in
a different UI shell.

## Testing

- **Backend**: `pytest` + FastAPI's `TestClient`, same rigor as the
  existing 30 `app/core/` tests — one or more tests per route (upload,
  thumbnail, each tool endpoint, history list/delete), verifying real
  behavior (status codes, actual file output, actual history entries) not
  just "no exception."
- **Frontend**: manual click-through verification, same policy already
  established for the desktop app's Qt UI — no automated JS test framework
  for a personal project's UI layer. `app/core/`'s existing 30 tests are
  unaffected and continue to pass unchanged, since no core code changes.

## Feature scope (v1)

Same 10 tools as the desktop app, since the underlying logic is already
built and tested — the marginal cost per tool here is one API endpoint +
one React view, not a full dialog build:

Merge, Split, Remove pages, Extract pages, Reorder pages, Rotate, Add
watermark, Compress, PDF→JPG, PDF→Word.

Plus the new Recent Files / output history page (not a "tool," but a core
part of this build).

## Open questions / risks

- React requires Node.js + npm installed to build the frontend during
  development; the built static output (what actually ships) has no such
  requirement at runtime — only Python/FastAPI needs to be running.
- Packaging the whole thing (backend + built frontend) into a standalone
  `.exe` via PyInstaller is deferred to a later phase of this same
  project, after the app works correctly as a dev-mode local server.
- **Mobile (raised during design, explicitly out of scope for this
  build)**: because the frontend is now a real web app, a *thin-client*
  Android APK is realistic later — wrap the built React app with something
  like Capacitor and point it at the FastAPI server's LAN address instead
  of `localhost`. This requires the PC running the server to be on and
  reachable over the same network; it is not a standalone-on-phone app.
  Running the actual PDF engine natively on-device (no PC involved) would
  mean embedding Python in the APK (e.g. via Chaquopy), which is
  unsupported/uncertain for PyMuPDF and is real research, not a build
  task — not recommended. Neither path is part of this plan.
