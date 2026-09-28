"""Build an onedir desktop bundle on the current operating system."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> int:
    root = Path(__file__).resolve().parent
    debug = "--console" in sys.argv
    bundle_name = "vyro-debug" if debug else "vyro"
    if importlib.util.find_spec("PyInstaller") is None:
        print("Install the build dependency: python -m pip install -r requirements-build.txt")
        return 2
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--console" if debug else "--windowed", "--name", bundle_name,
        "--add-data", f"{root / 'alembic.ini'}{os.pathsep}.",
        "--add-data", f"{root / 'migrations'}{os.pathsep}migrations",
        "--collect-submodules", "sqlalchemy.dialects",
        "--collect-submodules", "keyring.backends",
        "--hidden-import", "logging.config",
    ]
    if importlib.util.find_spec("faster_whisper") is not None:
        command += ["--collect-all", "faster_whisper"]
    command.append(str(root / "main.py"))
    # External toolchains on PATH can shadow Qt's system DLL dependencies.
    build_environment = {**os.environ}
    build_environment["PATH"] = os.pathsep.join(
        entry for entry in os.environ.get("PATH", "").split(os.pathsep)
        if "poppler" not in entry.lower()
    )
    subprocess.run(command, cwd=root, env=build_environment, check=True)
    executable = root / "dist" / bundle_name / (f"{bundle_name}.exe" if sys.platform == "win32" else bundle_name)
    with tempfile.TemporaryDirectory(prefix="vyro-bundle-") as temp_dir:
        isolated = Path(temp_dir)
        environment = {**os.environ,
            "QT_QPA_PLATFORM": "offscreen",
            "DATABASE_URL": f"sqlite:///{(isolated / 'check.sqlite3').as_posix()}",
            "DATA_FOLDER": str(isolated / "data"),
            "CACHE_FOLDER": str(isolated / "cache"),
            "UPLOAD_FOLDER": str(isolated / "uploads"),
            "OUTPUT_FOLDER": str(isolated / "outputs"),
            "TAISLY_API_KEY": "", "AI_PROVIDER": "mock", "TRANSCRIPTION_PROVIDER": "mock",
            "TRENDS_MOCK_MODE": "true", "SCHEDULER_ENABLED": "false",
        }
        try:
            result = subprocess.run([str(executable), "--self-test"], cwd=root,
                                    env=environment, capture_output=True, text=True,
                                    timeout=30, check=False)
        except subprocess.TimeoutExpired as exc:
            marker = isolated / "data" / "self-test-stage.txt"
            stage = marker.read_text(encoding="utf-8") if marker.is_file() else "before startup"
            raise RuntimeError(f"Bundle self-test timed out at: {stage}") from exc
        if result.returncode:
            raise RuntimeError(f"Bundle self-test failed ({result.returncode}): {result.stderr.strip()}")
    print(f"Bundle ready: {root / 'dist' / bundle_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
