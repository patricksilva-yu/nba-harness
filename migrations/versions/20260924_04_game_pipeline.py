"""Track each followed team's final through the post-game pipeline.

pending: the final is known; its stats are being loaded and checked.
loaded: box scores and play-by-play match the final score.
analyzed: the shared breakdown run exists.
failed: retries ran out; `last_error` says why.

The timestamps record how long the NBA took to publish complete stats.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260924_04"
down_revision = "20260924_03"
branch_labels = None
depends_on = None

UTC_NOW = sa.text("timezone('utc', now())")


def upgrade():
    op.create_table(
        "game_pipeline",
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.Column("last_error", sa.Text()),
        sa.Column("breakdown_run_id", sa.Text(), sa.ForeignKey("harness_runs.run_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.Column("loaded_at", sa.DateTime(timezone=True)),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'loaded', 'analyzed', 'failed')", name="ck_game_pipeline_status"),
    )
    op.create_index("ix_game_pipeline_due", "game_pipeline", ["status", "next_attempt_at"])
    op.execute(sa.text('ALTER TABLE "game_pipeline" ENABLE ROW LEVEL SECURITY'))


def downgrade():
    op.drop_table("game_pipeline")
