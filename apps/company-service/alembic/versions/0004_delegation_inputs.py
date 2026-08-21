"""persist parent input references for delegation continuation

Revision ID: 0004_delegation_inputs
Revises: 0003_governance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_delegation_inputs"
down_revision: str | None = "0003_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_nodes",
        sa.Column(
            "input_references_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
    )
    with op.batch_alter_table(
        "delegations",
        naming_convention={
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        },
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_delegations_target_employee_id_employees",
            type_="foreignkey",
        )
        batch_op.alter_column(
            "target_node_id",
            existing_type=sa.String(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("delegations") as batch_op:
        batch_op.alter_column(
            "target_node_id",
            existing_type=sa.String(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            "fk_delegations_target_employee_id_employees",
            "employees",
            ["target_employee_id"],
            ["id"],
        )
    op.drop_column("work_nodes", "input_references_json")
