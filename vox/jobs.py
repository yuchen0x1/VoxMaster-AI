import threading
from PySide6.QtCore import QThread, Signal


class Worker(QThread):
    progress = Signal(float, str)
    succeeded = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.cancel = threading.Event()

    def run(self):
        try:
            result = self.action(self.cancel, self.progress.emit)
            if self.cancel.is_set():
                self.cancelled.emit()
            else:
                self.succeeded.emit(result)
        except Exception as exc:
            if self.cancel.is_set() or isinstance(exc, InterruptedError):
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc) or type(exc).__name__)
