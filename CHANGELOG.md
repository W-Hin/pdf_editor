# Changelog

All notable changes to PDF Editor. The **web app** is packaged by `PDFEditorSetup.exe`
and the **desktop app** (PySide6) by `PDFEditorDesktopSetup.exe` (also runnable from
source with `python -m app.main`). Both share the same PDF engine in `app/core/`, so a
change to the engine lands in both.

## 0.17.2 — 2026-09-21

The desktop page tools get the same comfortable page view as Edit PDF.

- **Crop, Redact, Sign, PDF Forms and Compare** now show pages that fit the window and are
  centred (they were fixed, tiny thumbnails), redrawn sharply at any size.
- **Zoom** from 50% to 300% in each (a small - / 100% / + control, Ctrl+scroll,
  Ctrl+= / Ctrl+- / Ctrl+0). Crop boxes, redactions, signature placements and typed form
  values all stay exactly where they are when you zoom.
- Only the pages near the view are drawn, so long documents stay light.
- **Compare** shows both pages side by side at the window's width, with its controls on
  one row so the pages get the room.
- A page that fails to render is kept as a blank white page instead of being dropped, so
  page numbers can never shift.

## 0.17.1 — 2026-09-21

Desktop Edit PDF is now comfortable to work in.

- **Bigger, centred pages:** pages fit the window (previously a fixed, tiny 450 px thumbnail)
  and are redrawn sharply at any size.
- **Zoom** from 50% to 300% (toolbar buttons, Ctrl+scroll, Ctrl+= / Ctrl+- / Ctrl+0).
- **Slimmer layout:** the file box collapses to one "filename - Change file" line once a
  single file is chosen (all single-file tools), and Back and the title share a line.
- Only the pages near the view are drawn, so long documents stay light.
- Clicking a page now gives it the keyboard (Delete, arrows, Esc).

## 0.17.0 — 2026-09-21

The desktop app now matches the web app: same look, same tools inside the window, same
Edit PDF features. Both apps get a one-row Edit PDF toolbar.

- **Desktop app looks like the web app:** the same palette, Inter font and icons, a
  card grid home screen, and tools that open inside the main window with a Back link
  instead of pop-up windows.
- **Desktop Recent Files:** every file a tool produces is listed (newest first, with a
  thumbnail, Open, Show in folder and Remove), backed by a local SQLite database. Only
  names and paths are stored, never the PDFs.
- **Desktop Edit PDF, now equal to the web:** a click or short line leaves a dot instead
  of vanishing; drawing over an existing line draws instead of selecting it; a **Select**
  tool (drag across items, then Delete, drag or nudge them together); an **Eraser**; and
  a freehand **Highlighter** under Draw.
- **One-row Edit PDF toolbar (web and desktop):** modes, undo/redo, Arrange and the active
  tool's options share one row, in the same order on both. Only the active mode shows its
  name. The row scrolls sideways instead of wrapping in a narrow window.
- Fixed: Undo/Redo and Paste in the desktop toolbar now enable and disable correctly, and
  Bold/Italic buttons show when they are on.

## 0.16.1 — 2026-09-21

- **New:** a second installer, `PDFEditorDesktopSetup.exe`, for the desktop app ("PDF Editor
  (Desktop)"). Every release now has both it and `PDFEditorSetup.exe` (the web app); they
  can be installed side by side.
- The release build now runs the packaged desktop app's self-test (window, PDF to
  Markdown, OCR) before publishing.

## 0.16.0 — 2026-09-21

Edit PDF (web app) drawing overhaul, plus the fixes made since 0.15.2.

- **Fixed:** a short pen stroke or a plain click now registers (a click leaves a dot)
  instead of being thrown away.
- **Fixed:** starting a drawing on top of an existing line now draws; drawings can no
  longer be grabbed by accident. They are only selectable with the new Select tool.
- **New: Eraser** — drag across a hand-drawn line or highlight to erase it. One Undo
  restores everything a sweep erased.
- **New: freehand highlighter** — Draw now has Pen and Highlighter; the highlighter is a
  wide, translucent, round-ended marker in four colours and three widths.
- **New: Select tool** — drag across empty space to select any mix of drawings,
  highlights, shapes, boxes, images and text. Delete removes them, dragging moves them
  together, arrow keys nudge them, Esc deselects.
- Desktop Edit PDF: white and custom colours, and the Delete key (from the previous
  unreleased work).
- Browsers no longer show a stale copy of the app after an upgrade.

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
