import pytest

from app.core.edit_geometry import (
    clamp_move,
    element_bounds,
    polyline_near_point,
    rect_from_points,
    rects_intersect,
    union_bounds,
)


def test_bounds_of_a_stroke_cover_its_points():
    el = {"type": "stroke", "points": [{"x": 0.2, "y": 0.5}, {"x": 0.4, "y": 0.1}]}
    assert element_bounds(el) == {"left": 0.2, "top": 0.1, "right": 0.4, "bottom": 0.5}


def test_bounds_of_a_shape_order_its_corners():
    el = {"type": "shape", "x0": 0.6, "y0": 0.7, "x1": 0.2, "y1": 0.3}
    assert element_bounds(el) == {"left": 0.2, "top": 0.3, "right": 0.6, "bottom": 0.7}


def test_bounds_of_a_highlight_convert_its_insets():
    el = {"type": "highlight", "top": 0.1, "right": 0.2, "bottom": 0.3, "left": 0.4}
    b = element_bounds(el)
    assert b["left"] == 0.4 and b["top"] == 0.1
    assert b["right"] == pytest.approx(0.8) and b["bottom"] == pytest.approx(0.7)


def test_bounds_of_boxes_and_images_use_xywh():
    b = element_bounds({"type": "new_text", "x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1})
    assert b["left"] == 0.1 and b["top"] == 0.2
    assert b["right"] == pytest.approx(0.4) and b["bottom"] == pytest.approx(0.3)


def test_a_text_edit_needs_its_derived_box():
    el = {"type": "text_edit", "page": 1, "run_index": 0, "segments": []}
    assert element_bounds(el) is None
    b = element_bounds(el, {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05})
    assert b["right"] == pytest.approx(0.3) and b["bottom"] == pytest.approx(0.15)


def test_rects_overlap_and_separate():
    a = {"left": 0, "top": 0, "right": 0.5, "bottom": 0.5}
    assert rects_intersect(a, {"left": 0.4, "top": 0.4, "right": 0.9, "bottom": 0.9})
    assert not rects_intersect(a, {"left": 0.6, "top": 0.6, "right": 0.9, "bottom": 0.9})


def test_rect_from_two_corners_in_any_order():
    assert rect_from_points((0.8, 0.2), (0.3, 0.9)) == {"left": 0.3, "top": 0.2, "right": 0.8, "bottom": 0.9}


def test_union_of_rects_and_of_nothing():
    union = union_bounds([
        {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.4},
        {"left": 0.5, "top": 0.1, "right": 0.6, "bottom": 0.9},
    ])
    assert union == {"left": 0.1, "top": 0.1, "right": 0.6, "bottom": 0.9}
    assert union_bounds([]) is None


def test_clamp_move_keeps_the_group_on_the_page():
    b = {"left": 0.1, "top": 0.1, "right": 0.6, "bottom": 0.7}
    dx, dy = clamp_move(b, -0.5, 0.5)
    assert dx == pytest.approx(-0.1) and dy == pytest.approx(0.3)
    dx, dy = clamp_move(b, 0.5, -0.5)
    assert dx == pytest.approx(0.4) and dy == pytest.approx(-0.1)


LINE = [{"x": 0.1, "y": 0.5}, {"x": 0.9, "y": 0.5}]


def test_polyline_hit_within_the_radius_only():
    assert polyline_near_point(LINE, (0.5, 0.51), 10, 1000, 1000)
    assert not polyline_near_point(LINE, (0.5, 0.6), 10, 1000, 1000)


def test_polyline_distance_is_measured_in_pixels():
    # 0.02 of a 2000px-tall page is 40px, but of a 200px page it is 4px.
    assert not polyline_near_point(LINE, (0.5, 0.52), 10, 1000, 2000)
    assert polyline_near_point(LINE, (0.5, 0.52), 10, 1000, 200)


def test_a_single_point_stroke_is_a_dot():
    assert polyline_near_point([{"x": 0.5, "y": 0.5}], (0.5, 0.5), 5, 100, 100)
    assert not polyline_near_point([{"x": 0.5, "y": 0.5}], (0.9, 0.9), 5, 100, 100)
