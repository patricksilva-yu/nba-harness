"""Link follow-up harness runs into conversations."""

from alembic import op
import sqlalchemy as sa

revision = "20260923_02"
down_revision = "20260923_01"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("harness_runs", sa.Column("conversation_id", sa.Text()))
    op.add_column("harness_runs", sa.Column("parent_run_id", sa.Text()))
    op.create_foreign_key(
        "fk_harness_runs_parent_run_id", "harness_runs", "harness_runs", ["parent_run_id"], ["run_id"]
    )
    op.create_index("ix_harness_runs_conversation_id", "harness_runs", ["conversation_id", "created_at"])


def downgrade():
    op.drop_index("ix_harness_runs_conversation_id", table_name="harness_runs")
    op.drop_constraint("fk_harness_runs_parent_run_id", "harness_runs", type_="foreignkey")
    op.drop_column("harness_runs", "parent_run_id")
    op.drop_column("harness_runs", "conversation_id")
