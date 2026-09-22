"""Prevent concurrent active ingestion jobs for the same game.

Revision ID: 20260922_02
Revises: 20260922_01
Create Date: 2026-09-22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260922_02"
down_revision = "20260922_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_ingestion_jobs_active_game",
        "ingestion_jobs",
        ["game_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'fetching')"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingestion_jobs_active_game", table_name="ingestion_jobs")
