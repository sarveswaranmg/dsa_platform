"""initial

Revision ID: 13cb37e2451e
Revises: 
Create Date: 2026-07-19 10:59:24.129951

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '13cb37e2451e'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
