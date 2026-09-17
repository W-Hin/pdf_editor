# Desktop App: PDF Forms — Design

**Status:** Approved by user 2026-09-17.

## Context

Sub-project 4 of the 6 "hard" desktop tools identified while closing the
desktop app's tool gap (sub-project 1, the 10 easy dialogs; sub-project 2,
Crop+Redact; sub-project 3, Sign PDF — all three shipped, released as
v0.10.0). Unlike Sign PDF, this sub-project turned out to be narrow rather
than interaction-heavy: reading `web/frontend/src/toolConfigs.js`'s
`fill-form` entry and its component, `FormFillCanvas.jsx`, in full confirms
PDF Forms is purely a **fill** tool for an existing document's AcroForm
fields — there is no field-creation mode, no radio-button type, no
date/signature field type. `app/core/pdf_ops.py` already has everything
the desktop app needs, unchanged:

- `extract_form_fields(input_path) -> list[dict]` (line 958): one dict per
  fillable widget, `{page, index, label, type, rect, value, choices}`.
  `type` is exactly one of `"text"`, `"checkbox"`, `"combobox"` — the
  complete set (`_FORM_FIELD_TYPE_NAMES`, line 946). `rect` is a
  `{top, left, right, bottom}` inset-fraction dict, same convention as
  `RedactDialog`'s boxes. `choices` is only present (as a list of strings)
  for `combobox` fields.
- `fill_form(input_path, output_path, values) -> None` (line 997): takes
  `values: list[{"page": int, "index": int, "value": Any}]` and writes each
  field's new value, baking the result. Already raises
  `PDFError("Fill in at least one field before running.")` for an empty
  `values` list — the same "let core validate emptiness" pattern
  `edit_pdf` already gave Sign PDF, so `FillFormDialog` needs no dialog-level
  equivalent of that check either.

The desktop app has no existing widget that overlays *real* Qt input
controls on a page image — `RectangleOverlayWidget`/`SignaturePadWidget`/
`ImagePlacementWidget` all draw everything themselves via `QPainter`. PDF
Forms is the first tool where the right building block is genuine
`QLineEdit`/`QCheckBox`/`QComboBox` children positioned on top of a page
pixmap, mirroring what `FormFillCanvas.jsx` does with real `<input>`/
`<select>` elements positioned by CSS percentages.

## Scope decision (from brainstorming)

- **Continuous scroll of all pages**, matching the web app's
  `PageScrollViewer` exactly (the user's explicit choice over the
  simpler one-page-at-a-time convention every other desktop dialog this
  session has used) — every field on every page is reachable without
  switching pages, which matters more here than for Crop/Redact/Sign since
  a form's fields are often scattered across a multi-page document rather
  than concentrated on one page.

## Architecture

### `FormFieldsWidget` (new, in `app/ui/widgets.py`)

A `QScrollArea` whose contents are a `QVBoxLayout` stacking one "page
frame" per page, top to bottom:

- Each page frame is a plain `QWidget`, `setFixedSize` to that page's
  rendered `QPixmap` (via `render_page_thumbnail`, same mechanism every
  other dialog already uses for previews).
- A background `QLabel` (pixmap set, `setGeometry(0, 0, w, h)`) fills the
  frame first.
- One real input widget per field on that page is added as a **later**
  child of the same frame, so it paints on top of the background label
  without any custom `paintEvent` — plain Qt z-order via creation order,
  the same reason `ImagePlacementWidget` never needed to think about
  stacking (there, the reverse: it draws everything itself). Each widget's
  `.setGeometry()` is computed from the field's inset-fraction `rect` ×
  pixmap size (identical conversion `box_to_insets`/`insets_to_box` already
  encode, adapted from box corners to a single rect):
  ```
  x = rect["left"] * pixmap_width
  y = rect["top"] * pixmap_height
  w = (1 - rect["left"] - rect["right"]) * pixmap_width
  h = (1 - rect["top"] - rect["bottom"]) * pixmap_height
  ```
- Field type → widget: `"text"` → `QLineEdit` (`.setText(value)`),
  `"checkbox"` → `QCheckBox` (`.setChecked(bool(value))`), `"combobox"` →
  `QComboBox` (`.addItems(choices)`, `.setCurrentText(value)` if `value`
  is one of `choices` else leave at index 0 — mirrors the web version's
  own `value={values[key] ?? ""}` fallback, which likewise doesn't force
  a specific default when the current value isn't a valid choice).
  Every widget gets `.setToolTip(field["label"])`, matching
  `FormFillCanvas.jsx`'s `title={field.label}`.
- `set_fields(fields: list[dict], page_pixmaps: list[QPixmap]) -> None`:
  clears any existing page frames and rebuilds from scratch (same
  clear-then-rebuild shape `_refresh_thumbnails` already uses for the
  thumbnail strip) — called once per file load, not incrementally updated.
- `values() -> list[dict]`: reads every live field widget's current value
  and returns `[{"page": p, "index": i, "value": v}, ...]` for **all**
  held fields, not only ones the user touched — deliberately simpler than
  `FormFillCanvas.jsx`'s dirty-tracking (`values[fieldKey(f)] !==
  initialValues[fieldKey(f)]`). Re-submitting a field's own unchanged
  value through `fill_form` is a no-op in effect (it bakes the same value
  that was already there), so there is no behavioral downside, and it
  removes an entire layer of state (no separate "initial values" dict to
  keep in sync) that the widget would otherwise need to track.
- `has_fields() -> bool`: `True` iff at least one field widget was created
  during the last `set_fields` call — used by `FillFormDialog` only to
  decide whether to show the "No fillable fields found in this document."
  message (matching `FormFillCanvas.jsx`'s own such message); does **not**
  gate the Run button or duplicate `fill_form`'s own emptiness check (see
  below).

### `FillFormDialog` (`app/ui/dialogs/edit_dialogs.py`)

- `build_preview`: an instructional `QLabel` ("Fill in the fields below;
  values are read from the document as-is.") above a `FormFieldsWidget`,
  plus a status `QLabel` shown only when `has_fields()` is `False` after a
  file loads ("No fillable fields found in this document.").
- `on_files_changed`: calls `extract_form_fields(path)` once, renders every
  page 1..`get_page_count(path)` via `render_page_thumbnail`, and calls
  `self.fields_widget.set_fields(fields, pixmaps)`.
- `gather_params`: returns `{"values": self.fields_widget.values()}`. This
  runs on the GUI thread (per `ToolDialog`'s existing contract), so reading
  live widget state here — before the worker thread starts — is safe;
  `run_operation` then only ever reads from the already-snapshotted
  `params` dict, same as every other dialog.
- `run_operation`: `fill_form(input_path, out_path, params["values"])`,
  output `<stem>_filled.pdf` (matching the web route's own `_filled`
  suffix, `web/backend/routes/tools.py:555`). No dialog-level "at least one
  field" check — if the document has zero fields, `values()` naturally
  returns `[]` and `fill_form` raises its own
  `PDFError("Fill in at least one field before running.")`, the same
  "let core validate" pattern the Sign PDF plan already established for
  `edit_pdf`.

## Testing

Following the precedent set by Crop/Redact and Sign PDF: real
`PySide6.QtTest`-driven pytest tests (not a manual checklist), appended to
the existing `tests/test_ui_desktop.py`. `FormFieldsWidget`'s tests build a
real fixture PDF with actual AcroForm fields (via `fitz`'s widget API —
insert a text field, a checkbox, and a combobox with real choices on a
page, matching how other tests in this project build real fixtures rather
than mocking), call `extract_form_fields` on it for real, feed the result
into `set_fields`, then verify: each field type produced the right Qt
widget class at the right geometry (derived from the fixture's own known
rect), typing into a `QLineEdit`/toggling a `QCheckBox`/picking a
`QComboBox` option changes what `values()` reports, and `has_fields()`
correctly reports `False` for a fields-free document. `FillFormDialog`'s
test is a full end-to-end flow: build a real fixture PDF with form fields,
load it, change field values via the same synthetic widget interactions,
`gather_params`/`run_operation`, then re-open the output with `fitz` and
confirm (via a fresh `extract_form_fields` call on the *output* file) that
the new values actually landed.

## Out of scope

- Adding new form fields to a PDF that has none — this tool only fills
  what already exists, matching the web app exactly.
- Radio-button groups, date fields, or signature-field widgets — none of
  these exist in `_FORM_FIELD_TYPE_NAMES`; if a future PDF format need
  arises for them, that's a separate core-level project before any UI work.
- Any change to `extract_form_fields`, `fill_form`, or the web app's own
  `FormFillCanvas.jsx`/`fill-form` route — all already exist, already
  tested, and need no changes.
- The remaining 2 hard tools (Compare, Edit PDF) — each still needs its own
  future brainstorm; Edit PDF in particular remains a substantial project
  on its own.
