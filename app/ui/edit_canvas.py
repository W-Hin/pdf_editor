import math
import uuid

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygon,
    QTextCharFormat, QTextCursor, QTextDocument, QTextFormat,
)
from PySide6.QtWidgets import QTextEdit, QWidget

from app.core.pdf_ops import text_edit_final_sizes
from app.ui.widgets import box_to_insets, insets_to_box

_PASTE_OFFSET = 0.03
_MARKER_SIZE = 14
_HANDLE_SIZE = 14
_MIN_TEXT_WIDTH_FRACTION = 0.05
_MIN_TEXT_HEIGHT_FRACTION = 0.03
_MIN_DRAG_FRACTION = 0.02
_WIDTH_PRESETS = {"thin": 1, "medium": 3, "thick": 6}


def closest_base14_family(font_name) -> str:
    """Port of the web app's closestBase14Family (EditPdfCanvas.jsx:87): the
    core can only draw replacement text in the three base-14 families, so a
    run's detected font is snapped to the nearest one."""
    lowered = (font_name or "").lower()
    if "times" in lowered or "serif" in lowered or "georgia" in lowered:
        return "times"
    if "courier" in lowered or "mono" in lowered or "consolas" in lowered:
        return "courier"
    return "helvetica"


_PDF_SIZE_PROP = QTextFormat.UserProperty + 1  # a segment's TRUE size in PDF points


def _segment_format(segment: dict, px_per_pt: float) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontFamilies([segment["family"]])
    fmt.setFontWeight(QFont.Bold if segment["bold"] else QFont.Normal)
    fmt.setFontItalic(segment["italic"])
    # Display size in pixels (independent of screen DPI); the true PDF-point
    # size rides along as a custom property so the round trip is exact.
    fmt.setProperty(QTextFormat.FontPixelSize, max(1, round(segment["size"] * px_per_pt)))
    fmt.setProperty(_PDF_SIZE_PROP, float(segment["size"]))
    return fmt


def build_segments_document(segments: list[dict], px_per_pt: float) -> QTextDocument:
    """A QTextDocument holding `segments` in order - used both to seed the
    editor and to paint a committed edit, so the two can never disagree."""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    cursor = QTextCursor(doc)
    for segment in segments:
        cursor.insertText(segment["text"], _segment_format(segment, px_per_pt))
    return doc


def segments_from_document(doc: QTextDocument, default_style: dict) -> list[dict]:
    """Walks the document block-by-block, fragment-by-fragment - each
    QTextFragment is already a maximal run of uniform formatting, i.e. one
    segment - merging any identical neighbours. Blocks (a run is a single
    line, and the editor refuses Return, so this is defensive) are joined by
    one space. An empty document is an intentional erase: one empty segment
    in the run's own default style."""
    segments: list[dict] = []

    def push(text, style):
        if segments and all(segments[-1][k] == style[k] for k in ("family", "bold", "italic", "size")):
            segments[-1]["text"] += text
        else:
            segments.append({"text": text, **style})

    block = doc.begin()
    first = True
    while block.isValid():
        if not first and segments:
            push(" ", {k: segments[-1][k] for k in ("family", "bold", "italic", "size")})
        first = False
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                fmt = frag.charFormat()
                families = fmt.fontFamilies()
                pdf_size = fmt.property(_PDF_SIZE_PROP)
                push(frag.text(), {
                    "family": closest_base14_family(families[0]) if families else default_style["family"],
                    "bold": fmt.fontWeight() >= QFont.Bold,
                    "italic": fmt.fontItalic(),
                    "size": float(pdf_size) if pdf_size else float(default_style["size"]),
                })
            it += 1
        block = block.next()
    if not segments or all(s["text"] == "" for s in segments):
        return [{"text": "", **{k: default_style[k] for k in ("family", "bold", "italic", "size")}}]
    return segments


class _RunTextEdit(QTextEdit):
    """The in-place run editor. A run is a single text span, so line breaks
    are refused outright (verified: without this Return starts a second
    block)."""

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return
        super().keyPressEvent(e)


class EditElementsModel:
    """Owns the state that must be shared ACROSS every page of an Edit PDF
    session - unlike RedactDialog/SignDialog's fully independent per-page
    widgets, Edit PDF needs one selection, one undo/redo stack, and one
    clipboard slot spanning the whole document, matching the web app's own
    single flat `elements` array (never bucketed per page internally - each
    element dict carries its own "page" field). EditPageWidget instances
    are thin views onto this shared model, one per page.
    """

    def __init__(self):
        self.elements: list[dict] = []
        self.selected_id: str | None = None
        self._undo_stack: list[list[dict]] = []
        self._redo_stack: list[list[dict]] = []
        self._clipboard: dict | None = None
        # Caller-managed subscriptions: whoever appends a callback here is
        # responsible for calling remove_listener() before discarding the
        # object that callback is bound to, whenever this model will
        # outlive that object (otherwise _notify() would later call into a
        # deleted C++ widget).
        self.on_change: list = []
        # Per-page text-run data, filled by whoever opens a document (see
        # set_page_text_info). Kept on the model - not on the page widgets -
        # because clamped_translate/nudge need a text_edit's box and the
        # model is the single source of truth for move math.
        self.text_runs: dict[int, list[dict]] = {}
        self.page_info: dict[int, dict] = {}

    def _snapshot(self) -> list[dict]:
        return [dict(e) for e in self.elements]

    def remove_listener(self, callback) -> None:
        """Unsubscribes a callback previously appended to on_change; a
        no-op if it was never registered (or already removed)."""
        if callback in self.on_change:
            self.on_change.remove(callback)

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

    def set_page_text_info(self, page: int, runs: list[dict], rotation: int, width_pt: float, height_pt: float) -> None:
        self.text_runs[page] = list(runs)
        self.page_info[page] = {"rotation": rotation, "width_pt": width_pt, "height_pt": height_pt}

    def find_run(self, page: int, run_index: int) -> dict | None:
        return next((r for r in self.text_runs.get(page, []) if r["index"] == run_index), None)

    def text_edit_for_run(self, page: int, run_index: int) -> dict | None:
        return next(
            (e for e in self.elements if e["type"] == "text_edit" and e["page"] == page and e["run_index"] == run_index),
            None,
        )

    def text_edit_box(self, el: dict) -> dict | None:
        """The box a text_edit occupies, in page fractions - ALWAYS derived
        from its run (a text_edit never stores width/height). Position is
        the element's own x/y once it has been moved, else the run's
        top-left. Once moved on a 90/270 page the core draws the replacement
        upright in displayed space, transposing the (sideways) original
        run's extent - swapped in POINTS, not fractions, so it is exact for
        a non-square page (the web app swaps the fractions)."""
        run = self.find_run(el["page"], el["run_index"])
        if run is None:
            return None
        bbox = run["bbox"]
        width = 1 - bbox["left"] - bbox["right"]
        height = 1 - bbox["top"] - bbox["bottom"]
        moved = el.get("x") is not None and el.get("y") is not None
        info = self.page_info.get(el["page"])
        if moved and info and info["rotation"] in (90, 270):
            w_pt, h_pt = width * info["width_pt"], height * info["height_pt"]
            width, height = h_pt / info["width_pt"], w_pt / info["height_pt"]
            # A long sideways run can transpose to more than the whole page;
            # the box must never claim more than the page it sits on.
            width, height = min(width, 1.0), min(height, 1.0)
        return {
            "x": el["x"] if moved else bbox["left"],
            "y": el["y"] if moved else bbox["top"],
            "width": width,
            "height": height,
        }

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
        near-edge element), clamped to [0, _PASTE_OFFSET] per axis. Unlike
        _clamped_translate, the delta here is always down-and-right and is
        capped by the room LEFT of the page's bottom-right corner only."""
        shifted = dict(el)
        if el["type"] in ("new_text", "image"):
            room_x = 1 - (el["x"] + el["width"])
            room_y = 1 - (el["y"] + el["height"])
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["x"] = el["x"] + dx
            shifted["y"] = el["y"] + dy
        elif el["type"] == "shape":
            room_x = 1 - max(el["x0"], el["x1"])
            room_y = 1 - max(el["y0"], el["y1"])
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["x0"] = el["x0"] + dx
            shifted["x1"] = el["x1"] + dx
            shifted["y0"] = el["y0"] + dy
            shifted["y1"] = el["y1"] + dy
        elif el["type"] == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            room_x = 1 - max(xs)
            room_y = 1 - max(ys)
            dx = min(max(room_x, 0), _PASTE_OFFSET)
            dy = min(max(room_y, 0), _PASTE_OFFSET)
            shifted["points"] = [{"x": p["x"] + dx, "y": p["y"] + dy} for p in el["points"]]
        elif el["type"] == "highlight":
            # The stored right/bottom insets ARE the remaining-room
            # quantity directly - unlike every other type, no separate
            # max-corner calculation is needed here at all.
            dx = min(max(el["right"], 0), _PASTE_OFFSET)
            dy = min(max(el["bottom"], 0), _PASTE_OFFSET)
            shifted["left"] = el["left"] + dx
            shifted["right"] = el["right"] - dx
            shifted["top"] = el["top"] + dy
            shifted["bottom"] = el["bottom"] - dy
        return shifted

    def copy(self) -> None:
        if self.selected_id is None:
            return
        for el in self.elements:
            if el["id"] == self.selected_id:
                if el["type"] == "text_edit":
                    return  # a run_index is meaningless anywhere but its own run
                clip = dict(el)
                clip.pop("id", None)
                self._clipboard = clip
                return

    def cut(self) -> None:
        selected = next((e for e in self.elements if e["id"] == self.selected_id), None)
        if selected is not None and selected["type"] == "text_edit":
            return  # not copyable, so cutting would just destroy it
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

    def clamped_translate(self, el: dict, dx: float, dy: float) -> dict:
        """Returns the coordinate changes that translate the WHOLE of `el`
        by (dx, dy), with that delta first clamped per axis so no part of
        the element can leave the page - mirroring the web app's own
        moveElement(). `el` itself is never mutated.

        THE single source of truth for move math, shared by nudge (a
        keypress) and EditPageWidget's mouse-drag "move" branch, so a drag
        stops at the page edge exactly like a nudge does. That matters
        beyond cosmetics: QPainter silently clips at the widget edge, so
        out-of-page coordinates look fine on screen but make edit_pdf's
        _validate_shape/_validate_stroke/_validate_highlight reject the
        export of the WHOLE document.

        The delta - not each coordinate independently - is what gets
        clamped: clamping coordinates one by one would squash a
        part-way-off-page element instead of sliding it."""
        el_type = el["type"]
        if el_type == "shape":
            x_min, x_max = min(el["x0"], el["x1"]), max(el["x0"], el["x1"])
            y_min, y_max = min(el["y0"], el["y1"]), max(el["y0"], el["y1"])
            clamped_dx = min(max(dx, -x_min), 1 - x_max)
            clamped_dy = min(max(dy, -y_min), 1 - y_max)
            return {
                "x0": el["x0"] + clamped_dx, "x1": el["x1"] + clamped_dx,
                "y0": el["y0"] + clamped_dy, "y1": el["y1"] + clamped_dy,
            }
        if el_type == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            clamped_dx = min(max(dx, -min(xs)), 1 - max(xs))
            clamped_dy = min(max(dy, -min(ys)), 1 - max(ys))
            return {"points": [{"x": p["x"] + clamped_dx, "y": p["y"] + clamped_dy} for p in el["points"]]}
        if el_type == "highlight":
            # The stored insets ARE the available room on each side, so
            # they double as this type's own clamp bounds directly.
            clamped_dx = min(max(dx, -el["left"]), el["right"])
            clamped_dy = min(max(dy, -el["top"]), el["bottom"])
            return {
                "left": el["left"] + clamped_dx, "right": el["right"] - clamped_dx,
                "top": el["top"] + clamped_dy, "bottom": el["bottom"] - clamped_dy,
            }
        if el_type == "text_edit":
            # Box comes from the run; only x/y are ever returned, so a
            # move can never leak width/height onto the stored element.
            box = self.text_edit_box(el)
            if box is None:
                return {}
            return {
                "x": min(max(box["x"] + dx, 0), max(0, 1 - box["width"])),
                "y": min(max(box["y"] + dy, 0), max(0, 1 - box["height"])),
            }
        # new_text / image: x,y is the top-left corner and width/height are
        # stored, so the clamp can be expressed on the coordinates directly.
        return {
            "x": min(max(el["x"] + dx, 0), 1 - el["width"]),
            "y": min(max(el["y"] + dy, 0), 1 - el["height"]),
        }

    def nudge(self, element_id: str, dx: float, dy: float) -> None:
        """A discrete, deliberate action (one keypress = one small move) -
        unlike a mouse drag's many intermediate positions, each nudge call
        commits its own undo step, matching add/remove's own
        commit-before-mutate pattern."""
        el = next((e for e in self.elements if e["id"] == element_id), None)
        if el is None:
            return
        changes = self.clamped_translate(el, dx, dy)
        if not changes:
            return  # nothing to move (e.g. unknown run): no useless undo step
        self.commit()
        el.update(changes)
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

    run_editor_cursor_moved = Signal()  # the dialog's style row listens to keep itself in step

    def __init__(self, model, page_number: int, parent=None, on_image_click=None):
        super().__init__(parent)
        self.model = model
        self.page_number = page_number
        self.page_pixmap = None
        self.create_mode = "new_text"
        self.on_image_click = on_image_click
        # Set by the owning dialog: commits the OTHER pages' open editors so
        # only one editor is ever open across the whole dialog.
        self.commit_other_editors = None
        self.image_cache: dict = {}
        self.shape_type = "rectangle"
        self.color = "#ff0000"
        self.width_preset = "medium"
        self.filled = False
        self.px_per_pt = 1.0
        self._run_editor: _RunTextEdit | None = None
        self._editing_run: dict | None = None
        self._drag: dict | None = None
        self._create_drag: dict | None = None
        self._text_editor: QTextEdit | None = None
        self._editing_element_id: str | None = None
        self.model.on_change.append(self.update)

    def set_page_pixmap(self, pixmap) -> None:
        self.page_pixmap = pixmap
        self.setFixedSize(pixmap.size())
        info = self.model.page_info.get(self.page_number)
        if info and info["width_pt"]:
            self.px_per_pt = pixmap.width() / info["width_pt"]
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
        t = el.get("type")
        if t == "text_edit":
            box = self.model.text_edit_box(el)
            if box is None:
                return QRect()
            x0, y0, x1, y1 = box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"]
        elif t == "shape":
            x0, x1 = sorted((el["x0"], el["x1"]))
            y0, y1 = sorted((el["y0"], el["y1"]))
        elif t == "stroke":
            xs = [p["x"] for p in el["points"]]
            ys = [p["y"] for p in el["points"]]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        elif t == "highlight":
            box = insets_to_box({"top": el["top"], "left": el["left"], "right": el["right"], "bottom": el["bottom"]})
            x0, y0, x1, y1 = box["x0"], box["y0"], box["x1"], box["y1"]
        else:
            x0, y0 = el["x"], el["y"]
            x1, y1 = el["x"] + el["width"], el["y"] + el["height"]
        px0, py0 = x0 * self.width(), y0 * self.height()
        px1, py1 = x1 * self.width(), y1 * self.height()
        return QRect(int(px0), int(py0), int(px1 - px0), int(py1 - py0))

    def _corner_size(self, rect: QRect) -> int:
        # Same clamp ImagePlacementWidget._corner_size uses (deliberately
        # duplicated - these two widgets share no base class). QRect's
        # bottom()/right() are inclusive (bottom() == top() + height() - 1),
        # so a marker anchored at the top and a handle anchored at the
        # bottom, each sized height()//2, would share one row right where
        # they meet. Halving (height() - 1) instead keeps them strictly
        # apart. Without this, a minimum-sized element's marker rect
        # swallows the resize handle's centre and - since markers are
        # hit-tested first - a click meant to resize deletes instead.
        return max(6, min(_MARKER_SIZE, _HANDLE_SIZE, (rect.height() - 1) // 2, (rect.width() - 1) // 2))

    def _marker_rect(self, el: dict) -> QRect:
        rect = self._element_rect_px(el)
        size = self._corner_size(rect)
        return QRect(rect.right() - size, rect.top(), size, size)

    def _resize_handles(self, el: dict) -> dict:
        """One bottom-right handle for new_text (free resize), for shape
        (drags x1,y1 directly - see mouseMoveEvent) and for highlight
        (drags the right/bottom insets only, keeping left/top pinned).
        None at all for stroke, whose freehand points have no meaningful
        resize gesture. Three for image: a corner (aspect-locked uniform
        scale, matching
        ImagePlacementWidget's existing formula exactly), plus independent
        width-only and height-only handles (mid-right / mid-bottom edges)
        that deliberately allow aspect distortion, matching the web app's
        own three-handle image behavior (_apply_image's own
        keep_proportion=False trusts whatever box the editor produced)."""
        rect = self._element_rect_px(el)
        size = self._corner_size(rect)
        if el["type"] in ("new_text", "shape", "highlight"):
            return {"corner": QRect(rect.right() - size, rect.bottom() - size, size, size)}
        if el["type"] == "image":
            mid_x = rect.left() + rect.width() // 2
            mid_y = rect.top() + rect.height() // 2
            return {
                "corner": QRect(rect.right() - size, rect.bottom() - size, size, size),
                "width": QRect(rect.right() - size, mid_y - size // 2, size, size),
                "height": QRect(mid_x - size // 2, rect.bottom() - size, size, size),
            }
        return {}

    def _qfont_for(self, el: dict) -> QFont:
        font = QFont(el["family"], el["size"])
        font.setBold(el["bold"])
        font.setItalic(el["italic"])
        font.setUnderline(el["underline"])
        return font

    def _run_bbox_rect_px(self, run: dict) -> QRect:
        b = run["bbox"]
        x0, y0 = b["left"] * self.width(), b["top"] * self.height()
        x1, y1 = (1 - b["right"]) * self.width(), (1 - b["bottom"]) * self.height()
        return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _run_at(self, pos) -> dict | None:
        """The detected run under `pos`, topmost (last) first."""
        for run in reversed(self.model.text_runs.get(self.page_number, [])):
            if self._run_bbox_rect_px(run).contains(pos):
                return run
        return None

    @staticmethod
    def _run_default_style(run: dict) -> dict:
        return {"family": closest_base14_family(run["font"]), "bold": run["bold"],
                "italic": run["italic"], "size": float(run["size"])}

    def mousePressEvent(self, e) -> None:
        # Every gesture this widget understands is a LEFT-button one, and
        # this guard runs before anything else (including the text-editor
        # commit and all hit-testing) so a non-left button is inert: a
        # right-click must not delete an element via its marker, must not
        # start a drag-to-create, and - crucially - must not re-arm
        # _create_drag partway through a freehand stroke, which silently
        # threw away everything drawn so far.
        if e.button() != Qt.LeftButton:
            return
        # THE commit path for an open text draft in the real running app:
        # clicking anywhere else on the page finishes whatever is being
        # typed, before any hit-testing runs (so the click itself then
        # acts on the post-commit element list). Without this, a typed
        # draft is silently discarded and _text_editor never returns to
        # None - which would also leave EditPdfDialog._any_text_editor_open
        # stuck True, disabling every shortcut for the rest of the session.
        self._commit_others()
        self.commit_open_editors()
        pos = e.position().toPoint()
        elements = self._elements()
        for i in reversed(range(len(elements))):
            el = elements[i]
            # A text_edit's marker is only drawn (so only live) while it is
            # selected; otherwise it is an invisible hotspot on the run.
            if el["type"] == "text_edit" and self.model.selected_id != el["id"]:
                continue
            if self._marker_rect(el).contains(pos):
                self.model.remove(el["id"])
                return
        for i in reversed(range(len(elements))):
            el = elements[i]
            for handle_name, rect in self._resize_handles(el).items():
                if rect.contains(pos):
                    point = self._point_from_pos(pos)
                    self.model.select(el["id"])
                    self._drag = {"mode": f"resize-{handle_name}", "id": el["id"], "start": point, "start_element": dict(el), "committed": False}
                    return
        for i in reversed(range(len(elements))):
            el = elements[i]
            hit_rect = self._element_rect_px(el)
            if el["type"] in ("shape", "stroke"):
                # EVERY shape and stroke bbox is inflated, by at least 6px
                # on each side: the degenerate case is a horizontal/vertical
                # line or arrow, whose zero-height/zero-width bbox
                # QRect.contains() could never match for a real
                # (integer-rounded) click point, but a thin diagonal line or
                # freehand stroke is just as hard to hit exactly, so the
                # margin is applied unconditionally (and grows with the
                # stroke's own drawn width).
                margin = max(6, el["width"])
                hit_rect = hit_rect.adjusted(-margin, -margin, margin, margin)
            if hit_rect.contains(pos):
                point = self._point_from_pos(pos)
                self.model.select(el["id"])
                self._drag = {"mode": "move", "id": el["id"], "start": point, "start_element": dict(el), "committed": False}
                return
        point = self._point_from_pos(pos)
        if point is None:
            return
        if self.create_mode == "new_text":
            self._open_text_editor_for_new(point)
        elif self.create_mode == "image" and self.on_image_click is not None:
            self.on_image_click(point)
        elif self.create_mode in ("shape", "stroke", "highlight") and self._create_drag is None:
            # Never re-arm an already-running gesture: a second press
            # arriving mid-drag would reset it to the new press position
            # and discard the in-progress element.
            self._create_drag = {"start": point, "current": point, "points": [point]}

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
        if e.button() != Qt.LeftButton:
            return
        pos = e.position().toPoint()
        for el in reversed(self._elements()):
            if el["type"] == "new_text" and self._element_rect_px(el).contains(pos):
                self._drag = None
                self._open_text_editor_for_existing(el)
                return
            if el["type"] == "text_edit" and self.create_mode == "text" and self._element_rect_px(el).contains(pos):
                run = self.model.find_run(self.page_number, el["run_index"])
                if run is not None:
                    self._drag = None
                    self.open_run_editor(run)
                return
        if self.create_mode == "text":
            run = self._run_at(pos)
            if run is not None:
                self._drag = None
                self.open_run_editor(run)

    def _apply_drag(self, **changes) -> None:
        """Applies one intermediate position of the in-progress gesture,
        committing an undo step LAZILY: on the first move that genuinely
        changes the element, and never afterwards. That single commit runs
        before that first mutation, so - exactly like add/remove/nudge/
        reorder - the snapshot it pushes is the PRE-gesture state and an
        undo after the drag really does put the element back. Committing at
        gesture-END instead would snapshot the already-mutated element,
        making undo pop the state it already has (a silent no-op), and
        committing unconditionally at gesture-START would let a plain
        zero-movement click-to-select push a junk undo step and wipe the
        redo stack."""
        current = next((el for el in self.model.elements if el["id"] == self._drag["id"]), None)
        if current is None:
            return
        if all(current.get(k) == v for k, v in changes.items()):
            return  # nothing actually moved yet
        if not self._drag["committed"]:
            self.model.commit()
            self._drag["committed"] = True
        self.model.update(self._drag["id"], **changes)

    def mouseMoveEvent(self, e) -> None:
        if self._create_drag is not None:
            point = self._point_from_pos(e.position().toPoint())
            if point is not None:
                self._create_drag["current"] = point
                self._create_drag["points"].append(point)
                self.update()
            return
        if self._drag is None:
            return
        point = self._point_from_pos(e.position().toPoint())
        if point is None:
            return
        dx = point[0] - self._drag["start"][0]
        dy = point[1] - self._drag["start"][1]
        sp = self._drag["start_element"]
        if self._drag["mode"] == "move":
            # Always translated from the PRE-gesture snapshot by the drag's
            # total delta (never incrementally), so re-clamping on every
            # intermediate move is stable: dragging past the edge and back
            # returns the element to where the cursor actually is.
            changes = self.model.clamped_translate(sp, dx, dy)
            if sp["type"] == "text_edit" and sp.get("x") is None:
                box = self.model.text_edit_box(sp)
                if box is not None and changes.get("x") == box["x"] and changes.get("y") == box["y"]:
                    return  # clamped to exactly where it already is: no move
            self._apply_drag(**changes)
        elif self._drag["mode"] == "resize-corner":
            if sp["type"] == "shape":
                new_x1 = min(max(sp["x1"] + dx, 0), 1)
                new_y1 = min(max(sp["y1"] + dy, 0), 1)
                self._apply_drag(x1=new_x1, y1=new_y1)
            elif sp["type"] == "highlight":
                box = insets_to_box({"top": sp["top"], "left": sp["left"], "right": sp["right"], "bottom": sp["bottom"]})
                new_x1 = min(max(box["x1"] + dx, box["x0"] + _MIN_DRAG_FRACTION), 1)
                new_y1 = min(max(box["y1"] + dy, box["y0"] + _MIN_DRAG_FRACTION), 1)
                self._apply_drag(right=1 - new_x1, bottom=1 - new_y1)
            elif sp["type"] == "image":
                aspect = sp["height"] / sp["width"]
                width_cap = min(1 - sp["x"], (1 - sp["y"]) / aspect)
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, width_cap))
                height = width * aspect
                self._apply_drag(width=width, height=height)
            else:
                width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
                height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
                self._apply_drag(width=width, height=height)
        elif self._drag["mode"] == "resize-width":
            width = max(_MIN_TEXT_WIDTH_FRACTION, min(sp["width"] + dx, 1 - sp["x"]))
            self._apply_drag(width=width)
        elif self._drag["mode"] == "resize-height":
            height = max(_MIN_TEXT_HEIGHT_FRACTION, min(sp["height"] + dy, 1 - sp["y"]))
            self._apply_drag(height=height)

    def mouseReleaseEvent(self, e) -> None:
        # Mirrors mousePressEvent's left-button guard: only the button that
        # can START a gesture may end one, so releasing a second button
        # mid-stroke neither commits nor cancels what is being drawn.
        if e.button() != Qt.LeftButton:
            return
        if self._create_drag is not None:
            drag = self._create_drag
            self._create_drag = None
            self._finish_create_drag(drag)
            self.update()
            return
        # Deliberately commits NOTHING: _apply_drag already pushed this
        # gesture's single undo step, pre-mutation, the moment the gesture
        # first changed anything - and a gesture that changed nothing (the
        # plain click-to-select mousePressEvent also arms a drag for) must
        # not push one at all.
        self._drag = None

    def _finish_create_drag(self, drag: dict) -> str | None:
        """Dispatches a completed drag-to-create gesture by self.create_mode
        into the appropriate new element, or discards it if it didn't clear
        that type's own minimum-size/extent gate. Each gate matches the web
        app's own EditPdfCanvas.jsx rule for that type, and they genuinely
        differ: a rectangle/ellipse or a highlight needs BOTH axes to clear
        _MIN_DRAG_FRACTION, a line/arrow needs EITHER axis, and a freehand
        stroke is discarded only when BOTH axes of its whole extent fall
        below it (so a deliberate near-straight line survives)."""
        x0, y0 = drag["start"]
        x1, y1 = drag["current"]
        if self.create_mode == "shape":
            if self.shape_type in ("rectangle", "ellipse"):
                ok = abs(x1 - x0) >= _MIN_DRAG_FRACTION and abs(y1 - y0) >= _MIN_DRAG_FRACTION
            else:
                ok = abs(x1 - x0) >= _MIN_DRAG_FRACTION or abs(y1 - y0) >= _MIN_DRAG_FRACTION
            if not ok:
                return None
            filled = self.filled if self.shape_type in ("rectangle", "ellipse") else False
            return self.model.add({
                "page": self.page_number, "type": "shape", "shape": self.shape_type,
                "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset], "filled": filled,
            })
        elif self.create_mode == "stroke":
            pts = drag["points"]
            if len(pts) < 2:
                return None
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if (max(xs) - min(xs)) < _MIN_DRAG_FRACTION and (max(ys) - min(ys)) < _MIN_DRAG_FRACTION:
                return None
            return self.model.add({
                "page": self.page_number, "type": "stroke",
                "points": [{"x": x, "y": y} for x, y in pts],
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset],
            })
        elif self.create_mode == "highlight":
            sx0, sx1 = sorted((x0, x1))
            sy0, sy1 = sorted((y0, y1))
            if (sx1 - sx0) < _MIN_DRAG_FRACTION or (sy1 - sy0) < _MIN_DRAG_FRACTION:
                return None
            insets = box_to_insets({"x0": sx0, "y0": sy0, "x1": sx1, "y1": sy1})
            return self.model.add({"page": self.page_number, "type": "highlight", "color": self.color, **insets})
        return None

    def _paint_create_preview(self, painter: QPainter) -> None:
        """Renders the in-progress drag-to-create gesture directly from
        local widget state - deliberately never touches the model, so
        there is nothing to undo/commit if the drag is abandoned (e.g.
        released below the minimum threshold)."""
        if self._create_drag is None:
            return
        if self.create_mode == "shape":
            filled = self.filled if self.shape_type in ("rectangle", "ellipse") else False
            preview = {
                "type": "shape", "shape": self.shape_type,
                "x0": self._create_drag["start"][0], "y0": self._create_drag["start"][1],
                "x1": self._create_drag["current"][0], "y1": self._create_drag["current"][1],
                "color": self.color, "width": _WIDTH_PRESETS[self.width_preset], "filled": filled,
            }
            self._paint_shape(painter, preview)
        elif self.create_mode == "stroke":
            preview = {"points": [{"x": x, "y": y} for x, y in self._create_drag["points"]], "color": self.color, "width": _WIDTH_PRESETS[self.width_preset]}
            self._paint_stroke(painter, preview)
        elif self.create_mode == "highlight":
            sx0, sx1 = sorted((self._create_drag["start"][0], self._create_drag["current"][0]))
            sy0, sy1 = sorted((self._create_drag["start"][1], self._create_drag["current"][1]))
            insets = box_to_insets({"x0": sx0, "y0": sy0, "x1": sx1, "y1": sy1})
            preview = {"color": self.color, **insets}
            self._paint_highlight(painter, preview)

    def _commit_others(self) -> None:
        if self.commit_other_editors is not None:
            self.commit_other_editors()

    def _open_text_editor_for_new(self, point: tuple[float, float]) -> None:
        self._commit_others()
        width, height = 0.25, 0.08
        x = min(max(point[0] - width / 2, 0), 1 - width)
        y = min(max(point[1] - height / 2, 0), 1 - height)
        self._editing_element_id = None
        self._show_text_editor(x, y, width, height, "", {
            "family": "helvetica", "bold": False, "italic": False,
            "underline": False, "size": 14, "color": "#1f2937", "align": "left",
        })

    def _open_text_editor_for_existing(self, el: dict) -> None:
        self._commit_others()
        self._editing_element_id = el["id"]
        self._show_text_editor(el["x"], el["y"], el["width"], el["height"], el["text"], el)

    def _show_text_editor(self, x: float, y: float, width: float, height: float, text: str, style: dict) -> None:
        if self._text_editor is not None:
            # Switching straight from one text box to another commits the
            # outgoing draft rather than discarding it. _commit_text_editor
            # clears _editing_element_id as part of finishing that element,
            # so the INCOMING element's id - already set by our caller - is
            # saved across the call and restored afterwards.
            incoming_id = self._editing_element_id
            self._commit_text_editor()
            self._editing_element_id = incoming_id
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
            # commit() BEFORE update(), matching add/remove/nudge/reorder:
            # commit() snapshots the CURRENT (pre-edit) state onto the undo
            # stack, so mutating first would make the pre-edit text
            # unrecoverable.
            self.model.commit()
            self.model.update(self._editing_element_id, **{k: v for k, v in element.items() if k != "page"})
        else:
            self.model.add(element)
        self._editing_element_id = None

    def open_run_editor(self, run: dict) -> None:
        """Opens the unified rich-text editor over a detected run, seeded from
        the pending text_edit's segments if there is one, else from the run's
        own text in the run's own default style."""
        self._commit_others()
        self.commit_open_editors()
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        default = self._run_default_style(run)
        segments = pending["segments"] if pending else [{"text": run["text"], **default}]
        editor = _RunTextEdit(self)
        editor.setFrameShape(QTextEdit.NoFrame)
        editor.setAcceptRichText(False)  # paste/drop is plain text and takes the cursor's format
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setLineWrapMode(QTextEdit.NoWrap)
        doc = build_segments_document(segments, self.px_per_pt)
        doc.setParent(editor)  # QTextEdit does not own a parentless document; without this it can be collected mid-use
        # Verified: after select-all + Delete, Qt drops the character format,
        # so whatever is typed next is unformatted. The document's default font
        # is what such text displays in - set it to the run's own default style
        # (export already falls back to that same style for a format-less
        # fragment, see segments_from_document).
        self._apply_default_font(doc, default)
        editor.setDocument(doc)
        editor.setStyleSheet("QTextEdit { background: white; color: #1f2937; }")
        # typing continues in the style of the last segment (or the run's default)
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        editor.setTextCursor(cursor)
        editor.setCurrentCharFormat(_segment_format(segments[-1] if segments else {**default, "text": ""}, self.px_per_pt))
        rect = self._element_rect_px(pending) if pending else self._run_bbox_rect_px(run)
        # never narrower than a usable input, never past the page's right edge
        width = min(max(rect.width() + 8, 120), max(self.width() - rect.x(), 40))
        editor.setGeometry(rect.x(), rect.y(), width, max(rect.height() + 6, 20))
        editor.show()
        editor.setFocus()
        self._run_editor = editor
        self._editing_run = {"run": run, "default": default,
                             "initial_segments": segments_from_document(doc, default)}
        editor.cursorPositionChanged.connect(self.run_editor_cursor_moved)
        self.run_editor_cursor_moved.emit()
        self.update()

    def _apply_default_font(self, doc: QTextDocument, default: dict) -> None:
        font = QFont(default["family"])
        font.setPixelSize(max(1, round(default["size"] * self.px_per_pt)))
        font.setBold(default["bold"])
        font.setItalic(default["italic"])
        doc.setDefaultFont(font)

    def _commit_run_editor(self) -> None:
        if self._run_editor is None:
            return
        editor, info = self._run_editor, self._editing_run
        self._run_editor = None
        self._editing_run = None
        run = info["run"]
        segments = segments_from_document(editor.document(), info["default"])
        editor.deleteLater()
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        default = info["default"]
        # Compared against the seeded document as Qt actually holds it (not
        # run["text"]), so Qt-normalised characters never look like an edit.
        unchanged = segments == info["initial_segments"]
        if unchanged:
            self.update()
            return  # opened and closed without touching it: no element, no undo step
        if pending is not None:
            # commit() BEFORE update(): the snapshot must be the pre-edit
            # state so undo really restores the previous segments.
            self.model.commit()
            self.model.update(pending["id"], segments=segments)
        else:
            self.model.add({"page": self.page_number, "type": "text_edit", "run_index": run["index"], "segments": segments})
        self.update()

    def commit_open_editors(self) -> None:
        """Commits whichever editor is open (new_text or run). Safe to call
        with none open."""
        if self._text_editor is not None:
            self._commit_text_editor()
        if self._run_editor is not None:
            self._commit_run_editor()

    def apply_run_style(self, **patch) -> None:
        """Applies family/bold/italic/size to the run editor's SELECTION, or -
        with nothing selected - to the cursor's typing format, so the next
        characters typed take the style. No-op with no run editor open."""
        if self._run_editor is None:
            return
        fmt = QTextCharFormat()
        if "family" in patch:
            fmt.setFontFamilies([patch["family"]])
        if "bold" in patch:
            fmt.setFontWeight(QFont.Bold if patch["bold"] else QFont.Normal)
        if "italic" in patch:
            fmt.setFontItalic(patch["italic"])
        if "size" in patch:
            fmt.setProperty(QTextFormat.FontPixelSize, max(1, round(float(patch["size"]) * self.px_per_pt)))
            fmt.setProperty(_PDF_SIZE_PROP, float(patch["size"]))
        cursor = self._run_editor.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
            self._run_editor.setTextCursor(cursor)
        else:
            self._run_editor.mergeCurrentCharFormat(fmt)
        self._run_editor.setFocus()

    def run_editor_state(self) -> dict | None:
        """The style at the run editor's cursor (for the dialog's style row)."""
        if self._run_editor is None:
            return None
        fmt = self._run_editor.currentCharFormat()
        families = fmt.fontFamilies()
        size = fmt.property(_PDF_SIZE_PROP)
        default = self._editing_run["default"]
        return {
            "family": families[0] if families else default["family"],
            "bold": fmt.fontWeight() >= QFont.Bold,
            "italic": fmt.fontItalic(),
            "size": float(size) if size else default["size"],
        }

    def revert_run_editor(self) -> None:
        """Discards this run's pending text_edit (if any) and reseeds the
        still-open editor from the run's own original text and style."""
        if self._run_editor is None:
            return
        run, default = self._editing_run["run"], self._editing_run["default"]
        pending = self.model.text_edit_for_run(self.page_number, run["index"])
        if pending is not None:
            self.model.remove(pending["id"])
        doc = build_segments_document([{"text": run["text"], **default}], self.px_per_pt)
        doc.setParent(self._run_editor)
        self._apply_default_font(doc, default)
        self._run_editor.setDocument(doc)
        self._run_editor.setCurrentCharFormat(_segment_format({**default, "text": ""}, self.px_per_pt))
        self._editing_run["initial_segments"] = segments_from_document(doc, default)
        self._run_editor.setFocus()
        self.update()

    def paintEvent(self, e) -> None:
        painter = QPainter(self)
        if self.page_pixmap is not None:
            painter.drawPixmap(0, 0, self.page_pixmap)
        elements = self._elements()
        # edit_pdf applies every text_edit FIRST and everything else after,
        # in array order - paint in that same order so the preview layers
        # the way the export will.
        for el in elements:
            if el["type"] == "text_edit":
                self._paint_text_edit(painter, el)
        for el in elements:
            if el["type"] == "new_text":
                self._paint_new_text(painter, el)
            elif el["type"] == "image":
                self._paint_image(painter, el)
            elif el["type"] == "shape":
                self._paint_shape(painter, el)
            elif el["type"] == "stroke":
                self._paint_stroke(painter, el)
            elif el["type"] == "highlight":
                self._paint_highlight(painter, el)
        for el in elements:
            self._paint_chrome(painter, el)
        self._paint_create_preview(painter)

    def _paint_new_text(self, painter: QPainter, el: dict) -> None:
        if self._editing_element_id == el["id"] and self._text_editor is not None:
            return  # the live QTextEdit overlay is showing instead
        rect = self._element_rect_px(el)
        painter.setFont(self._qfont_for(el))
        painter.setPen(QColor(el["color"]))
        align_flag = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[el["align"]]
        painter.drawText(rect, align_flag | Qt.AlignTop | Qt.TextWordWrap, el["text"])

    def _text_edit_preview_segments(self, el: dict, run: dict) -> list[dict]:
        """The segments as the EXPORT will draw them: over-wide replacement
        text is shrunk to fit the original run's width by the core's own
        text_edit_final_sizes (never below half size / 6pt). Only the
        preview uses these sizes - the stored element is never touched.
        Falls back to the stored sizes when the page's size is unknown."""
        info = self.model.page_info.get(el["page"])
        if not info or not info["width_pt"] or not el["segments"]:
            return el["segments"]
        b = run["bbox"]
        displayed_w = (1 - b["left"] - b["right"]) * info["width_pt"]
        displayed_h = (1 - b["top"] - b["bottom"]) * info["height_pt"]
        # raw and displayed axes are swapped on a 90/270 page
        original_width = displayed_h if info["rotation"] in (90, 270) else displayed_w
        sizes = text_edit_final_sizes(el["segments"], original_width)
        return [{**seg, "size": size} for seg, size in zip(el["segments"], sizes)]

    def _paint_text_edit(self, painter: QPainter, el: dict) -> None:
        run = self.model.find_run(el["page"], el["run_index"])
        if run is None:
            return
        # the export redacts the ORIGINAL run with a white fill, wherever the
        # replacement ends up - mirror that
        painter.fillRect(self._run_bbox_rect_px(run), QColor("white"))
        if self._editing_run is not None and self._editing_run["run"]["index"] == el["run_index"]:
            return  # the live editor overlay is showing this run's text
        rect = self._element_rect_px(el)
        doc = build_segments_document(self._text_edit_preview_segments(el, run), self.px_per_pt)
        painter.save()
        painter.translate(rect.x(), rect.y())
        painter.setPen(QColor("#1f2937"))
        doc.drawContents(painter, QRectF(0, 0, max(rect.width(), int(doc.idealWidth()) + 1), max(rect.height(), int(doc.size().height()) + 1)))
        painter.restore()

    def _paint_image(self, painter: QPainter, el: dict) -> None:
        pixmap = self.image_cache.get(el["file_id"])
        if pixmap is None:
            pixmap = QPixmap(el["file_id"])
            self.image_cache[el["file_id"]] = pixmap
        painter.drawPixmap(self._element_rect_px(el), pixmap)

    def _paint_shape(self, painter: QPainter, el: dict) -> None:
        x0_px, y0_px = el["x0"] * self.width(), el["y0"] * self.height()
        x1_px, y1_px = el["x1"] * self.width(), el["y1"] * self.height()
        color = QColor(el["color"])
        painter.setPen(QPen(color, el["width"]))
        if el["shape"] in ("rectangle", "ellipse"):
            rect = QRect(int(min(x0_px, x1_px)), int(min(y0_px, y1_px)), int(abs(x1_px - x0_px)), int(abs(y1_px - y0_px)))
            painter.setBrush(color if el["filled"] else Qt.NoBrush)
            if el["shape"] == "rectangle":
                painter.drawRect(rect)
            else:
                painter.drawEllipse(rect)
        elif el["shape"] == "line":
            painter.setBrush(Qt.NoBrush)
            painter.drawLine(int(x0_px), int(y0_px), int(x1_px), int(y1_px))
        else:  # arrow
            painter.setBrush(color)
            self._draw_arrow_head(painter, x0_px, y0_px, x1_px, y1_px, el["width"])

    def _paint_stroke(self, painter: QPainter, el: dict) -> None:
        points = el["points"]
        if not points:
            return
        path = QPainterPath()
        first = points[0]
        path.moveTo(first["x"] * self.width(), first["y"] * self.height())
        for p in points[1:]:
            path.lineTo(p["x"] * self.width(), p["y"] * self.height())
        painter.setPen(QPen(QColor(el["color"]), el["width"]))
        painter.drawPath(path)

    def _paint_highlight(self, painter: QPainter, el: dict) -> None:
        box = insets_to_box({"top": el["top"], "left": el["left"], "right": el["right"], "bottom": el["bottom"]})
        rect = QRect(
            int(box["x0"] * self.width()), int(box["y0"] * self.height()),
            int((box["x1"] - box["x0"]) * self.width()), int((box["y1"] - box["y0"]) * self.height()),
        )
        color = QColor(el["color"])
        color.setAlphaF(0.4)
        painter.setPen(Qt.NoPen)
        painter.fillRect(rect, color)

    def _draw_arrow_head(self, painter: QPainter, x0: float, y0: float, x1: float, y1: float, width: float) -> None:
        """Client-side port of _apply_shape's _draw_arrow (pdf_ops.py:693)
        for the on-screen preview only - the actual PDF export still goes
        through the unchanged, existing _apply_shape/_draw_arrow, so this
        only needs to look reasonably like an arrow, not byte-for-byte
        match the export's geometry."""
        painter.drawLine(int(x0), int(y0), int(x1), int(y1))
        angle = math.atan2(y1 - y0, x1 - x0)
        head_len = max(8, width * 3)
        head_angle = math.radians(25)
        h1x = x1 - head_len * math.cos(angle - head_angle)
        h1y = y1 - head_len * math.sin(angle - head_angle)
        h2x = x1 - head_len * math.cos(angle + head_angle)
        h2y = y1 - head_len * math.sin(angle + head_angle)
        painter.drawPolygon(QPolygon([
            QPoint(int(x1), int(y1)), QPoint(int(h1x), int(h1y)), QPoint(int(h2x), int(h2y)),
        ]))

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
