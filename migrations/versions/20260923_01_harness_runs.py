"""Durable, independently inspectable MCP harness runs."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260923_01"
down_revision = "20260922_03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "harness_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("stop_reason", sa.Text()),
        sa.Column("record_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name="ck_harness_runs_status"),
    )
    op.create_index("ix_harness_runs_created_at", "harness_runs", ["created_at"])


def downgrade():
    op.drop_table("harness_runs")
