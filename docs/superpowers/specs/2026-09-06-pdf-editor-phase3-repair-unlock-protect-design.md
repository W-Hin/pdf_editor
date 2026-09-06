# Phase 3, Group 2: Repair + Unlock + Protect — Design

**Status:** Approved by user 2026-09-06.

## Context

Second sub-project of Phase 3 (see the decomposition and queue order in
`docs/superpowers/specs/2026-09-06-pdf-editor-phase3-compare-markdown-design.md`'s Context
section). All three tools here are built on `pikepdf` (a prebuilt-wheel Python binding for
`qpdf`, no separate binary install) — the smallest new dependency of the remaining Phase 3 groups.

Verified empirically before writing this spec (see this session's own investigation, not just
library docs): `pikepdf` cleanly round-trips encrypt/decrypt with a distinguishable
`pikepdf.PasswordError` on a wrong password; `pikepdf.open()` performs `qpdf`'s structural
recovery automatically, and `pdf.get_warnings()` reliably reports whether recovery was actually
needed (empty list for a healthy file, populated with the specific structural issues for a
genuinely damaged one) — this is what makes Repair's "healthy vs. recovered" reporting possible
without needing to know a corrupted file's unknowable "true original" state.

Also found and resolved during brainstorming: every existing upload in this app immediately
tries to open the file (for page count + thumbnail), which currently rejects any encrypted PDF
outright and deletes the just-uploaded file — meaning the normal "upload, then configure" flow
can never even reach a password field for an encrypted file. Unlock therefore gets its own
combined upload endpoint (file + password together), not the standard two-step flow every other
tool uses.

## Scope decisions (from brainstorming)

- **Repair reports page count before/after and a clear success/partial-recovery message** — not
  a raw structural repair log. "File is healthy, N pages" or "Recovered N pages after M
  structural issues found," using `pikepdf`'s own warning count as the signal, not a diagnostic
  dump of qpdf's internals (written for PDF-format debugging, not this app's audience).
- **Unlock takes the file and password together in one combined step** — a dedicated form, not
  the standard upload-then-configure flow, since the standard flow can't even accept an encrypted
  file to begin with.
- **Protect exposes a single password only** — used as both PDF's "user" (open) and "owner"
  (permissions) password, with no separate permissions/restrictions UI (allow printing, allow
  copying, etc.). Matches this app's existing YAGNI pattern of not exposing configuration nobody
  asked for.
- **Encryption is always AES-256 (`pikepdf.Encryption(..., R=6)`)** — the modern secure default,
  no legacy RC4/40-bit option exposed.

## Architecture

### Repair

`app/core/pdf_repair.py` (new module — shared home for all three tools here, since they're all
thin wrappers around `pikepdf` operations distinct from `pdf_ops.py`'s PyMuPDF-based logic):

```python
def repair_pdf(input_path: str, output_path: str) -> dict:
    """Returns {"page_count": int, "warnings_count": int}."""
```

Opens `input_path` via `pikepdf.open()` (qpdf's structural recovery runs automatically for
damaged files), reads `len(pdf.get_warnings())`, saves to `output_path`, returns the page count
and warning count. If `pikepdf.open()` itself raises (confirmed empirically: past a certain
corruption threshold, even qpdf's recovery gives up and raises `pikepdf.PdfError` with a message
like "unable to find any pages while recovering damaged file"), that's caught and re-raised as a
plain `PDFError` with a user-facing message — no different from any other tool's failure path.

Route: `POST /api/tools/repair` in `tools.py`, fitting the existing single-file-in/single-file-out
shape exactly. The response's summary text (healthy vs. recovered, with counts) is added to
`_output_response`'s existing per-tool result-summary convention (whatever the current tools use
to show e.g. Watermark's applied settings alongside the download link — confirmed during planning
against the current `_output_response`/frontend result-display code).

### Unlock

Also in `pdf_repair.py`:

```python
def unlock_pdf(input_path: str, output_path: str, password: str) -> None:
```

`pikepdf.open(input_path, password=password)` then `.save(output_path)` with no `encryption=`
argument (a plain, decrypted copy). A wrong password raises `pikepdf.PasswordError`, caught and
turned into `PDFError("Incorrect password.")` — the underlying exception's raw text (which
includes the input file's temp path) is never shown to the user.

Because the normal upload flow can't accept an encrypted file, Unlock gets a dedicated route,
`POST /api/tools/unlock`, accepting multipart form data (`file`, `password`) in one request rather
than a `file_id` referencing an already-uploaded file. It saves the upload to a temp path
server-side, calls `unlock_pdf`, and returns the normal `_output_response` shape on success (the
decrypted file is now a normal output, downloadable and recorded in history like anything else).
On a wrong password, it returns a 422 with a clear message — no file is retained.

Frontend: a small dedicated form (file picker + password field + Run button), bypassing
`ToolView`'s generic upload-then-configure flow entirely — the exact wiring (a new route
component vs. a special-cased branch in `ToolView`) is decided during planning against the
current routing structure, matching how Compare PDF's two-file form is handled the same way.

### Protect

Also in `pdf_repair.py`:

```python
def protect_pdf(input_path: str, output_path: str, password: str) -> None:
```

Validates `password.strip()` is non-empty up front (`PDFError("Enter a password.")` otherwise,
matching this codebase's existing "reject empty/invalid config before doing any real work"
convention), then `pikepdf.open(input_path)` → `.save(output_path, encryption=pikepdf.Encryption(
user=password, owner=password, R=6))`.

Route: `POST /api/tools/protect`, fitting the normal single-file-in/single-file-out pattern (the
input file is never itself encrypted, so the standard upload flow works unmodified) — a password
field is just one more config option in `toolConfigs.js`, the same shape as Watermark's text
field.

## Testing

`tests/test_pdf_repair.py` (new file, matching `test_pdf_ops.py`'s house style — throwaway PDFs
generated at test time, every numeric claim verified empirically before being written into a
test, not guessed):

- `test_repair_pdf_reports_healthy_file_with_no_warnings`: a normal PDF — `warnings_count == 0`,
  correct page count.
- `test_repair_pdf_recovers_a_truncated_file`: a PDF truncated to a level confirmed (during
  planning, by actually running it) to still be recoverable — `warnings_count > 0`, and the
  recovered page count matches exactly what `pikepdf` actually salvages at that truncation level
  (not an assumed "original" count).
- `test_repair_pdf_raises_on_unrecoverable_file`: truncated past the point confirmed to break even
  `pikepdf`'s recovery — asserts `PDFError`.
- `test_unlock_pdf_decrypts_with_correct_password`: encrypt via `pikepdf.Encryption`, unlock,
  assert the output's `is_encrypted` is `False` via `fitz`.
- `test_unlock_pdf_rejects_wrong_password`: same encrypted fixture, wrong password — `PDFError`,
  message contains no raw exception/path text.
- `test_protect_pdf_encrypts_with_password`: output's `is_encrypted` is `True`, and re-opening
  with the exact password given succeeds.
- `test_protect_pdf_rejects_empty_password`: `PDFError`, no output file written.

Route-level tests (`tests/web/`) for Unlock's combined file+password endpoint: success, wrong
password, and the case where the uploaded file isn't actually encrypted at all (should pass
through cleanly as a plain copy, not error — `pikepdf.open()` with a `password=` on an
unencrypted file is a normal, harmless no-op, confirmed to be worth an explicit test since it's an
easy edge case to get wrong).

No frontend automated tests (established convention) — manual checklist: Repair on both a healthy
and a truncated file; Unlock with correct and incorrect passwords, and with a non-encrypted file
given by mistake; Protect producing a file that genuinely requires the password to open in a
separate PDF viewer, not just within this app.

## Out of scope

- Permission-only restrictions (printing/copying disabled without an open password) — single
  password only, per the scope decision above.
- A structural repair diagnostic log — summary counts only.
- Detecting/warning the user elsewhere in the app when PyMuPDF's own SILENT auto-repair (already
  present in every existing tool via `open_pdf`) kicks in — out of scope for this spec; Repair is
  a dedicated, explicit tool, not a change to existing tools' error handling.
