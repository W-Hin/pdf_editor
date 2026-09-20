"""The desktop app's look, matching the web app's: colours, font, icons.

The values mirror the design tokens at the top of web/frontend/src/index.css, so
a change to the web palette should be repeated here.
"""
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent / "assets"

PRIMARY = "#1e293b"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
BACKGROUND = "#f8fafc"
CARD = "#ffffff"
FOREGROUND = "#0f172a"
MUTED = "#f1f5f9"
MUTED_FOREGROUND = "#64748b"
BORDER = "#e2e8f0"

_STYLESHEET = """
QWidget {
    font-family: "Inter";
    font-size: 14px;
    color: @FOREGROUND@;
}
QMainWindow, QDialog, QScrollArea, QStackedWidget, #page {
    background: @BACKGROUND@;
}
QScrollArea { border: none; }
QScrollArea > QWidget > QWidget { background: @BACKGROUND@; }

QLabel { background: transparent; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; }
QLabel#categoryLabel {
    font-size: 12px; font-weight: 600; color: @MUTED_FOREGROUND@;
}
QLabel#historyName { font-weight: 500; }
QLabel#historyMeta { color: @MUTED_FOREGROUND@; font-size: 13px; }
QLabel#historyThumb { background: @MUTED@; border-radius: 6px; }
QLabel#emptyState { color: @MUTED_FOREGROUND@; padding: 48px; }
QFrame#historyRow { background: @CARD@; border: 1px solid @BORDER@; border-radius: 10px; }
QPushButton#headerLink {
    background: transparent; border: none; color: #ffffff; font-weight: 500; padding: 4px 0;
}
QPushButton#headerLink:hover { color: #cbd5e1; }
QLabel#toolIcon { background: @MUTED@; border-radius: 6px; }
QLabel#toolName { font-size: 15px; font-weight: 500; }

#header { background: @PRIMARY@; }
#header QLabel { color: #ffffff; font-size: 15px; font-weight: 600; }

QPushButton {
    background: @CARD@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
}
QPushButton:hover { border-color: @ACCENT@; }
QPushButton:pressed { background: @MUTED@; }
QPushButton:disabled { color: #94a3b8; background: @MUTED@; }
QPushButton[primary="true"] {
    background: @ACCENT@; border-color: @ACCENT@; color: #ffffff;
}
QPushButton[primary="true"]:hover { background: @ACCENT_HOVER@; border-color: @ACCENT_HOVER@; }
QPushButton[primary="true"]:disabled {
    background: @BORDER@; border-color: @BORDER@; color: #94a3b8;
}
QPushButton#dropButton {
    background: @CARD@; border: 1px solid @BORDER@; border-radius: 10px;
    padding: 16px; color: @MUTED_FOREGROUND@;
}
QPushButton#dropButton:hover { border-color: @ACCENT@; color: @FOREGROUND@; }
QPushButton#backButton {
    border: none; background: transparent; color: @MUTED_FOREGROUND@;
    padding: 4px 0; text-align: left;
}
QPushButton#backButton:hover { color: @FOREGROUND@; }
QPushButton#toolCard {
    border: 1px solid @BORDER@; border-radius: 10px; background: @CARD@;
    padding: 0; text-align: left;
}
QPushButton#toolCard:hover { border-color: @ACCENT@; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: @CARD@;
    border: 1px solid @BORDER@;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: @ACCENT@;
    selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus { border-color: @ACCENT@; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: @CARD@; border: 1px solid @BORDER@;
    selection-background-color: @MUTED@; selection-color: @FOREGROUND@;
}

QListWidget {
    background: @CARD@; border: 1px solid @BORDER@; border-radius: 10px; padding: 4px;
}
QListWidget::item { padding: 4px 6px; border-radius: 4px; }
QListWidget::item:selected { background: @MUTED@; color: @FOREGROUND@; }

QGroupBox {
    background: @CARD@; border: 1px solid @BORDER@; border-radius: 10px;
    margin-top: 12px; padding: 12px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }

QCheckBox, QRadioButton { spacing: 8px; background: transparent; }

QSlider::groove:horizontal { height: 4px; background: @BORDER@; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @ACCENT@; border-radius: 2px; }
QSlider::handle:horizontal {
    background: @ACCENT@; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}

QProgressBar {
    background: @BORDER@; border: none; border-radius: 3px;
    max-height: 6px; min-height: 6px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: @ACCENT@; border-radius: 3px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #cbd5e1; border-radius: 5px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #cbd5e1; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QToolTip {
    background: @PRIMARY@; color: #ffffff; border: none; padding: 4px 8px;
}
QMessageBox { background: @CARD@; }
"""


def stylesheet() -> str:
    text = _STYLESHEET
    for name, value in {
        "PRIMARY": PRIMARY, "ACCENT_HOVER": ACCENT_HOVER, "ACCENT": ACCENT,
        "BACKGROUND": BACKGROUND, "CARD": CARD, "FOREGROUND": FOREGROUND,
        "MUTED_FOREGROUND": MUTED_FOREGROUND, "MUTED": MUTED, "BORDER": BORDER,
    }.items():
        text = text.replace(f"@{name}@", value)
    return text


def apply_theme(app: QApplication) -> None:
    """Load Inter and install the stylesheet. Fusion is the style the stylesheet
    is written against; the platform default draws some widgets its own way."""
    for weight in (400, 500, 600, 700):
        QFontDatabase.addApplicationFont(str(ASSETS / "fonts" / f"Inter-{weight}.ttf"))
    app.setStyle("Fusion")
    app.setFont(QFont("Inter", 10))
    app.setStyleSheet(stylesheet())


def icon_pixmap(name: str, color: str = ACCENT, size: int = 20) -> QPixmap:
    """A Phosphor icon (assets/icons/<name>.svg) tinted `color`, drawn at 2x so it
    stays crisp on high-DPI screens."""
    svg = (ASSETS / "icons" / f"{name}.svg").read_text(encoding="utf-8")
    renderer = QSvgRenderer(QByteArray(svg.replace("currentColor", color).encode("utf-8")))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


def icon(name: str, color: str = ACCENT, size: int = 20) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))
