"""Add industry and custom_instructions to company_settings

Revision ID: 004_company_fields
Revises: 003_billing
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "004_company_fields"
down_revision: Union[str, None] = "003_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company_settings",
        sa.Column("industry", sa.String(255), nullable=True),
    )
    op.add_column(
        "company_settings",
        sa.Column("custom_instructions", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company_settings", "custom_instructions")
    op.drop_column("company_settings", "industry")
