"""persist declarative business plugin registrations

Revision ID: 0007_business_plugins
Revises: 0006_orchestration_capacity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_business_plugins"
down_revision: str | None = "0006_orchestration_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_plugin_registrations",
        sa.Column("plugin_id", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("plugin_id"),
    )


def downgrade() -> None:
    op.drop_table("business_plugin_registrations")
