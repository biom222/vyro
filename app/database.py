from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.config import RESOURCE_ROOT, settings
from app.models import engine, prepare_legacy_schema

logger = logging.getLogger(__name__)


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


def _sqlite_database_path() -> Path | None:
    url = make_url(settings.database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def backup_database() -> Path | None:
    source = _sqlite_database_path()
    if source is None or not source.is_file() or source.stat().st_size == 0:
        return None
    settings.data_folder.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = settings.data_folder / f"{source.stem}-before-migration-{timestamp}.sqlite3.bak"
    shutil.copy2(source, destination)
    logger.info("Created database backup at %s", destination)
    return destination


def upgrade_database() -> None:
    config = alembic_config()
    existing_tables = set(inspect(engine).get_table_names())
    has_version_table = "alembic_version" in existing_tables
    revision = current_revision() if has_version_table else None
    target = head_revision()

    if revision == target:
        return

    if existing_tables and not has_version_table:
        backup_database()
        logger.info("Adopting legacy database as Alembic baseline")
        prepare_legacy_schema()
        command.stamp(config, "head")
        return

    if revision is not None:
        backup_database()
    logger.info("Upgrading database from %s to %s", revision or "empty", target)
    command.upgrade(config, "head")
