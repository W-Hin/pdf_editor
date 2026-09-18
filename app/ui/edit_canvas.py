import uuid

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QTextEdit, QWidget

_PASTE_OFFSET = 0.03
_MARKER_SIZE = 14
_HANDLE_SIZE = 14
_MIN_TEXT_WIDTH_FRACTION = 0.05
_MIN_TEXT_HEIGHT_FRACTION = 0.03


class EditElementsModel:
    """Owns the state that must be shared ACROSS every page of an Edit PDF
    session - unlike RedactDialog/SignDialog's fully independent per-page
    widgets, Edit PDF needs one selection, one undo/redo stack, and one
    clipboard slot spanning the whole document, matching the web app's own
    single flat `elements` array (never bucketed per page internally - each
    element dict carries its own "page" field). EditPageWidget instances
    (Task 2) are thin views onto this shared model, one per page.
    """

    def __init__(self):
        self.elements: list[dict] = []
        self.selected_id: str | None = None
        self._undo_stack: list[list[dict]] = []
        self._redo_stack: list[list[dict]] = []
        self._clipboard: dict | None = None
        self.on_change: list = []

    def _snapshot(self) -> list[dict]:
        return [dict(e) for e in self.elements]

    def _notify(self) -> None:
        for callback in self.on_change:
            callback()

    def commit(self) -> None:
        """Pushes the CURRENT state onto the undo stack and clears redo -
        call once per discrete action (an add, a delete, a completed
        drag/resize gesture, a paste), never per intermediate mouse-move
        during a drag."""
        self._undo_stack.append(self._snapshot())
        self._redo_stack.clear()

    def add(self, element: dict) -> str:
        self.commit()
        new_id = str(uuid.uuid4())
        el = dict(element)
        el["id"] = new_id
        self.elements.append(el)
        self.selected_id = new_id
        self._notify()
        return new_id

    def update(self, element_id: str, **changes) -> None:
        """Live in-place mutation with NO commit - used for drag/resize
        feedback while a gesture is in progress. The caller commits once,
        separately, at gesture-end."""
        for el in self.elements:
            if el["id"] == element_id:
                el.update(changes)
                break
        self._notify()

    def remove(self, element_id: str) -> None:
        self.commit()
        self.elements = [e for e in self.elements if e["id"] != element_id]
        if self.selected_id == element_id:
            self.selected_id = None
        self._notify()

    def select(self, element_id: str | None) -> None:
        self.selected_id = element_id
        self._notify()

    def elements_for_page(self, page: int) -> list[dict]:
        return [e for e in self.elements if e["page"] == page]

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self.elements = self._undo_stack.pop()
        self._notify()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self.elements = self._redo_stack.pop()
        self._notify()

    def _shift_for_paste(self, el: dict) -> dict:
        """Per-type paste-offset math, mirroring the web app's own shift()
        helper: translate the WHOLE element by the same delta on each axis
        (never clamp each coordinate independently - that would distort a
        near-edge element), clamped to [0, _PASTE_OFFSET] per axis. Phase
        6B/6C add their own type branches here later; nothing below needs
        revisiting when they do."""
        shifted = dict(el)
        if el["type"] in ("new_text", "image"):
            room_x = 1 - (el["x"] + el["width"])
            room_y = 1 - (el["y"] + el["height"])
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["x"] = el["x"] + dx
            shifted["y"] = el["y"] + dy
        return shifted

    def copy(self) -> None:
        if self.selected_id is None:
            return
        for el in self.elements:
            if el["id"] == self.selected_id:
                clip = dict(el)
                clip.pop("id", None)
                self._clipboard = clip
                return

    def cut(self) -> None:
        self.copy()
        if self.selected_id is not None:
            self.remove(self.selected_id)

    def paste(self) -> str | None:
        if self._clipboard is None:
            return None
        return self.add(self._shift_for_paste(self._clipboard))

    def reorder(self, element_id: str, direction: str) -> None:
        """direction in {"front","back","forward","backward"}. "forward"/
        "backward" swap with the nearest SAME-PAGE neighbor in that array
        direction, skipping over any other page's elements sitting between
        them - so this is never a silent no-op just because another
        page's element happens to sit adjacent in the flat array.
        "front"/"back" move the element to be the last/first among its own
        page's elements."""
        self.commit()
        idx = next(i for i, e in enumerate(self.elements) if e["id"] == element_id)
        page = self.elements[idx]["page"]
        if direction in ("forward", "backward"):
            step = 1 if direction == "forward" else -1
            j = idx + step
            while 0 <= j < len(self.elements) and self.elements[j]["page"] != page:
                j += step
            if 0 <= j < len(self.elements):
                self.elements[idx], self.elements[j] = self.elements[j], self.elements[idx]
        elif direction == "front":
            el = self.elements.pop(idx)
            insert_at = max([i for i, e in enumerate(self.elements) if e["page"] == page], default=-1) + 1
            self.elements.insert(insert_at, el)
        elif direction == "back":
            el = self.elements.pop(idx)
            insert_at = min([i for i, e in enumerate(self.elements) if e["page"] == page], default=0)
            self.elements.insert(insert_at, el)
        self._notify()

    def nudge(self, element_id: str, dx: float, dy: float) -> None:
        """A discrete, deliberate action (one keypress = one small move) -
        unlike a mouse drag's many intermediate positions, each nudge call
        commits its own undo step, matching add/remove's own
        commit-before-mutate pattern."""
        self.commit()
        for el in self.elements:
            if el["id"] == element_id:
                if el["type"] in ("new_text", "image"):
                    el["x"] = min(max(el["x"] + dx, 0), 1 - el["width"])
                    el["y"] = min(max(el["y"] + dy, 0), 1 - el["height"])
                break
        self._notify()


class EditPageWidget(QWidget):
    """One page's view onto a shared EditElementsModel - renders that
    page's own filtered elements via QPainter, dispatching by
    element["type"], and translates mouse events into calls on the shared
    model. Hit-test order (topmost-first, matching ImagePlacementWidget's
    proven convention): marker (delete) -> handle(s) (resize) -> body
    (move) -> empty space, which creates a new element of whichever type
    `self.create_mode` currently names. Existing elements of ANY type
    remain selectable/movable/resizable/deletable regardless of which
    creation mode is active - the mode only gates what an empty-space
    click does."""

    def __init__(self, model, page_number: int, parent=None, on_image_click=None):
        super().__init__(parent)
        self.model = model
        self.page_number = page_number
        self.page_pixmap = None
        self.create_mode = "new_text"
        self.on_image_click = on_image_click
        self.image_cache: dict = {}
        self._drag: dict | None = None
        self._text_editor: QTextEdit | None = None
        self._editing_element_id: str | None = None
        self.model.on_change.append(self.update)

    def set_page_pixmap(self, pixmap) -> None:
        self.page_pixmap = pixmap
        self.setFixedSize(pixmap.size())
        self.update()

    def _elements(self) -> list[dict]:
        return self.model.elements_for_page(self.page_number)

    def _point_from_pos(self, pos) -> tuple[float, float] | None:
        if self.width() == 0 or self.height() == 0:
            return None
        x = min(max(pos.x() / self.width(), 0), 1)
        y = min(max(pos.y() / self.height(), 0), 1)
        return (x, y)

    def _element_rect_px(self, el: dict) -> QRect:
        x0 = el["x"] * self.width()
        y0 = el["y"] * self.height()
        x1 = (el["x"] + el["width"]) * self.width()
        y1 = (el["y"] + el["height"]) * self.height()
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _marker_rect(self, el: dict) -> QRect:
        rect = self._element_rect_px(el)
        return QRect(rect.right() - _MARKER_SIZE, rect.top(), _MARKER_SIZE, _MARKER_SIZE)

    def _resize_handles(self, el: dict) -> dict:
        """One handle for new_text (free resize, bottom-right). Three for
        image: a corner (aspect-locked uniform scale, matching
        ImagePlacementWidget's existing formula exactly), plus independent
        width-only and height-only handles (mid-right / mid-bottom edges)
        that deliberately allow aspect distortion, matching the web app's
        own three-handle image behavior (_apply_image's own
        keep_proportion=False trusts whatever box the editor produced)."""
        rect = self._element_rect_px(el)
        if el["type"] == "new_text":
            return {"corner": QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE)}
        if el["type"] == "image":
            mid_x = rect.left() + rect.width() // 2
            mid_y = rect.top() + rect.height() // 2
            return {
                "corner": QRect(rect.right() - _HANDLE_SIZE, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE),
                "width": QRect(rect.right() - _HANDLE_SIZE, mid_y - _HANDLE_SIZE // 2, _HANDLE_SIZE, _HANDLE_SIZE),
                "height": QRect(mid_x - _HANDLE_SIZE // 2, rect.bottom() - _HANDLE_SIZE, _HANDLE_SIZE, _HANDLE_SIZE),
            }
        return {}

    def _qfont_for(self, el: dict) -> QFont:
        font = QFont(el["family"], el["size"])
        font.setBold(el["bold"])
        font.setItalic(el["italic"])
        font.setUnderline(el["underline"])
        return font

    def mousePressEvent(self, e) -> None:
        pos = e.position().toPoint()
        elements = self._elements()
        for i in reversed(range(len(elements))):
            el = elements[i]
            if self._marker_rect(el).contains(pos):
                self.model.remove(el["id"])
                return
        for i in reversed(range(len(elements))):
            el = elements[i]
            for handle_name, rect in self._resize_handles(el).items():
                if rect.contains(pos):
                    point = self._point_from_pos(pos)
                    self.model.select(el["id"])
                    self._drag = {"mode": f"resize-{handle_name}", "id": el["id"], "start": point, "start_element": dict(el)}
                    return
        for i in reversed(range(len(elements))):
            el = elements[i]
            if self._element_rect_px(el).contains(pos):
                point = self._point_from_pos(pos)
                self.model.select(el["id"])
                self._drag = {"mode": "move", "id": el["id"], "start": point, "start_element": dict(el)}
                return
        point = self._point_from_pos(pos)
        if point is None:
            return
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)
        elif self.create_mode == "image" and self.on_image_click is not None:
            self.on_image_click(point)

    def create_image_at(self, x: float, y: float, image_path: str) -> str:
        pixmap = self.image_cache.get(image_path)
        if pixmap is None:
            pixmap = QPixmap(image_path)
            self.image_cache[image_path] = pixmap
        sig_w, sig_h = pixmap.width(), pixmap.height()
        width = 0.25
        height = min(0.9, width * (sig_h / sig_w))
        box_x = min(max(x - width / 2, 0), 1 - width)
        box_y = min(max(y - height / 2, 0), 1 - height)
        return self.model.add({
            "page": self.page_number, "type": "image",
            "x": box_x, "y": box_y, "width": width, "height": height,
            "file_id": image_path,
        })

    def mouseDoubleClickEvent(self, e) -> None:
        pos = e.position().toPoint()
        for el in reversed(self._elements()):
            if el["type"] == "new_text" and self._element_rect_px(el).contains(pos):
                self._drag = None
                self._open_text_editor_for_existing(el)
                return

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        dx = point[0] - self._drag["start"][0]
        dy = point[1] - self._drag["start"][1]
        sp = self._drag["start_element"]
        if self._drag["mode"] == "move":
            x = min(max(sp["x"] + dx, 0), 1 - sp["width"])
            y = min(max(sp["y"] + dy, 0), 1 - sp["height"])
            self.model.update(self._drag["id"], x=x, y=y)
        elif self._drag["mode"] == "resize-corner":
            if sp["type"] == "image":
                aspect = sp["height"] / sp["width"]
                width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, width_cap))
                height = width * aspect
                self.model.update(self._drag["id"], width=width, height=height)
            else:
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
                height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
                self.model.update(self._drag["id"], width=width, height=height)
        elif self._drag["mode"] == "resize-width":
            width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
            self.model.update(self._drag["id"], width=width)
        elif self._drag["mode"] == "resize-height":
            height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
            self.model.update(self._drag["id"], height=height)

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is not None:
            self.model.commit()
            self._drag = None

    def _open_text_editor_for_new(self, point: tuple[float, float]) -> None:
        width, height = 0.25, 0.08
        x = min(max(point[0] - width / 2, 0), 1 - width)
        y = min(max(point[1] - height / 2, 0), 1 - height)
        self._editing_element_id = None
        self._show_text_editor(x, y, width, height, "", {
            "family": "helvetica", "bold": False, "italic": False,
            "underline": False, "size": 14, "color": "#1f2937", "align": "left",
        })

    def _open_text_editor_for_existing(self, el: dict) -> None:
        self._editing_element_id = el["id"]
        self._show_text_editor(el["x"], el["y"], el["width"], el["height"], el["text"], el)

    def _show_text_editor(self, x: float, y: float, width: float, height: float, text: str, style: dict) -> None:
        if self._text_editor is not None:
            self._text_editor.deleteLater()
        editor = QTextEdit(self)
        editor.setPlainText(text)
        editor.setFont(self._qfont_for({**style, "text": text}))
        rect = self._element_rect_px({"x": x, "y": y, "width": width, "height": height})
        editor.setGeometry(rect)
        editor.show()
        editor.setFocus()
        self._text_editor = editor
        self._pending_style = dict(style)
        self._pending_box = {"x": x, "y": y, "width": width, "height": height}

    def _commit_text_editor(self) -> None:
        if self._text_editor is None:
            return
        text = self._text_editor.toPlainText()
        editor = self._text_editor
        self._text_editor = None
        editor.deleteLater()
        if not text.strip():
            self._editing_element_id = None
            return
        element = {
            "page": self.page_number, "type": "new_text",
            "x": self._pending_box["x"], "y": self._pending_box["y"],
            "width": self._pending_box["width"], "height": self._pending_box["height"],
            "text": text, **{k: self._pending_style[k] for k in ("family", "bold", "italic", "underline", "size", "color", "align")},
        }
        if self._editing_element_id is not None:
            self.model.update(self._editing_element_id, **{k: v for k, v in element.items() if k != "page"})
            self.model.commit()
        else:
            self.model.add(element)
        self._editing_element_id = None

    def focusOutEvent(self, e) -> None:
        super().focusOutEvent(e)

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        for el in self._elements():
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            elif el["type"] == "image":
                self._paint_image(painter, el)
            self._paint_chrome(painter, el)

    def _paint_new_text(self, painter: QPainter, el: dict) -> None:
        if self._editing_element_id == el["id"] and self._text_editor is not None:
            return  # the live QTextEdit overlay is showing instead
        rect = self._element_rect_px(el)
        painter.setFont(self._qfont_for(el))
        painter.setPen(QColor(el["color"]))
        align_flag = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[el["align"]]
        painter.drawText(rect, align_flag | Qt.AlignTop | Qt.TextWordWrap, el["text"])

    def _paint_image(self, painter: QPainter, el: dict) -> None:
        pixmap = self.image_cache.get(el["file_id"])
        if pixmap is None:
            pixmap = QPixmap(el["file_id"])
            self.image_cache[el["file_id"]] = pixmap
        painter.drawPixmap(self._element_rect_px(el), pixmap)

    def _paint_chrome(self, painter: QPainter, el: dict) -> None:
        if self.model.selected_id != el["id"]:
            return
        marker = self._marker_rect(el)
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.setBrush(QColor(220, 40, 40))
        painter.drawEllipse(marker)
        for rect in self._resize_handles(el).values():
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(QColor(40, 100, 220))
            painter.drawRect(rect)
