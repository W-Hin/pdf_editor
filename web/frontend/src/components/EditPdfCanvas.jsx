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
  Cursor,
  Eraser,
} from "@phosphor-icons/react";
import { downloadUrl, fetchTextRuns, uploadFile } from "../api";
import {
  clampMove,
  elementBounds,
  polylineNearPoint,
  rectFromPoints,
  rectsIntersect,
  unionBounds,
} from "../editGeometry";
import PageScrollViewer, { DEFAULT_MAX_SIZE as PAGE_THUMBNAIL_MAX_SIZE } from "./PageScrollViewer";

const MODES = [
  { id: "select", label: "Select", icon: Cursor },
  { id: "text", label: "Edit Text", icon: CursorText },
  { id: "draw", label: "Draw", icon: PencilSimple },
  { id: "shapes", label: "Shapes", icon: Rectangle },
  { id: "highlight", label: "Highlight", icon: Highlighter },
  { id: "image", label: "Insert Image", icon: ImageSquare },
  { id: "new_text", label: "Add Text", icon: TextAa },
  { id: "eraser", label: "Eraser", icon: Eraser },
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

// Renders a row of preset color swatch buttons plus a native color picker
// input for anything else. The native <input type="color"> is genuinely
// free (built into every browser, zero new dependencies) and produces the
// exact #rrggbb hex format the backend already accepts with no whitelist —
// verified against app/core/pdf_ops.py's _hex_to_rgb this session.
function renderColorOptions(colors, activeColor, onPick) {
  return (
    <>
      {colors.map((c) => (
        <button
          key={c}
          type="button"
          className={c === activeColor ? "edit-pdf-canvas__color-swatch edit-pdf-canvas__color-swatch--active" : "edit-pdf-canvas__color-swatch"}
          style={{ background: c }}
          onClick={() => onPick(c)}
          aria-label={`Color ${c}`}
        />
      ))}
      <input
        type="color"
        className="edit-pdf-canvas__color-picker-input"
        value={activeColor}
        onChange={(e) => onPick(e.target.value)}
        aria-label="Custom color"
      />
    </>
  );
}

// Mirrors app/core/pdf_ops.py's _closest_base14_family exactly, so a
// freshly-opened run's default style is the closest base-14 APPROXIMATION
// of its actually-detected font (serif -> times, monospace -> courier, else
// helvetica) instead of always defaulting to helvetica regardless of the
// run's real font — see this plan's Global Constraints for why the run's
// actual embedded font itself can no longer be preserved once any edit
// exists.
function closestBase14Family(fontName) {
  const lowered = (fontName || "").toLowerCase();
  if (lowered.includes("times") || lowered.includes("serif") || lowered.includes("georgia")) return "times";
  if (lowered.includes("courier") || lowered.includes("mono") || lowered.includes("consolas")) return "courier";
  return "helvetica";
}

// Rough width-per-character estimate for the three base-14 families this
// tool supports, used only to enforce a REASONABLE minimum box size client-
// side — the backend's own _wrap_text_lines (using the real font metrics)
// is still what actually determines final layout at Run time. This doesn't
// need to be exact, just conservative enough that the box the user is
// allowed to shrink to always fits what they typed.
const AVG_CHAR_WIDTH_FACTOR = { helvetica: 0.55, times: 0.5, courier: 0.6 };

// A reference page long-edge (in PDF points) used ONLY to convert the pixel
// estimate above into a page fraction. The frontend has no way to learn a
// PDF's actual point dimensions (the backend never sends them — thumbnails
// are rasterized to fit PAGE_THUMBNAIL_MAX_SIZE px and nothing else is
// exposed), so converting a points-based estimate straight through the
// on-screen CSS-rendered page rect is wrong on two counts: (1) that rect's
// size tracks the browser window/layout, not the PDF, so the floor would
// silently vary with window width; (2) for a typical Letter/A4 page — whose
// point dimensions (~595-842pt) are much smaller than the ~1800px thumbnail
// they're rasterized to — dividing by the CSS rect instead of the true point
// size undershoots the real minimum by roughly 2x, verified empirically to
// be enough to drop an entire line of text from the exported PDF. Anchoring
// to the thumbnail's own natural pixel size (fixed by the backend, immune to
// CSS layout) and US Letter's 792pt long edge — the smaller of the two
// common page standards, so this stays conservative for A4 too — fixes both
// problems for the overwhelming majority of real documents; it's still an
// approximation for unusually large/small custom page sizes, but a
// conservative one (see estimateMinTextBoxFraction below).
const TYPICAL_PAGE_LONG_EDGE_PT = 792;

function estimateMinTextBoxSize(text, family, size) {
  const charWidth = size * (AVG_CHAR_WIDTH_FACTOR[family] ?? 0.55);
  const lines = text.split("\n").flatMap((paragraph) => {
    const words = paragraph.split(" ");
    // Longest single word sets the minimum WIDTH (a box narrower than its
    // longest word can't usefully wrap at all); count of words roughly
    // approximates how many lines a very narrow box would need.
    return words;
  });
  const longestWordChars = Math.max(1, ...lines.map((w) => w.length));
  const minWidthPx = longestWordChars * charWidth;
  const lineHeight = size * 1.2;
  const paragraphCount = text.split("\n").length;
  const minHeightPx = Math.max(lineHeight, paragraphCount * lineHeight);
  return { minWidthPx, minHeightPx };
}

// Converts estimateMinTextBoxSize's points-based estimate into a page
// fraction via the page thumbnail's own natural (raster) pixel size, which —
// unlike the CSS-rendered page rect — is fixed by the backend independent of
// browser window width and was itself derived from the real page dimensions
// (scaled so the longer edge is PAGE_THUMBNAIL_MAX_SIZE px). See
// TYPICAL_PAGE_LONG_EDGE_PT above for why a reference point size is needed
// and why it's biased conservative. Returns null if the thumbnail image
// isn't available/loaded yet, so callers can fall back to a fixed floor.
function estimateMinTextBoxFraction(text, family, size, pageImg) {
  if (!pageImg || !pageImg.naturalWidth || !pageImg.naturalHeight) return null;
  const { minWidthPx, minHeightPx } = estimateMinTextBoxSize(text, family, size);
  const pxPerPoint = PAGE_THUMBNAIL_MAX_SIZE / TYPICAL_PAGE_LONG_EDGE_PT;
  return {
    minWidthFraction: (minWidthPx * pxPerPoint) / pageImg.naturalWidth,
    minHeightFraction: (minHeightPx * pxPerPoint) / pageImg.naturalHeight,
  };
}

function segmentsEqualStyle(a, b) {
  return a.family === b.family && a.bold === b.bold && a.italic === b.italic && a.size === b.size;
}

// Merges adjacent segments that ended up with identical style after a split
// — keeps the list from growing unboundedly across repeated restyles of
// overlapping ranges (e.g. styling the same word bold twice in a row should
// not leave two separate bold segments sitting next to each other).
function mergeAdjacentSegments(segments) {
  const merged = [];
  for (const seg of segments) {
    const last = merged[merged.length - 1];
    if (last && segmentsEqualStyle(last, seg)) {
      last.text += seg.text;
    } else {
      merged.push({ ...seg });
    }
  }
  return merged;
}

// Splits whichever segment(s) the [start, end) character range (0-indexed,
// into the CONCATENATED text of all segments in order) overlaps, at the
// exact character boundary, and applies `patch` (e.g. {bold: true}) only to
// the newly-split piece(s) covering the selected text. Every segment fully
// outside the range is returned unchanged.
function splitAndRestyleSegments(segments, start, end, patch) {
  const result = [];
  let offset = 0;
  for (const seg of segments) {
    const segStart = offset;
    const segEnd = offset + seg.text.length;
    offset = segEnd;
    const overlapStart = Math.max(start, segStart);
    const overlapEnd = Math.min(end, segEnd);
    if (overlapStart >= overlapEnd) {
      result.push(seg);
      continue;
    }
    const beforeText = seg.text.slice(0, overlapStart - segStart);
    const insideText = seg.text.slice(overlapStart - segStart, overlapEnd - segStart);
    const afterText = seg.text.slice(overlapEnd - segStart);
    if (beforeText) result.push({ ...seg, text: beforeText });
    result.push({ ...seg, ...patch, text: insideText });
    if (afterText) result.push({ ...seg, text: afterText });
  }
  return mergeAdjacentSegments(result);
}

// The style to pre-fill the popover's controls with: the FIRST segment the
// selection overlaps. If the selection spans multiple differently-styled
// segments, this is a reasonable single representative rather than an
// attempt to show a "mixed" state — consistent with this file's existing
// "first segment wins" default pattern (see openRunEditor's family default).
function segmentStyleForRange(segments, selection) {
  let offset = 0;
  for (const seg of segments) {
    const segEnd = offset + seg.text.length;
    if (selection.start < segEnd && selection.end > offset) {
      return { family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size };
    }
    offset = segEnd;
  }
  return { family: "helvetica", bold: false, italic: false, size: 14 };
}

// Collapses a multi-segment styled line back into ONE segment for phase
// "type" — concatenates every segment's TEXT (so no characters are lost),
// using the FIRST segment's style as phase "type"'s single style. This is
// a deliberate, spec-consistent trade-off: phase "type" is a single-style
// input by design, so re-entering it to retype necessarily discards any
// partial styling that existed before — you can't "type into" a
// multi-styled line while preserving per-character styles without
// reintroducing the hard live-sync problem this two-phase design exists
// to avoid.
function flattenSegmentsForTyping(segments) {
  const text = segments.map((s) => s.text).join("");
  const first = segments[0];
  return { text, family: first.family, bold: first.bold, italic: first.italic, size: first.size };
}

const MARKUP_COLORS = ["#1f2937", "#e03131", "#f08c00", "#2f9e44", "#1971c2", "#9c36b5", "#ffffff"];
const STROKE_WIDTHS = { thin: 1, medium: 3, thick: 6 };

// Smallest drag (as a fraction of the page) that counts as a real gesture
// rather than a click with a pixel of jitter. Used by shapes/highlight so a
// stray click never commits a degenerate element the backend then rejects.
// Draw is exempt: even a click makes a dot.
const MIN_DRAG_FRACTION = 0.02;

// Freehand highlighter: a translucent, wide, round-capped stroke.
const MARKER_COLORS = ["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"];
const MARKER_WIDTHS = { thin: 8, medium: 14, thick: 24 };
const MARKER_OPACITY = 0.4;

// How close (in screen pixels, beyond the line's own half-width) the eraser
// has to pass to a stroke to erase it.
const ERASER_RADIUS_PX = 8;

// A marquee smaller than this (as a page fraction) is a click, not a drag.
const MIN_MARQUEE_FRACTION = 0.005;

// Nudge step sizes, as fractions of the page (element coordinates are
// stored as 0-1 fractions, not pixel counts). Reasoned against
// pasteClipboard's own OFFSET = 0.03 (a one-time diagonal "paste nearby"
// jump) as a reference point: on a typical on-screen render of a US Letter
// page (612x792pt, commonly rendered somewhere around 600-900px tall),
// 0.004 works out to roughly 3-4px per keypress (a precise, perceptible
// nudge, not a sub-pixel no-op), and 0.02 works out to roughly 16px (a
// clear, deliberate move, slightly more conservative than paste's one-time
// offset since nudge is meant to feel incremental and repeatable).
const NUDGE_SMALL_STEP = 0.004;
const NUDGE_BIG_STEP = 0.02;

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
  const [pageRotations, setPageRotations] = useState({}); // { [pageNumber]: rotationDegrees }
  // Null when no run is being edited. { page, runIndex, phase: "type" |
  // "style", segments: [{text, family, bold, italic, size}, ...], selection:
  // {start, end} | null } while the inline editor is open — mirrors
  // textDraft's null-object pattern below. This task only ever produces
  // phase "type" with a single-element segments array; Task 3 makes phase
  // "style" and multi-element segments reachable.
  const [runEditor, setRunEditor] = useState(null);
  const runEditorInputRef = useRef(null);
  // Wraps phase-"style"'s inline editor (renderRunStyleOverlay). Used by the
  // outside-click effect below instead of onBlur — see that effect's comment
  // for why blur's relatedTarget is unreliable here.
  const runStyleWrapperRef = useRef(null);
  const [drawColor, setDrawColor] = useState(MARKUP_COLORS[0]);
  const [drawWidth, setDrawWidth] = useState("medium");
  const [activeStroke, setActiveStroke] = useState(null); // { page, points } | null
  const [drawTool, setDrawTool] = useState("pen"); // "pen" | "marker"
  const [markerColor, setMarkerColor] = useState(MARKER_COLORS[0]);
  const [markerWidth, setMarkerWidth] = useState("medium");
  const [pageSizes, setPageSizes] = useState({}); // { [pageNumber]: { w, h } } in PDF points
  const [multiIds, setMultiIds] = useState([]); // ids picked by the Select marquee
  const [marquee, setMarquee] = useState(null); // { page, start, current } | null
  const [erasingIds, setErasingIds] = useState([]); // strokes swept by the eraser, not yet committed
  const erasingRef = useRef(null); // { last } while the eraser button is held
  const suppressStageClickRef = useRef(false);
  const groupDragRef = useRef(null);
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
    if (runEditor) runEditorInputRef.current?.focus();
  }, [runEditor?.page, runEditor?.runIndex, runEditor?.phase]);

  // The run-editor overlays (both phases) only render while activeMode ===
  // "text". Switching to a different mode by any means that doesn't route
  // through a mousedown on the mode button (e.g. keyboard activation via
  // Tab+Enter/Space, or a programmatic .click()) unmounts the overlay
  // without ever triggering the phase-"style" outside-click listener below,
  // which would otherwise leave runStyleWrapperRef.current null and that
  // listener permanently inert. Close any open run editor directly on the
  // mode change so it can never survive a mode switch by any trigger.
  useEffect(() => {
    if (activeMode !== "text") {
      // Phase "type" may hold text the user typed but hasn't committed yet
      // (no blur ever fired on this path — see comment above) — commit it
      // via the same path handleRunEditorBlur uses rather than discarding it
      // with a bare setRunEditor(null). Phase "style" has nothing pending
      // (every restyle already commits immediately) AND commitRunEditor
      // itself is unsafe there: it only ever writes editor.segments[0] into
      // a single-segment element, so calling it while phase "style" holds
      // multiple styled segments would silently collapse them back into one.
      if (runEditor?.phase === "type") commitRunEditor();
      else setRunEditor(null);
    }
  }, [activeMode]);

  // A selection made in one tool has no meaning in another (strokes, for one,
  // are only selectable with the Select tool), so switching tools drops it.
  useEffect(() => {
    setSelectedId(null);
    setMultiIds([]);
    setMarquee(null);
    setErasingIds([]);
    erasingRef.current = null;
  }, [activeMode]);

  // Phase-"style" close-on-outside-click. Attached only while phase ===
  // "style" (phase "type" keeps using onBlur/handleRunEditorBlur below,
  // since its only focusable children are the <input> itself and
  // preventDefault()-guarded buttons, for which blur's relatedTarget works
  // correctly). Phase "style" also renders non-focusable <span>s as its
  // styled text, and the popover's family <select>/size <input> take real
  // DOM focus by design — starting a new drag-selection on a <span> while
  // one of those holds focus fires a blur with relatedTarget: null (a
  // <span> isn't a native focus target), which is indistinguishable from a
  // genuine outside click using relatedTarget alone. A mousedown-time
  // "is this inside the wrapper" check (the standard pattern for dismissing
  // popovers with non-focusable content) sidesteps that ambiguity entirely.
  // Listens on the capture phase so it still sees the click even though the
  // wrapper's own onMouseDown calls stopPropagation() during the bubble
  // phase. Re-running this effect on every `runEditor` change (not just
  // when the phase flag flips) guarantees a fresh listener is attached
  // whenever phase "style" becomes active, and torn down the instant it
  // isn't — so this can never fire while phase is "type" or while there is
  // no editor open at all.
  useEffect(() => {
    if (runEditor?.phase !== "style") return;
    function handleDocumentMouseDown(e) {
      // A null ref means the overlay is already unmounted (e.g. activeMode
      // changed away from "text" without going through this mousedown path)
      // — treat that as definitely outside rather than silently skipping,
      // so this listener can't get stuck permanently inert.
      if (!runStyleWrapperRef.current || !runStyleWrapperRef.current.contains(e.target)) {
        setRunEditor(null);
      }
    }
    document.addEventListener("mousedown", handleDocumentMouseDown, true);
    return () => document.removeEventListener("mousedown", handleDocumentMouseDown, true);
  }, [runEditor]);

  useEffect(() => {
    if (!fileId || !pageCount) return;
    let cancelled = false;
    async function loadRuns() {
      const perPage = await Promise.all(
        Array.from({ length: pageCount }, (_, i) => i + 1).map((pageNumber) =>
          fetchTextRuns(fileId, pageNumber)
            .then((data) => ({
              page: pageNumber,
              runs: data.runs.map((r) => ({ ...r, page: pageNumber })),
              rotation: data.rotation,
              size: data.width_pt && data.height_pt ? { w: data.width_pt, h: data.height_pt } : null,
            }))
            .catch((err) => {
              console.error(`Failed to load text runs for page ${pageNumber}:`, err);
              return { page: pageNumber, runs: [], rotation: 0 };
            })
        )
      );
      if (!cancelled) {
        setRuns(perPage.flatMap((p) => p.runs));
        setPageRotations(Object.fromEntries(perPage.map((p) => [p.page, p.rotation])));
        setPageSizes(Object.fromEntries(perPage.filter((p) => p.size).map((p) => [p.page, p.size])));
      }
    }
    loadRuns();
    setRunEditor(null);
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
      if (textDraft || runEditor || isTypingTarget(document.activeElement)) return;
      const ctrl = e.ctrlKey || e.metaKey;
      if (!ctrl && multiIds.length > 0) {
        const members = elements.filter((item) => multiIds.includes(item.id));
        if (e.key === "Escape") {
          setMultiIds([]);
          return;
        }
        if (e.key === "Delete" || e.key === "Backspace") {
          e.preventDefault();
          commitElements(elements.filter((item) => !multiIds.includes(item.id)));
          setMultiIds([]);
          return;
        }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) {
          e.preventDefault();
          const step = e.shiftKey ? NUDGE_BIG_STEP : NUDGE_SMALL_STEP;
          const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
          const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
          const moved = moveGroup(members, dx, dy);
          if (moved) commitElements(elements.map((item) => moved.get(item.id) ?? item));
          return;
        }
      }
      if (!ctrl) {
        if (e.key === "Escape") {
          setSelectedId(null);
        } else if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
          e.preventDefault();
          removeElement(selectedId);
        } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key) && selectedId) {
          const el = elements.find((item) => item.id === selectedId);
          if (el) {
            let target = el;
            if (el.type === "text_edit") {
              // A stored text_edit element never has width/height (its size
              // always comes from its own run) - moveElement's text_edit
              // branch needs those to clamp correctly, so build the same
              // dimension-carrying object renderTextEditElement's drag start
              // already builds via textEditBoxRect, instead of handing it
              // the raw stored element (which would read undefined -> NaN).
              const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
              if (!run) return; // runs haven't loaded yet - nothing to nudge against safely
              const box = textEditBoxRect(run, el, pageRotations);
              target = { ...el, x: box.left, y: box.top, width: box.width, height: box.height };
            }
            e.preventDefault();
            const step = e.shiftKey ? NUDGE_BIG_STEP : NUDGE_SMALL_STEP;
            let dx = 0;
            let dy = 0;
            if (e.key === "ArrowLeft") dx = -step;
            else if (e.key === "ArrowRight") dx = step;
            else if (e.key === "ArrowUp") dy = -step;
            else dy = step;
            const moved = moveElement(target, dx, dy);
            commitElements(elements.map((item) => (item.id === selectedId ? moved : item)));
          }
        }
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
  }, [elements, selectedId, multiIds, textDraft, runEditor, runs, pageRotations]);

  if (!fileId || !pageCount) return null;

  function commitElements(next) {
    historyRef.current = { undoStack: [...historyRef.current.undoStack, elements], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    setElements(next);
    onChange(next);
  }

  function updateSelectedElementStyle(type, patch) {
    if (!selectedId) return false; // nothing selected — caller should fall back to its default-setting behavior
    const el = elements.find((e) => e.id === selectedId);
    if (!el || el.type !== type) return false; // a different-type element is selected — don't corrupt its fields
    commitElements(elements.map((e) => (e.id === selectedId ? { ...e, ...patch } : e)));
    return true;
  }

  // Z-order is simply the selected element's position within `elements` — the
  // backend applies `other_elements` in array order, and the interleaved
  // renderer below paints elements in that same order, so moving an element's
  // index here is the entire implementation of front/back/forward/backward.
  function reorderSelected(direction) {
    if (!selectedId) return;
    const index = elements.findIndex((e) => e.id === selectedId);
    if (index === -1) return;
    const el = elements[index];

    if (direction === "front" || direction === "back") {
      // Front/back apply relative to array-order painting globally, so no
      // same-page skipping is needed here.
      const next = [...elements];
      next.splice(index, 1);
      if (direction === "front") next.push(el);
      else next.unshift(el);
      commitElements(next);
      return;
    }

    if (direction !== "forward" && direction !== "backward") return;

    // `elements` is a single global array spanning every page, and
    // renderPageOverlay only paints elements where el.page === pageNumber
    // (a text_edit element is excluded only while its own editor is
    // actively open). A plain one-slot array swap can land on an array
    // neighbor that isn't actually adjacent in what's rendered on any page
    // (e.g. a different page's element), producing no visible change. So
    // instead, find the nearest neighbor in that direction that WOULD
    // render adjacent to this element on its own page, and move past that
    // one instead.
    const step = direction === "forward" ? 1 : -1;
    let targetIndex = -1;
    for (let i = index + step; i >= 0 && i < elements.length; i += step) {
      if (elements[i].page === el.page) {
        targetIndex = i;
        break;
      }
    }
    if (targetIndex === -1) return; // already frontmost/backmost among this page's visible elements — no-op

    // Removing el at `index` first, then (re-)inserting at `targetIndex`,
    // lands el on the correct side of its same-page neighbor in both
    // directions: forward's targetIndex was found after index, so removing
    // el shifts the neighbor back by one first — inserting at targetIndex
    // then places el immediately after the neighbor's new position.
    // Backward's targetIndex was found before index, so removing el doesn't
    // shift the neighbor at all — inserting at targetIndex places el
    // immediately before it, unchanged.
    const next = [...elements];
    next.splice(index, 1);
    next.splice(targetIndex, 0, el);
    commitElements(next);
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
    // A marquee drag ends in a click on the stage; it must not undo the
    // selection that drag just made.
    if (suppressStageClickRef.current) {
      suppressStageClickRef.current = false;
      return;
    }
    // Spec: clicking empty canvas deselects. Clicks that landed on an element
    // stop propagating before they reach here.
    setSelectedId(null);
    setMultiIds([]);
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
    // leaving a stroke armed makes a line follow the cursor and commit a
    // phantom stroke on the next mouseup/mouseleave.
    const stroke = activeStroke;
    setActiveStroke(null);
    // Any press-and-release makes a mark, however short: a lone point is a dot.
    if (!stroke || stroke.points.length < 1) return;
    const marker = drawTool === "marker";
    commitElements([
      ...elements,
      {
        id: newElementId(),
        type: "stroke",
        page: stroke.page,
        points: stroke.points,
        color: marker ? markerColor : drawColor,
        width: marker ? MARKER_WIDTHS[markerWidth] : STROKE_WIDTHS[drawWidth],
        ...(marker ? { opacity: MARKER_OPACITY } : {}),
      },
    ]);
  }

  // On-screen thickness (CSS px) of a stroke. Pen widths keep their long-
  // standing rough scale; the marker is drawn to true page scale so the
  // translucent band covers the same area on screen as in the export.
  function strokeScreenWidth(width, opacity, page, pageRef) {
    const size = pageSizes[page];
    const cssWidth = pageRef?.current?.getBoundingClientRect().width;
    if (opacity != null && size?.w && cssWidth) return (width * cssWidth) / size.w;
    return width / 3;
  }

  function eraseAt(pageNumber, pageRef, e) {
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    const rect = pageRef.current.getBoundingClientRect();
    // A fast drag delivers sparse mouse events, so test the whole segment
    // since the last event, not just its endpoint, or the eraser would skip
    // over thin lines.
    const from = erasingRef.current?.last ?? point;
    erasingRef.current = { last: point };
    const lengthPx = Math.hypot((point.x - from.x) * rect.width, (point.y - from.y) * rect.height);
    const steps = Math.max(1, Math.ceil(lengthPx / 4));
    const samples = Array.from({ length: steps + 1 }, (_, i) => ({
      x: from.x + ((point.x - from.x) * i) / steps,
      y: from.y + ((point.y - from.y) * i) / steps,
    }));
    const hits = elements
      .filter((el) => el.type === "stroke" && el.page === pageNumber && !erasingIds.includes(el.id))
      .filter((el) => {
        const radius = ERASER_RADIUS_PX + strokeScreenWidth(el.width, el.opacity, el.page, pageRef) / 2;
        return samples.some((sample) => polylineNearPoint(el.points, sample, radius, rect.width, rect.height));
      })
      .map((el) => el.id);
    if (hits.length > 0) setErasingIds((prev) => [...new Set([...prev, ...hits])]);
  }

  function handleEraserMouseDown(pageNumber, pageRef, e) {
    erasingRef.current = { last: null };
    eraseAt(pageNumber, pageRef, e);
  }

  function handleEraserMouseMove(pageNumber, pageRef, e) {
    if (erasingRef.current) eraseAt(pageNumber, pageRef, e);
  }

  function handleEraserMouseUp() {
    if (!erasingRef.current) return;
    erasingRef.current = null;
    // One history entry per sweep, so a single Undo restores everything.
    if (erasingIds.length > 0) commitElements(elements.filter((el) => !erasingIds.includes(el.id)));
    setErasingIds([]);
  }

  // The box a member occupies for selection and group moves, or null when it
  // can't be measured yet (a text edit whose run hasn't loaded).
  function boundsOf(el) {
    if (el.type === "text_edit") {
      const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
      return run ? elementBounds(el, textEditBoxRect(run, el, pageRotations)) : null;
    }
    return elementBounds(el);
  }

  // moveElement needs a text_edit's box size, which is never stored on it.
  function moveTargetFor(el) {
    if (el.type !== "text_edit") return el;
    const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
    if (!run) return null;
    const box = textEditBoxRect(run, el, pageRotations);
    return { ...el, x: box.left, y: box.top, width: box.width, height: box.height };
  }

  // Moves every member by the same (dx, dy), clamped so the group as a whole
  // stays on the page. Returns Map(id -> moved element), or null if nothing
  // is movable.
  function moveGroup(members, dx, dy) {
    const targets = members
      .map((el) => ({ el, target: moveTargetFor(el), bounds: boundsOf(el) }))
      .filter((m) => m.target && m.bounds);
    if (targets.length === 0) return null;
    const clamped = clampMove(unionBounds(targets.map((m) => m.bounds)), dx, dy);
    return new Map(targets.map((m) => [m.el.id, moveElement(m.target, clamped.dx, clamped.dy)]));
  }

  function handleSelectMouseDown(pageNumber, pageRef, e) {
    // Only empty page space starts a marquee; elements handle their own presses.
    if (e.target !== e.currentTarget) return;
    suppressStageClickRef.current = false;
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    setSelectedId(null);
    setMultiIds([]);
    setMarquee({ page: pageNumber, start: point, current: point });
  }

  function handleSelectMouseMove(pageRef, e) {
    if (!marquee) return;
    const point = pointFromEvent(pageRef, e);
    if (point) setMarquee((m) => m && { ...m, current: point });
  }

  function handleSelectMouseUp() {
    if (!marquee) return;
    const box = rectFromPoints(marquee.start, marquee.current);
    setMarquee(null);
    if (box.right - box.left < MIN_MARQUEE_FRACTION && box.bottom - box.top < MIN_MARQUEE_FRACTION) return;
    const picked = elements
      .filter((el) => {
        if (el.page !== marquee.page) return false;
        const bounds = boundsOf(el);
        return bounds && rectsIntersect(bounds, box);
      })
      .map((el) => el.id);
    setMultiIds(picked);
    suppressStageClickRef.current = true;
  }

  function startGroupDrag(pageRef, e) {
    e.stopPropagation();
    const point = pointFromEvent(pageRef, e);
    if (!point) return;
    groupDragRef.current = {
      start: point,
      pageRef,
      members: elements.filter((el) => multiIds.includes(el.id)),
      snapshot: elements,
      result: null,
    };
    window.addEventListener("mousemove", handleGroupDragMove);
    window.addEventListener("mouseup", handleGroupDragEnd);
    window.addEventListener("blur", handleGroupDragEnd);
  }

  function handleGroupDragMove(e) {
    const drag = groupDragRef.current;
    if (!drag) return;
    const point = pointFromEvent(drag.pageRef, e);
    if (!point) return;
    const moved = moveGroup(drag.members, point.x - drag.start.x, point.y - drag.start.y);
    if (!moved) return;
    drag.result = moved;
    setElements(drag.snapshot.map((el) => moved.get(el.id) ?? el));
  }

  function handleGroupDragEnd() {
    window.removeEventListener("mousemove", handleGroupDragMove);
    window.removeEventListener("mouseup", handleGroupDragEnd);
    window.removeEventListener("blur", handleGroupDragEnd);
    const drag = groupDragRef.current;
    groupDragRef.current = null;
    if (!drag?.result) return;
    historyRef.current = { undoStack: [...historyRef.current.undoStack, drag.snapshot], redoStack: [] };
    setHistoryVersion((v) => v + 1);
    onChange(drag.snapshot.map((el) => drag.result.get(el.id) ?? el));
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
    const rect = pageRef.current?.getBoundingClientRect();
    const pageAspect = rect && rect.width ? rect.height / rect.width : 1; // fallback: assume square if unmeasurable
    pendingImageDropRef.current = { page: pageNumber, point, pageAspect };
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
    const drop = pendingImageDropRef.current ?? { page: 1, point: { x: 0.375, y: 0.375 }, pageAspect: 1 };
    const [uploaded, naturalSize] = await Promise.all([uploadFile(file), loadImageNaturalSize(file)]);
    const width = 0.25;
    // The image's own pixel aspect ratio, converted into a HEIGHT FRACTION
    // OF THE PAGE, must account for the page's own (non-square) aspect
    // ratio — dividing by pageAspect (the rendered page container's actual
    // height/width ratio) converts "fraction of page width" into "fraction
    // of page height" correctly, instead of assuming they're the same unit.
    const height = Math.min(0.9, (width * (naturalSize.height / naturalSize.width)) / drop.pageAspect);
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
      let minWidth = 0.05;
      let minHeight = 0.03;
      if (startElement.type === "new_text") {
        // Convert the estimated pixel minimums into page fractions via the
        // thumbnail's natural (raster) size — see estimateMinTextBoxFraction
        // for why that, not this drag's on-screen CSS rect, is the right
        // denominator: the CSS rect scales with the browser window, while
        // the thumbnail's raster size is fixed by the backend and actually
        // tracks the PDF's own point dimensions.
        const pageImg = drag.pageRef.current?.querySelector("img");
        const estimate = estimateMinTextBoxFraction(startElement.text, startElement.family, startElement.size, pageImg);
        if (estimate) {
          minWidth = Math.max(0.05, estimate.minWidthFraction);
          minHeight = Math.max(0.03, estimate.minHeightFraction);
        }
      }
      const width = Math.min(Math.max(minWidth, startElement.width + dx), 1 - startElement.x);
      const height = Math.min(Math.max(minHeight, startElement.height + dy), 1 - startElement.y);
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
    if (el.type === "text_edit") {
      // Reconstructed explicitly (not `{ ...el, x, y }`) so the width/height
      // this function needs for clamping — merged onto `el` only for the
      // duration of the drag by renderTextEditElement below — never leaks
      // into the stored element. A text_edit element's size always comes
      // from its own run, never from anything persisted on the element.
      const x = Math.min(Math.max(el.x + dx, 0), 1 - el.width);
      const y = Math.min(Math.max(el.y + dy, 0), 1 - el.height);
      return { id: el.id, type: el.type, page: el.page, run_index: el.run_index, segments: el.segments, x, y };
    }
    // x/y/width/height (image, new_text) — text_edit has its own branch above
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
    if (activeMode === "select") return handleSelectMouseDown(pageNumber, pageRef, e);
    if (activeMode === "eraser") return handleEraserMouseDown(pageNumber, pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseDown(pageNumber, pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseDown(pageNumber, pageRef, e);
    if (activeMode === "image") return handleImageStageClick(pageNumber, pageRef, e);
    if (activeMode === "new_text") return handleNewTextStageClick(pageNumber, pageRef, e);
  }

  function handleStageMouseMove(pageNumber, pageRef, e) {
    if (activeMode === "draw") return handleDrawMouseMove(pageRef, e);
    if (activeMode === "select") return handleSelectMouseMove(pageRef, e);
    if (activeMode === "eraser") return handleEraserMouseMove(pageNumber, pageRef, e);
    if (activeMode === "shapes") return handleShapeMouseMove(pageRef, e);
    if (activeMode === "highlight") return handleHighlightMouseMove(pageRef, e);
  }

  function handleStageMouseUp(e) {
    if (activeMode === "draw") return handleDrawMouseUp(e);
    if (activeMode === "select") return handleSelectMouseUp();
    if (activeMode === "eraser") return handleEraserMouseUp();
    if (activeMode === "shapes") return handleShapeMouseUp(e);
    if (activeMode === "highlight") return handleHighlightMouseUp(e);
  }

  // The box a text_edit element (or its live editor overlay) occupies: the
  // original run's own detected size always (per this feature's "move only,
  // never resize" scope decision), positioned at the element's moved x/y
  // once it has one, falling back to the run's own top-left when it hasn't
  // been moved yet (or no pending edit exists at all).
  //
  // On a 90/270-rotated page, once actually moved, width/height are
  // transposed: the backend draws the replacement with rotate=page.rotation
  // once an override is active (_apply_text_edit's override_xy branch) so it
  // reads upright to the viewer, which transposes its actual extent relative
  // to the ORIGINAL run's own (possibly sideways) orientation. Swapping here
  // keeps the box's on-screen shape matching what will actually export —
  // but only once moved, since an un-moved element still draws (and must
  // still be shown) in the original run's own unrotated orientation.
  //
  // Known, accepted limitation: this swap is keyed off the CURRENT pending
  // element's x/y, so it only takes effect starting from the render right
  // after a move commits. A drag gesture's own clamp bound (moveElement, via
  // the `positioned` snapshot captured once at drag-start) is computed
  // against PRE-swap dimensions for an element's very FIRST-ever move — so
  // dropping it very close to a page edge on that first drag can show a
  // small overflow past that edge. Dragging it again uses the now-current
  // (already-swapped) dimensions and is correctly bounded. Deliberately not
  // closed: doing so would mean reconciling two different clamp bases
  // mid-gesture, real complexity for a cosmetic, self-fixing edge case.
  function textEditBoxRect(run, pending, pageRotations) {
    let width = 1 - run.bbox.left - run.bbox.right;
    let height = 1 - run.bbox.top - run.bbox.bottom;
    const moved = pending?.x !== undefined && pending?.y !== undefined;
    const rotation = pageRotations[run.page] ?? 0;
    if (moved && (rotation === 90 || rotation === 270)) {
      [width, height] = [height, width];
    }
    const left = pending?.x ?? run.bbox.left;
    const top = pending?.y ?? run.bbox.top;
    return { left, top, width, height };
  }

  function pendingTextEditFor(run) {
    return elements.find((el) => el.type === "text_edit" && el.page === run.page && el.run_index === run.index);
  }

  function openRunEditor(pageNumber, run) {
    const pending = pendingTextEditFor(run);
    // No pending edit: nothing to style yet, open straight into typing.
    // A pending edit already exists: open into the styling view instead
    // (Task 3) — reopening an already-committed run is normally to review
    // or restyle it, not retype it from scratch. "Edit text" (Task 3) is
    // the explicit way back into phase "type" from there.
    const segments = pending
      ? pending.segments
      : [{ text: run.text, family: closestBase14Family(run.font), bold: run.bold, italic: run.italic, size: run.size }];
    setRunEditor({
      page: pageNumber,
      runIndex: run.index,
      phase: pending ? "style" : "type",
      segments,
      selection: null,
    });
  }

  // Only ever called while phase === "type" (see handleRunEditorBlur) — in
  // phase "style", every restyle action already commits immediately
  // (Task 3's applySelectionStyle), so there is nothing left to commit on
  // blur there.
  function commitRunEditor() {
    const editor = runEditor;
    setRunEditor(null);
    if (!editor) return;
    const run = runs.find((r) => r.index === editor.runIndex && r.page === editor.page);
    if (!run) return;
    const pending = pendingTextEditFor(run);
    const seg = editor.segments[0];
    const isDefaultStyle =
      seg.family === closestBase14Family(run.font) && seg.bold === run.bold && seg.italic === run.italic && seg.size === run.size;
    const textChanged = seg.text !== run.text;
    // Nothing pending and nothing changed from the run's own detected
    // text/default style — the user opened the editor and closed it without
    // editing anything. Skip queuing a no-op text_edit so merely looking at
    // a run doesn't clutter `elements`/undo history. An empty text IS a
    // real change whenever the run originally had text (textChanged catches
    // this), and is deliberately committed as an erase per this
    // sub-project's design — never treated as "nothing to do".
    if (!pending && !textChanged && isDefaultStyle) return;
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: editor.page,
      run_index: editor.runIndex,
      segments: [{ text: seg.text, family: seg.family, bold: seg.bold, italic: seg.italic, size: seg.size }],
      x: pending?.x,
      y: pending?.y,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  function revertRunEditor(run) {
    const pending = pendingTextEditFor(run);
    if (pending) commitElements(elements.filter((el) => el.id !== pending.id));
    // Reset the still-open editor back to phase "type" showing the run's own
    // detected text/font — nothing styled remains once reverted, so there is
    // nothing left to show in phase "style".
    setRunEditor((e) => ({
      ...e,
      phase: "type",
      segments: [{ text: run.text, family: closestBase14Family(run.font), bold: run.bold, italic: run.italic, size: run.size }],
      selection: null,
    }));
  }

  // Only ever wired to phase "type"'s wrapper (renderRunEditorOverlay) —
  // phase "style" closes via the document-mousedown outside-click effect
  // above instead (see that effect's comment for why blur's relatedTarget
  // is unreliable for phase "style"'s non-focusable spans). The phase guard
  // below is a defensive no-op should this ever be wired elsewhere.
  function handleRunEditorBlur(e) {
    if (runEditor?.phase !== "type") return;
    if (!e.currentTarget.contains(e.relatedTarget)) {
      commitRunEditor();
    }
  }

  // Only ever called from the styled-text view's onMouseUp (phase "style").
  // Deliberately the ONLY place `runEditor.selection` is ever written — see
  // this plan's Global Constraints on why it must never be cleared
  // reactively by native-selection-collapse or a global selectionchange
  // listener (doing so would let the popover unmount itself mid-click on
  // its own controls, the exact bug class Sub-project 4's fix wave found).
  function handleStyleSelectionChange(run) {
    const sel = window.getSelection();
    const container = document.querySelector(`[data-run-style-text="${runEditor.page}-${run.index}"]`);
    if (!sel || sel.isCollapsed || sel.rangeCount === 0 || !container || !container.contains(sel.anchorNode) || !container.contains(sel.focusNode)) {
      setRunEditor((r) => (r ? { ...r, selection: null } : r));
      return;
    }
    const anchorSpan = sel.anchorNode.nodeType === Node.TEXT_NODE ? sel.anchorNode.parentElement : sel.anchorNode;
    const focusSpan = sel.focusNode.nodeType === Node.TEXT_NODE ? sel.focusNode.parentElement : sel.focusNode;
    const anchorGlobal = Number(anchorSpan.dataset.segStart) + sel.anchorOffset;
    const focusGlobal = Number(focusSpan.dataset.segStart) + sel.focusOffset;
    const start = Math.min(anchorGlobal, focusGlobal);
    const end = Math.max(anchorGlobal, focusGlobal);
    setRunEditor((r) => (r ? { ...r, selection: start === end ? null : { start, end } } : r));
  }

  function applySelectionStyle(run, patch) {
    if (!runEditor || !runEditor.selection) return;
    const { start, end } = runEditor.selection;
    const newSegments = splitAndRestyleSegments(runEditor.segments, start, end, patch);
    setRunEditor((r) => ({ ...r, segments: newSegments }));
    const pending = pendingTextEditFor(run);
    const newEl = {
      id: pending?.id ?? newElementId(),
      type: "text_edit",
      page: runEditor.page,
      run_index: runEditor.runIndex,
      segments: newSegments,
      x: pending?.x,
      y: pending?.y,
    };
    const next = pending ? elements.map((el) => (el.id === newEl.id ? newEl : el)) : [...elements, newEl];
    commitElements(next);
  }

  // --- Per-type element renderers -----------------------------------------
  // Each function renders exactly ONE element and is dispatched by
  // renderElement below. Strokes and shapes each get their own small
  // page-sized <svg> (instead of sharing one page-wide <svg> per type) so
  // that a single element can independently take its place in the
  // interleaved, array-order z-stack built by renderPageOverlay.

  function renderStroke(el, pageRef) {
    const xs = el.points.map((p) => p.x);
    const ys = el.points.map((p) => p.y);
    const left = Math.min(...xs);
    const top = Math.min(...ys);
    const width = Math.max(...xs) - left;
    const height = Math.max(...ys) - top;
    // Strokes are only selectable with the Select tool, so a press on one in
    // any other tool is never swallowed.
    const selectable = activeMode === "select";
    const points = el.points.length === 1 ? [el.points[0], el.points[0]] : el.points;
    const strokeClass = !selectable
      ? "edit-pdf-canvas__stroke edit-pdf-canvas__stroke--inert"
      : el.id === selectedId
        ? "edit-pdf-canvas__stroke edit-pdf-canvas__stroke--selected"
        : "edit-pdf-canvas__stroke";
    return (
      <>
        <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
          <g onClick={selectable ? (e) => selectElement(el.id, e) : undefined}>
            <polyline
              points={points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={el.color}
              strokeWidth={strokeScreenWidth(el.width, el.opacity, el.page, pageRef)}
              strokeOpacity={el.opacity ?? 1}
              strokeLinecap={el.opacity != null || el.points.length === 1 ? "round" : "butt"}
              strokeLinejoin={el.opacity != null || el.points.length === 1 ? "round" : "miter"}
              vectorEffect="non-scaling-stroke"
              className={strokeClass}
            />
          </g>
        </svg>
        {selectable && (
          <>
            <div
              className="edit-pdf-canvas__hit-overlay"
              style={{ left: `${left * 100}%`, top: `${top * 100}%`, width: `${width * 100}%`, height: `${height * 100}%` }}
              onMouseDown={(e) => {
                setMultiIds([]);
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
          </>
        )}
      </>
    );
  }

  function renderShape(el, pageRef) {
    const stroke = el.color;
    const fill = el.filled ? el.color : "none";
    const commonProps = {
      stroke,
      fill,
      strokeWidth: el.width / 3,
      vectorEffect: "non-scaling-stroke",
      className: el.id === selectedId ? "edit-pdf-canvas__shape edit-pdf-canvas__shape--selected" : "edit-pdf-canvas__shape",
    };
    let shapeContent;
    if (el.shape === "rectangle") {
      shapeContent = (
        <g onClick={(e) => selectElement(el.id, e)}>
          <rect
            {...commonProps}
            x={Math.min(el.x0, el.x1) * 100}
            y={Math.min(el.y0, el.y1) * 100}
            width={Math.abs(el.x1 - el.x0) * 100}
            height={Math.abs(el.y1 - el.y0) * 100}
          />
        </g>
      );
    } else if (el.shape === "ellipse") {
      shapeContent = (
        <g onClick={(e) => selectElement(el.id, e)}>
          <ellipse
            {...commonProps}
            cx={((el.x0 + el.x1) / 2) * 100}
            cy={((el.y0 + el.y1) / 2) * 100}
            rx={(Math.abs(el.x1 - el.x0) / 2) * 100}
            ry={(Math.abs(el.y1 - el.y0) / 2) * 100}
          />
        </g>
      );
    } else if (el.shape === "arrow") {
      const x1p = el.x0 * 100, y1p = el.y0 * 100, x2p = el.x1 * 100, y2p = el.y1 * 100;
      const angle = Math.atan2(y2p - y1p, x2p - x1p);
      const headLen = Math.max(2, el.width);
      const headAngle = (25 * Math.PI) / 180;
      const hx1 = x2p - headLen * Math.cos(angle - headAngle);
      const hy1 = y2p - headLen * Math.sin(angle - headAngle);
      const hx2 = x2p - headLen * Math.cos(angle + headAngle);
      const hy2 = y2p - headLen * Math.sin(angle + headAngle);
      shapeContent = (
        <g onClick={(e) => selectElement(el.id, e)}>
          <line {...commonProps} x1={x1p} y1={y1p} x2={x2p} y2={y2p} />
          <polygon
            points={`${hx1},${hy1} ${x2p},${y2p} ${hx2},${hy2}`}
            fill={el.color}
            stroke={el.color}
          />
        </g>
      );
    } else {
      // line renders as a plain line — the arrow branch above is what makes
      // it visually distinct from Arrow in the live preview.
      shapeContent = (
        <g onClick={(e) => selectElement(el.id, e)}>
          <line {...commonProps} x1={el.x0 * 100} y1={el.y0 * 100} x2={el.x1 * 100} y2={el.y1 * 100} />
        </g>
      );
    }
    const left = Math.min(el.x0, el.x1);
    const top = Math.min(el.y0, el.y1);
    const width = Math.abs(el.x1 - el.x0);
    const height = Math.abs(el.y1 - el.y0);
    return (
      <>
        <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
          {shapeContent}
        </svg>
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
      </>
    );
  }

  function renderHighlight(el, pageRef) {
    return (
      <div
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
    );
  }

  function renderImageElement(el, pageRef) {
    return (
      <div
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
        <img src={downloadUrl(el.file_id)} alt="" className="edit-pdf-canvas__image-el-preview" draggable={false} />
        <div className="edit-pdf-canvas__image-el-handle" onMouseDown={(e) => startElementDrag(pageRef, el, "resize", e, { lockAspect: true })} />
        <div
          className="edit-pdf-canvas__image-el-handle edit-pdf-canvas__image-el-handle--width"
          onMouseDown={(e) => startElementDrag(pageRef, el, "resize-width", e)}
        />
        <div
          className="edit-pdf-canvas__image-el-handle edit-pdf-canvas__image-el-handle--height"
          onMouseDown={(e) => startElementDrag(pageRef, el, "resize-height", e)}
        />
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
    );
  }

  function renderNewTextElement(el, pageRef) {
    return (
      <div
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
    );
  }

  function renderTextEditElement(el, pageRef) {
    const run = runs.find((r) => r.page === el.page && r.index === el.run_index);
    if (!run) return null; // runs haven't loaded yet for this page
    const box = textEditBoxRect(run, el, pageRotations);
    const positioned = { ...el, x: box.left, y: box.top, width: box.width, height: box.height };
    return (
      <div
        className={
          el.id === selectedId
            ? "edit-pdf-canvas__text-edit-el edit-pdf-canvas__text-edit-el--selected"
            : "edit-pdf-canvas__text-edit-el"
        }
        style={{ left: `${box.left * 100}%`, top: `${box.top * 100}%`, width: `${box.width * 100}%`, height: `${box.height * 100}%` }}
        onMouseDown={(e) => {
          setSelectedId(el.id);
          startElementDrag(pageRef, positioned, "move", e);
        }}
        onClick={(e) => e.stopPropagation()}
        onDoubleClick={(e) => {
          e.stopPropagation();
          if (activeMode === "text") openRunEditor(el.page, run);
        }}
      >
        <div className="edit-pdf-canvas__run-style-text edit-pdf-canvas__run-style-text--static">
          {renderSegmentSpans(el.segments)}
        </div>
      </div>
    );
  }

  function renderElement(el, pageNumber, pageRef) {
    if (el.type === "stroke") return renderStroke(el, pageRef);
    if (el.type === "shape") return renderShape(el, pageRef);
    if (el.type === "highlight") return renderHighlight(el, pageRef);
    if (el.type === "image") return renderImageElement(el, pageRef);
    if (el.type === "new_text") return renderNewTextElement(el, pageRef);
    if (el.type === "text_edit") return renderTextEditElement(el, pageRef);
    return null;
  }

  function renderTextDraftEditor(pageRef) {
    return (
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
          {renderColorOptions(MARKUP_COLORS, textDraft.color, (c) => setTextDraft((d) => ({ ...d, color: c })))}
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
    );
  }

  function renderSegmentSpans(segments) {
    let offset = 0;
    return segments.map((seg, i) => {
      const start = offset;
      offset += seg.text.length;
      return (
        <span
          key={i}
          data-seg-start={start}
          style={{
            fontFamily: newTextFontFamilyCss(seg.family),
            fontWeight: seg.bold ? "bold" : "normal",
            fontStyle: seg.italic ? "italic" : "normal",
            fontSize: `${seg.size}px`,
          }}
        >
          {seg.text}
        </span>
      );
    });
  }

  function renderRunStyleOverlay(run) {
    const pending = pendingTextEditFor(run);
    const box = textEditBoxRect(run, pending, pageRotations);
    const spanEls = renderSegmentSpans(runEditor.segments);
    return (
      <div
        key={run.index}
        ref={runStyleWrapperRef}
        className="edit-pdf-canvas__run-editor-inline"
        style={{
          left: `${box.left * 100}%`,
          top: `${box.top * 100}%`,
          width: `${box.width * 100}%`,
          height: `${box.height * 100}%`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div
          className="edit-pdf-canvas__run-style-text"
          data-run-style-text={`${runEditor.page}-${run.index}`}
          onMouseUp={() => handleStyleSelectionChange(run)}
        >
          {spanEls}
        </div>
        <div className="edit-pdf-canvas__new-text-style-bar">
          <button
            type="button"
            className="edit-pdf-canvas__width-button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => setRunEditor((r) => ({ ...r, phase: "type", segments: [flattenSegmentsForTyping(r.segments)], selection: null }))}
          >
            Edit text
          </button>
          {pending && (
            <button
              type="button"
              className="edit-pdf-canvas__width-button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => revertRunEditor(run)}
            >
              Revert
            </button>
          )}
        </div>
        {runEditor.selection && renderStylePopover(run)}
      </div>
    );
  }

  function renderStylePopover(run) {
    const style = segmentStyleForRange(runEditor.segments, runEditor.selection);
    return (
      <div className="edit-pdf-canvas__style-popover">
        <select
          value={style.family}
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => applySelectionStyle(run, { family: e.target.value })}
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
          value={style.size}
          onMouseDown={(e) => e.stopPropagation()}
          onChange={(e) => applySelectionStyle(run, { size: Number(e.target.value) })}
        />
        <button
          type="button"
          className={style.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => applySelectionStyle(run, { bold: !style.bold })}
          aria-label="Bold selection"
        >
          <TextB size={14} weight="bold" />
        </button>
        <button
          type="button"
          className={style.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => applySelectionStyle(run, { italic: !style.italic })}
          aria-label="Italicize selection"
        >
          <TextItalic size={14} weight="bold" />
        </button>
      </div>
    );
  }

  function renderRunEditorOverlay(run) {
    if (runEditor.phase === "style") {
      return renderRunStyleOverlay(run); // Task 3
    }
    const box = textEditBoxRect(run, pendingTextEditFor(run), pageRotations);
    const seg = runEditor.segments[0];
    function updateSeg(patch) {
      setRunEditor((r) => ({ ...r, segments: [{ ...r.segments[0], ...patch }] }));
    }
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run-editor-inline"
        style={{
          left: `${box.left * 100}%`,
          top: `${box.top * 100}%`,
          width: `${box.width * 100}%`,
          height: `${box.height * 100}%`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onBlur={handleRunEditorBlur}
      >
        <input
          ref={runEditorInputRef}
          type="text"
          className="edit-pdf-canvas__run-editor-input"
          value={seg.text}
          onChange={(e) => updateSeg({ text: e.target.value })}
          style={{
            fontFamily: newTextFontFamilyCss(seg.family),
            fontWeight: seg.bold ? "bold" : "normal",
            fontStyle: seg.italic ? "italic" : "normal",
            fontSize: `${seg.size}px`,
          }}
        />
        <div className="edit-pdf-canvas__new-text-style-bar">
          <select value={seg.family} onChange={(e) => updateSeg({ family: e.target.value })}>
            {FAMILY_OPTIONS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <input type="number" min={1} value={seg.size} onChange={(e) => updateSeg({ size: Number(e.target.value) })} />
          <button
            type="button"
            className={seg.bold ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => updateSeg({ bold: !seg.bold })}
            aria-label="Bold"
          >
            <TextB size={14} weight="bold" />
          </button>
          <button
            type="button"
            className={seg.italic ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
            onClick={() => updateSeg({ italic: !seg.italic })}
            aria-label="Italic"
          >
            <TextItalic size={14} weight="bold" />
          </button>
          {pendingTextEditFor(run) && (
            <button
              type="button"
              className="edit-pdf-canvas__width-button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => revertRunEditor(run)}
            >
              Revert
            </button>
          )}
        </div>
      </div>
    );
  }

  function renderTextRun(run, pageNumber) {
    if (runEditor && runEditor.page === pageNumber && runEditor.runIndex === run.index) {
      return renderRunEditorOverlay(run);
    }
    if (pendingTextEditFor(run)) return null;
    return (
      <div
        key={run.index}
        className="edit-pdf-canvas__run"
        style={{
          left: `${run.bbox.left * 100}%`,
          top: `${run.bbox.top * 100}%`,
          width: `${(1 - run.bbox.left - run.bbox.right) * 100}%`,
          height: `${(1 - run.bbox.top - run.bbox.bottom) * 100}%`,
        }}
        onDoubleClick={() => openRunEditor(pageNumber, run)}
      />
    );
  }

  function renderPageOverlay(pageNumber, pageRef) {
    // Drawing and erasing must work anywhere on the page, including over
    // existing elements, so those tools make everything else click-through.
    const stageClassName = ["draw", "eraser"].includes(activeMode)
      ? "edit-pdf-canvas__stage edit-pdf-canvas__stage--passthrough edit-pdf-canvas__stage--crosshair"
      : activeMode === "select"
        ? "edit-pdf-canvas__stage edit-pdf-canvas__stage--crosshair"
        : "edit-pdf-canvas__stage";
    const multiMembers = elements.filter((el) => el.page === pageNumber && multiIds.includes(el.id) && boundsOf(el));
    const multiBoxes = multiMembers.map((el) => boundsOf(el));
    const groupBox = unionBounds(multiBoxes);
    const percentBox = (b) => ({
      left: `${b.left * 100}%`,
      top: `${b.top * 100}%`,
      width: `${(b.right - b.left) * 100}%`,
      height: `${(b.bottom - b.top) * 100}%`,
    });
    return (
      <div
        className={stageClassName}
        onMouseDown={(e) => handleStageMouseDown(pageNumber, pageRef, e)}
        onMouseMove={(e) => handleStageMouseMove(pageNumber, pageRef, e)}
        onMouseUp={handleStageMouseUp}
        onMouseLeave={handleStageMouseUp}
        onClick={handleStageClick}
      >
        {elements
          .filter((el) => {
            if (el.page !== pageNumber || el.id === textDraft?.id || erasingIds.includes(el.id)) return false;
            if (el.type === "text_edit" && runEditor && runEditor.page === el.page && runEditor.runIndex === el.run_index) {
              return false;
            }
            return true;
          })
          .map((el) => (
            <div key={el.id} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              <div style={{ pointerEvents: "auto" }}>{renderElement(el, pageNumber, pageRef)}</div>
            </div>
          ))}

        {activeStroke && activeStroke.page === pageNumber && (
          <svg className="edit-pdf-canvas__strokes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
            <polyline
              points={activeStroke.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
              fill="none"
              stroke={drawTool === "marker" ? markerColor : drawColor}
              strokeWidth={
                drawTool === "marker"
                  ? strokeScreenWidth(MARKER_WIDTHS[markerWidth], MARKER_OPACITY, activeStroke.page, pageRef)
                  : STROKE_WIDTHS[drawWidth] / 3
              }
              strokeOpacity={drawTool === "marker" ? MARKER_OPACITY : 1}
              strokeLinecap={drawTool === "marker" || activeStroke.points.length === 1 ? "round" : "butt"}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}
        {marquee && marquee.page === pageNumber && (
          <div className="edit-pdf-canvas__marquee" style={percentBox(rectFromPoints(marquee.start, marquee.current))} />
        )}
        {multiBoxes.map((box, i) => (
          <div key={multiMembers[i].id} className="edit-pdf-canvas__multi-outline" style={percentBox(box)} />
        ))}
        {activeMode === "select" && groupBox && (
          <div
            className="edit-pdf-canvas__group-overlay"
            style={percentBox(groupBox)}
            onMouseDown={(e) => startGroupDrag(pageRef, e)}
            onClick={(e) => e.stopPropagation()}
          />
        )}
        {shapeDragPage === pageNumber && shapeDragStart && shapeDragCurrent && (
          <svg className="edit-pdf-canvas__shapes" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ position: "absolute", inset: 0 }}>
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
          </svg>
        )}
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

        {textDraft && textDraft.page === pageNumber && <>{renderTextDraftEditor(pageRef)}</>}

        {activeMode === "text" &&
          runs.filter((r) => r.page === pageNumber).map((run) => renderTextRun(run, pageNumber))}
      </div>
    );
  }

  return (
    <div className="edit-pdf-canvas">
      {/* ONE toolbar row: modes, undo/redo, arrange, then the active mode's own
          options. It scrolls sideways when the window is narrow instead of
          wrapping onto more rows and taking the page's room. */}
      <div className="edit-pdf-canvas__toolbar" role="toolbar" aria-label="Edit PDF tools">
      <div className="edit-pdf-canvas__modes">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            title={mode.label}
            aria-label={mode.label}
            aria-pressed={activeMode === mode.id}
            className={activeMode === mode.id ? "edit-pdf-canvas__mode-button edit-pdf-canvas__mode-button--active" : "edit-pdf-canvas__mode-button"}
            onClick={() => setActiveMode(mode.id)}
          >
            <mode.icon size={16} weight="regular" />
            {activeMode === mode.id && mode.label}
          </button>
        ))}
      </div>

      <span className="edit-pdf-canvas__divider" aria-hidden="true" />

      <div className="edit-pdf-canvas__history-bar">
        <button type="button" title="Undo (Ctrl+Z)" aria-label="Undo" onClick={undo} disabled={historyRef.current.undoStack.length === 0}>
          <ArrowUUpLeft size={16} weight="regular" />
        </button>
        <button type="button" title="Redo (Ctrl+Y)" aria-label="Redo" onClick={redo} disabled={historyRef.current.redoStack.length === 0}>
          <ArrowUUpRight size={16} weight="regular" />
        </button>
      </div>

      <select
        className="edit-pdf-canvas__arrange"
        aria-label="Arrange"
        title="Bring the selected item forward or send it back"
        value=""
        disabled={!selectedId}
        onChange={(e) => {
          if (e.target.value) reorderSelected(e.target.value);
        }}
      >
        <option value="" disabled>
          Arrange
        </option>
        <option value="front">Bring to front</option>
        <option value="forward">Forward</option>
        <option value="backward">Backward</option>
        <option value="back">Send to back</option>
      </select>

      <span className="edit-pdf-canvas__divider" aria-hidden="true" />

      {activeMode === "draw" && (
        <div className="edit-pdf-canvas__style-bar">
          {["pen", "marker"].map((tool) => (
            <button
              key={tool}
              type="button"
              className={tool === drawTool ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
              onClick={() => setDrawTool(tool)}
            >
              {tool === "pen" ? "Pen" : "Highlighter"}
            </button>
          ))}
          {drawTool === "marker" ? (
            <>
              {renderColorOptions(MARKER_COLORS, markerColor, setMarkerColor)}
              {Object.keys(MARKER_WIDTHS).map((w) => (
                <button
                  key={w}
                  type="button"
                  className={w === markerWidth ? "edit-pdf-canvas__width-button edit-pdf-canvas__width-button--active" : "edit-pdf-canvas__width-button"}
                  onClick={() => setMarkerWidth(w)}
                >
                  {w}
                </button>
              ))}
            </>
          ) : (
            <>
          {renderColorOptions(
            MARKUP_COLORS,
            selectedElementForStyle?.type === "stroke" ? selectedElementForStyle.color : drawColor,
            (c) => {
              if (!updateSelectedElementStyle("stroke", { color: c })) setDrawColor(c);
            }
          )}
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
                if (!updateSelectedElementStyle("stroke", { width: STROKE_WIDTHS[w] })) setDrawWidth(w);
              }}
            >
              {w}
            </button>
          ))}
            </>
          )}
        </div>
      )}

      {activeMode === "select" && (
        <div className="edit-pdf-canvas__style-bar">
          <span className="edit-pdf-canvas__hint">Drag to select. Del removes, drag moves.</span>
        </div>
      )}

      {activeMode === "eraser" && (
        <div className="edit-pdf-canvas__style-bar">
          <span className="edit-pdf-canvas__hint">Drag across a line to erase it.</span>
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
          {renderColorOptions(
            MARKUP_COLORS,
            selectedElementForStyle?.type === "shape" ? selectedElementForStyle.color : shapeColor,
            (c) => {
              if (!updateSelectedElementStyle("shape", { color: c })) setShapeColor(c);
            }
          )}
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
                if (!updateSelectedElementStyle("shape", { width: STROKE_WIDTHS[w] })) setShapeWidth(w);
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
                  if (!updateSelectedElementStyle("shape", { filled: e.target.checked })) setShapeFilled(e.target.checked);
                }}
              />
              Fill
            </label>
          )}
        </div>
      )}

      {activeMode === "highlight" && (
        <div className="edit-pdf-canvas__style-bar">
          {renderColorOptions(
            ["#ffd43b", "#69db7c", "#66d9e8", "#ff8787"],
            selectedElementForStyle?.type === "highlight" ? selectedElementForStyle.color : highlightColor,
            (c) => {
              if (!updateSelectedElementStyle("highlight", { color: c })) setHighlightColor(c);
            }
          )}
        </div>
      )}

      </div>

      <PageScrollViewer
        fileId={fileId}
        pageCount={pageCount}
        maxSize={PAGE_THUMBNAIL_MAX_SIZE}
        className="edit-pdf-canvas__viewer"
        renderPageOverlay={renderPageOverlay}
      />

      <input
        ref={imageFileInputRef}
        type="file"
        accept="image/png,image/jpeg"
        style={{ display: "none" }}
        onChange={handleImageFileSelected}
      />

    </div>
  );
}
