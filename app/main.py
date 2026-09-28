"""Compatibility launcher for the desktop application.

The project no longer exposes a FastAPI server. Use ``python main.py`` from the
project root; this module remains so older shortcuts can use ``python -m app.main``.
"""

from main import run


if __name__ == "__main__":
    raise SystemExit(run())
