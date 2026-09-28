from __future__ import annotations

import shutil
import subprocess
import importlib.util
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.models import engine


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str


def _resolve_binary(value: str) -> str | None:
    candidate = Path(value)
    if candidate.is_file():
        return str(candidate)
    return shutil.which(value)


def _binary_check(name: str, configured: str) -> HealthCheck:
    resolved = _resolve_binary(configured)
    if not resolved:
        return HealthCheck(name, False, f"Not found: {configured}")
    try:
        result = subprocess.run(
            [resolved, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError as exc:
        return HealthCheck(name, False, str(exc))
    lines = (result.stdout or result.stderr).splitlines()
    detail = lines[0] if lines else "No version output"
    return HealthCheck(name, result.returncode == 0, detail)


def run_health_checks() -> list[HealthCheck]:
    checks = [
        _binary_check("ffmpeg", settings.ffmpeg_binary),
        _binary_check("ffprobe", settings.ffprobe_binary),
        HealthCheck(
            "faster-whisper",
            importlib.util.find_spec("faster_whisper") is not None,
            (
                "Installed"
                if importlib.util.find_spec("faster_whisper") is not None
                else "Optional dependency is not installed"
            ),
        ),
    ]
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks.append(HealthCheck("database", True, settings.database_url))
    except Exception as exc:
        checks.append(HealthCheck("database", False, str(exc)))
    for name, folder in (
        ("uploads", settings.upload_folder),
        ("outputs", settings.output_folder),
        ("data", settings.data_folder),
        ("cache", settings.cache_folder),
    ):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            checks.append(HealthCheck(name, True, str(folder.resolve())))
        except OSError as exc:
            checks.append(HealthCheck(name, False, str(exc)))
    return checks


def health_report() -> list[dict]:
    return [asdict(item) for item in run_health_checks()]
