"""Repair adopted legacy schemas and add transactional project revisions.

Revision ID: 7c1e4d2a9100
Revises: beb1f4933f58
"""
from alembic import op
import sqlalchemy as sa

revision = "7c1e4d2a9100"
down_revision = "beb1f4933f58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    # Refuse ambiguous repairs rather than discard or silently reassign user data.
    duplicate = connection.execute(sa.text(
        "SELECT 1 FROM analytics_snapshots WHERE period_start IS NOT NULL AND period_end IS NOT NULL "
        "GROUP BY account_id, period_start, period_end HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("Duplicate analytics periods require review; no rows were removed")
    foreign_keys = {
        "videos": ("project_id", "projects", "SET NULL"),
        "posts": ("account_id", "connected_accounts", "SET NULL"),
        "content_ideas": ("project_id", "projects", "SET NULL"),
    }
    for table, (column, target, _action) in foreign_keys.items():
        orphan = connection.execute(sa.text(
            f"SELECT 1 FROM {table} t LEFT JOIN {target} p ON p.id=t.{column} "
            f"WHERE t.{column} IS NOT NULL AND p.id IS NULL LIMIT 1"
        )).first()
        if orphan:
            raise RuntimeError(f"Orphaned {table}.{column} requires review; no rows were removed")

    for table, column in (("posts", "retry_count"),
                          ("analytics_snapshots", "raw_schema_version"),
                          ("trend_snapshots", "raw_schema_version")):
        connection.execute(sa.text(f"UPDATE {table} SET {column}=:value WHERE {column} IS NULL"),
                           {"value": 0 if column == "retry_count" else 1})

    for table in ("videos", "posts", "content_ideas", "analytics_snapshots", "trend_snapshots"):
        columns = {item["name"]: item for item in inspector.get_columns(table)}
        missing_fk = table in foreign_keys and not any(
            item["constrained_columns"] == [foreign_keys[table][0]]
            for item in inspector.get_foreign_keys(table))
        null_column = "retry_count" if table == "posts" else "raw_schema_version"
        fix_null = null_column in columns and columns[null_column]["nullable"]
        missing_unique = table == "analytics_snapshots" and not any(
            item["column_names"] == ["account_id", "period_start", "period_end"]
            for item in inspector.get_unique_constraints(table))
        if missing_fk or fix_null or missing_unique:
            with op.batch_alter_table(table, recreate="always") as batch:
                if missing_fk:
                    column, target, action = foreign_keys[table]
                    batch.create_foreign_key(f"fk_{table}_{column}", target, [column], ["id"], ondelete=action)
                if fix_null:
                    batch.alter_column(null_column, existing_type=sa.Integer(), nullable=False)
                if missing_unique:
                    batch.create_unique_constraint("uq_analytics_period", ["account_id", "period_start", "period_end"])

    for table, column in (("videos", "project_id"), ("posts", "account_id"),
                          ("posts", "scheduled_at"), ("content_ideas", "project_id"),
                          ("analytics_snapshots", "captured_at"), ("trend_snapshots", "captured_at")):
        name = f"ix_{table}_{column}"
        if name not in {item["name"] for item in sa.inspect(connection).get_indexes(table)}:
            op.create_index(name, table, [column])
    if "draft_revision" not in {item["name"] for item in sa.inspect(connection).get_columns("projects")}:
        op.add_column("projects", sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="0"))
    if "project_revisions" not in sa.inspect(connection).get_table_names():
        op.create_table("project_revisions",
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("revision", sa.Integer(), primary_key=True),
            sa.Column("state", sa.JSON(), nullable=False),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    if connection.dialect.name == "sqlite" and connection.exec_driver_sql("PRAGMA foreign_key_check").first():
        raise RuntimeError("Foreign-key check failed; migration must be restored from its backup")


def downgrade() -> None:
    op.drop_table("project_revisions")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("draft_revision")
    # Corrected baseline constraints intentionally remain; downgrade does not recreate drift.
