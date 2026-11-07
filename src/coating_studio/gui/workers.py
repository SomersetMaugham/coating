"""Background workers.  Only plain data crosses threads (via Qt signals);
Matplotlib and widgets are touched exclusively from the GUI thread."""

from __future__ import annotations

import threading
import traceback

from PySide6.QtCore import QObject, QThread, Signal, Slot

from coating_studio.optimize import optimize
from coating_studio.tolerance import run_tolerance, run_tolerance_corners


class OptimizationWorker(QObject):
    progress = Signal(dict)
    finished = Signal(object)  # OptimizationResult
    failed = Signal(str)

    def __init__(self, project, settings):
        super().__init__()
        self.project = project.copy()
        self.settings = self.project.optimization if settings is None else settings
        self._stop = threading.Event()

    def request_stop(self):
        self._stop.set()

    @Slot()
    def run(self):
        try:
            def cb(info):
                # progress() is already throttled by the optimiser (~10 Hz)
                self.progress.emit({k: v for k, v in info.items()})
                return self._stop.is_set()

            res = optimize(self.project, self.settings, progress=cb, throttle_s=0.1)
            self.finished.emit(res)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{e}\n\n{traceback.format_exc(limit=3)}" if not str(e) else str(e))


class ToleranceWorker(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, project, f, band, corners=False):
        super().__init__()
        self.project = project.copy()
        self.f, self.band, self.corners = f, band, corners
        self._stop = threading.Event()

    def request_stop(self):
        self._stop.set()

    @Slot()
    def run(self):
        try:
            last = [0]

            def cb(k, n):
                if k - last[0] >= max(n // 50, 1) or k == n:
                    last[0] = k
                    self.progress.emit(k, n)
                return self._stop.is_set()

            if self.corners:  # every target corner; emits a tolerance.CornerResult
                res = run_tolerance_corners(self.project, self.f, progress=lambda k, n, _c, _nc: cb(k, n),
                                            should_stop=self._stop.is_set)
            else:
                res = run_tolerance(self.project, self.f, band=self.band, progress=cb)
            self.finished.emit(res)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def start_worker(worker, owner):
    """Move ``worker`` to a new QThread owned by ``owner`` and start it; returns the thread."""
    th = QThread(owner)
    worker.moveToThread(th)
    th.started.connect(worker.run)
    worker.finished.connect(th.quit)
    worker.failed.connect(th.quit)
    # The worker has no Qt parent, so Python owns it: the caller keeps a reference until the
    # thread has finished and then drops it.  (Also scheduling worker.deleteLater would delete
    # the C++ object twice.)  The thread itself is parented to ``owner``.
    th.finished.connect(th.deleteLater)
    th.start()
    return th
