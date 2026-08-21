"""persist durable work node graph fields

Revision ID: 0005_node_graph_fields
Revises: 0004_delegation_inputs
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_node_graph_fields"
down_revision: str | None = "0004_delegation_inputs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_nodes",
        sa.Column("required_actions_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "work_nodes",
        sa.Column("resource_values_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "work_nodes",
        sa.Column("output_references_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "work_nodes",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "work_nodes",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("work_nodes", "attempt_count")
    op.drop_column("work_nodes", "max_attempts")
    op.drop_column("work_nodes", "output_references_json")
    op.drop_column("work_nodes", "resource_values_json")
    op.drop_column("work_nodes", "required_actions_json")
