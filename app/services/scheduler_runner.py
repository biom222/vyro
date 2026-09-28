from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


class LocalScheduler:
    """Run a short scheduler tick periodically without blocking the Qt event loop."""

    def __init__(
        self,
        run_once: Callable[[], list[int]],
        interval_seconds: float = 15.0,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Scheduler interval must be positive")
        self._run_once = run_once
        self._interval = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="vyro-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Local publication scheduler started")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, timeout))
        if self._thread and not self._thread.is_alive():
            self._thread = None
        logger.info("Local publication scheduler stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                published_ids = self._run_once()
                if published_ids:
                    logger.info("Scheduler processed posts: %s", published_ids)
            except Exception:
                logger.exception("Unexpected scheduler tick failure")
            self._stop_event.wait(self._interval)
