"""persist employee role profiles

Revision ID: 0008_employee_profiles
Revises: 0007_business_plugins
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_employee_profiles"
down_revision: str | None = "0007_business_plugins"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employee_revision_profiles",
        sa.Column("employee_revision_id", sa.String(), nullable=False),
        sa.Column("role_template_key", sa.String(), nullable=False),
        sa.Column("work_type", sa.String(), nullable=False),
        sa.Column("avatar_key", sa.String(), nullable=False),
        sa.Column("skill_refs_json", sa.Text(), nullable=False),
        sa.Column("tool_refs_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["employee_revision_id"], ["employee_revisions.id"]),
        sa.PrimaryKeyConstraint("employee_revision_id"),
    )


def downgrade() -> None:
    op.drop_table("employee_revision_profiles")
