from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


class _WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(object)
    finished = pyqtSignal()


class _Worker(QRunnable):
    def __init__(self, fn: Callable, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = _WorkerSignals()

    def run(self) -> None:  # noqa: D401 - Qt entrypoint
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:  # noqa: BLE001 - propagate to UI thread
            traceback.print_exc()
            self.signals.error.emit(exc)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class TaskRunner(QObject):
    task_started = pyqtSignal(str)
    task_finished = pyqtSignal(str)
    task_failed = pyqtSignal(str, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()

    def run(
        self,
        fn: Callable,
        *args: Any,
        description: str = "",
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
        **kwargs: Any,
    ) -> None:
        worker = _Worker(fn, *args, **kwargs)

        if description:
            self.task_started.emit(description)

        if on_result is not None:
            worker.signals.result.connect(on_result)

        def _handle_error(exc: Exception) -> None:
            if on_error is not None:
                on_error(exc)
            if description:
                self.task_failed.emit(description, exc)

        worker.signals.error.connect(_handle_error)

        def _handle_finished() -> None:
            if on_finished is not None:
                on_finished()
            if description:
                self.task_finished.emit(description)

        worker.signals.finished.connect(_handle_finished)

        self._pool.start(worker)
