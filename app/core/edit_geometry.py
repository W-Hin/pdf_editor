"""Pure geometry helpers for the Edit PDF canvas, in page fractions (0-1).

A port of web/frontend/src/editGeometry.js: keep the two in step.
Rects are dicts with "left", "top", "right", "bottom".
"""
import math


def element_bounds(el: dict, text_edit_box: dict | None = None) -> dict | None:
    """Bounding box of any element. A text_edit stores no size of its own, so the
    caller passes the box derived from its run ({"x","y","width","height"}); with
    none, a text_edit has no bounds."""
    if el["type"] == "text_edit":
        if text_edit_box is None:
            return None
        return {
            "left": text_edit_box["x"],
            "top": text_edit_box["y"],
            "right": text_edit_box["x"] + text_edit_box["width"],
            "bottom": text_edit_box["y"] + text_edit_box["height"],
        }
    if "points" in el:
        xs = [p["x"] for p in el["points"]]
        ys = [p["y"] for p in el["points"]]
        return {"left": min(xs), "top": min(ys), "right": max(xs), "bottom": max(ys)}
    if "x0" in el:
        return {
            "left": min(el["x0"], el["x1"]),
            "top": min(el["y0"], el["y1"]),
            "right": max(el["x0"], el["x1"]),
            "bottom": max(el["y0"], el["y1"]),
        }
    if "left" in el:
        return {"left": el["left"], "top": el["top"], "right": 1 - el["right"], "bottom": 1 - el["bottom"]}
    return {"left": el["x"], "top": el["y"], "right": el["x"] + el["width"], "bottom": el["y"] + el["height"]}


def rects_intersect(a: dict, b: dict) -> bool:
    return a["left"] <= b["right"] and a["right"] >= b["left"] and a["top"] <= b["bottom"] and a["bottom"] >= b["top"]


def rect_from_points(p: tuple[float, float], q: tuple[float, float]) -> dict:
    return {"left": min(p[0], q[0]), "top": min(p[1], q[1]), "right": max(p[0], q[0]), "bottom": max(p[1], q[1])}


def union_bounds(rects: list[dict]) -> dict | None:
    if not rects:
        return None
    return {
        "left": min(r["left"] for r in rects),
        "top": min(r["top"] for r in rects),
        "right": max(r["right"] for r in rects),
        "bottom": max(r["bottom"] for r in rects),
    }


def clamp_move(bounds: dict, dx: float, dy: float) -> tuple[float, float]:
    """Limit a move of (dx, dy) so `bounds` stays on the page."""
    return (
        min(max(dx, -bounds["left"]), 1 - bounds["right"]),
        min(max(dy, -bounds["top"]), 1 - bounds["bottom"]),
    )


def _distance_to_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    abx, aby = b[0] - a[0], b[1] - a[1]
    length_squared = abx * abx + aby * aby
    t = 0.0 if length_squared == 0 else ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby) / length_squared
    t = min(max(t, 0.0), 1.0)
    return math.hypot(p[0] - (a[0] + t * abx), p[1] - (a[1] + t * aby))


def polyline_near_point(points: list[dict], point: tuple[float, float], radius_px: float, page_w_px: float, page_h_px: float) -> bool:
    """True when `point` is within `radius_px` of the polyline. Distances are in
    pixels (fractions scaled by the page's on-screen size) so the eraser feels the
    same on a wide and a tall page."""
    target = (point[0] * page_w_px, point[1] * page_h_px)
    scaled = [(p["x"] * page_w_px, p["y"] * page_h_px) for p in points]
    if len(scaled) == 1:
        return math.hypot(target[0] - scaled[0][0], target[1] - scaled[0][1]) <= radius_px
    return any(_distance_to_segment(target, scaled[i], scaled[i + 1]) <= radius_px for i in range(len(scaled) - 1))
