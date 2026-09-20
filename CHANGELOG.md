# Changelog

All notable changes to PDF Editor. The **web app** is what the Windows installer
(`PDFEditorSetup.exe`) packages; the **desktop app** (PySide6, `python -m app.main`) is
run from source. Both share the same PDF engine in `app/core/`, so a change to the
engine lands in both.

## 0.15.2 — 2026-09-20

The installed app now actually starts. Every installer built since 0.5.0 crashed on launch
(a terminal window opened and closed at once). None of those were published until 0.15.1,
and 0.15.1's installer had the same crash. This release bundles the files the packaged app
was missing, and every tool was run against the packaged app to confirm it works.

- **Fixed:** the app crashed at startup because a layout-model file used by PDF to Markdown
  was missing from the installer.
- **Fixed:** OCR and PDF to PDF/A failed in the installer with "No OCR engine selected"
  (the OCR engine plug-ins weren't bundled).
- The launcher now supports background worker processes in the packaged app.

## 0.15.1 — 2026-09-20

The first release actually published since 0.4.0: the release build had been failing
on every tag from 0.5.0 to 0.15.0 (see below), so those versions were tagged but never
built or published. This release carries everything from 0.5.0 through 0.15.0 plus:

- **Fixed (web and desktop):** PDF to Markdown wrote absolute image paths (pointing into
  a deleted temp folder) into the Markdown on Windows accounts whose username is longer
  than 8 characters. The images in the zip are now always linked by bare filename. This
  was also the one test that failed on the release machine and stopped every build.
- **Fixed (Edit PDF):** editing a text run with a replacement wider than the original now
  shows at the size the export will draw it (it shrinks to fit, never below half size).
  The export also gives a clear error, instead of a crash, for malformed text-edit data.
- **Fixed (desktop Edit PDF):** only the selected element's delete button and resize
  handles can be clicked (invisible ones used to sit on every element, so a click meant
  to select could delete or resize), and line widths, arrowheads and new-text sizes on
  screen now match the page scale of the exported PDF.

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
