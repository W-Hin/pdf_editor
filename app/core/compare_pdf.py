import difflib

import fitz
import numpy as np

from app.core.pdf_ops import open_pdf

# A per-channel difference below this is treated as noise rather than a real
# content change. Verified empirically: rendering the SAME page twice via
# fitz's get_pixmap is bit-exact deterministic (max per-channel diff is 0),
# so this value isn't compensating for observed rendering noise between
# identical renders — it's a conservative margin for real-world cross-file
# comparisons (different PDF producers can rasterize visually-identical
# content with tiny colour/positioning differences this codebase has no way
# to synthesize in a test). Confirmed this value causes no false negatives:
# a genuinely moved 200x150pt rectangle was detected identically at every
# tolerance tested from 0 to 50.
_VISUAL_DIFF_TOLERANCE = 24

# Coarse-grid cell size (px) used to cluster differing pixels into bounding
# boxes. Verified empirically on a real rendered page at max_size 1800: a
# moved rectangle produced two clean ~60x340px boxes at the changed edges —
# neither tiny slivers nor one overly-coarse blob.
_DIFF_GRID_CELL_PX = 20


def extract_page_texts(path: str) -> list[str]:
    doc = open_pdf(path)
    try:
        return [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()


def diff_page_text(text_a: str, text_b: str) -> list[dict]:
    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    result: list[dict] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            result.extend({"op": "equal", "text": line} for line in lines_a[i1:i2])
        elif op == "delete":
            result.extend({"op": "delete", "text": line} for line in lines_a[i1:i2])
        elif op == "insert":
            result.extend({"op": "insert", "text": line} for line in lines_b[j1:j2])
        elif op == "replace":
            result.extend({"op": "delete", "text": line} for line in lines_a[i1:i2])
            result.extend({"op": "insert", "text": line} for line in lines_b[j1:j2])
    return result


def render_page_image(path: str, page_num: int, max_size: int) -> bytes:
    doc = open_pdf(path)
    try:
        page = doc[page_num - 1]
        rect = page.rect
        scale = max_size / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return pix.tobytes("png")
    finally:
        doc.close()


def _render_pixmap_array(path: str, page_num: int, max_size: int) -> np.ndarray:
    doc = open_pdf(path)
    try:
        page = doc[page_num - 1]
        rect = page.rect
        scale = max_size / max(rect.width, rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    finally:
        doc.close()


def _cluster_diff_boxes(mask: np.ndarray, cell: int = _DIFF_GRID_CELL_PX) -> list[tuple[int, int, int, int]]:
    """Coarse-grid flood-fill: divides `mask` into `cell`x`cell` blocks, flags
    any block containing at least one True pixel, then merges 4-connected
    flagged blocks into pixel-space (x0, y0, x1, y1) bounding boxes. No
    scipy dependency — box-level precision is enough for "here's roughly
    where it changed," not pixel-perfect segmentation.
    """
    h, w = mask.shape
    grid_h, grid_w = (h + cell - 1) // cell, (w + cell - 1) // cell
    grid = np.zeros((grid_h, grid_w), dtype=bool)
    for gy in range(grid_h):
        for gx in range(grid_w):
            block = mask[gy * cell : (gy + 1) * cell, gx * cell : (gx + 1) * cell]
            if block.any():
                grid[gy, gx] = True

    visited = np.zeros_like(grid)
    boxes: list[tuple[int, int, int, int]] = []
    for gy in range(grid_h):
        for gx in range(grid_w):
            if not grid[gy, gx] or visited[gy, gx]:
                continue
            stack = [(gy, gx)]
            visited[gy, gx] = True
            cells = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < grid_h and 0 <= nx < grid_w and grid[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            y0, y1 = min(ys) * cell, min((max(ys) + 1) * cell, h)
            x0, x1 = min(xs) * cell, min((max(xs) + 1) * cell, w)
            boxes.append((x0, y0, x1, y1))
    return boxes


def diff_page_visual(path_a: str, path_b: str, page_num: int, max_size: int) -> list[dict]:
    arr_a = _render_pixmap_array(path_a, page_num, max_size)
    arr_b = _render_pixmap_array(path_b, page_num, max_size)

    # Pad the smaller array to the larger's canvas size (black fill), never
    # stretch — lets pages with different aspect ratios still be diffed
    # pixel-for-pixel without distorting either.
    h = max(arr_a.shape[0], arr_b.shape[0])
    w = max(arr_a.shape[1], arr_b.shape[1])
    n = arr_a.shape[2]

    def pad(arr: np.ndarray) -> np.ndarray:
        if arr.shape[0] == h and arr.shape[1] == w:
            return arr
        canvas = np.zeros((h, w, n), dtype=np.uint8)
        canvas[: arr.shape[0], : arr.shape[1], :] = arr
        return canvas

    arr_a = pad(arr_a)
    arr_b = pad(arr_b)

    per_channel_diff = np.abs(arr_a.astype(int) - arr_b.astype(int))
    mask = (per_channel_diff > _VISUAL_DIFF_TOLERANCE).any(axis=2)
    boxes = _cluster_diff_boxes(mask)
    return [{"x0": x0 / w, "y0": y0 / h, "x1": x1 / w, "y1": y1 / h} for x0, y0, x1, y1 in boxes]
