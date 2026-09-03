# Phase 2, Group D2: PDF Forms — Design

**Status:** Approved by user 2026-09-03.

## Context

This is the second and final sub-project of Phase 2's Group D (see
`docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s roadmap). Group D was originally
scoped as "PDF Forms, Sign" bundled together, but split during Sign's brainstorming (see
`docs/superpowers/specs/2026-09-03-pdf-editor-phase2-sign-design.md`'s Context section) because
PDF Forms is a completely different mechanism from every prior Phase 2 tool: it detects
pre-existing form fields already embedded in a PDF and lets the user fill them, rather than
drawing, placing, or editing anything new on the page.

## Key technical findings (verified empirically before finalizing this design)

All verified directly against this project's actual PyMuPDF version via throwaway scripts before
writing this spec:

1. **Field detection is direct.** `page.widgets()` reports each field's name, type
   (`field_type_string`: `"Text"`, `"CheckBox"`, `"ComboBox"`, plus `"RadioButton"` and others this
   spec excludes), position (`rect`), and current value — no parsing or reconstruction needed.
2. **Writing a value and persisting it works exactly as expected.** Setting `widget.field_value`
   and calling `widget.update()`, then saving, round-trips correctly on reopen — verified for
   Text, CheckBox, and ComboBox.
3. **Checkbox on/off values can vary per-PDF, but a plain boolean is a safe interface regardless.**
   `widget.button_states()` reports each checkbox's actual export-value strings (e.g.
   `{'normal': ['Off', 'Yes']}` — some forms use different strings), but setting `field_value` to
   a plain Python `True`/`False` round-trips correctly without needing to know or expose those
   strings. The frontend/backend interface for CheckBox fields is therefore a simple boolean, not
   a raw PDF export-value string.
4. **`doc.bake(annots=False, widgets=True)` genuinely flattens a filled form.** Verified: after
   `bake()`, zero widgets remain, `doc.is_form_pdf` becomes `False`, and the filled values appear
   as real, static extracted text — not just visually similar, genuinely converted to permanent
   page content. `annots=False` deliberately leaves any other annotations (e.g. from Redact/Edit
   PDF/Sign, if this file passed through those first) untouched — only form widgets are baked.

## Scope decisions (from brainstorming)

- **Field types: Text, CheckBox, ComboBox (dropdown) only.** Covers the large majority of
  real-world fillable PDFs. Radio button groups and multi-select list boxes are deferred — radio
  groups specifically need extra logic (matching multiple widgets to one logical field, each with
  its own distinct "on" export value) that's out of proportion for a first version.
- **Fields are addressed by `(page, index-within-page)`**, not by field name — mirroring Edit
  Text's `run_index` precedent exactly. This sidesteps any assumption that field names are unique
  (real-world forms occasionally reuse or omit them); the field's name/label is used only for
  display, never as an identifying key.
- **Fields are overlaid directly on the page at their real position** — real HTML form controls
  (a text input, a checkbox, a select) positioned over the rendered page image at each field's
  actual rect, navigable across pages like Redact/Edit PDF/Sign. Not a page-position-agnostic flat
  list.
- **Output is always flattened** (`doc.bake(widgets=True)`) — no toggle for "keep as an editable
  form." The saved PDF looks the same but the fields become permanent content, matching what most
  people expect from a "filled and finished" form. If someone needs to change a filled form later,
  Edit PDF (already shipped) can edit any text on any PDF regardless of whether it was ever a
  form — that's the escape hatch, not a toggle here.
- **Run stays disabled until at least one field's value has changed** from what it was when the
  file was loaded — matching Redact/Edit PDF/Sign's exact "at least one edit queued" precedent.

## Architecture

### Backend

`app/core/pdf_ops.py` gets two new functions:

```python
def extract_form_fields(input_path: str) -> list[dict]
```
Walks every page's `page.widgets()`, keeping only `field_type_string` in `{"Text", "CheckBox",
"ComboBox"}`, skipping everything else (RadioButton, ListBox, Signature, etc.). Returns each kept
widget as:
```python
{
    "page": int,           # 1-indexed
    "index": int,          # position within this page's widget walk (the addressing key)
    "label": str,          # widget.field_label, falling back to widget.field_name if unset
    "type": str,           # "text" | "checkbox" | "combobox"
    "rect": {"top": float, "left": float, "right": float, "bottom": float},  # displayed-space
                                                                              # fractions, via
                                                                              # rotation_matrix —
                                                                              # same convention
                                                                              # and same mapping
                                                                              # Edit Text's run
                                                                              # bboxes use
    "value": str | bool,   # current text/combobox value, or checked state for checkbox
    "choices": list[str] | None,  # ComboBox only, else None
}
```

```python
def fill_form(input_path: str, output_path: str, values: list[dict]) -> None
```
Each item in `values` is `{"page": int, "index": int, "value": str | bool}`. Processing:
1. Validate every `(page, index)` up front, before any widget is touched — reusing
   `extract_form_fields`'s *exact* per-page widget walk (not a re-implementation) so indices are
   guaranteed to correspond, the same lesson the Edit Text `run_index` design already established.
2. For each entry, set the matched widget's `field_value` to the given value and call
   `.update()`.
3. `doc.bake(annots=False, widgets=True)` to flatten.
4. Save.

A corrupt/unreadable input PDF raises `PDFError` via the existing `open_pdf()` path.

`web/backend/routes/files.py` gets one new route, sibling to the existing thumbnail/text-runs
routes:
```
GET /files/{file_id}/form-fields → {"fields": [...]}
```
(All fields across all pages in one call — forms are small enough that per-page fetching, like
Edit Text needed for potentially-large text-run counts, isn't worth the added complexity.)

`web/backend/routes/tools.py` gets one new route:
```
POST /tools/fill-form   body: {"file_id": str, "values": [{"page": int, "index": int, "value": str | bool}, ...]}
```
Following the established pattern: resolve `file_id`, convert validated Pydantic values to plain
dicts, call `fill_form()`, return via `_output_response()`.

### Frontend

New `FormFillCanvas.jsx`, structurally like `RedactSelector`/`EditPdfCanvas` (page nav,
`key={primaryFile.id}` remount fix from the start) but each field renders as a real HTML form
control — `<input type="text">`, `<input type="checkbox">`, or `<select>` — absolutely positioned
at the field's `rect` over the rendered page image, pre-filled with its current value, rather than
a drawn box or placed image.

- On file load, fetch all fields once via `GET .../form-fields`. If `fields.length === 0`, render
  "No fillable fields found in this document" instead of any page canvas — this is the common
  case (most PDFs aren't authored as fillable forms), so it must read as normal, not broken.
- **Page nav:** Previous/Next, "Page X of N (K fields changed)" — `K` computed the same way
  Redact/Edit PDF compute their marked-page/edit counts, but counting *changed* fields specifically
  (not just fields present), matching the Run-gating decision.
- Each field's current value is tracked in local state, initialized from the fetched `value`.
  Typing in a text input, toggling a checkbox, or picking a combobox option updates that field's
  entry.
- **Run:** disabled until at least one field's value differs from its initial fetched value,
  matching `config.preview === "fill-form" && changedCount === 0`-style guard already established
  by Crop/Redact/Edit PDF/Sign in `ToolView.jsx`. The request body includes only the *changed*
  fields — `fill_form` only touches what's given, so unchanged fields are simply omitted.

`toolConfigs.js` gets a `fill-form` entry: category `"Edit"`, `multiFile: false`,
`preview: "fill-form"`, `endpoint: "fill-form"`, `fields: []`.

## Error handling

- `extract_form_fields`: a corrupt/unreadable PDF raises `PDFError` via the existing `open_pdf()`
  path.
- `fill_form`: every `(page, index)` validated against a fresh `extract_form_fields` walk before
  any widget is touched — a bad reference leaves no partially-filled output.
- The route reuses `storage.resolve_file()` — an unknown `file_id` 404s via the existing app-level
  handler, identical to every other tool.
- Frontend: the "no fillable fields" empty state is a first-class, expected UI state, not an
  error. Run stays disabled until at least one field has changed.

## Testing

- `app/core/pdf_ops.py` unit tests (`tests/test_pdf_ops.py`): `extract_form_fields` returns
  correct data for a Text/CheckBox/ComboBox widget built the same way this spec's own empirical
  probes were (`page.add_widget()`), including a rotated-page case for the rect-mapping (this
  project's recurring bug class — a dedicated regression test here too, not assumed safe by
  analogy); `fill_form` genuinely changes the value (extract before/after) and genuinely flattens
  (assert `is_form_pdf` is `False` and zero widgets remain afterward, not just "ran without
  error"); out-of-range `(page, index)` rejected before any page is modified.
- `web/backend/routes/*` route tests: success case, unknown `file_id` → 404, bad `(page, index)` →
  422.
- No new frontend automated tests, per this project's established convention — manual browser
  verification at the end of implementation: a form-bearing PDF shows the right control type at
  the right position for each field; a non-form PDF shows the empty-state message; filling and
  running produces genuinely static, flattened output; file-switch resets state.

## Out of scope (for this spec)

- Radio button groups and list boxes (deferred — see Scope decisions).
- Signature form fields (cryptographic signing is out of scope project-wide, same as Sign).
- Required-field validation/enforcement — the PDF's own "required" flag is not checked; the user
  can Run with any subset of fields filled.
- A flatten/keep-editable toggle — always flattens; Edit PDF is the escape hatch for post-hoc
  changes to a filled form.
- Adding brand-new text anywhere on a page with custom font/size/style controls (a separate,
  already-flagged gap in the shipped Edit PDF tool, to be brainstormed as its own follow-up after
  this spec).
