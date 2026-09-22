"""Create the canonical PostgreSQL schema for NBA harness.

Revision ID: 20260922_01
Revises:
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260922_01"
down_revision = None
branch_labels = None
depends_on = None


UTC_NOW = sa.text("timezone('utc', now())")
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _statistics_columns() -> list[sa.Column]:
    return [
        sa.Column("fgm", sa.Double()),
        sa.Column("fga", sa.Double()),
        sa.Column("fg_pct", sa.Double()),
        sa.Column("fg3m", sa.Double()),
        sa.Column("fg3a", sa.Double()),
        sa.Column("fg3_pct", sa.Double()),
        sa.Column("ftm", sa.Double()),
        sa.Column("fta", sa.Double()),
        sa.Column("ft_pct", sa.Double()),
        sa.Column("oreb", sa.Double()),
        sa.Column("dreb", sa.Double()),
        sa.Column("reb", sa.Double()),
        sa.Column("ast", sa.Double()),
        sa.Column("stl", sa.Double()),
        sa.Column("blk", sa.Double()),
        sa.Column("tov", sa.Double()),
        sa.Column("pf", sa.Double()),
        sa.Column("pts", sa.Double()),
        sa.Column("plus_minus", sa.Double()),
    ]


def upgrade() -> None:
    # Raw capture intentionally has no foreign key: league-log requests can be
    # stored before a corresponding game has been normalized.
    op.create_table(
        "raw_responses",
        sa.Column("response_id", sa.Text(), primary_key=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("game_id", sa.Text()),
        sa.Column("request_json", JSONB, nullable=False),
        sa.Column("response_json", JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
    )
    op.create_index("ix_raw_responses_game_id", "raw_responses", ["game_id"])
    op.create_index("ix_raw_responses_fetched_at", "raw_responses", ["fetched_at"])

    op.create_table(
        "games",
        sa.Column("game_id", sa.Text(), primary_key=True),
        sa.Column("season_id", sa.Text()),
        sa.Column("game_date", sa.Date()),
        sa.Column("season_type", sa.Text()),
        sa.Column("home_team_id", sa.Text()),
        sa.Column("home_team_abbr", sa.Text()),
        sa.Column("home_team_name", sa.Text()),
        sa.Column("away_team_id", sa.Text()),
        sa.Column("away_team_abbr", sa.Text()),
        sa.Column("away_team_name", sa.Text()),
        sa.Column("home_score", sa.Integer()),
        sa.Column("away_score", sa.Integer()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("home_score IS NULL OR home_score >= 0", name="ck_games_home_score_nonnegative"),
        sa.CheckConstraint("away_score IS NULL OR away_score >= 0", name="ck_games_away_score_nonnegative"),
    )
    op.create_index("ix_games_game_date", "games", ["game_date"])
    op.create_index("ix_games_season_type_game_date", "games", ["season_type", "game_date"])

    op.create_table(
        "box_scores_team",
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("team_side", sa.Text(), primary_key=True),
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("team_abbr", sa.Text(), nullable=False),
        *_statistics_columns(),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("team_side IN ('home', 'away')", name="ck_box_scores_team_side"),
    )
    op.create_index("ix_box_scores_team_team_id", "box_scores_team", ["team_id"])

    op.create_table(
        "box_scores_player",
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("player_id", sa.Text(), primary_key=True),
        sa.Column("player_name", sa.Text()),
        sa.Column("team_abbr", sa.Text()),
        sa.Column("matchup", sa.Text()),
        sa.Column("minutes", sa.Double()),
        *_statistics_columns(),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("minutes IS NULL OR minutes >= 0", name="ck_box_scores_player_minutes_nonnegative"),
    )
    op.create_index("ix_box_scores_player_game_team", "box_scores_player", ["game_id", "team_abbr"])
    op.create_index("ix_box_scores_player_player_id", "box_scores_player", ["player_id"])

    op.create_table(
        "box_scores_advanced_team",
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("team_id", sa.Text(), primary_key=True),
        sa.Column("team_abbr", sa.Text(), nullable=False),
        sa.Column("minutes", sa.Double()),
        sa.Column("offensive_rating", sa.Double()),
        sa.Column("defensive_rating", sa.Double()),
        sa.Column("net_rating", sa.Double()),
        sa.Column("assist_pct", sa.Double()),
        sa.Column("assist_to_turnover", sa.Double()),
        sa.Column("assist_ratio", sa.Double()),
        sa.Column("oreb_pct", sa.Double()),
        sa.Column("dreb_pct", sa.Double()),
        sa.Column("reb_pct", sa.Double()),
        sa.Column("estimated_team_tov_pct", sa.Double()),
        sa.Column("turnover_ratio", sa.Double()),
        sa.Column("efg_pct", sa.Double()),
        sa.Column("ts_pct", sa.Double()),
        sa.Column("usage_pct", sa.Double()),
        sa.Column("estimated_usage_pct", sa.Double()),
        sa.Column("pace", sa.Double()),
        sa.Column("possessions", sa.Double()),
        sa.Column("pie", sa.Double()),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.create_index("ix_box_scores_advanced_team_game_abbr", "box_scores_advanced_team", ["game_id", "team_abbr"])

    op.create_table(
        "play_by_play_events",
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("eventnum", sa.Integer(), primary_key=True),
        sa.Column("eventmsgtype", sa.Integer()),
        sa.Column("eventmsgactiontype", sa.Integer()),
        sa.Column("period", sa.Integer()),
        sa.Column("pctimestring", sa.Text()),
        sa.Column("homedescription", sa.Text()),
        sa.Column("neutraldescription", sa.Text()),
        sa.Column("visitordescription", sa.Text()),
        sa.Column("score", sa.Text()),
        sa.Column("score_away", sa.Integer()),
        sa.Column("score_home", sa.Integer()),
        sa.Column("scoremargin", sa.Text()),
        sa.Column("player1_id", sa.Text()),
        sa.Column("player1_name", sa.Text()),
        sa.Column("player1_team_id", sa.Text()),
        sa.Column("player1_team_abbreviation", sa.Text()),
        sa.Column("player2_id", sa.Text()),
        sa.Column("player2_name", sa.Text()),
        sa.Column("player2_team_id", sa.Text()),
        sa.Column("player2_team_abbreviation", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("eventnum >= 0", name="ck_play_by_play_events_eventnum_nonnegative"),
        sa.CheckConstraint("period IS NULL OR period >= 1", name="ck_play_by_play_events_period_positive"),
    )
    op.create_index("ix_play_by_play_events_game_period_event", "play_by_play_events", ["game_id", "period", "eventnum"])

    op.create_table(
        "lineup_stints",
        sa.Column("stint_id", sa.Text(), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False),
        sa.Column("team_abbr", sa.Text()),
        sa.Column("team_id", sa.Text()),
        sa.Column("player_id", sa.Text()),
        sa.Column("player_name", sa.Text()),
        sa.Column("period", sa.Integer()),
        sa.Column("start_clock", sa.Text()),
        sa.Column("end_clock", sa.Text()),
        sa.Column("start_eventnum", sa.Integer()),
        sa.Column("end_eventnum", sa.Integer()),
        sa.Column("start_elapsed_seconds", sa.Double()),
        sa.Column("end_elapsed_seconds", sa.Double()),
        sa.Column("duration_seconds", sa.Double()),
        sa.Column("player_pts", sa.Double()),
        sa.Column("plus_minus", sa.Double()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text()),
        sa.Column("caveat", sa.Text()),
        sa.CheckConstraint("period IS NULL OR period >= 1", name="ck_lineup_stints_period_positive"),
        sa.CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_lineup_stints_duration_nonnegative"),
        sa.CheckConstraint("confidence IS NULL OR confidence IN ('low', 'medium', 'high')", name="ck_lineup_stints_confidence"),
    )
    op.create_index("ix_lineup_stints_game_source", "lineup_stints", ["game_id", "source"])
    op.create_index("ix_lineup_stints_game_team_period", "lineup_stints", ["game_id", "team_abbr", "period"])

    op.create_table(
        "evidence_packets",
        sa.Column("packet_id", sa.Text(), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="CASCADE"), nullable=False),
        sa.Column("packet_type", sa.Text(), nullable=False),
        sa.Column("claim_seed", sa.Text()),
        sa.Column("source_provider", sa.Text()),
        sa.Column("source_detail", sa.Text()),
        sa.Column("evidence_level", sa.Text()),
        sa.Column("confidence", sa.Text()),
        sa.Column("payload_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("confidence IS NULL OR confidence IN ('low', 'medium', 'high')", name="ck_evidence_packets_confidence"),
    )
    op.create_index("ix_evidence_packets_game_type_created", "evidence_packets", ["game_id", "packet_type", "created_at"])

    # Analysis history is retained if a normalized game is later removed.
    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.Text(), primary_key=True),
        sa.Column("game_id", sa.Text(), sa.ForeignKey("games.game_id", ondelete="SET NULL")),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("memo_markdown", sa.Text(), nullable=False),
        sa.Column("packet_ids_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
    )
    op.create_index("ix_analysis_runs_game_created", "analysis_runs", ["game_id", "created_at"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("game_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("result_json", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=UTC_NOW),
        sa.CheckConstraint("status IN ('queued', 'fetching', 'ready', 'partial', 'failed')", name="ck_ingestion_jobs_status"),
    )
    op.create_index("ix_ingestion_jobs_status_created", "ingestion_jobs", ["status", "created_at"])
    op.create_index("ix_ingestion_jobs_game_created", "ingestion_jobs", ["game_id", "created_at"])


def downgrade() -> None:
    for table in (
        "ingestion_jobs",
        "analysis_runs",
        "evidence_packets",
        "lineup_stints",
        "play_by_play_events",
        "box_scores_advanced_team",
        "box_scores_player",
        "box_scores_team",
        "games",
        "raw_responses",
    ):
        op.drop_table(table)
