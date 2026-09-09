"""
002_add_migration_tracking

Add migration tracking metadata table to record migration history.

This table tracks when migrations were applied, by whom, and any
relevant metadata. Serves as proof that the migration system is working.

Revision ID: 002
Revises: 001
Create Date: 2025-02-26
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add migration tracking table.

    Creates a table to track migration history, including:
    - Migration ID and name
    - Applied timestamp
    - Applied by (user or system)
    - Execution time and status
    """
    op.create_table(
        "_migrations_meta",
        sa.Column("migration_id", sa.String(64), primary_key=True),
        sa.Column("migration_name", sa.String(255), nullable=False),
        sa.Column("applied_at", sa.String(32), nullable=False),
        sa.Column("applied_by", sa.String(255), nullable=False),
        sa.Column("execution_time_ms", sa.Integer, default=0),
        sa.Column("status", sa.String(32), default="applied"),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("idx_migrations_meta_applied_at", "_migrations_meta", ["applied_at"])

    # Record this migration being applied
    op.execute(
        """
        INSERT INTO _migrations_meta
        (migration_id, migration_name, applied_at, applied_by, status)
        VALUES ('002', 'add_migration_tracking',
                datetime('now'), 'system', 'applied')
        """
    )


def downgrade() -> None:
    """
    Remove migration tracking table.

    Drops the migration metadata tracking table. Note that the migration
    history will be lost, so you may want to export it before downgrading.
    """
    op.drop_index("idx_migrations_meta_applied_at")
    op.drop_table("_migrations_meta")
