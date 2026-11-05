from __future__ import annotations

import logging
import sqlite3
import os
import json
import hashlib
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.config import RESOURCE_ROOT, settings
from app.models import Base, engine, prepare_legacy_schema

logger = logging.getLogger(__name__)


class DatabaseSafetyError(RuntimeError):
    """Startup must stop without discarding the user's database."""


def _check_sqlite(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("Integrity check failed")
    except sqlite3.Error as exc:
        raise DatabaseSafetyError(
            "База данных недоступна или повреждена. Исходный файл сохранён. "
            "Выберите проверенную резервную копию для восстановления."
        ) from exc


def _marker_path(database: Path) -> Path:
    key = hashlib.sha256(str(database.resolve()).encode()).hexdigest()[:16]
    return settings.data_folder / f"migration-{key}.json"


def _write_marker(database: Path, backup: Path | None) -> None:
    marker = _marker_path(database)
    temporary = marker.with_suffix(".part")
    with temporary.open("w", encoding="utf-8") as destination:
        json.dump({"database": str(database), "backup": str(backup) if backup else None,
                   "empty": backup is None}, destination)
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(temporary, marker)


def _preserve_database(database: Path) -> Path | None:
    recovery = settings.data_folder / "recovery"
    recovery.mkdir(parents=True, exist_ok=True)
    preserved = recovery / f"{database.name}-{uuid.uuid4().hex}.before-restore"
    engine.dispose()
    if database.exists():
        os.replace(database, preserved)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            os.replace(sidecar, Path(str(preserved) + suffix))
    return preserved if preserved.exists() else None


def restore_database(backup: Path, *, require_application_schema: bool = True) -> Path | None:
    """Validate a backup first; preserve the replaced DB and sidecars for recovery."""
    database = _sqlite_database_path()
    if database is None:
        raise DatabaseSafetyError("Автоматическое восстановление поддерживается только для SQLite.")
    backup = Path(backup).resolve()
    if backup == database:
        raise DatabaseSafetyError("Выберите резервную копию, а не текущую базу данных.")
    _check_sqlite(backup)
    if require_application_schema:
        with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"videos", "posts"}.issubset(tables):
            raise DatabaseSafetyError("Выбранный файл не является резервной копией vyro.")
    temporary = database.with_name(database.name + ".restore-" + uuid.uuid4().hex)
    try:
        with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(temporary)) as target:
            source.backup(target)
        _check_sqlite(temporary)
        preserved = _preserve_database(database)
        os.replace(temporary, database)
    finally:
        temporary.unlink(missing_ok=True)
    logger.warning("Restored database; previous file preserved at %s", preserved)
    _marker_path(database).unlink(missing_ok=True)
    return preserved


def recover_interrupted_migration() -> bool:
    database = _sqlite_database_path()
    if database is None or not _marker_path(database).exists():
        return False
    marker = _marker_path(database)
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
        if Path(state["database"]).resolve() != database:
            raise ValueError("Unexpected migration recovery path")
        if state["backup"] is None and state.get("empty") is True:
            _preserve_database(database)
            marker.unlink(missing_ok=True)
            return True
        backup = Path(state["backup"]).resolve()
        if backup.parent != (settings.data_folder / "backups").resolve():
            raise ValueError("Unexpected migration backup path")
        restore_database(backup, require_application_schema=False)
        marker.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError) as exc:
        raise DatabaseSafetyError("Не удалось восстановить прерванную миграцию. Резервная копия сохранена.") from exc
    return True


def alembic_config() -> Config:
    config = Config(str(RESOURCE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(RESOURCE_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    return config


def current_revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def validate_schema() -> None:
    """A revision stamp alone is not evidence that a legacy schema is complete."""
    from alembic.autogenerate import compare_metadata
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    if differences:
        logger.error("Database schema differs from application metadata: %s", differences)
        raise DatabaseSafetyError("Структура базы данных не соответствует версии vyro. Файл сохранён; восстановите проверенную резервную копию.")


def _sqlite_database_path() -> Path | None:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def backup_database() -> Path | None:
    source = _sqlite_database_path()
    if source is None or not source.is_file() or source.stat().st_size == 0:
        return None
    _check_sqlite(source)
    folder = settings.data_folder / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = folder / f"{source.stem}-before-migration-{timestamp}-{uuid.uuid4().hex[:8]}.sqlite3.bak"
    temporary = destination.with_suffix(".part")
    try:
        with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5)) as original, closing(sqlite3.connect(temporary)) as target:
            original.backup(target)
        _check_sqlite(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    logger.info("Created database backup at %s", destination)
    return destination


def upgrade_database() -> None:
    settings.data_folder.mkdir(parents=True, exist_ok=True)
    recover_interrupted_migration()
    database = _sqlite_database_path()
    if database and database.exists() and database.stat().st_size:
        _check_sqlite(database)
    config = alembic_config()
    existing_tables = set(inspect(engine).get_table_names())
    has_version_table = "alembic_version" in existing_tables
    revision = current_revision() if has_version_table else None
    target = head_revision()

    if revision == target:
        validate_schema()
        return

    backup = backup_database() if existing_tables else None
    if database:
        _write_marker(database, backup)
    try:
        if existing_tables and not has_version_table:
            logger.info("Adopting legacy database at the historical baseline")
            prepare_legacy_schema()
            command.stamp(config, "beb1f4933f58")
        logger.info("Upgrading database from %s to %s", revision or "empty", target)
        command.upgrade(config, "head")
        validate_schema()
        if database:
            _check_sqlite(database)
    except Exception as exc:
        logger.exception("Database migration failed")
        if backup:
            restore_database(backup)
            _marker_path(database).unlink(missing_ok=True)
        elif database:
            _preserve_database(database)
            _marker_path(database).unlink(missing_ok=True)
        raise DatabaseSafetyError(
            "Обновление базы данных не завершено. Предыдущая версия восстановлена из резервной копии. "
            "Данные не удалены; подробности записаны в журнал."
            if backup else "Не удалось создать базу данных. Проверьте доступ к папке данных."
        ) from exc
    if database:
        _marker_path(database).unlink(missing_ok=True)
