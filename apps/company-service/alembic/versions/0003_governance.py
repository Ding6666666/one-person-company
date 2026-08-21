"""Persist governance facts and immutable graph revision membership."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_governance"
down_revision: str | None = "0002_direct_work"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_capability_grants",
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("resource_kind", sa.String(), nullable=False),
        sa.Column("resource_values_json", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("workspace_id", "action"),
    )
    op.create_table(
        "node_capability_grants",
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("resource_kind", sa.String(), nullable=False),
        sa.Column("resource_values_json", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["work_nodes.id"]),
        sa.PrimaryKeyConstraint("node_id", "action"),
    )
    op.create_table(
        "work_graph_nodes",
        sa.Column("graph_revision_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["graph_revision_id"], ["work_graph_revisions.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["work_nodes.id"]),
        sa.PrimaryKeyConstraint("graph_revision_id", "node_id"),
        sa.UniqueConstraint("graph_revision_id", "node_id"),
        sa.UniqueConstraint("graph_revision_id", "position"),
    )
    op.execute(
        sa.text(
            "INSERT INTO work_graph_nodes (graph_revision_id, node_id, position) "
            "SELECT graph_revision_id, id, "
            "ROW_NUMBER() OVER (PARTITION BY graph_revision_id ORDER BY id) - 1 "
            "FROM work_nodes"
        )
    )
    op.create_table(
        "work_edges",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("graph_revision_id", sa.String(), nullable=False),
        sa.Column("from_node_id", sa.String(), nullable=False),
        sa.Column("to_node_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["graph_revision_id"], ["work_graph_revisions.id"]),
        sa.ForeignKeyConstraint(["from_node_id"], ["work_nodes.id"]),
        sa.ForeignKeyConstraint(["to_node_id"], ["work_nodes.id"]),
    )
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resources_json", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.CheckConstraint("length(reason) <= 500"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.ForeignKeyConstraint(["node_id"], ["work_nodes.id"]),
    )
    op.create_table(
        "delegations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), nullable=False),
        sa.Column("source_node_id", sa.String(), nullable=False),
        sa.Column("target_node_id", sa.String(), nullable=False),
        sa.Column("proposer_employee_id", sa.String(), nullable=False),
        sa.Column("target_employee_id", sa.String(), nullable=False),
        sa.Column("graph_revision_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["work_nodes.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["work_nodes.id"]),
        sa.ForeignKeyConstraint(["proposer_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["target_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["graph_revision_id"], ["work_graph_revisions.id"]),
    )


def downgrade() -> None:
    op.drop_table("delegations")
    op.drop_table("approvals")
    op.drop_table("work_edges")
    op.drop_table("work_graph_nodes")
    op.drop_table("node_capability_grants")
    op.drop_table("workspace_capability_grants")
