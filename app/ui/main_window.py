from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.recent_files import RecentFilesPage
from app.ui.theme import MUTED_FOREGROUND, icon, icon_pixmap

APP_TITLE = "PDF Editor (Desktop)"

# The web grid packs cards at least this wide (plus this gap) per row.
CARD_MIN_WIDTH = 210
CARD_GAP = 12


class ToolCard(QPushButton):
    """One tool on the home screen: a tinted icon square beside the tool's name."""

    def __init__(self, label: str, icon_name: str):
        super().__init__()
        self.setObjectName("toolCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(68)
        self.setAccessibleName(label)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)
        icon_label = QLabel()
        icon_label.setObjectName("toolIcon")
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setPixmap(icon_pixmap(icon_name))
        name_label = QLabel(label)
        name_label.setObjectName("toolName")
        for child in (icon_label, name_label):
            child.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(icon_label)
        row.addWidget(name_label, 1)


class HomePage(QScrollArea):
    """Category labels over grids of tool cards; the column count follows the
    window's width like the web app's auto-fill grid."""

    def __init__(self, categories):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("page")
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(32)
        self._cards: dict[str, list[ToolCard]] = {}
        self._grids: dict[str, QGridLayout] = {}
        for name in categories:
            section = QVBoxLayout()
            section.setSpacing(12)
            label = QLabel(name.upper())
            label.setObjectName("categoryLabel")
            section.addWidget(label)
            grid = QGridLayout()
            grid.setSpacing(CARD_GAP)
            section.addLayout(grid)
            outer.addLayout(section)
            self._cards[name] = []
            self._grids[name] = grid
        outer.addStretch(1)
        self.setWidget(content)
        self._columns = 0

    def add_card(self, category: str, card: ToolCard) -> None:
        self._cards[category].append(card)
        self._relayout(force=True)

    def _column_count(self) -> int:
        usable = self.viewport().width() - 48
        return max(1, (usable + CARD_GAP) // (CARD_MIN_WIDTH + CARD_GAP))

    def _relayout(self, force: bool = False) -> None:
        columns = self._column_count()
        if columns == self._columns and not force:
            return
        self._columns = columns
        for category, cards in self._cards.items():
            grid = self._grids[category]
            for card in cards:
                grid.removeWidget(card)
            for column in range(grid.columnCount()):
                grid.setColumnStretch(column, 0)
            for index, card in enumerate(cards):
                grid.addWidget(card, index // columns, index % columns)
            for column in range(columns):
                grid.setColumnStretch(column, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()


class MainWindow(QMainWindow):
    CATEGORIES = ("Organize", "Edit", "Optimize", "Convert")

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1100, 760)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(44)
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(24, 0, 24, 0)
        header_row.setSpacing(8)
        brand_icon = QLabel()
        brand_icon.setPixmap(icon_pixmap("file-pdf-fill", "#ffffff", 22))
        header_row.addWidget(brand_icon)
        header_row.addWidget(QLabel(APP_TITLE))
        header_row.addStretch(1)
        self._recent_link = QPushButton("Recent Files")
        self._recent_link.setObjectName("headerLink")
        self._recent_link.setIcon(icon("clock-counter-clockwise", "#ffffff", 18))
        self._recent_link.setIconSize(QSize(18, 18))
        self._recent_link.setCursor(Qt.PointingHandCursor)
        self._recent_link.clicked.connect(self.show_recent)
        header_row.addWidget(self._recent_link)
        layout.addWidget(header)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._home = HomePage(self.CATEGORIES)
        self._stack.addWidget(self._home)

        self._tool_page = QWidget()
        self._tool_page.setObjectName("page")
        tool_layout = QVBoxLayout(self._tool_page)
        self._tool_layout = tool_layout
        tool_layout.setContentsMargins(32, 24, 32, 24)
        tool_layout.setSpacing(12)
        # Back link over the title, like the web app - or side by side for a
        # tool that wants every pixel of height (see open_tool).
        self._tool_header = QBoxLayout(QBoxLayout.TopToBottom)
        self._tool_header.setSpacing(12)
        tool_layout.addLayout(self._tool_header)
        self._back_button = self._make_back_button()
        self._tool_header.addWidget(self._back_button, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._tool_title = QLabel()
        self._tool_title.setObjectName("pageTitle")
        self._tool_header.addWidget(self._tool_title, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self._tool_header.addStretch(1)
        self._tool_holder = QVBoxLayout()
        self._tool_holder.setContentsMargins(0, 0, 0, 0)
        tool_layout.addLayout(self._tool_holder, 1)
        self._stack.addWidget(self._tool_page)

        self._recent_page = QWidget()
        self._recent_page.setObjectName("page")
        recent_layout = QVBoxLayout(self._recent_page)
        recent_layout.setContentsMargins(32, 24, 32, 24)
        recent_layout.setSpacing(12)
        self._recent_back = self._make_back_button()
        recent_layout.addWidget(self._recent_back, 0, Qt.AlignLeft)
        recent_title = QLabel("Recent Files")
        recent_title.setObjectName("pageTitle")
        recent_layout.addWidget(recent_title)
        self._recent_list = RecentFilesPage()
        recent_layout.addWidget(self._recent_list, 1)
        self._stack.addWidget(self._recent_page)

        self._current_tool = None

    def _make_back_button(self) -> QPushButton:
        button = QPushButton("Back")
        button.setObjectName("backButton")
        button.setIcon(icon("arrow-left", MUTED_FOREGROUND, 16))
        button.setIconSize(QSize(16, 16))
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(self.show_home)
        return button

    def show_recent(self) -> None:
        if not self._leave_current_tool():
            return
        self._recent_list.refresh()
        self._stack.setCurrentWidget(self._recent_page)

    def add_tool(self, category: str, label: str, dialog_cls, icon_name: str = "file") -> None:
        card = ToolCard(label, icon_name)
        card.clicked.connect(lambda: self.open_tool(label, dialog_cls))
        self._home.add_card(category, card)

    def open_tool(self, label: str, dialog_cls) -> None:
        """Show a tool inside this window (with a Back link) rather than as a
        pop-up, like the web app."""
        self._discard_current_tool()
        tool = dialog_cls(self)
        tool.embed()
        self._current_tool = tool
        self._tool_title.setText(label)
        compact = tool.fills_page
        self._tool_header.setDirection(QBoxLayout.LeftToRight if compact else QBoxLayout.TopToBottom)
        self._tool_header.setSpacing(20 if compact else 12)
        self._tool_layout.setContentsMargins(*((24, 12, 24, 12) if compact else (32, 24, 32, 24)))
        if tool.fills_page:
            self._tool_holder.addWidget(tool, 1)
        else:
            self._tool_holder.addWidget(tool)
            self._tool_holder.addStretch(1)
        tool.show()
        self._stack.setCurrentWidget(self._tool_page)

    def _leave_current_tool(self) -> bool:
        """Close the open tool, unless it is still running (then say so and stay)."""
        worker = getattr(self._current_tool, "_worker", None)
        if worker is not None and worker.isRunning():
            QMessageBox.information(self, "Still working", "This tool is still running. Wait for it to finish, then go back.")
            return False
        self._discard_current_tool()
        return True

    def show_home(self) -> None:
        if self._leave_current_tool():
            self._stack.setCurrentWidget(self._home)

    def _discard_current_tool(self) -> None:
        tool, self._current_tool = self._current_tool, None
        if tool is not None:
            while self._tool_holder.count():
                self._tool_holder.takeAt(0)
            tool.hide()
            tool.deleteLater()
