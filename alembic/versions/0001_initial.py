"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "athletes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("disciplines", sa.JSON(), nullable=False),
        sa.Column("thresholds", sa.JSON(), nullable=False),
        sa.Column("hr_zones", sa.JSON(), nullable=True),
        sa.Column("power_zones", sa.JSON(), nullable=True),
        sa.Column("run_pace_zones", sa.JSON(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("birthdate", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_athletes_user_id"),
    )

    op.create_table(
        "training_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_date", sa.String(), nullable=False),
        sa.Column("end_date", sa.String(), nullable=False),
        sa.Column("goal_event_id", sa.String(), nullable=True),
        sa.Column("phase", sa.String(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index(
        "ix_training_plans_athlete_id", "training_plans", ["athlete_id"]
    )

    op.create_table(
        "race_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("date", sa.String(), nullable=False),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("distance", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_race_events_athlete_id", "race_events", ["athlete_id"])

    op.create_table(
        "workouts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "athlete_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column("plan_id", sa.String(), nullable=True),
        sa.Column("date", sa.String(), nullable=True),
        sa.Column("sport", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("structure", sa.JSON(), nullable=False),
        sa.Column("planned_duration", sa.Integer(), nullable=False),
        sa.Column("planned_tss", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("completed", sa.JSON(), nullable=True),
        sa.Column("is_template", sa.Boolean(), nullable=False),
        sa.Column("template_category", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_workouts_athlete_id", "workouts", ["athlete_id"])
    op.create_index("ix_workouts_plan_id", "workouts", ["plan_id"])
    op.create_index("ix_workouts_date", "workouts", ["date"])


def downgrade() -> None:
    op.drop_table("workouts")
    op.drop_table("race_events")
    op.drop_table("training_plans")
    op.drop_table("athletes")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
