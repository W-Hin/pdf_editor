# Desktop App: Crop PDF and Redact PDF — Design

**Status:** Approved by user 2026-09-17.

## Context

Sub-project 2 of the 6 "hard" desktop tools identified while closing the
desktop app's tool gap (sub-project 1, the 10 easy dialogs, shipped this
session as v0.9.0 — see
`docs/superpowers/specs/2026-09-17-pdf-editor-desktop-easy-dialogs-design.md`).
Crop and Redact were grouped together because both need the same core
interaction the web app already has: drag a rectangle over a page preview.
Confirmed by reading the actual web implementations fresh:

- `CropSelector.jsx`: a single draggable box over page 1's preview only,
  converted to `{top, left, right, bottom}` page-fraction insets on mouse-up
  (`pointFromEvent` clamps to [0,1] and divides by the container's own
  rendered size; `MIN_DRAG_FRACTION = 0.02` ignores accidental tiny drags).
  Re-dragging replaces the box outright — there's no separate "remove"
  affordance.
- `RedactSelector.jsx`: the same per-point math, but multiple boxes across
  any number of pages, each independently removable via a small × button
  drawn on the box itself. Uses `PageScrollViewer` to show every page in one
  continuous scroll.
- `app/core/pdf_ops.py`: `crop_pdf(input_path, output_path, top, right,
  bottom, left)` — one set of four floats, applied identically to every
  page; already validates ranges and "positive width/height", raising
  `PDFError`. `redact_pdf(input_path, output_path, redactions: list[dict])`
  — each dict `{"page": int, "top": float, "right": float, "bottom": float,
  "left": float}`; already raises `PDFError("Select at least one area to
  redact.")` for an empty list, plus the same per-box range/size validation.
- Both routes in `web/backend/routes/tools.py` are thin passthroughs to
  these functions, confirming the dialogs need to gather exactly this shape
  and nothing more.

Neither tool fits `app/ui/dialogs/base.py`'s `ToolDialog` as-is — its
`__init__` hard-codes building a passive horizontal thumbnail strip, but
both tools need an *interactive* preview in its place.

**Testability was verified, not assumed, before proposing this design**:
`QTest.mousePress`/`mouseMove`/`mouseRelease` (`PySide6.QtTest`) were run
against a real custom `QWidget` under `QT_QPA_PLATFORM=offscreen` (this
project's only way to drive PySide6 without a display) and correctly
triggered `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`, producing
exact fraction coordinates matching the synthesized drag. This means the
core drag-rectangle interaction — and a click-to-remove-a-box interaction,
by computing the marker's expected pixel position and synthesizing a click
there — is fully testable by an implementer with no display.

## Scope decisions (from brainstorming)

- **Redact shows one page at a time** (a page-number spinner above the
  preview), not the web app's continuous scroll of every page — chosen over
  full UX parity because a scrollable multi-page canvas is meaningfully more
  work for a desktop "fallback" app, and redactions still accumulate across
  every page visited in the same underlying `{page, top, left, right,
  bottom}` list the web app uses, just navigated differently.
- **Removing a redaction box works by clicking its × marker directly**,
  matching the web app's UX exactly (a side-list-with-Remove-button
  alternative was considered and declined) — confirmed buildable and
  testable via the `QTest` verification above before committing to it.
- **Crop has no remove affordance**, matching `CropSelector.jsx` exactly —
  dragging a new box simply replaces the old one.

## Architecture

### `ToolDialog` base-class extension

`app/ui/dialogs/base.py`'s `__init__` currently builds the thumbnail strip
inline. It gains a new override point, `build_preview(container)`, called
where that inline code currently sits — the method's *default*
implementation is exactly today's thumbnail-strip code, moved verbatim, so
none of the 15 existing dialogs change behavior at all. `_refresh_thumbnails`
(called from `_pick_files`) becomes a no-op when `self._thumbnail_layout`
doesn't exist (i.e., a subclass overrode `build_preview` and built something
else instead), guarded by a single `hasattr` check at its top.

A new `dialog_size: tuple[int, int] = (480, 360)` class attribute replaces
the hard-coded `self.resize(480, 360)` call, read as `self.resize(*self.dialog_size)`
— matching the existing `title`/`file_filter`/`allow_multiple_files`
class-attribute override convention. `CropDialog`/`RedactDialog` set a
larger `dialog_size` to fit their bigger preview.

### `RectangleOverlayWidget` (new file: `app/ui/widgets.py`)

A `QWidget` subclass, shared by both dialogs:

- `set_pixmap(pixmap: QPixmap)` — stores it and calls `setFixedSize(pixmap.size())`.
- `set_boxes(boxes: list[dict])` / `.boxes` — the currently-displayed
  fraction-space boxes (`{"x0","y0","x1","y1"}`), settable directly (needed
  by `RedactDialog` when switching pages).
- `single_box() -> dict | None` — convenience for `CropDialog` (`multi=False`
  always has 0 or 1 boxes).
- `mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent` reproduce
  `CropSelector.jsx`/`RedactSelector.jsx`'s exact point-from-position and
  `MIN_DRAG_FRACTION = 0.02` logic. In `multi=True` mode, `mousePressEvent`
  first hit-tests against each existing box's marker rect (computed fresh
  from current widget size — a small fixed-pixel square at the box's
  top-right corner) and removes that box instead of starting a drag if hit.
- `paintEvent` draws the pixmap, then every committed box, then (in
  `multi=True`) each box's × marker, then the in-progress drag box if any.

Two module-level helpers alongside the widget:
```python
def box_to_insets(box: dict) -> dict:
    return {"top": box["y0"], "left": box["x0"], "right": 1 - box["x1"], "bottom": 1 - box["y1"]}

def insets_to_box(insets: dict) -> dict:
    return {"x0": insets["left"], "y0": insets["top"], "x1": 1 - insets["right"], "y1": 1 - insets["bottom"]}
```

### `CropDialog` and `RedactDialog` (both in `app/ui/dialogs/edit_dialogs.py`
— both tools are "Edit" category per `toolConfigs.js`, confirmed fresh; no
new dialog file needed)

`CropDialog`: `build_preview` creates one `RectangleOverlayWidget(multi=False)`;
`on_files_changed` loads page 1's thumbnail into it (a larger `max_size`
than the existing 100px thumbnail strip — matching `CropSelector.jsx`'s own
`PREVIEW_MAX_SIZE = 700`); `gather_params` returns `{"box": self.overlay.single_box()}`;
`run_operation` raises `PDFError("Drag to select a crop area first.")` if
`box` is `None` (a case `crop_pdf`'s signature has no way to express itself,
unlike Protect/Unlock's core-level validation this session's earlier dialogs
could just delegate to), otherwise converts via `box_to_insets` and calls
`crop_pdf`. Output: `<stem>_cropped.pdf`.

`RedactDialog`: `build_preview` adds a `QSpinBox` page selector above the
same kind of overlay widget (`multi=True`). Switching pages (or finalizing
via `gather_params`) flushes the currently-displayed page's `overlay.boxes`
into an accumulated `self._all_redactions: list[dict]` (page-tagged, in the
core function's own dict shape) before loading whichever boxes already
exist for the newly-selected page via `insets_to_box`. `redact_pdf` already
raises `PDFError("Select at least one area to redact.")` for an empty list
— no extra dialog-side check needed. Output: `<stem>_redacted.pdf`.

### `app/main.py`

Two new imports from `edit_dialogs`, two new `window.add_tool("Edit", ...)`
registrations.

## Testing

No automated tests exist for `app/ui/` and none are added here, matching
established convention. Manual verification is driven entirely through
`QT_QPA_PLATFORM=offscreen` + `QTest` synthetic mouse events (confirmed
working above) rather than a real window — for each dialog: synthesize a
drag to draw a box, confirm the resulting fraction coordinates and the
final exported PDF's actual crop/redaction; for Redact specifically, also
synthesize a drag on one page, switch pages via the spinner, draw a second
box, switch back, confirm the first page's box is still there, then
synthesize a click on that box's marker rect and confirm it's removed.

## Out of scope

- Redact's continuous multi-page scroll (see scope decisions above) — one
  page at a time instead.
- Any change to `crop_pdf`/`redact_pdf` or their web routes — both already
  exist, are already tested, and need no changes; this is a pure
  desktop-UI addition consuming them exactly as the web app does.
- The remaining 4 hard tools (Sign, PDF Forms, Compare, Edit PDF) — each
  still needs its own future brainstorm.
