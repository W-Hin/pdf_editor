import uuid

_PASTE_OFFSET = 0.03


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
