# Changelog

All notable changes to PDF Editor. The **web app** is what the Windows installer
(`PDFEditorSetup.exe`) packages; the **desktop app** (PySide6, `python -m app.main`) is
run from source. Both share the same PDF engine in `app/core/`, so a change to the
engine lands in both.

## 0.15.0 — 2026-09-20 (desktop)

The desktop Edit PDF dialog can now **edit existing text in place**, completing the
tool and bringing the desktop app to the same 26 tools as the web app.

- **Edit Text mode.** Double-click any line of text on a page to edit it. One rich-text
  editor covers everything: type to retype, select a range and use the family / size /
  bold / italic controls to restyle just that part. **Revert** restores the original.
- Editing a line you already edited updates that edit (never a second one); emptying a
  line erases it; opening and closing a line without changing it leaves no trace.
- Edited text can be dragged or nudged with the arrow keys, including on rotated pages.
  It cannot be copied or cut (an edit only makes sense on its own line).
- **Fixed:** typed text was silently lost if you clicked **Run** without first clicking
  back on the page. This affected New Text since 0.13.0. Run and the toolbar buttons now
  commit what you have typed first.
- **Fixed:** with several pages, two text editors could stay open at once and the style
  controls acted on the wrong one.
- **Fixed:** an invisible delete spot sat on the last characters of an edited line.
- **Fixed:** moving an edit twice on a rotated page pushed it off the page, and the
  whole document then failed to export.

## 0.14.0 — 2026-09-19 (desktop)

Desktop Edit PDF gains **shapes** (rectangle, ellipse, line, arrow), **freehand draw**
and **highlight**, with a per-tool colour and width.

- **Fixed:** dragging a shape, stroke or highlight past the page edge left it outside
  the page and made the whole document fail to export. Drags now stop at the edge, the
  same as arrow-key nudges.
- **Fixed:** right-clicking could create or delete elements and could wipe a stroke in
  progress; only the left button is used now.
- Each tool remembers its own colour and width, the selected colour is shown, and the
  default highlight colour is amber instead of red.

## 0.13.0 — 2026-09-18 (desktop)

New **Edit PDF** dialog for the desktop app: add **text** and **images**, with undo /
redo, copy / cut / paste, arrow-key nudging and bring-forward / send-back ordering.

## 0.12.0 — 2026-09-18 (desktop)

- **Compare PDF** dialog (text differences and a page-by-page visual diff).
- Crop, Redact and Sign now scroll through every page continuously instead of one page
  at a time.

## 0.11.0 — 2026-09-17 (desktop)

**PDF Forms** dialog: fill existing text, checkbox and dropdown fields.

## 0.10.0 — 2026-09-17 (desktop)

**Crop**, **Redact** and **Sign** dialogs (draw or import a signature, then place and
resize it on the page).

## 0.9.0 — 2026-09-17 (desktop)

Ten tools that the web app already had arrive on the desktop: Repair, Protect, Unlock,
OCR, PDF to PDF/A, PDF to Markdown, PDF to PowerPoint, PDF to Excel, Images to PDF and
Add page numbers.

## 0.8.0 — 2026-09-16 (web)

Movable in-place text edits with arrow-key nudging, and fixes for rotated pages.

## 0.7.0 — 2026-09-13 (web)

Edited text in Edit PDF can be dragged to a new position, independent of the original
line's position.

## 0.6.0 — 2026-09-12 (web)

- Delete / Backspace and arrow-key nudge shortcuts in Edit PDF, and a colour picker
  for its colour-using tools.
- **Fixed:** PDF to Word / PowerPoint / Excel and Compare PDF silently read no text from
  pages the OCR tool had auto-rotated.
- New tools: **OCR PDF** and **PDF to PDF/A** (front end), and the release build now
  bundles all eight OCR languages.

## 0.5.0 — 2026-09-12 (web)

New tools: **PDF to PowerPoint**, **PDF to Excel**, **Repair**, **Protect** and
**Unlock**. Fixes for Unlock destroying damaged-and-encrypted files and for out-of-range
font sizes crashing the Office conversions.

## 0.4.0 — 2026-09-06 (web)

Edit PDF: a real-time in-place editor for existing text, with partial restyling of a
selected range (bold, italic, family, size).

## 0.3.0 — 2026-09-04 (web)

Edit PDF: click anywhere to select, move and resize strokes, shapes and highlights;
bring-to-front / send-to-back ordering; live image preview with independent resize
handles; live restyling of a selected element.

## 0.2.0 — 2026-09-04 (web)

Edit PDF: **Add Text** boxes (place, move, resize, re-edit, copy / paste). New **PDF
Forms** tool.

## 0.1.x — 2026-09-02 (web)

First releases: the Organize, Edit, Optimize and Convert tool groups, per-tool result
previews and a Recent Files history.
