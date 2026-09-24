"""Record which Supabase user owns each harness run; keep app tables off the Data API.

`user_id` is the Supabase Auth user id. It has no foreign key to `auth.users`:
that schema belongs to Supabase and is absent from disposable test databases.

Row Level Security with no policies denies Supabase's anon and authenticated
roles, whose publishable key ships to browsers. The application connects as
the table owner, which bypasses RLS, so its access is unchanged. Enabling is
idempotent where RLS was already turned on from the dashboard.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260924_01"
down_revision = "20260923_02"
branch_labels = None
depends_on = None

APP_TABLES = (
    "alembic_version", "analysis_runs", "box_scores_advanced_team", "box_scores_player", "box_scores_team",
    "evidence_packets", "games", "harness_runs", "ingestion_jobs", "lineup_stints", "play_by_play_events",
    "raw_responses", "seed_player_game_logs",
)


def upgrade():
    op.add_column("harness_runs", sa.Column("user_id", postgresql.UUID(as_uuid=False)))
    op.create_index("ix_harness_runs_user_id", "harness_runs", ["user_id", "created_at"])
    for table in APP_TABLES:
        op.execute(sa.text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))


def downgrade():
    # RLS stays enabled: turning it off would expose these tables to browser keys.
    op.drop_index("ix_harness_runs_user_id", table_name="harness_runs")
    op.drop_column("harness_runs", "user_id")
