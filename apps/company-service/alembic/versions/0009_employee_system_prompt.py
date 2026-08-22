"""persist employee system prompts

Revision ID: 0009_employee_system_prompt
Revises: 0008_employee_profiles
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_employee_system_prompt"
down_revision: str | None = "0008_employee_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "employee_revision_profiles",
        sa.Column("system_prompt", sa.Text(), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("employee_revision_profiles", "system_prompt")
