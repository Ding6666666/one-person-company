"""Create company core tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_company_core"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "employees",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_revision_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_index("ix_employees_workspace_id", "employees", ["workspace_id"])
    op.create_table(
        "employee_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employee_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("responsibility", sa.Text(), nullable=False),
        sa.Column("runtime_profile", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
        sa.UniqueConstraint("employee_id", "revision_number"),
    )
    op.create_index(
        "ix_employee_revisions_employee_id", "employee_revisions", ["employee_id"]
    )
    op.create_table(
        "capability_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employee_revision_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("resource_kind", sa.String(), nullable=False),
        sa.Column("resource_values_json", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["employee_revision_id"], ["employee_revisions.id"]),
    )
    op.create_index(
        "ix_capability_grants_employee_revision_id",
        "capability_grants",
        ["employee_revision_id"],
    )
    op.create_table(
        "employee_agent_bindings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employee_id", sa.String(), nullable=False, unique=True),
        sa.Column("dsh_agent_id", sa.String(), nullable=False),
        sa.Column("dsh_session_id", sa.String(), nullable=False),
        sa.Column("memory_scope_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"]),
    )


def downgrade() -> None:
    op.drop_table("employee_agent_bindings")
    op.drop_index("ix_capability_grants_employee_revision_id", table_name="capability_grants")
    op.drop_table("capability_grants")
    op.drop_index("ix_employee_revisions_employee_id", table_name="employee_revisions")
    op.drop_table("employee_revisions")
    op.drop_index("ix_employees_workspace_id", table_name="employees")
    op.drop_table("employees")
    op.drop_table("workspaces")
