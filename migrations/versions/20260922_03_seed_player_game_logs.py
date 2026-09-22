"""Preserve legacy player-game log history during DuckDB transfer.

Revision ID: 20260922_03
Revises: 20260922_02
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260922_03"
down_revision = "20260922_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "seed_player_game_logs",
        sa.Column("season_id", sa.BigInteger()), sa.Column("player_id", sa.BigInteger()),
        sa.Column("game_id", sa.Text()), sa.Column("game_date", sa.Text()), sa.Column("matchup", sa.Text()),
        sa.Column("wl", sa.Text()), sa.Column("min", sa.BigInteger()), sa.Column("fgm", sa.BigInteger()),
        sa.Column("fga", sa.BigInteger()), sa.Column("fg_pct", sa.Double()), sa.Column("fg3m", sa.BigInteger()),
        sa.Column("fg3a", sa.BigInteger()), sa.Column("fg3_pct", sa.Double()), sa.Column("ftm", sa.BigInteger()),
        sa.Column("fta", sa.BigInteger()), sa.Column("ft_pct", sa.Double()), sa.Column("oreb", sa.BigInteger()),
        sa.Column("dreb", sa.BigInteger()), sa.Column("reb", sa.BigInteger()), sa.Column("ast", sa.BigInteger()),
        sa.Column("stl", sa.BigInteger()), sa.Column("blk", sa.BigInteger()), sa.Column("tov", sa.BigInteger()),
        sa.Column("pf", sa.BigInteger()), sa.Column("pts", sa.BigInteger()), sa.Column("plus_minus", sa.BigInteger()),
        sa.Column("video_available", sa.BigInteger()), sa.Column("player_id_1", sa.BigInteger()),
    )
    op.create_index("ix_seed_player_game_logs_game_id", "seed_player_game_logs", ["game_id"])
    op.create_index("ix_seed_player_game_logs_player_id_game_date", "seed_player_game_logs", ["player_id", "game_date"])


def downgrade() -> None:
    op.drop_table("seed_player_game_logs")
