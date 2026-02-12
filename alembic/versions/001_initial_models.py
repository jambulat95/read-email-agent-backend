"""Initial models - users, email_accounts, reviews, draft_responses, notification_settings, company_settings

Revision ID: 001_initial
Revises:
Create Date: 2026-02-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, default=False),
        sa.Column("plan", sa.String(50), nullable=False, default="free"),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Create email_accounts table
    op.create_table(
        "email_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("oauth_token", sa.String(2000), nullable=True),
        sa.Column("oauth_refresh_token", sa.String(2000), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_interval_minutes", sa.Integer(), nullable=False, default=15),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_email_accounts_user_id", "email_accounts", ["user_id"])

    # Create reviews table
    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=False),
        sa.Column("sender_email", sa.String(255), nullable=False),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(1000), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sentiment", sa.String(50), nullable=True),
        sa.Column("priority", sa.String(50), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("problems", postgresql.JSON(), nullable=True),
        sa.Column("suggestions", postgresql.JSON(), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False, default=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["email_account_id"],
            ["email_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_email_account_id", "reviews", ["email_account_id"])
    op.create_index("ix_reviews_sentiment", "reviews", ["sentiment"])
    op.create_index("ix_reviews_priority", "reviews", ["priority"])
    op.create_index(
        "ix_reviews_email_account_message",
        "reviews",
        ["email_account_id", "message_id"],
        unique=True,
    )

    # Create draft_responses table
    op.create_table(
        "draft_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False),
        sa.Column("variant_number", sa.Integer(), nullable=False, default=1),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["review_id"],
            ["reviews.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_draft_responses_review_id", "draft_responses", ["review_id"])

    # Create notification_settings table
    op.create_table(
        "notification_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("telegram_enabled", sa.Boolean(), nullable=False, default=False),
        sa.Column("telegram_chat_id", sa.String(100), nullable=True),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False, default=False),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("notify_on_critical", sa.Boolean(), nullable=False, default=True),
        sa.Column("notify_on_important", sa.Boolean(), nullable=False, default=True),
        sa.Column("notify_on_normal", sa.Boolean(), nullable=False, default=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_notification_settings_user_id", "notification_settings", ["user_id"]
    )

    # Create company_settings table
    op.create_table(
        "company_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column(
            "response_tone", sa.String(50), nullable=False, default="professional"
        ),
        sa.Column("custom_templates", postgresql.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_company_settings_user_id", "company_settings", ["user_id"])


def downgrade() -> None:
    op.drop_table("company_settings")
    op.drop_table("notification_settings")
    op.drop_table("draft_responses")
    op.drop_table("reviews")
    op.drop_table("email_accounts")
    op.drop_table("users")
