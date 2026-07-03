"""Add unique constraint on target_url to make dedup atomic at the DB level

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f("ix_urls_target_url"), "urls", ["target_url"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_urls_target_url"), table_name="urls")
