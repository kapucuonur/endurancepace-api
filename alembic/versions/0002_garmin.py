"""garmin sync: linked account, session state, workout provenance

Revision ID: 0002_garmin
Revises: 0001_initial
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_garmin"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("garmin_email", sa.String(), nullable=True))
        batch.add_column(sa.Column("garmin_password", sa.String(), nullable=True))

    with op.batch_alter_table("workouts") as batch:
        batch.add_column(
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="manual",
            )
        )
        batch.add_column(sa.Column("external_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("garmin_raw", sa.JSON(), nullable=True))
        batch.create_unique_constraint(
            "uq_workouts_athlete_external", ["athlete_id", "external_id"]
        )

    op.create_table(
        "garmin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column("token_blob", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="error"),
        sa.Column("mfa_initiated_at", sa.String(), nullable=True),
        sa.Column("last_verified_at", sa.String(), nullable=True),
        sa.Column("cooldown_until", sa.String(), nullable=True),
        sa.Column("last_sync_at", sa.String(), nullable=True),
        sa.Column(
            "sync_in_progress", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("athlete_id", name="uq_garmin_sessions_athlete_id"),
    )
    op.create_index(
        "ix_garmin_sessions_athlete_id", "garmin_sessions", ["athlete_id"]
    )


def downgrade() -> None:
    op.drop_table("garmin_sessions")
    with op.batch_alter_table("workouts") as batch:
        batch.drop_constraint("uq_workouts_athlete_external", type_="unique")
        batch.drop_column("garmin_raw")
        batch.drop_column("external_id")
        batch.drop_column("source")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("garmin_password")
        batch.drop_column("garmin_email")
