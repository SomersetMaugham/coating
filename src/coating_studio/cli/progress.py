"""Cancellation, time limits and JSONL progress for long CLI commands (docs/CLI_PLAN.md, section 5).

All stop requests (Ctrl-C, SIGTERM, ``--timeout``) set one ``threading.Event``; the engine progress callbacks
return True once it is set, so the optimiser / tolerance loop stops and returns its best partial result.
"""

from __future__ import annotations

import signal
import sys
import threading
import time

from coating_studio.cli.output import dumps


class RunControl:
    """Stop event + deadline + throttled JSONL progress on stderr."""

    def __init__(self, timeout=None, progress=False, progress_interval=1.0, command="", stream=None):
        self.stop_event = threading.Event()
        self.t0 = time.monotonic()
        self.deadline = None if timeout is None else self.t0 + float(timeout)
        self.progress = progress
        self.interval = float(progress_interval)
        self.command = command
        self.stream = stream if stream is not None else sys.stderr
        self._last_emit = -1e9
        self.timed_out = False

    def elapsed(self):
        return time.monotonic() - self.t0

    def should_stop(self):
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.timed_out = True
            self.stop_event.set()
        return self.stop_event.is_set()

    def emit(self, payload, force=False):
        if not self.progress:
            return
        now = time.monotonic()
        if not force and now - self._last_emit < self.interval:
            return
        self._last_emit = now
        line = {"event": "progress", "command": self.command, **payload, "elapsed_s": round(self.elapsed(), 3)}
        self.stream.write(dumps(line) + "\n")
        self.stream.flush()

    # -- engine callbacks ----------------------------------------------------
    def optimize_callback(self, extra=None):
        def cb(info):
            if info.get("stage") == "done":  # final notification; not a progress line
                return False
            self.emit({k: v for k, v in info.items() if k != "history"} | (extra or {}))
            return self.should_stop()
        return cb

    def tolerance_callback(self, extra=None):
        def cb(done, total):
            self.emit({"done": done, "total": total} | (extra or {}), force=done == total)
            # run_tolerance calls back *after* adding sample ``done``; stopping on the last one would mark a
            # complete run as stopped.
            return False if done >= total else self.should_stop()
        return cb


class signal_handlers:
    """Route SIGINT (and SIGTERM on POSIX) to ``control.stop_event``; restore the previous handlers on exit.

    Installed only in the main thread (signal handlers cannot be set elsewhere).  A second Ctrl-C restores
    the default handler, so it interrupts immediately."""

    def __init__(self, control: RunControl):
        self.control = control
        self.saved = {}

    def _handler(self, signum, frame):
        self.control.stop_event.set()
        signal.signal(signum, self.saved.get(signum, signal.SIG_DFL)
                      if signum != signal.SIGINT else signal.default_int_handler)

    def __enter__(self):
        if threading.current_thread() is not threading.main_thread():
            return self
        sigs = [signal.SIGINT] + ([signal.SIGTERM] if hasattr(signal, "SIGTERM") and sys.platform != "win32" else [])
        for s in sigs:
            self.saved[s] = signal.getsignal(s)
            signal.signal(s, self._handler)
        return self

    def __exit__(self, *exc):
        for s, h in self.saved.items():
            signal.signal(s, h)
        return False
