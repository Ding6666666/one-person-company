"""serialize orchestration capacity reservations

Revision ID: 0006_orchestration_capacity
Revises: 0005_node_graph_fields
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_orchestration_capacity"
down_revision: str | None = "0005_node_graph_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = op.create_table(
        "orchestration_capacity",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(table, [{"id": "runtime", "revision": 0}])


def downgrade() -> None:
    op.drop_table("orchestration_capacity")
