"""coach workout assignments

Revision ID: 0004_coach_assignments
Revises: 0003_plan_blocks
Create Date: 2026-08-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_coach_assignments"
down_revision: Union[str, None] = "0003_plan_blocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("workouts") as batch:
        batch.add_column(sa.Column("assigned_by_id", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workouts") as batch:
        batch.drop_column("assigned_by_id")
