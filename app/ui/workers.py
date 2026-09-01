from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.result = None
        self.error = None

    def run(self) -> None:
        try:
            self.result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            self.error = str(exc)
            self.failed.emit(self.error)
        else:
            self.finished_ok.emit(self.result)
