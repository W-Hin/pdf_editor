import { describe, expect, it } from "vitest";
import {
  clampMove,
  elementBounds,
  polylineNearPoint,
  rectFromPoints,
  rectsIntersect,
  unionBounds,
} from "./editGeometry";

describe("elementBounds", () => {
  it("covers a stroke's points", () => {
    const el = { type: "stroke", points: [{ x: 0.2, y: 0.5 }, { x: 0.4, y: 0.1 }] };
    expect(elementBounds(el)).toEqual({ left: 0.2, top: 0.1, right: 0.4, bottom: 0.5 });
  });
  it("orders a shape's corners", () => {
    const el = { type: "shape", x0: 0.6, y0: 0.7, x1: 0.2, y1: 0.3 };
    expect(elementBounds(el)).toEqual({ left: 0.2, top: 0.3, right: 0.6, bottom: 0.7 });
  });
  it("converts a highlight's insets", () => {
    const el = { type: "highlight", top: 0.1, right: 0.2, bottom: 0.3, left: 0.4 };
    const b = elementBounds(el);
    expect(b.left).toBe(0.4);
    expect(b.top).toBe(0.1);
    expect(b.right).toBeCloseTo(0.8);
    expect(b.bottom).toBeCloseTo(0.7);
  });
  it("uses x/y/width/height for text boxes and images", () => {
    expect(elementBounds({ type: "new_text", x: 0.1, y: 0.2, width: 0.3, height: 0.1 })).toEqual({
      left: 0.1, top: 0.2, right: 0.4, bottom: 0.30000000000000004,
    });
  });
  it("needs a derived box for text_edit", () => {
    const el = { type: "text_edit", page: 1, run_index: 0, segments: [] };
    expect(elementBounds(el)).toBeNull();
    expect(elementBounds(el, { left: 0.1, top: 0.1, width: 0.2, height: 0.05 })).toEqual({
      left: 0.1, top: 0.1, right: 0.30000000000000004, bottom: 0.15000000000000002,
    });
  });
});

describe("rect helpers", () => {
  it("detects overlap and separation", () => {
    const a = { left: 0, top: 0, right: 0.5, bottom: 0.5 };
    expect(rectsIntersect(a, { left: 0.4, top: 0.4, right: 0.9, bottom: 0.9 })).toBe(true);
    expect(rectsIntersect(a, { left: 0.6, top: 0.6, right: 0.9, bottom: 0.9 })).toBe(false);
  });
  it("builds a rect from two corners in any order", () => {
    expect(rectFromPoints({ x: 0.8, y: 0.2 }, { x: 0.3, y: 0.9 })).toEqual({ left: 0.3, top: 0.2, right: 0.8, bottom: 0.9 });
  });
  it("unions rects", () => {
    expect(unionBounds([{ left: 0.1, top: 0.2, right: 0.3, bottom: 0.4 }, { left: 0.5, top: 0.1, right: 0.6, bottom: 0.9 }])).toEqual({
      left: 0.1, top: 0.1, right: 0.6, bottom: 0.9,
    });
    expect(unionBounds([])).toBeNull();
  });
  it("clamps a group move to the page", () => {
    const b = { left: 0.1, top: 0.1, right: 0.6, bottom: 0.7 };
    expect(clampMove(b, -0.5, 0.5)).toEqual({ dx: -0.1, dy: 0.30000000000000004 });
    expect(clampMove(b, 0.5, -0.5)).toEqual({ dx: 0.4, dy: -0.1 });
  });
});

describe("polylineNearPoint", () => {
  const line = [{ x: 0.1, y: 0.5 }, { x: 0.9, y: 0.5 }];
  it("hits within the radius and misses outside it", () => {
    expect(polylineNearPoint(line, { x: 0.5, y: 0.51 }, 10, 1000, 1000)).toBe(true);
    expect(polylineNearPoint(line, { x: 0.5, y: 0.6 }, 10, 1000, 1000)).toBe(false);
  });
  it("measures in pixels, so page shape matters", () => {
    // 0.02 of a 2000px-tall page is 40px, but of a 200px page it is 4px.
    expect(polylineNearPoint(line, { x: 0.5, y: 0.52 }, 10, 1000, 2000)).toBe(false);
    expect(polylineNearPoint(line, { x: 0.5, y: 0.52 }, 10, 1000, 200)).toBe(true);
  });
  it("treats a single-point stroke as a dot", () => {
    expect(polylineNearPoint([{ x: 0.5, y: 0.5 }], { x: 0.5, y: 0.5 }, 5, 100, 100)).toBe(true);
    expect(polylineNearPoint([{ x: 0.5, y: 0.5 }], { x: 0.9, y: 0.9 }, 5, 100, 100)).toBe(false);
  });
});
