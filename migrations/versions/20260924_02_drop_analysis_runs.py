"""Drop analysis_runs: the removed deterministic agent was its only writer.

Harness runs are recorded in harness_runs. Downgrade restores an empty table.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260924_02"
down_revision = "20260924_01"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("analysis_runs")


def downgrade():
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="SET NULL")),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("memo_markdown", sa.Text(), nullable=False),
        sa.Column("packet_ids_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("timezone('utc', now())")),
    )
    op.create_index("ix_analysis_runs_game_created", "analysis_runs", ["game_id", "created_at"])
    op.execute(sa.text('ALTER TABLE "analysis_runs" ENABLE ROW LEVEL SECURITY'))
