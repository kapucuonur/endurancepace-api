"""training plan periodization blocks

Revision ID: 0003_plan_blocks
Revises: 0002_garmin
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_plan_blocks"
down_revision: Union[str, None] = "0002_garmin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("training_plans") as batch:
        batch.add_column(sa.Column("blocks", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("training_plans") as batch:
        batch.drop_column("blocks")
