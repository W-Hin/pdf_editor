"""Live previews painted on the page-grid thumbnails: what a tool WILL do to each
page, drawn from the same numbers the tool itself uses, so the preview is honest."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont

from app.core.pdf_ops import _PAGE_NUMBER_BAND_HEIGHT, _PAGE_NUMBER_MARGIN, _format_page_number

DEFAULT_WATERMARK_FONT_SIZE_PT = 40  # add_watermark's own default
PAGE_NUMBER_FONT_SIZE_PT = 10  # what add_page_numbers draws at


def watermark_overlay(grid, text, opacity, font_size=None, rotation=None):
    """`text()`, `opacity()` (0-1), `font_size()` (points) and `rotation()` (degrees,
    counter-clockwise like the exported watermark) are read fresh on every paint."""

    def paint(painter, rect, page, total):
        value = text().strip()
        if not value:
            return
        width_pt, _height_pt = grid.page_size_pt(0, page)
        scale = rect.width() / width_pt
        size_pt = font_size() if font_size is not None else DEFAULT_WATERMARK_FONT_SIZE_PT
        font = QFont("Helvetica")
        font.setPixelSize(max(4, round(size_pt * scale)))
        painter.setFont(font)
        colour = QColor(128, 128, 128)
        colour.setAlphaF(opacity())
        painter.setPen(colour)
        painter.translate(rect.center())
        # The export rotates counter-clockwise (PDF's y axis points up); Qt's rotate()
        # is clockwise on screen, hence the minus.
        painter.rotate(-(rotation() if rotation is not None else 0))
        text_rect = QRectF(-rect.width() * 2, -rect.height(), rect.width() * 4, rect.height() * 2)
        painter.drawText(text_rect, Qt.AlignCenter, value)

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
