"""Add weekly_reports table and notes column to reviews

Revision ID: 002_weekly_reports
Revises: 001_initial
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_weekly_reports"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create weekly_reports table
    op.create_table(
        "weekly_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("total_reviews", sa.Integer(), nullable=False, default=0),
        sa.Column("sentiment_breakdown", postgresql.JSON(), nullable=True),
        sa.Column("top_problems", postgresql.JSON(), nullable=True),
        sa.Column("critical_reviews", postgresql.JSON(), nullable=True),
        sa.Column("total_change_percent", sa.Float(), nullable=True),
        sa.Column("sentiment_change", postgresql.JSON(), nullable=True),
        sa.Column("recommendations", postgresql.JSON(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weekly_reports_user_id", "weekly_reports", ["user_id"])
    op.create_index(
        "ix_weekly_reports_user_week",
        "weekly_reports",
        ["user_id", "week_start"],
        unique=True,
    )

    # Add notes column to reviews if not exists
    op.add_column(
        "reviews",
        sa.Column("notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reviews", "notes")
    op.drop_table("weekly_reports")
