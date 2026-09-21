import os
import threading

from PySide6.QtCore import QObject, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from app.core.updates import check_for_update
from app.core.version import APP_VERSION
from app.ui.theme import icon

# Set to any non-empty value to skip the (optional) update check entirely.
DISABLE_ENV = "PDF_EDITOR_NO_UPDATE_CHECK"


class _Result(QObject):
    """Carries the check's answer from its thread back to the GUI thread."""

    done = Signal(dict)


class UpdateBanner(QFrame):
    """"A newer version is available" strip, like the web app's. Hidden unless the
    check finds a newer release; a failed check (offline, GitHub down) is simply
    invisible. Dismissing hides it until the next launch."""

    def __init__(self, check=check_for_update, current_version: str = APP_VERSION, parent=None):
        super().__init__(parent)
        self._check = check
        self._current = current_version
        self._release_url: str | None = None
        self._result = _Result(self)
        self._result.done.connect(self._on_result)
        self.setObjectName("updateBanner")
        self.setVisible(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 8, 24, 8)
        row.setSpacing(12)
        self._label = QLabel()
        row.addWidget(self._label)
        self.download_button = QPushButton("Download update")
        self.download_button.setIcon(icon("arrow-square-out", "#1d4ed8", 16))
        self.download_button.setCursor(Qt.PointingHandCursor)
        self.download_button.clicked.connect(self._open_release)
        row.addWidget(self.download_button)
        row.addStretch(1)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setObjectName("bannerDismiss")
        self.dismiss_button.setCursor(Qt.PointingHandCursor)
        self.dismiss_button.clicked.connect(self.hide)
        row.addWidget(self.dismiss_button)

    def start(self) -> None:
        """Ask in the background; the window never waits on the network."""
        if os.environ.get(DISABLE_ENV):
            return

        def work() -> None:
            try:
                info = self._check(self._current)
            except Exception:
                info = {}
            try:
                self._result.done.emit(info)
            except RuntimeError:
                pass  # the window was closed while this was running

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_result(self, info: dict) -> None:
        if not info.get("update_available") or not info.get("latest"):
            return
        self._release_url = info.get("release_url")
        self._label.setText(f"A newer version (v{info['latest']}) is available — you're on v{info.get('version', self._current)}.")
        self.download_button.setVisible(bool(self._release_url))
        self.setVisible(True)

    def _open_release(self) -> None:
        if self._release_url:
            QDesktopServices.openUrl(QUrl(self._release_url))
