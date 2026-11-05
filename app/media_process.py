"""Bounded, cancellable subprocess execution shared by local media operations."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import subprocess
import threading
import time


class VideoProcessingError(RuntimeError):
    """A readable media processing failure."""


class RenderCancelled(VideoProcessingError):
    """Cancellation requested by the user."""


@dataclass
class RenderControl:
    timeout: float = 3600
    cancelled: threading.Event = field(default_factory=threading.Event)
    started: float = field(default_factory=time.monotonic)

    def cancel(self) -> None:
        self.cancelled.set()

    def check(self) -> None:
        if self.cancelled.is_set():
            raise RenderCancelled("Media processing cancelled")
        if time.monotonic() - self.started >= self.timeout:
            raise VideoProcessingError("Media processing exceeded its time limit")


_control: ContextVar[RenderControl | None] = ContextVar("media_control", default=None)


def current_control() -> RenderControl | None:
    return _control.get()


@contextmanager
def media_operation(control: RenderControl):
    token = _control.set(control)
    try:
        control.check()
        yield
    finally:
        _control.reset(token)


def execute(command: list[str], timeout: float = 1800, progress=None, cwd=None) -> str:
    """Drain both pipes concurrently; retain only bounded output and reap on every exit."""
    control = _control.get()
    if control:
        control.check()
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=flags, cwd=cwd)
    except OSError as exc:
        raise VideoProcessingError(f"Could not start media tool: {command[0]}") from exc
    stdout, stderr = deque(maxlen=64), deque(maxlen=64)
    latest = [0.0]

    def drain(pipe, target, parse=False):
        try:
            while chunk := pipe.read1(4096):
                target.append(chunk)
                if parse:
                    # Progress lines can straddle reads; keep one small pending fragment.
                    drain_progress(chunk)
        finally:
            pipe.close()

    pending = [b""]

    def drain_progress(chunk):
        lines = (pending[0] + chunk).split(b"\n")
        pending[0] = lines.pop()[-4096:]
        for line in lines:
            if line.startswith(b"out_time_us="):
                try:
                    latest[0] = max(latest[0], int(line.split(b"=", 1)[1]) / 1_000_000)
                except ValueError:
                    pass

    readers = [threading.Thread(target=drain, args=(process.stdout, stdout, bool(progress))),
               threading.Thread(target=drain, args=(process.stderr, stderr))]
    for reader in readers:
        reader.start()
    started = time.monotonic()
    try:
        while process.poll() is None:
            if control:
                control.check()
            if time.monotonic() - started >= timeout:
                raise VideoProcessingError("Media tool exceeded its time limit")
            if progress:
                progress(latest[0])
            time.sleep(0.05)
        if control:
            control.check()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
        process.wait()
        for reader in readers:
            reader.join()
    if process.returncode:
        detail = b"".join(stderr).decode("utf-8", errors="replace").strip()
        raise VideoProcessingError("Media tool could not process this file.\n" + detail[-4000:])
    if progress:
        progress(latest[0])
    return b"".join(stdout).decode("utf-8", errors="replace")
