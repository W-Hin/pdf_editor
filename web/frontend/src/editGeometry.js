// Pure geometry helpers for the Edit PDF canvas. Everything is in page
// fractions (0-1) unless a function says it takes pixels.

// Bounding box { left, top, right, bottom } of any element, in page fractions.
// A text_edit element stores no size of its own, so callers pass the box they
// derived from its run as `textEditBox` ({ left, top, width, height }); without
// one a text_edit has no bounds (null).
export function elementBounds(el, textEditBox) {
  if (el.type === "text_edit") {
    if (!textEditBox) return null;
    return {
      left: textEditBox.left,
      top: textEditBox.top,
      right: textEditBox.left + textEditBox.width,
      bottom: textEditBox.top + textEditBox.height,
    };
  }
  if ("points" in el) {
    const xs = el.points.map((p) => p.x);
    const ys = el.points.map((p) => p.y);
    return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
  }
  if ("x0" in el) {
    return {
      left: Math.min(el.x0, el.x1),
      top: Math.min(el.y0, el.y1),
      right: Math.max(el.x0, el.x1),
      bottom: Math.max(el.y0, el.y1),
    };
  }
  if ("left" in el) {
    return { left: el.left, top: el.top, right: 1 - el.right, bottom: 1 - el.bottom };
  }
  return { left: el.x, top: el.y, right: el.x + el.width, bottom: el.y + el.height };
}

export function rectsIntersect(a, b) {
  return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
}

export function rectFromPoints(a, b) {
  return {
    left: Math.min(a.x, b.x),
    top: Math.min(a.y, b.y),
    right: Math.max(a.x, b.x),
    bottom: Math.max(a.y, b.y),
  };
}

export function unionBounds(list) {
  if (list.length === 0) return null;
  return {
    left: Math.min(...list.map((r) => r.left)),
    top: Math.min(...list.map((r) => r.top)),
    right: Math.max(...list.map((r) => r.right)),
    bottom: Math.max(...list.map((r) => r.bottom)),
  };
}

// Limit a move of (dx, dy) so `bounds` stays on the page.
export function clampMove(bounds, dx, dy) {
  return {
    dx: Math.min(Math.max(dx, -bounds.left), 1 - bounds.right),
    dy: Math.min(Math.max(dy, -bounds.top), 1 - bounds.bottom),
  };
}

function distanceToSegment(p, a, b) {
  const abx = b.x - a.x;
  const aby = b.y - a.y;
  const lengthSquared = abx * abx + aby * aby;
  let t = lengthSquared === 0 ? 0 : ((p.x - a.x) * abx + (p.y - a.y) * aby) / lengthSquared;
  t = Math.min(Math.max(t, 0), 1);
  return Math.hypot(p.x - (a.x + t * abx), p.y - (a.y + t * aby));
}

// True when `point` (page fractions) is within `radiusPx` of the polyline.
// Distances are measured in pixels (fractions scaled by the page's on-screen
// size) so the eraser feels the same on a wide and a tall page.
export function polylineNearPoint(points, point, radiusPx, pageWidthPx, pageHeightPx) {
  const scale = (p) => ({ x: p.x * pageWidthPx, y: p.y * pageHeightPx });
  const target = scale(point);
  const scaled = points.map(scale);
  if (scaled.length === 1) return Math.hypot(target.x - scaled[0].x, target.y - scaled[0].y) <= radiusPx;
  for (let i = 0; i < scaled.length - 1; i += 1) {
    if (distanceToSegment(target, scaled[i], scaled[i + 1]) <= radiusPx) return true;
  }
  return false;
}
