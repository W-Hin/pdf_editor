# Desktop App: PDF Forms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add PDF Forms (fill an existing document's AcroForm fields) to the desktop app, with all pages scrolling continuously so every field on a multi-page form is reachable without switching pages.

**Architecture:** A new `FormFieldsWidget` in `app/ui/widgets.py` — a `QScrollArea` stacking one page-sized frame per page, each with a background page-image `QLabel` and real `QLineEdit`/`QCheckBox`/`QComboBox` children positioned on top via plain widget geometry (no custom painting, unlike every other widget in this file) — consumed by a two-line `FillFormDialog` that reads `extract_form_fields`, renders every page, and submits through the already-existing `fill_form` core function.

**Tech Stack:** Python, PySide6, PySide6.QtTest, pytest, PyMuPDF (fitz).

## Global Constraints

- Commit trailers (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`) go **only** on commits whose subject starts with `fix:`/`fix(scope):`. Both tasks in this plan ship new, intentional behavior — commits are `feat:` and must **not** carry the trailer.
- Real automated pytest tests using `PySide6.QtTest`'s synthetic mouse/keyboard events, appended to the existing `tests/test_ui_desktop.py` — not a manual checklist, not a second test file.
- Output filename must be exactly `<stem>_filled.pdf`.
- `fill_form` already raises `PDFError("Fill in at least one field before running.")` when `values` is empty — no dialog-side "at least one field" check is needed (same pattern already used for Sign PDF's `edit_pdf` call).
- `fill_form` always calls `doc.bake(annots=False, widgets=True)`, which **flattens every widget into static page content**. `extract_form_fields` on a `fill_form` output therefore always returns `[]` — verify a filled output via `get_text()` (text/combobox values render as literal text) or a pixel-render diff (checkbox state), never via a second `extract_form_fields` call. Confirmed empirically while writing this plan, and already the convention `tests/test_pdf_ops.py`'s own `fill_form` tests use.

---

### Task 1: `FormFieldsWidget`

**Files:**
- Modify: `app/ui/widgets.py` (add the new class)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: nothing from another task (this is the first task).
- Produces: `FormFieldsWidget()` with `.set_fields(fields: list[dict], page_pixmaps: list[QPixmap]) -> None`, `.values() -> list[dict]` (each `{"page": int, "index": int, "value": Any}`, one per field currently held, in the same order `fields` was given), `.has_fields() -> bool`. Task 2's `FillFormDialog` uses all three directly. `fields` is exactly `extract_form_fields`'s own return shape: `{"page": int, "index": int, "label": str, "type": "text"|"checkbox"|"combobox", "rect": {"top","left","right","bottom"}, "value": Any, "choices": list[str]|None}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. This needs three new imports: add `QCheckBox, QComboBox, QLineEdit` to the file's existing `from PySide6.QtWidgets import QApplication` line (making it `from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit`), add `extract_form_fields` to the existing `from app.core.pdf_ops import crop_pdf, render_page_thumbnail` line, and add `FormFieldsWidget` to the existing `from app.ui.widgets import ...` line:
```python
def _build_form_fixture(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    text_widget = fitz.Widget()
    text_widget.field_name = "full_name"
    text_widget.field_label = "Full Name"
    text_widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    text_widget.field_value = "PREFILLED"
    text_widget.rect = fitz.Rect(72, 100, 300, 120)
    page.add_widget(text_widget)

    checkbox_widget = fitz.Widget()
    checkbox_widget.field_name = "agree"
    checkbox_widget.field_label = "Agree"
    checkbox_widget.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX
    checkbox_widget.rect = fitz.Rect(72, 140, 90, 158)
    page.add_widget(checkbox_widget)

    combo_widget = fitz.Widget()
    combo_widget.field_name = "country"
    combo_widget.field_label = "Country"
    combo_widget.field_type = fitz.PDF_WIDGET_TYPE_COMBOBOX
    combo_widget.rect = fitz.Rect(72, 180, 250, 200)
    combo_widget.choice_values = ["USA", "Canada", "Mexico"]
    page.add_widget(combo_widget)

    path = tmp_path / "form.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_form_fields_widget_creates_the_right_qt_widget_per_field_type(tmp_path):
    from app.core.pdf_ops import extract_form_fields

    input_path = _build_form_fixture(tmp_path)
    fields = extract_form_fields(input_path)
    thumb_bytes = render_page_thumbnail(input_path, 1, max_size=450)
    pixmap = QPixmap()
    pixmap.loadFromData(thumb_bytes)

    widget = FormFieldsWidget()
    widget.set_fields(fields, [pixmap])
    assert widget.has_fields() is True

    text_field = next(f for f in fields if f["type"] == "text")
    checkbox_field = next(f for f in fields if f["type"] == "checkbox")
    combo_field = next(f for f in fields if f["type"] == "combobox")

    text_qwidget = widget._field_widgets[(text_field["page"], text_field["index"])]
    checkbox_qwidget = widget._field_widgets[(checkbox_field["page"], checkbox_field["index"])]
    combo_qwidget = widget._field_widgets[(combo_field["page"], combo_field["index"])]

    assert isinstance(text_qwidget, QLineEdit)
    assert isinstance(checkbox_qwidget, QCheckBox)
    assert isinstance(combo_qwidget, QComboBox)

    # Verified empirically before this test was written: on a 595x842 page
    # rendered at max_size=450, the pixmap is exactly 318x450, and the text
    # field's rect ({"top": 0.1187648456057007, "left": 0.12100840336134454,
    # "right": 0.4957983193277311, "bottom": 0.8574821852731591}) converts
    # to exactly this pixel geometry.
    geom = text_qwidget.geometry()
    assert (geom.x(), geom.y(), geom.width(), geom.height()) == (38, 53, 121, 10)

    # Initial values reflect the fixture's own field_value/default.
    assert text_qwidget.text() == "PREFILLED"
    assert checkbox_qwidget.isChecked() is False
    assert combo_qwidget.currentText() == ""  # fixture's own value ("") isn't in choices, so index 0 (blank) stands
    assert list(combo_field["choices"]) == ["USA", "Canada", "Mexico"]


def test_form_fields_widget_values_reflects_synthetic_user_interaction(tmp_path):
    from app.core.pdf_ops import extract_form_fields

    input_path = _build_form_fixture(tmp_path)
    fields = extract_form_fields(input_path)
    thumb_bytes = render_page_thumbnail(input_path, 1, max_size=450)
    pixmap = QPixmap()
    pixmap.loadFromData(thumb_bytes)

    widget = FormFieldsWidget()
    widget.set_fields(fields, [pixmap])

    text_field = next(f for f in fields if f["type"] == "text")
    checkbox_field = next(f for f in fields if f["type"] == "checkbox")
    combo_field = next(f for f in fields if f["type"] == "combobox")

    text_qwidget = widget._field_widgets[(text_field["page"], text_field["index"])]
    checkbox_qwidget = widget._field_widgets[(checkbox_field["page"], checkbox_field["index"])]
    combo_qwidget = widget._field_widgets[(combo_field["page"], combo_field["index"])]

    text_qwidget.clear()
    QTest.keyClicks(text_qwidget, "Jane Doe")
    QTest.mouseClick(checkbox_qwidget, Qt.LeftButton)
    combo_qwidget.setCurrentText("Canada")

    values_by_key = {(v["page"], v["index"]): v["value"] for v in widget.values()}
    assert values_by_key[(text_field["page"], text_field["index"])] == "Jane Doe"
    assert values_by_key[(checkbox_field["page"], checkbox_field["index"])] is True
    assert values_by_key[(combo_field["page"], combo_field["index"])] == "Canada"
    # values() reports ALL held fields, not only ones the user touched.
    assert len(widget.values()) == 3


def test_form_fields_widget_has_fields_false_for_a_fields_free_document():
    widget = FormFieldsWidget()
    widget.set_fields([], [QPixmap(100, 100)])
    assert widget.has_fields() is False
    assert widget.values() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k form_fields_widget -v`
Expected: FAIL — `FormFieldsWidget` doesn't exist yet.

- [ ] **Step 3: Implement `FormFieldsWidget`**

Add `QScrollArea, QCheckBox, QComboBox, QLabel, QLineEdit, QVBoxLayout` to the existing `from PySide6.QtWidgets import QWidget` line in `app/ui/widgets.py` (making it `from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget`), then add this class at the end of the file:
```python
class FormFieldsWidget(QWidget):
    """Displays every page of a document, stacked in a continuous scroll,
    with the document's existing AcroForm fields rendered as real Qt input
    widgets (QLineEdit/QCheckBox/QComboBox) positioned on top of each page's
    image - mirrors FormFillCanvas.jsx's own real <input>/<select> overlay,
    but as genuine Qt children rather than custom-painted shapes, since
    unlike every other widget in this file nothing here is drawn or
    dragged: plain widget z-order (each field widget added as a LATER
    child of its page frame than the background QLabel) is enough to paint
    it on top, with no paintEvent override needed at all."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)
        self._field_widgets: dict[tuple[int, int], QWidget] = {}
        self._fields: list[dict] = []

    def set_fields(self, fields: list[dict], page_pixmaps: list) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._field_widgets = {}
        self._fields = fields

        for page_num, pixmap in enumerate(page_pixmaps, start=1):
            frame = QWidget(self._container)
            frame.setFixedSize(pixmap.size())
            background = QLabel(frame)
            background.setPixmap(pixmap)
            background.setGeometry(0, 0, pixmap.width(), pixmap.height())

            for field in fields:
                if field["page"] != page_num:
                    continue
                rect = field["rect"]
                x = rect["left"] * pixmap.width()
                y = rect["top"] * pixmap.height()
                w = (1 - rect["left"] - rect["right"]) * pixmap.width()
                h = (1 - rect["top"] - rect["bottom"]) * pixmap.height()

                if field["type"] == "text":
                    field_widget = QLineEdit(frame)
                    field_widget.setText(field["value"] or "")
                elif field["type"] == "checkbox":
                    field_widget = QCheckBox(frame)
                    field_widget.setChecked(bool(field["value"]))
                elif field["type"] == "combobox":
                    field_widget = QComboBox(frame)
                    # A bare QComboBox.addItems() defaults currentText() to
                    # the FIRST real choice (confirmed empirically while
                    # writing this plan - e.g. addItems(["USA","Canada"])
                    # silently starts on "USA", not blank). FormFillCanvas.jsx's
                    # own <select> instead shows a real blank
                    # <option value="" disabled>-- Select --</option> until
                    # something is chosen, so an untouched field submits ""
                    # rather than an accidental first choice. Add the same
                    # blank placeholder at index 0 to match.
                    field_widget.addItem("")
                    field_widget.addItems(field["choices"] or [])
                    if field["value"] in (field["choices"] or []):
                        field_widget.setCurrentText(field["value"])
                else:
                    continue

                field_widget.setGeometry(int(x), int(y), int(w), int(h))
                field_widget.setToolTip(field["label"])
                field_widget.show()
                self._field_widgets[(field["page"], field["index"])] = field_widget

            self._container_layout.addWidget(frame)

    def values(self) -> list[dict]:
        result = []
        for field in self._fields:
            key = (field["page"], field["index"])
            widget = self._field_widgets.get(key)
            if widget is None:
                continue
            if isinstance(widget, QLineEdit):
                value = widget.text()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QComboBox):
                value = widget.currentText()
            else:
                continue
            result.append({"page": field["page"], "index": field["index"], "value": value})
        return result

    def has_fields(self) -> bool:
        return len(self._field_widgets) > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -k form_fields_widget -v`
Expected: PASS (3 tests).

Run the full suite: `pytest -q`
Expected: PASS, same total as before plus 3.

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets.py tests/test_ui_desktop.py
git commit -m "feat: add a widget that overlays real Qt inputs on AcroForm fields"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.

---

### Task 2: `FillFormDialog`

**Files:**
- Modify: `app/ui/dialogs/edit_dialogs.py` (add the new class)
- Modify: `app/main.py` (import line, registration line)
- Test: `tests/test_ui_desktop.py` (append)

**Interfaces:**
- Consumes: `FormFieldsWidget` (Task 1), unchanged.
- Produces: nothing consumed by any other task (this is the last task in the plan).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ui_desktop.py`. Reuses `_build_form_fixture` from Task 1 (already in this file — do not redefine it):
```python
def test_fill_form_dialog_fills_and_exports_real_values(tmp_path):
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    input_path = _build_form_fixture(tmp_path)

    dlg = FillFormDialog()
    dlg.on_files_changed([input_path])
    assert dlg.fields_widget.has_fields() is True

    fields = dlg.fields_widget._fields
    text_field = next(f for f in fields if f["type"] == "text")
    combo_field = next(f for f in fields if f["type"] == "combobox")
    text_qwidget = dlg.fields_widget._field_widgets[(text_field["page"], text_field["index"])]
    combo_qwidget = dlg.fields_widget._field_widgets[(combo_field["page"], combo_field["index"])]

    text_qwidget.clear()
    QTest.keyClicks(text_qwidget, "Jane Doe")
    combo_qwidget.setCurrentText("Canada")

    params = dlg.gather_params()
    assert len(params["values"]) == 3

    output_paths = dlg.run_operation([input_path], params)

    # fill_form always bakes (flattens) its output, so extract_form_fields
    # on the OUTPUT returns [] - there are no widgets left to extract
    # (verified empirically while writing this plan; see this plan's Global
    # Constraints). Verify the filled values the same way
    # tests/test_pdf_ops.py's own fill_form tests do: via get_text() on the
    # output page, since text/combobox values render as literal text after
    # baking.
    result = fitz.open(output_paths[0])
    text = result[0].get_text()
    result.close()
    assert "Jane Doe" in text
    assert "Canada" in text


def test_fill_form_dialog_raises_when_document_has_no_fields(tmp_path):
    from app.core.errors import PDFError
    from app.ui.dialogs.edit_dialogs import FillFormDialog

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "No form fields here")
    input_path = tmp_path / "input.pdf"
    doc.save(str(input_path))
    doc.close()

    dlg = FillFormDialog()
    dlg.on_files_changed([str(input_path)])
    assert dlg.fields_widget.has_fields() is False

    params = dlg.gather_params()
    assert params["values"] == []
    try:
        dlg.run_operation([str(input_path)], params)
        assert False, "expected PDFError"
    except PDFError as exc:
        assert "at least one" in str(exc)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui_desktop.py -k fill_form_dialog -v`
Expected: FAIL — `FillFormDialog` doesn't exist yet.

- [ ] **Step 3: Implement `FillFormDialog`**

Add `extract_form_fields` and `fill_form` to `app/ui/dialogs/edit_dialogs.py`'s existing `from app.core.pdf_ops import ...` line (making it `from app.core.pdf_ops import rotate_pages, add_watermark, add_page_numbers, crop_pdf, redact_pdf, render_page_thumbnail, get_page_count, edit_pdf, extract_form_fields, fill_form`), and add `FormFieldsWidget` to the existing `from app.ui.widgets import ...` line. Add this class at the end of the file, after `SignDialog`:
```python
class FillFormDialog(ToolDialog):
    title = "PDF Forms"
    dialog_size = (650, 780)

    def build_preview(self, container: QWidget) -> None:
        layout = QVBoxLayout(container)
        instruction = QLabel("Fill in the fields below; values are read from the document as-is.")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self.empty_label = QLabel("No fillable fields found in this document.")
        self.empty_label.setVisible(False)
        layout.addWidget(self.empty_label)
        self.fields_widget = FormFieldsWidget()
        layout.addWidget(self.fields_widget)

    def on_files_changed(self, paths: list[str]) -> None:
        if not paths:
            self.fields_widget.set_fields([], [])
            self.empty_label.setVisible(False)
            return
        input_path = paths[0]
        try:
            fields = extract_form_fields(input_path)
            count = get_page_count(input_path)
        except PDFError:
            return
        pixmaps = []
        for page_num in range(1, count + 1):
            thumb_bytes = render_page_thumbnail(input_path, page_num, max_size=450)
            pixmap = QPixmap()
            pixmap.loadFromData(thumb_bytes)
            pixmaps.append(pixmap)
        self.fields_widget.set_fields(fields, pixmaps)
        self.empty_label.setVisible(not self.fields_widget.has_fields())

    def gather_params(self) -> dict:
        return {"values": self.fields_widget.values()}

    def run_operation(self, input_paths: list[str], params: dict) -> list[str]:
        input_path = input_paths[0]
        out_path = str(Path(input_path).with_name(Path(input_path).stem + "_filled.pdf"))
        fill_form(input_path, out_path, params["values"])
        return [out_path]
```

- [ ] **Step 4: Register `FillFormDialog` in `app/main.py`**

Change the import line (currently ending `..., RedactDialog, SignDialog`):
```python
from app.ui.dialogs.edit_dialogs import RotateDialog, WatermarkDialog, AddPageNumbersDialog, CropDialog, RedactDialog, SignDialog, FillFormDialog
```
Add this line directly after `window.add_tool("Edit", "Sign PDF", SignDialog)`:
```python
    window.add_tool("Edit", "PDF Forms", FillFormDialog)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ui_desktop.py -v`
Expected: PASS (all prior tests plus this task's 2).

Run the full suite: `pytest -q`
Expected: PASS, same total as after Task 1 plus 2.

- [ ] **Step 6: Commit**

```bash
git add app/ui/dialogs/edit_dialogs.py app/main.py tests/test_ui_desktop.py
git commit -m "feat: add a PDF Forms dialog to the desktop app"
```

No trailer on this commit — it's a `feat:`, not a `fix:`.
