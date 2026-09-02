"""direct messages between athletes (coach ↔ athlete chat)

Revision ID: 0005_messages
Revises: 0004_coach_assignments
Create Date: 2026-09-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_messages"
down_revision: Union[str, None] = "0004_coach_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "sender_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column(
            "recipient_id", sa.String(), sa.ForeignKey("athletes.id"), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("read_at", sa.String(), nullable=True),
    )
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index("ix_messages_recipient_id", "messages", ["recipient_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("messages")
