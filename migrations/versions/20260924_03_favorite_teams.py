"""Store each user's favorite NBA teams."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260924_03"
down_revision = "20260924_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "favorite_teams",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("team_abbr", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "team_abbr"),
        sa.CheckConstraint("team_abbr IN ('ATL','BOS','BKN','CHA','CHI','CLE','DAL','DEN','DET','GSW','HOU','IND','LAC','LAL','MEM','MIA','MIL','MIN','NOP','NYK','OKC','ORL','PHI','PHX','POR','SAC','SAS','TOR','UTA','WAS')", name="ck_favorite_teams_abbr"),
    )
    op.execute(sa.text('ALTER TABLE "favorite_teams" ENABLE ROW LEVEL SECURITY'))


def downgrade():
    op.drop_table("favorite_teams")
