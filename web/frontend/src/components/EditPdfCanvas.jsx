import { useEffect, useRef, useState } from "react";
import {
  CursorText,
  PencilSimple,
  Rectangle,
  Highlighter,
  ImageSquare,
  TextAa,
  TextB,
  TextItalic,
  TextAUnderline,
  TextAlignLeft,
  TextAlignCenter,
  TextAlignRight,
  X,
  ArrowUUpLeft,
  ArrowUUpRight,
} from "@phosphor-icons/react";
import { fetchTextRuns, uploadFile } from "../api";
import PageScrollViewer from "./PageScrollViewer";

const MODES = [
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
  { id: "new_text", label: "Add Text", icon: TextAa },
];

const FAMILY_OPTIONS = ["helvetica", "times", "courier"];

const NEW_TEXT_DEFAULT_WIDTH = 0.25;
const NEW_TEXT_DEFAULT_HEIGHT = 0.08;
const NEW_TEXT_DEFAULTS = {
  family: "helvetica",
  bold: false,
  italic: false,
  underline: false,
  size: 14,
  color: "#1f2937",
  align: "left",
};

function newTextFontFamilyCss(family) {
  if (family === "times") return '"Times New Roman", Times, serif';
  if (family === "courier") return '"Courier New", Courier, monospace';
  return "Helvetica, Arial, sans-serif";
}

const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5"];
const STROKE_WIDTHS = { thin: 1, medium: 3, thick: 6 };

// Smallest drag (as a fraction of the page) that counts as a real gesture
// rather than a click with a pixel of jitter. Shared by draw/shapes/highlight
// so a stray click never commits a degenerate element the backend then rejects.
const MIN_DRAG_FRACTION = 0.02;

// Alpha suffix for an 8-digit hex colour, matching the 0.4 fill opacity
// edit_pdf renders highlights at. Baking translucency into the colour (rather
// than using CSS `opacity`) keeps the element's children — the remove button —
// fully opaque, since `opacity` creates a stacking context its children cannot
// escape.
const HIGHLIGHT_ALPHA_HEX = "66";

export default function EditPdfCanvas({ fileId, pageCount, onChange }) {
  const [activeMode, setActiveMode] = useState("text");
  const [elements, setElements] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [runs, setRuns] = useState([]);
  const [editingRunIndex, setEditingRunIndex] = useState(null);
  const [editingRunPage, setEditingRunPage] = useState(null);
  const [draftText, setDraftText] = useState("");
  const [draftOverride, setDraftOverride] = useState(null);
  // The family dropdown always defaults to "helvetica" regardless of the run's
  // detected font, so comparing its VALUE against "helvetica" cannot tell
  // "explicitly chose Helvetica on a Times run" from "never touched it" — and
  // silently drops the user's choice. Track the interaction itself instead.
  const [draftFamilyTouched, setDraftFamilyTouched] = useState(false);
  const [drawColor, setDrawColor] = useState(MARKUP_COLORS[0]);
  const [drawWidth, setDrawWidth] = useState("medium");
  const [activeStroke, setActiveStroke] = useState(null); // { page, points } | null
  const [shapeType, setShapeType] = useState("rectangle");
  const [shapeColor, setShapeColor] = useState(MARKUP_COLORS[0]);
  const [shapeWidth, setShapeWidth] = useState("medium");
  const [shapeFilled, setShapeFilled] = useState(false);
  const [shapeDragPage, setShapeDragPage] = useState(null);
  const [shapeDragStart, setShapeDragStart] = useState(null);
  const [shapeDragCurrent, setShapeDragCurrent] = useState(null);
  const [highlightColor, setHighlightColor] = useState("#ffd43b");
  const [highlightDragPage, setHighlightDragPage] = useState(null);
  const [highlightDragStart, setHighlightDragStart] = useState(null);
  const [highlightDragCurrent, setHighlightDragCurrent] = useState(null);
  const [textDraft, setTextDraft] = useState(null);
  const textDraftAreaRef = useRef(null);
  const imageFileInputRef = useRef(null);
  const pendingImageDropRef = useRef(null);
  const dragRef = useRef(null);
  const historyRef = useRef({ undoStack: [], redoStack: [] });
  const [historyVersion, setHistoryVersion] = useState(0); // bump to force a re-render when the stacks change
  const clipboardRef = useRef(null);
  const elementsRef = useRef(elements);
  const selectedElementForStyle = elements.find((e) => e.id === selectedId) ?? null;

  useEffect(() => {
    elementsRef.current = elements;
  }, [elements]);

  useEffect(() => {
    if (textDraft) textDraftAreaRef.current?.focus();
  }, [textDraft?.id]);

  useEffect(() => {
    if (!fileId || !pageCount) return;
    let cancelled = false;
    async function loadRuns() {
      const perPage = await Promise.all(
        Array.from({ length: pageCount }, (_, i) => i + 1).map((pageNumber) =>
          fetchTextRuns(fileId, pageNumber)
            .then((data) => data.runs.map((r) => ({ ...r, page: pageNumber })))
            .catch((err) => {
              console.error(`Failed to load text runs for page ${pageNumber}:`, err);
              return [];
            })
        )
      );
      if (!cancelled) setRuns(perPage.flat());
    }
    loadRuns();
    setEditingRunIndex(null);
    return () => {
      cancelled = true;
    };
  }, [fileId, pageCount]);

  useEffect(() => {
    function isTypingTarget(target) {
      return target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
    }

    function copySelected() {
      const el = elements.find((e) => e.id === selectedId);
      if (!el || el.type === "text_edit") return null;
      // Keep `page` (unlike the id) — paste lands on the SAME page the
      // copied element came from. There's no longer a single "current page"
      // to fall back on now that every page is visible at once.
      const { id, ...rest } = el;
      return rest;
    }

    function pasteClipboard() {
      if (!clipboardRef.current) return;
      const OFFSET = 0.03;
      // Paste TRANSLATES the element by OFFSET. Every type therefore shifts all
      // of its coordinates on an axis by the SAME amount, shrunk to whatever
      // room is actually left on the page. Clamping each coordinate
      // independently against a fixed bound distorts the element near an edge
      // instead of moving it — and for a highlight (whose "right"/"bottom" are
      // insets from the FAR edges) shifting only "left"/"top" shrinks the box,
      // which for a near-minimum highlight goes negative and fails the Run.
      const shift = (remaining) => Math.max(0, Math.min(OFFSET, remaining));
      const base = { ...clipboardRef.current };
      if ("x0" in base) {
        const dx = shift(1 - Math.max(base.x0, base.x1));
        const dy = shift(1 - Math.max(base.y0, base.y1));
        base.x0 += dx;
        base.x1 += dx;
        base.y0 += dy;
        base.y1 += dy;
      } else if ("left" in base) {
        // "right"/"bottom" are exactly the space remaining on those edges.
        const dx = shift(base.right);
        const dy = shift(base.bottom);
        base.left += dx;
        base.right -= dx;
        base.top += dy;
        base.bottom -= dy;
      } else if ("x" in base) {
        const dx = shift(1 - (base.x + base.width));
        const dy = shift(1 - (base.y + base.height));
        base.x += dx;
        base.y += dy;
      } else if ("points" in base) {
        const dx = shift(1 - Math.max(...base.points.map((p) => p.x)));
        const dy = shift(1 - Math.max(...base.points.map((p) => p.y)));
        base.points = base.points.map((p) => ({ x: p.x + dx, y: p.y + dy }));
      }
      const pasted = { ...base, id: newElementId() };
      commitElements([...elements, pasted]);
      setSelectedId(pasted.id);
    }

    function handleKeyDown(e) {
      if (textDraft || isTypingTarget(document.activeElement)) return;
      const ctrl = e.ctrlKey || e.metaKey;
      if (!ctrl) {
        if (e.key === "Escape") setSelectedId(null);
        return;
      }
      if (e.key === "z" || e.key === "Z") {
        e.preventDefault();
        undo();
      } else if (e.key === "y" || e.key === "Y") {
        e.preventDefault();
        redo();
      } else if (e.key === "c" || e.key === "C") {
        const copied = copySelected();
        if (copied) {
          e.preventDefault();
          clipboardRef.current = copied;
        }
      } else if (e.key === "x" || e.key === "X") {
        const copied = copySelected();
        if (copied) {
          e.preventDefault();
          clipboardRef.current = copied;
          commitElements(elements.filter((el) => el.id !== selectedId));
          setSelectedId(null);
        }
      } else if (e.key === "v" || e.key === "V") {
        e.preventDefault();
        pasteClipboard();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [elements, selectedId, textDraft]);

  if (!fileId || !pageCount) return null;

  function commitElements(next) {
    historyRef.current = { undoStack: [...historyRef.current.undoStack, elements], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    setElements(next);
    onChange(next);
  }

  function updateSelectedElementStyle(patch) {
    if (!selectedId) return false; // nothing selected — caller should fall back to its default-setting behavior
    const el = elements.find((e) => e.id === selectedId);
    if (!el) return false;
    commitElements(elements.map((e) => (e.id === selectedId ? { ...e, ...patch } : e)));
    return true;
  }

  function undo() {
    const { undoStack, redoStack } = historyRef.current;
    if (undoStack.length === 0) return;
    const previous = undoStack[undoStack.length - 1];
    historyRef.current = { undoStack: undoStack.slice(0, -1), redoStack: [...redoStack, elements] };
    setHistoryVersion((v) => v + 1);
    setElements(previous);
    onChange(previous);
  }

  function redo() {
    const { undoStack, redoStack } = historyRef.current;
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    historyRef.current = { undoStack: [...undoStack, elements], redoStack: redoStack.slice(0, -1) };
    setHistoryVersion((v) => v + 1);
    setElements(next);
    onChange(next);
  }

  function newElementId() {
    return crypto.randomUUID();
  }

  // Selecting stops the click from reaching the stage, whose own handler treats
  // any click that gets there as a click on empty canvas and deselects.
  function selectElement(id, e) {
    e.stopPropagation();
    setSelectedId(id);
  }

  function removeElement(id) {
    commitElements(elements.filter((el) => el.id !== id));
    // Otherwise selectedId keeps pointing at a deleted element.
    if (selectedId === id) setSelectedId(null);
  }

  function handleStageClick() {
    // Spec: clicking empty canvas deselects. Clicks that landed on an element
    // stop propagating before they reach here.
    setSelectedId(null);
  }

  function pointFromEvent(pageRef, e) {
    const rect = pageRef.current.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const x = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    const y = Math.min(Math.max((e.clientY - rect.top) / rect.height, 0), 1);
    return { x, y };
  }

  function handleDrawMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setActiveStroke({ page: pageNumber, points: [point] });
  }

  function handleDrawMouseMove(pageRef, e) {
    if (!activeStroke) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setActiveStroke((s) => ({ ...s, points: [...s.points, point] }));
  }

  function handleDrawMouseUp() {
    // Clear FIRST, unconditionally. handleDrawMouseMove is gated only on
    // activeStroke being non-null, not on a button actually being held, so
    // leaving a 1-point stroke armed after a plain click makes a line follow
    // the cursor and commit a phantom stroke on the next mouseup/mouseleave.
    const stroke = activeStroke;
    setActiveStroke(null);
    if (!stroke || stroke.points.length < 2) return;
    // A point count is not a size: a click with a pixel of jitter still yields
    // two points. Measure the actual extent instead, as Highlight mode does.
    const xs = stroke.points.map((p) => p.x);
    const ys = stroke.points.map((p) => p.y);
    if (
      Math.max(...xs) - Math.min(...xs) < MIN_DRAG_FRACTION &&
      Math.max(...ys) - Math.min(...ys) < MIN_DRAG_FRACTION
    ) {
      return;
    }
    const next = [
      ...elements,
      { id: newElementId(), type: "stroke", page: stroke.page, points: stroke.points, color: drawColor, width: STROKE_WIDTHS[drawWidth] },
    ];
    commitElements(next);
  }
  function handleShapeMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setShapeDragPage(pageNumber);
    setShapeDragStart(point);
    setShapeDragCurrent(point);
  }

  function handleShapeMouseMove(pageRef, e) {
    if (!shapeDragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setShapeDragCurrent(point);
  }

  function handleShapeMouseUp() {
    if (!shapeDragStart || !shapeDragCurrent) return;
    const { x: x0, y: y0 } = shapeDragStart;
    const { x: x1, y: y1 } = shapeDragCurrent;
    const page = shapeDragPage;
    setShapeDragPage(null);
    setShapeDragStart(null);
    setShapeDragCurrent(null);
    // Check both axes independently, as Highlight mode does. A perfectly
    // horizontal or vertical drag is not "stationary", but it still produces a
    // zero-dimension rectangle/ellipse that _validate_shape rejects at Run time
    // with an error pointing at nothing visible on screen.
    if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION || Math.abs(y1 - y0) < MIN_DRAG_FRACTION) {
      if (shapeType === "rectangle" || shapeType === "ellipse") return;
      // A line or arrow only needs two distinct points, so only a drag that is
      // degenerate on BOTH axes is unusable.
      if (Math.abs(x1 - x0) < MIN_DRAG_FRACTION && Math.abs(y1 - y0) < MIN_DRAG_FRACTION) return;
    }
    const next = [
      ...elements,
      {
        id: newElementId(),
        type: "shape",
        page,
        shape: shapeType,
        x0,
        y0,
        x1,
        y1,
        color: shapeColor,
        width: STROKE_WIDTHS[shapeWidth],
        filled: shapeType === "rectangle" || shapeType === "ellipse" ? shapeFilled : false,
      },
    ];
    commitElements(next);
  }
  function handleHighlightMouseDown(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setHighlightDragPage(pageNumber);
    setHighlightDragStart(point);
    setHighlightDragCurrent(point);
  }

  function handleHighlightMouseMove(pageRef, e) {
    if (!highlightDragStart) return;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setHighlightDragCurrent(point);
  }

  function handleHighlightMouseUp() {
    if (!highlightDragStart || !highlightDragCurrent) return;
    const x0 = Math.min(highlightDragStart.x, highlightDragCurrent.x);
    const x1 = Math.max(highlightDragStart.x, highlightDragCurrent.x);
    const y0 = Math.min(highlightDragStart.y, highlightDragCurrent.y);
    const y1 = Math.max(highlightDragStart.y, highlightDragCurrent.y);
    const page = highlightDragPage;
    setHighlightDragPage(null);
    setHighlightDragStart(null);
    setHighlightDragCurrent(null);
    if (x1 - x0 < MIN_DRAG_FRACTION || y1 - y0 < MIN_DRAG_FRACTION) return;
    const next = [
      ...elements,
      { id: newElementId(), type: "highlight", page, top: y0, left: x0, right: 1 - x1, bottom: 1 - y1, color: highlightColor },
    ];
    commitElements(next);
  }
  function handleImageStageClick(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    pendingImageDropRef.current = { page: pageNumber, point };
    imageFileInputRef.current?.click();
  }

  function loadImageNaturalSize(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        resolve({ width: img.naturalWidth, height: img.naturalHeight });
        URL.revokeObjectURL(url);
      };
      img.src = url;
    });
  }

  async function handleImageFileSelected(e) {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const drop = pendingImageDropRef.current ?? { page: 1, point: { x: 0.375, y: 0.375 } };
    const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSize(file)]);
    const width = 0.25;
    const height = Math.min(0.9, width * (naturalSize.height / naturalSize.width));
    const x = Math.min(Math.max(drop.point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(drop.point.y - height / 2, 0), 1 - height);
    commitElements([...elements, { id: newElementId(), type: "image", page: drop.page, file_id: uploaded.id, x, y, width, height }]);
  }

  function handleNewTextStageClick(pageNumber, pageRef, e) {
    if (textDraft) return; // an editor is already open — closing it happens via blur, not another placement in the same click
    // The browser's own mousedown default action clears focus shortly after
    // this handler returns (since the stage div itself isn't focusable),
    // racing the effect below that focuses the new textarea and winning —
    // the textarea gets focus then loses it a fraction of a millisecond
    // later, firing the wrapper's onBlur and discarding the just-placed,
    // still-empty draft before the user can type. Suppressing the default
    // action here stops the browser from clearing focus so the effect's
    // focus() call sticks.
    e.preventDefault();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    const width = NEW_TEXT_DEFAULT_WIDTH;
    const height = NEW_TEXT_DEFAULT_HEIGHT;
    const x = Math.min(Math.max(point.x - width / 2, 0), 1 - width);
    const y = Math.min(Math.max(point.y - height / 2, 0), 1 - height);
    setTextDraft({ id: null, page: pageNumber, x, y, width, height, text: "", ...NEW_TEXT_DEFAULTS });
  }

  function commitTextDraft() {
    const draft = textDraft;
    setTextDraft(null);
    if (!draft || !draft.text.trim()) return; // empty placements are discarded, not saved
    const { id, ...rest } = draft;
    const newEl = { id: id ?? newElementId(), type: "new_text", ...rest };
    const next = id ? elements.map((el) => (el.id === id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  function openTextDraftForEdit(el) {
    const { id, ...rest } = el;
    setTextDraft({ id, ...rest });
  }

  function handleTextDraftBlur(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) {
      commitTextDraft();
    }
  }

  function handleTextDraftKeyDown(e) {
    const ctrl = e.ctrlKey || e.metaKey;
    if (!ctrl) return;
    if (e.key === "b" || e.key === "B") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, bold: !d.bold }));
    } else if (e.key === "i" || e.key === "I") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, italic: !d.italic }));
    } else if (e.key === "u" || e.key === "U") {
      e.preventDefault();
      setTextDraft((d) => ({ ...d, underline: !d.underline }));
    }
  }

  function startElementDrag(pageRef, el, mode, e, options = {}) {
    e.stopPropagation();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    dragRef.current = {
      id: el.id, mode, start: point, startElement: { ...el }, startElementsSnapshot: elements, moved: false,
      lockAspect: options.lockAspect ?? false, pageRef,
    };
    window.addEventListener("mousemove", handleElementDragMove);
    window.addEventListener("mouseup", handleElementDragEnd);
    window.addEventListener("blur", handleElementDragEnd);
  }

  function handleElementDragMove(e) {
    const drag = dragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
    if (!point) return;
    drag.moved = true;
    const dx = point.x - drag.start.x;
    const dy = point.y - drag.start.y;
    const { startElement } = drag;
    let updated;
    if (drag.mode === "move") {
      updated = moveElement(startElement, dx, dy);
    } else if (drag.mode === "resize-width") {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      updated = { ...startElement, width };
    } else if (drag.mode === "resize-height") {
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, height };
    } else if (drag.mode === "resize-corner-xy") {
      const x1 = Math.min(Math.max(startElement.x1 + dx, 0), 1);
      const y1 = Math.min(Math.max(startElement.y1 + dy, 0), 1);
      updated = { ...startElement, x1, y1 };
    } else if (drag.mode === "resize" && "left" in startElement) {
      const width = Math.max(0.02, 1 - startElement.left - startElement.right + dx);
      const height = Math.max(0.02, 1 - startElement.top - startElement.bottom + dy);
      const right = Math.max(0, 1 - startElement.left - width);
      const bottom = Math.max(0, 1 - startElement.top - height);
      updated = { ...startElement, right, bottom };
    } else if (drag.lockAspect) {
      const aspect = startElement.height / startElement.width;
      const widthCap = Math.min(1 - startElement.x, (1 - startElement.y) / aspect);
      const desiredWidth = Math.max(0.05, startElement.width + dx);
      const width = Math.min(desiredWidth, widthCap);
      const height = width * aspect;
      updated = { ...startElement, width, height };
    } else {
      const width = Math.min(Math.max(0.05, startElement.width + dx), 1 - startElement.x);
      const height = Math.min(Math.max(0.03, startElement.height + dy), 1 - startElement.y);
      updated = { ...startElement, width, height };
    }
    drag.latestElement = updated;
    setElements((prev) => prev.map((el) => (el.id === drag.id ? updated : el)));
  }

  // Moving translates the element by (dx, dy), clamped so it stays on the
  // page. Each element type keeps its own coordinates within bounds, so the
  // clamp differs by shape: x/y/width/height types clamp directly; x0/x1 and
  // left/right/top/bottom types clamp the pair together; points translate as
  // a whole group, clamped by their own min/max extent.
  function moveElement(el, dx, dy) {
    if ("x0" in el) {
      const width = Math.abs(el.x1 - el.x0);
      const height = Math.abs(el.y1 - el.y0);
      const minX = Math.min(el.x0, el.x1);
      const minY = Math.min(el.y0, el.y1);
      const clampedDx = Math.min(Math.max(dx, -minX), 1 - width - minX);
      const clampedDy = Math.min(Math.max(dy, -minY), 1 - height - minY);
      return { ...el, x0: el.x0 + clampedDx, x1: el.x1 + clampedDx, y0: el.y0 + clampedDy, y1: el.y1 + clampedDy };
    }
    if ("left" in el) {
      const width = 1 - el.left - el.right;
      const height = 1 - el.top - el.bottom;
      const clampedDx = Math.min(Math.max(dx, -el.left), el.right);
      const clampedDy = Math.min(Math.max(dy, -el.top), el.bottom);
      return { ...el, left: el.left + clampedDx, right: el.right - clampedDx, top: el.top + clampedDy, bottom: el.bottom - clampedDy };
    }
    if ("points" in el) {
      const xs = el.points.map((p) => p.x);
      const ys = el.points.map((p) => p.y);
      const clampedDx = Math.min(Math.max(dx, -Math.min(...xs)), 1 - Math.max(...xs));
      const clampedDy = Math.min(Math.max(dy, -Math.min(...ys)), 1 - Math.max(...ys));
      return { ...el, points: el.points.map((p) => ({ x: p.x + clampedDx, y: p.y + clampedDy })) };
    }
    // x/y/width/height (image, new_text)
    const x = Math.min(Math.max(el.x + dx, 0), 1 - el.width);
    const y = Math.min(Math.max(el.y + dy, 0), 1 - el.height);
    return { ...el, x, y };
  }

  function handleElementDragEnd() {
    window.removeEventListener("mousemove", handleElementDragMove);
    window.removeEventListener("mouseup", handleElementDragEnd);
    window.removeEventListener("blur", handleElementDragEnd);
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || !drag.moved) return;
    historyRef.current = { undoStack: [...historyRef.current.undoStack, drag.startElementsSnapshot], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    const finalElements = drag.latestElement
      ? elementsRef.current.map((el) => (el.id === drag.id ? drag.latestElement : el))
      : elementsRef.current;
    onChange(finalElements);
  }

  function handleStageMouseDown(pageNumber, pageRef, e) {
    if (activeMode === "draw") return handleDrawMouseDown(pageNumber, pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseDown(pageNumber, pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseDown(pageNumber, pageRef, e);
    if (activeMode === "image") return handleImageStageClick(pageNumber, pageRef, e);
    if (activeMode === "new_text") return handleNewTextStageClick(pageNumber, pageRef, e);
  }

  function handleStageMouseMove(pageRef, e) {
    if (activeMode === "draw") return handleDrawMouseMove(pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseMove(pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseMove(pageRef, e);
  }

  function handleStageMouseUp(e) {
    if (activeMode === "draw") return handleDrawMouseUp(e);
    if (activeMode === "shapes") return handleShapeMouseUp(e);
    if (activeMode === "highlight") return handleHighlightMouseUp(e);
  }

  function pendingTextEditFor(run) {
    return elements.find((el) => el.type === "text_edit" && el.page === run.page && el.run_index === run.index);
  }

  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    setEditingRunIndex(run.index);
    setEditingRunPage(pageNumber);
    setDraftText(pending ? pending.text : run.text);
    // Re-opening a queued edit that already carries an override means its
    // family was an explicit choice — keep it explicit.
    setDraftFamilyTouched(Boolean(pending?.font_override));
    setDraftOverride(
      pending?.font_override ?? {
        family: "helvetica",
        bold: run.bold,
        italic: run.italic,
        size: run.size,
      }
    );
  }

  function submitRunEditor(run) {
    const pending = pendingTextEditFor(run);
    const overrideChanged =
      draftFamilyTouched || draftOverride.bold !== run.bold || draftOverride.italic !== run.italic || draftOverride.size !== run.size;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editingRunPage,
      run_index: run.index,
      text: draftText,
      font_override: overrideChanged ? draftOverride : null,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
    setEditingRunIndex(null);
  }

  function removeTextEdit(run) {
    const pending = pendingTextEditFor(run);
    if (!pending) return;
    commitElements(elements.filter((el) => el.id !== pending.id));
    setEditingRunIndex(null);
  }

  function renderPageOverlay(pageNumber, pageRef) {
    return (
      <div
        className="edit-pdf-canvas__stage"
        onMouseDown={(e) => handleStageMouseDown(pageNumber, pageRef, e)}
        onMouseMove={(e) => handleStageMouseMove(pageRef, e)}
        onMouseUp={handleStageMouseUp}
        onMouseLeave={handleStageMouseUp}
        onClick={handleStageClick}
      >
        <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none">
          {elements
            .filter((el) => el.type === "stroke" && el.page === pageNumber)
            .map((el) => (
              <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                <polyline
                  points={el.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
                  fill="none"
                  stroke={el.color}
                  strokeWidth={el.width / 3}
                  vectorEffect="non-scaling-stroke"
                  className={el.id === selectedId ? "edit-pdf-canvas__stroke edit-pdf-canvas__stroke--selected" : "edit-pdf-canvas__stroke"}
                />
              </g>
            ))}
          {activeStroke && activeStroke.page === pageNumber && (
            <polyline
              points={activeStroke.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={drawColor}
              strokeWidth={STROKE_WIDTHS[drawWidth] / 3}
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {elements
          .filter((el) => el.type === "stroke" && el.page === pageNumber)
          .map((el) => {
            const xs = el.points.map((p) => p.x);
            const ys = el.points.map((p) => p.y);
            const left = Math.min(...xs);
            const top = Math.min(...ys);
            const width = Math.max(...xs) - left;
            const height = Math.max(...ys) - top;
            return (
              <div key={`${el.id}-hit`}>
                <div
                  className="edit-pdf-canvas__hit-overlay"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }}
                  onMouseDown={(e) => {
                    setSelectedId(el.id);
                    startElementDrag(pageRef, el, "move", e);
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
                <button
                  type="button"
                  className="edit-pdf-canvas__element-remove"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => removeElement(el.id)}
                  aria-label="Remove this stroke"
                >
                  <X size={12} weight="bold" />
                </button>
              </div>
            );
          })}

        <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ zIndex: 2 }}>
          {elements
            .filter((el) => el.type === "shape" && el.page === pageNumber)
            .map((el) => {
              const stroke = el.color;
              const fill = el.filled ? el.color : "none";
              const commonProps = {
                stroke,
                fill,
                strokeWidth: el.width / 3,
                vectorEffect: "non-scaling-stroke",
                className: el.id === selectedId ? "edit-pdf-canvas__shape edit-pdf-canvas__shape--selected" : "edit-pdf-canvas__shape",
              };
              if (el.shape === "rectangle") {
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <rect
                      {...commonProps}
                      x={Math.min(el.x0, el.x1) * 100}
                      y={Math.min(el.y0, el.y1) * 100}
                      width={Math.abs(el.x1 - el.x0) * 100}
                      height={Math.abs(el.y1 - el.y0) * 100}
                    />
                  </g>
                );
              }
              if (el.shape === "ellipse") {
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <ellipse
                      {...commonProps}
                      cx={((el.x0 + el.x1) / 2) * 100}
                      cy={((el.y0 + el.y1) / 2) * 100}
                      rx={(Math.abs(el.x1 - el.x0) / 2) * 100}
                      ry={(Math.abs(el.y1 - el.y0) / 2) * 100}
                    />
                  </g>
                );
              }
              if (el.shape === "arrow") {
                const x1p = el.x0 * 100, y1p = el.y0 * 100, x2p = el.x1 * 100, y2p = el.y1 * 100;
                const angle = Math.atan2(y2p - y1p, x2p - x1p);
                const headLen = Math.max(2, el.width);
                const headAngle = (25 * Math.PI) / 180;
                const hx1 = x2p - headLen * Math.cos(angle - headAngle);
                const hy1 = y2p - headLen * Math.sin(angle - headAngle);
                const hx2 = x2p - headLen * Math.cos(angle + headAngle);
                const hy2 = y2p - headLen * Math.sin(angle + headAngle);
                return (
                  <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                    <line {...commonProps} x1={x1p} y1={y1p} x2={x2p} y2={y2p} />
                    <polygon
                      points={`${hx1},${hy1} ${x2p},${y2p} ${hx2},${hy2}`}
                      fill={el.color}
                      stroke={el.color}
                    />
                  </g>
                );
              }
              // line renders as a plain line — the arrow branch above is what
              // now makes it visually distinct from Arrow in the live preview.
              return (
                <g key={el.id} onClick={(e) => selectElement(el.id, e)}>
                  <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
                </g>
              );
            })}
          {shapeDragPage === pageNumber && shapeDragStart && shapeDragCurrent && (
            <line
              x1={shapeDragStart.x * 100}
              y1={shapeDragStart.y * 100}
              x2={shapeDragCurrent.x * 100}
              y2={shapeDragCurrent.y * 100}
              stroke={shapeColor}
              strokeWidth={STROKE_WIDTHS[shapeWidth] / 3}
              strokeDasharray="2,1"
              vectorEffect="non-scaling-stroke"
            />
          )}
        </svg>

        {elements
          .filter((el) => el.type === "shape" && el.page === pageNumber)
          .map((el) => {
            const left = Math.min(el.x0, el.x1);
            const top = Math.min(el.y0, el.y1);
            const width = Math.abs(el.x1 - el.x0);
            const height = Math.abs(el.y1 - el.y0);
            return (
              <div key={`${el.id}-hit`}>
                <div
                  className="edit-pdf-canvas__hit-overlay"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }}
                  onMouseDown={(e) => {
                    setSelectedId(el.id);
                    startElementDrag(pageRef, el, "move", e);
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <div
                    className="edit-pdf-canvas__shape-resize-handle"
                    onMouseDown={(e) => startElementDrag(pageRef, el, "resize-corner-xy", e)}
                  />
                </div>
                <button
                  type="button"
                  className="edit-pdf-canvas__element-remove"
                  style={{ left: `${left * 100}%`, top: `${top * 100}%` }}
                  onMouseDown={(e) => e.stopPropagation()}
                  onClick={() => removeElement(el.id)}
                  aria-label="Remove this shape"
                >
                  <X size={12} weight="bold" />
                </button>
              </div>
            );
          })}

        {elements
          .filter((el) => el.type === "highlight" && el.page === pageNumber)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__highlight edit-pdf-canvas__highlight--selected"
                  : "edit-pdf-canvas__highlight"
              }
              style={{
                left: `${el.left * 100}%`,
                top: `${el.top * 100}%`,
                width: `${(1 - el.left - el.right) * 100}%`,
                height: `${(1 - el.top - el.bottom) * 100}%`,
                background: `${el.color}${HIGHLIGHT_ALPHA_HEX}`,
              }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(pageRef, el, "move", e);
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div
                className="edit-pdf-canvas__shape-resize-handle"
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: false })}
              />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={(e) => {
                  e.stopPropagation();
                  removeElement(el.id);
                }}
                aria-label="Remove this highlight"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}
        {highlightDragPage === pageNumber && highlightDragStart && highlightDragCurrent && (
          <div
            className="edit-pdf-canvas__highlight edit-pdf-canvas__highlight--dragging"
            style={{
              left: `${Math.min(highlightDragStart.x, highlightDragCurrent.x) * 100}%`,
              top: `${Math.min(highlightDragStart.y, highlightDragCurrent.y) * 100}%`,
              width: `${Math.abs(highlightDragCurrent.x - highlightDragStart.x) * 100}%`,
              height: `${Math.abs(highlightDragCurrent.y - highlightDragStart.y) * 100}%`,
              background: `${highlightColor}${HIGHLIGHT_ALPHA_HEX}`,
            }}
          />
        )}

        {elements
          .filter((el) => el.type === "image" && el.page === pageNumber)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__image-el edit-pdf-canvas__image-el--selected"
                  : "edit-pdf-canvas__image-el"
              }
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(pageRef, el, "move", e);
              }}
              // Selection happens on mousedown here (it starts a drag), but the
              // click that follows would still reach the stage and deselect.
              onClick={(e) => e.stopPropagation()}
            >
              <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: true })} />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => removeElement(el.id)}
                aria-label="Remove this image"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}

        {elements
          .filter((el) => el.type === "new_text" && el.page === pageNumber && el.id !== textDraft?.id)
          .map((el) => (
            <div
              key={el.id}
              className={
                el.id === selectedId
                  ? "edit-pdf-canvas__new-text-el edit-pdf-canvas__new-text-el--selected"
                  : "edit-pdf-canvas__new-text-el"
              }
              style={{ left: `${el.x * 100}%`, top: `${el.y * 100}%`, width: `${el.width * 100}%`, height: `${el.height * 100}%` }}
              onMouseDown={(e) => {
                setSelectedId(el.id);
                startElementDrag(pageRef, el, "move", e);
              }}
              onClick={(e) => e.stopPropagation()}
              onDoubleClick={(e) => {
                e.stopPropagation();
                openTextDraftForEdit(el);
              }}
            >
              <p
                style={{
                  fontFamily: newTextFontFamilyCss(el.family),
                  fontWeight: el.bold ? "bold" : "normal",
                  fontStyle: el.italic ? "italic" : "normal",
                  textDecoration: el.underline ? "underline" : "none",
                  color: el.color,
                  fontSize: `${el.size}px`,
                  textAlign: el.align,
                }}
              >
                {el.text}
              </p>
              <div
                className="edit-pdf-canvas__new-text-el-handle"
                onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: false })}
              />
              <button
                type="button"
                className="edit-pdf-canvas__box-remove"
                onMouseDown={(e) => e.stopPropagation()}
                onClick={() => removeElement(el.id)}
                aria-label="Remove this text box"
              >
                <X size={12} weight="bold" />
              </button>
            </div>
          ))}

        {textDraft && textDraft.page === pageNumber && (
          <div
            className="edit-pdf-canvas__new-text-editor"
            style={{ left: `${textDraft.x * 100}%`, top: `${textDraft.y * 100}%`, width: `${textDraft.width * 100}%`, height: `${textDraft.height * 100}%` }}
            onMouseDown={(e) => e.stopPropagation()}
            onBlur={handleTextDraftBlur}
          >
            <textarea
              ref={textDraftAreaRef}
              className="edit-pdf-canvas__new-text-textarea"
              value={textDraft.text}
              onChange={(e) => setTextDraft((d) => ({ ...d, text: e.target.value }))}
              onKeyDown={handleTextDraftKeyDown}
              style={{
                fontFamily: newTextFontFamilyCss(textDraft.family),
                fontWeight: textDraft.bold ? "bold" : "normal",
                fontStyle: textDraft.italic ? "italic" : "normal",
                textDecoration: textDraft.underline ? "underline" : "none",
                color: textDraft.color,
                fontSize: `${textDraft.size}px`,
                textAlign: textDraft.align,
              }}
            />
            <div className="edit-pdf-canvas__new-text-style-bar">
              <select
                value={textDraft.family}
                onChange={(e) => setTextDraft((d) => ({ ...d, family: e.target.value }))}
              >
                {FAMILY_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              <input
                type="number"
                min={1}
                value={textDraft.size}
                onChange={(e) => setTextDraft((d) => ({ ...d, size: Number(e.target.value) }))}
              />
              <button
                type="button"
                className={textDraft.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, bold: !d.bold }))}
                aria-label="Bold"
              >
                <TextB size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, italic: !d.italic }))}
                aria-label="Italic"
              >
                <TextItalic size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.underline ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, underline: !d.underline }))}
                aria-label="Underline"
              >
                <TextAUnderline size={14} weight="bold" />
              </button>
              {MARKUP_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  className={c === textDraft.color ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
                  style={{ background: c }}
                  onClick={() => setTextDraft((d) => ({ ...d, color: c }))}
                  aria-label={`Color ${c}`}
                />
              ))}
              <button
                type="button"
                className={textDraft.align === "left" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "left" }))}
                aria-label="Align left"
              >
                <TextAlignLeft size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.align === "center" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "center" }))}
                aria-label="Align center"
              >
                <TextAlignCenter size={14} weight="bold" />
              </button>
              <button
                type="button"
                className={textDraft.align === "right" ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                onClick={() => setTextDraft((d) => ({ ...d, align: "right" }))}
                aria-label="Align right"
              >
                <TextAlignRight size={14} weight="bold" />
              </button>
            </div>
          </div>
        )}

        {activeMode === "text" &&
          runs
            .filter((r) => r.page === pageNumber)
            .map((run) => {
              const pending = pendingTextEditFor(run);
              return (
                <div
                  key={run.index}
                  className={pending ? "edit-pdf-canvas__run edit-pdf-canvas__run--queued" : "edit-pdf-canvas__run"}
                  style={{
                    left: `${run.bbox.left * 100}%`,
                    top: `${run.bbox.top * 100}%`,
                    width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
                    height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
                  }}
                  onClick={() => openRunEditor(pageNumber, run)}
                />
              );
            })}
      </div>
    );
  }

  return (
    <div className="edit-pdf-canvas">
      <div className="edit-pdf-canvas__modes">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            className={activeMode === mode.id ? "edit-pdf-canvas__mode-button edit-pdf-canvas__mode-button--active" : "edit-pdf-canvas__mode-button"}
            onClick={() => setActiveMode(mode.id)}
          >
            <mode.icon size={16} weight="regular" />
            {mode.label}
          </button>
        ))}
      </div>

      <div className="edit-pdf-canvas__history-bar">
        <button type="button" onClick={undo} disabled={historyRef.current.undoStack.length === 0}>
          <ArrowUUpLeft size={16} weight="regular" />
          Undo
        </button>
        <button type="button" onClick={redo} disabled={historyRef.current.redoStack.length === 0}>
          <ArrowUUpRight size={16} weight="regular" />
          Redo
        </button>
      </div>

      {activeMode === "draw" && (
        <div className="edit-pdf-canvas__style-bar">
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.color === c : c === drawColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle({ color: c })) setDrawColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
          {Object.keys(STROKE_WIDTHS).map((w) => (
            <button
              key={w}
              type="button"
              className={
                (selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.width === STROKE_WIDTHS[w] : w === drawWidth)
                  ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active"
                  : "edit-pdf-canvas__width-button"
              }
              onClick={() => {
                if (!updateSelectedElementStyle({ width: STROKE_WIDTHS[w] })) setDrawWidth(w);
              }}
            >
              {w}
            </button>
          ))}
        </div>
      )}

      {activeMode === "shapes" && (
        <div className="edit-pdf-canvas__style-bar">
          {["rectangle", "ellipse", "line", "arrow"].map((s) => (
            <button
              key={s}
              type="button"
              className={s === shapeType ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
              onClick={() => setShapeType(s)}
            >
              {s}
            </button>
          ))}
          {MARKUP_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "shape" ? selectedElementForStyle.color === c : c === shapeColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle({ color: c })) setShapeColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
          {Object.keys(STROKE_WIDTHS).map((w) => (
            <button
              key={w}
              type="button"
              className={
                (selectedElementForStyle?.type === "shape" ? selectedElementForStyle.width === STROKE_WIDTHS[w] : w === shapeWidth)
                  ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active"
                  : "edit-pdf-canvas__width-button"
              }
              onClick={() => {
                if (!updateSelectedElementStyle({ width: STROKE_WIDTHS[w] })) setShapeWidth(w);
              }}
            >
              {w}
            </button>
          ))}
          {(shapeType === "rectangle" || shapeType === "ellipse") && (
            <label className="field field--checkbox">
              <input
                type="checkbox"
                checked={selectedElementForStyle?.type === "shape" ? selectedElementForStyle.filled : shapeFilled}
                onChange={(e) => {
                  if (!updateSelectedElementStyle({ filled: e.target.checked })) setShapeFilled(e.target.checked);
                }}
              />
              Fill
            </label>
          )}
        </div>
      )}

      {activeMode === "highlight" && (
        <div className="edit-pdf-canvas__style-bar">
          {["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"].map((c) => (
            <button
              key={c}
              type="button"
              className={
                (selectedElementForStyle?.type === "highlight" ? selectedElementForStyle.color === c : c === highlightColor)
                  ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active"
                  : "edit-pdf-canvas__color-swatch"
              }
              style={{ background: c }}
              onClick={() => {
                if (!updateSelectedElementStyle({ color: c })) setHighlightColor(c);
              }}
              aria-label={`Color ${c}`}
            />
          ))}
        </div>
      )}

      <PageScrollViewer fileId={fileId} pageCount={pageCount} className="edit-pdf-canvas__viewer" renderPageOverlay={renderPageOverlay} />

      <input
        ref={imageFileInputRef}
        type="file"
        accept="image/png,image/jpeg"
        style={{ display: "none" }}
        onChange={handleImageFileSelected}
      />

      {activeMode === "text" && editingRunIndex !== null && (
        <div className="edit-pdf-canvas__run-editor">
          {(() => {
            const run = runs.find((r) => r.index === editingRunIndex && r.page === editingRunPage);
            if (!run) return null;
            const pending = pendingTextEditFor(run);
            return (
              <>
                <label className="field">
                  Replacement text
                  <input type="text" value={draftText} onChange={(e) => setDraftText(e.target.value)} />
                </label>
                <p className="edit-pdf-canvas__detected">
                  Detected: {run.font}, {run.size.toFixed(1)}pt{run.bold ? ", bold" : ""}
                  {run.italic ? ", italic" : ""}
                </p>
                <label className="field">
                  Font family override
                  <select
                    value={draftOverride.family}
                    onChange={(e) => {
                      setDraftFamilyTouched(true);
                      setDraftOverride((o) => ({ ...o, family: e.target.value }));
                    }}
                  >
                    {FAMILY_OPTIONS.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.bold} onChange={(e) => setDraftOverride((o) => ({ ...o, bold: e.target.checked }))} />
                  Bold
                </label>
                <label className="field field--checkbox">
                  <input type="checkbox" checked={draftOverride.italic} onChange={(e) => setDraftOverride((o) => ({ ...o, italic: e.target.checked }))} />
                  Italic
                </label>
                <label className="field">
                  Font size
                  <input type="number" min={1} value={draftOverride.size} onChange={(e) => setDraftOverride((o) => ({ ...o, size: Number(e.target.value) }))} />
                </label>
                <div className="edit-pdf-canvas__run-editor-actions">
                  <button type="button" onClick={() => submitRunEditor(run)}>
                    {pending ? "Update edit" : "Add edit"}
                  </button>
                  {pending && (
                    <button type="button" onClick={() => removeTextEdit(run)}>
                      Remove edit
                    </button>
                  )}
                  <button type="button" onClick={() => setEditingRunIndex(null)}>
                    Cancel
                  </button>
                </div>
              </>
            );
          })()}
        </div>
      )}
    </div>
  );
}
