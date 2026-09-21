"""Live previews painted on the page-grid thumbnails: what a tool WILL do to each
page, drawn from the same numbers the tool itself uses, so the preview is honest."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont

from app.core.pdf_ops import _PAGE_NUMBER_BAND_HEIGHT, _PAGE_NUMBER_MARGIN, _format_page_number

WATERMARK_FONT_SIZE_PT = 40  # what add_watermark draws at
PAGE_NUMBER_FONT_SIZE_PT = 10  # what add_page_numbers draws at


def watermark_overlay(grid, text, opacity):
    """`text()` and `opacity()` (0-1) are read fresh on every paint."""

    def paint(painter, rect, page, total):
        value = text().strip()
        if not value:
            return
        width_pt, _height_pt = grid.page_size_pt(0, page)
        scale = rect.width() / width_pt
        font = QFont("Helvetica")
        font.setPixelSize(max(4, round(WATERMARK_FONT_SIZE_PT * scale)))
        painter.setFont(font)
        colour = QColor(128, 128, 128)
        colour.setAlphaF(opacity())
        painter.setPen(colour)
        painter.drawText(rect, Qt.AlignCenter, value)

    return paint


def page_number_overlay(grid, position, fmt):
    """`position()` like "bottom-center" and `fmt()` like "number-of-total"."""

    def paint(painter, rect, page, total):
        width_pt, height_pt = grid.page_size_pt(0, page)
        scale = rect.width() / width_pt
        margin = _PAGE_NUMBER_MARGIN * scale
        # Real size would be ~4px on a thumbnail - unreadable - so the preview draws the
        # number a little larger than life; its POSITION and format are exact.
        pixel_size = max(9, round(PAGE_NUMBER_FONT_SIZE_PT * scale))
        band = max(_PAGE_NUMBER_BAND_HEIGHT * scale, pixel_size * 1.5)  # tall enough for the enlarged text
        where = position()
        top = rect.bottom() - margin - band if where.startswith("bottom") else rect.top() + margin
        band_rect = QRectF(rect.left() + margin, top, rect.width() - 2 * margin, band)
        align = Qt.AlignLeft if where.endswith("left") else Qt.AlignRight if where.endswith("right") else Qt.AlignHCenter
        font = QFont("Helvetica")
        font.setPixelSize(pixel_size)
        painter.setFont(font)
        painter.setPen(QColor(0, 0, 0))
        painter.drawText(band_rect, int(align | Qt.AlignVCenter), _format_page_number(fmt(), page, total))

    return paint
