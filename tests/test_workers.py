from PySide6.QtCore import QCoreApplication

from app.ui.workers import Worker

_app = QCoreApplication.instance() or QCoreApplication([])


def test_worker_runs_function_and_stores_result():
    worker = Worker(lambda a, b: a + b, 2, 3)
    worker.start()
    worker.wait()
    assert worker.result == 5
    assert worker.error is None


def test_worker_captures_exception_message():
    def boom():
        raise ValueError("bad input")

    worker = Worker(boom)
    worker.start()
    worker.wait()
    assert worker.result is None
    assert worker.error == "bad input"
