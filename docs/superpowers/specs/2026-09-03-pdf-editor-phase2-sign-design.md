# Phase 2, Group D1: Sign — Design

**Status:** Approved by user 2026-09-03.

## Context

This is a sub-project of Phase 2 (see `docs/superpowers/specs/2026-09-01-pdf-editor-design.md`'s
roadmap). Group D was originally scoped as "PDF Forms, Sign" bundled together, needing an
"overlay-elements-on-a-page UI" — but during brainstorming it was split, the same way Group C
split into Redact and Edit PDF: Sign (this spec) places a signature image on a page, mechanically
identical to Edit PDF's just-shipped Insert Image mode; PDF Forms fills pre-existing AcroForm
fields already embedded in a PDF (detected via `page.widgets()`, confirmed empirically), a
completely different mechanism with no drawing/placement step at all. PDF Forms gets its own
future spec.

## Scope decisions (from brainstorming)

- **Signature source: both upload and draw.** Matches the roadmap's own wording ("signature
  image/drawing"). Upload reuses Insert Image's exact flow; drawing uses a small signature-pad
  canvas (multiple freehand strokes, fixed black ink — not Draw mode's color/width choices, since
  a signature is conventionally single-color) that exports to a PNG on save.
- **Saved for reuse, one signature, overwritable.** Draw or upload once, it's saved to
  `localStorage` and offered as "Use saved signature" next time. Not a signature library — a new
  draw/upload replaces the saved one. Consistent with this app's fully offline, account-free
  design: no server-side storage, browser-local only.
- **Separate "Sign PDF" tool**, not a 6th mode bolted onto Edit PDF's already-dense mode switcher.
  Its own tile in the tool grid, purpose-built UI, reusing Insert Image mode's placement/resize
  code as a base rather than the whole Edit PDF canvas.
- **Multiple placements across any pages**, not a single fixed placement. Previous/Next page
  navigation (mirroring Redact/Edit PDF), place the signature on as many pages as needed in one
  Run — covers both "sign once at the end" and "initial every page."
- **No background removal.** An uploaded/drawn signature's background is placed as-is; a photo of
  ink on white paper shows its white background on the page. Matches Insert Image's existing
  behavior, keeps this spec YAGNI — real added complexity (color-key transparency) for a v1 meant
  to ship fast by reusing existing machinery. Stated explicitly as a known limitation, not silently
  "fixed."

## Architecture

### Backend — no new code

A signature placement is functionally identical to Edit PDF's `image` element: same
position/size fractions, same `insert_image` call, same rotation handling
(`_apply_image`/`_validate_image_element` in `app/core/pdf_ops.py`, already shipped and covered
by a rotated-page regression test). Sign's Run submits the exact same request shape
`edit_pdf`/`POST /tools/edit-pdf` already accept:

```json
{"file_id": "...", "elements": [{"type": "image", "page": 1, "file_id": "<sig file_id>", "x": ..., "y": ..., "width": ..., "height": ...}, ...]}
```

No new core function, no new route. This is a deliberate reuse decision, not an oversight — it
means Sign inherits Insert Image's already-independently-reviewed page-bounds clamping and
rotation correctness for free, with zero new backend surface to get wrong.

### Frontend — new `SignCanvas.jsx`

A separate, smaller component than `EditPdfCanvas.jsx`, built from Insert Image mode's exact
placement/resize/drag interaction code (not a copy-paste of the whole Edit PDF canvas — just the
one mode's mechanics, adapted).

- **Signature source panel**, shown before placement begins:
  - **"Use saved signature"** — shown only if `localStorage` has one, rendered as a thumbnail.
  - **"Draw new"** — opens a small signature-pad canvas: multiple freehand strokes (mousedown to
    mouseup, same drag-mechanics primitive Draw mode already established, but fixed black ink, no
    color/width controls), a "Clear" button to restart, a "Save" button that exports the canvas to
    a PNG (`canvas.toDataURL("image/png")`) and both saves it to `localStorage` and uses it for
    this session.
  - **"Upload new"** — a file picker, identical flow to Insert Image mode's upload.
  - Drawing or uploading a new signature **overwrites** whatever was previously saved.
- Once a signature is ready, it's uploaded once via the existing `POST /files` endpoint (same as
  Insert Image) to get a `file_id`, reused for every placement made in this session — the
  signature is only uploaded once even if placed on ten pages.
- **Placement:** Previous/Next page navigation; clicking the page preview places the signature at
  a default size centered on the click point; dragging the body repositions, dragging the corner
  handle resizes (aspect-ratio locked) — Insert Image mode's exact interaction code.
- Each placement gets a small × remove button. Run stays disabled until at least one placement
  exists (`config.preview === "sign" && placements.length === 0`-style guard, same pattern Crop
  through Edit PDF have all used in `ToolView.jsx`).
- **File-switch remount**: `<SignCanvas key={primaryFile.id} .../>` from the start — the exact
  fix Redact needed after shipping without it, applied proactively here rather than rediscovered.

`toolConfigs.js` gets a `sign` entry: category `"Edit"`, `multiFile: false`, `preview: "sign"`,
`endpoint: "edit-pdf"` (reusing Edit PDF's endpoint directly, per the backend-reuse decision
above), `fields: []`.

## Error handling

- Drawing nothing then clicking "Save" is rejected client-side ("Draw a signature first") —
  mirrors Crop's/Redact's "nothing drawn yet" guard.
- An upload that fails (bad file type, upload error) surfaces via the existing upload-flow error
  banner, same as every other tool.
- `localStorage` failures (quota exceeded, private-browsing restrictions, or simply unavailable)
  are caught and treated as "no saved signature" rather than crashing the tool — the user just
  doesn't see "Use saved signature," and a save attempt that fails falls back to "works for this
  session, just isn't remembered next time" rather than blocking the tool.
- Placement validation and backend errors come free from reusing `edit_pdf`/`POST /tools/edit-pdf`
  exactly as already shipped and reviewed — no new validation logic to get wrong.
- Run stays disabled until at least one signature is placed.

## Testing

- No new backend tests needed — `edit_pdf`'s `image` element path already has full test coverage
  (including the rotated-page regression test) from the Edit PDF plan; Sign adds no new backend
  surface.
- No new frontend automated tests, per this project's established convention for interactive
  canvas components — manual browser verification at the end of implementation: draw a signature,
  save it, reload the tool and confirm "Use saved signature" offers it; place it on two different
  pages, resize one, remove the other, Run, and inspect the output; confirm upload works as an
  alternative signature source; confirm the file-switch reset works (load file A, place a
  signature, load file B, confirm zero stale placements).

## Out of scope (for this spec)

- Cryptographic/digital signing (certificate-based signature verification) — explicitly out of
  scope per the roadmap's own wording ("not cryptographic signing").
- A library of multiple saved signatures — one saved signature, overwritable, not a signature
  manager.
- Background removal / transparency for uploaded or drawn signatures.
- Desktop (PySide6) app parity — like every other Phase 2 group so far, this ships to the web app
  only.
- PDF Forms (AcroForm field filling) — the other half of the original Group D, its own future spec
  per the split decision above.
