"""
001_initial_schema

Initial Thomas database schema with core tables.

Includes:
- preferences: User settings and model configurations
- runs: Execution tracking and telemetry
- events: Run event logs
- search_history: Query history and bookmarks
- autonomy tables: Job scheduling and approval tracking
- asset_studio tables: Asset generation jobs

Revision ID: 001
Revises: None
Create Date: 2025-02-26

This migration serves as the baseline schema. Existing databases will be
stamped with this version on first run (no actual tables created).
"""

import sqlalchemy as sa
from alembic import op

# Migration metadata
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Apply initial schema.

    Creates all core Thomas tables. For existing databases,
    use the migrate helper which will skip table creation and
    stamp the version instead.
    """

    # Preferences table
    op.create_table(
        "preferences",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("preferences_json", sa.Text, nullable=False),
    )
    op.create_index("idx_preferences_user_id", "preferences", ["user_id"])

    # Preferences metadata
    op.create_table(
        "preferences_meta",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.Text, nullable=True),
    )

    # Thread preferences (thread-scoped memory overrides)
    op.create_table(
        "thread_preferences",
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("preferences_json", sa.Text, nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_index(
        "idx_thread_preferences_user_thread",
        "thread_preferences",
        ["user_id", "thread_id"],
    )

    # Runs table (observability/run_db.py)
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(255), primary_key=True),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("ended_at", sa.String(32), nullable=True),
        sa.Column("ok", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("meta_json", sa.Text, nullable=True),
        sa.Column("last_seq", sa.Integer, default=0),
    )

    # Run events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(255), nullable=False),
        sa.Column("t_ms", sa.Integer, nullable=True),
        sa.Column("seq", sa.Integer, nullable=True),
        sa.Column("event_type", sa.String(128), nullable=True),
        sa.Column("payload_json", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"]),
    )
    op.create_index("idx_events_run_seq", "events", ["run_id", "seq", "id"])

    # Search history table (core/search_history.py)
    op.create_table(
        "search_history_meta",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", sa.String(1024), nullable=True),
    )

    op.create_table(
        "turn_map",
        sa.Column("turn_id", sa.String(36), primary_key=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("timestamp", sa.String(32), nullable=True),
    )

    op.create_table(
        "turn_index",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("turn_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
    )
    op.create_index("idx_turn_index_turn_id", "turn_index", ["turn_id"])
    op.create_index("idx_turn_index_sequence", "turn_index", ["sequence"])

    op.create_table(
        "query_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("timestamp", sa.String(32), nullable=False),
        sa.Column("turn_id", sa.String(36), nullable=True),
    )

    op.create_table(
        "bookmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    op.create_table(
        "saved_searches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    # Autonomy tables (autonomy/store.py)
    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer, nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("job_type", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer, default=0),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("idx_jobs_status", "jobs", ["status"])
    op.create_index("idx_jobs_created_at", "jobs", ["created_at"])

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("requested_at", sa.String(32), nullable=False),
        sa.Column("approved_by", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
    )
    op.create_index("idx_approvals_job_id", "approvals", ["job_id"])

    op.create_table(
        "audit",
        sa.Column("audit_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("timestamp", sa.String(32), nullable=False),
        sa.Column("details_json", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
    )
    op.create_index("idx_audit_job_id", "audit", ["job_id"])
    op.create_index("idx_audit_timestamp", "audit", ["timestamp"])

    op.create_table(
        "autonomy_messages",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
    )

    op.create_table(
        "briefings",
        sa.Column("briefing_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.job_id"]),
    )

    # Asset Studio tables (asset_studio/job_store.py)
    op.create_table(
        "asset_studio_jobs",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Integer, default=0),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.String(32), nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
    )
    op.create_index("idx_asset_studio_jobs_status", "asset_studio_jobs", ["status"])

    op.create_table(
        "asset_studio_job_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("timestamp", sa.String(32), nullable=False),
        sa.Column("data_json", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["asset_studio_jobs.job_id"]),
    )

    op.create_table(
        "asset_studio_templates",
        sa.Column("template_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    op.create_table(
        "asset_studio_webhook_configs",
        sa.Column("webhook_id", sa.String(36), primary_key=True),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("events", sa.String(512), nullable=False),
        sa.Column("active", sa.Integer, default=1),
        sa.Column("created_at", sa.String(32), nullable=False),
    )

    op.create_table(
        "asset_studio_template_webhook_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), nullable=False),
        sa.Column("webhook_id", sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["asset_studio_templates.template_id"]),
        sa.ForeignKeyConstraint(["webhook_id"], ["asset_studio_webhook_configs.webhook_id"]),
    )


def downgrade() -> None:
    """
    Downgrade initial schema.

    WARNING: This drops all Thomas tables. Use with extreme caution.
    """
    # Asset Studio tables
    op.drop_table("asset_studio_template_webhook_configs")
    op.drop_table("asset_studio_webhook_configs")
    op.drop_table("asset_studio_templates")
    op.drop_table("asset_studio_job_events")
    op.drop_table("asset_studio_jobs")

    # Autonomy tables
    op.drop_table("briefings")
    op.drop_table("autonomy_messages")
    op.drop_table("audit")
    op.drop_table("approvals")
    op.drop_table("jobs")
    op.drop_table("schema_version")

    # Search history tables
    op.drop_table("saved_searches")
    op.drop_table("bookmarks")
    op.drop_table("query_history")
    op.drop_index("idx_turn_index_sequence")
    op.drop_index("idx_turn_index_turn_id")
    op.drop_table("turn_index")
    op.drop_table("turn_map")
    op.drop_table("search_history_meta")

    # Run tables
    op.drop_index("idx_events_run_seq")
    op.drop_table("events")
    op.drop_table("runs")

    # Preferences tables
    op.drop_index("idx_thread_preferences_user_thread")
    op.drop_table("thread_preferences")
    op.drop_table("preferences_meta")
    op.drop_index("idx_preferences_user_id")
    op.drop_table("preferences")
