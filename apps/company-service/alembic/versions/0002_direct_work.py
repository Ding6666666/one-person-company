"""Create direct work lifecycle tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_direct_work"
down_revision: str | None = "0001_company_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "works",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("current_graph_revision_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "command_id"),
    )
    op.create_table(
        "work_graph_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("work_id", sa.String(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.UniqueConstraint("work_id", "revision_number"),
    )
    op.create_table(
        "work_nodes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("graph_revision_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria_json", sa.Text(), nullable=False),
        sa.Column("assigned_employee_id", sa.String(), nullable=False),
        sa.Column("employee_revision_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("active_attempt_id", sa.String(), nullable=True),
        sa.Column("failure_code", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["graph_revision_id"], ["work_graph_revisions.id"]),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.ForeignKeyConstraint(["assigned_employee_id"], ["employees.id"]),
        sa.ForeignKeyConstraint(["employee_revision_id"], ["employee_revisions.id"]),
    )
    op.create_table(
        "execution_links",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("node_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), nullable=False, unique=True),
        sa.Column("command_id", sa.String(), nullable=False, unique=True),
        sa.Column("dsh_session_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("diagnostic_code", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["work_nodes.id"]),
    )
    op.create_table(
        "artifact_references",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("source_session_id", sa.String(), nullable=False),
        sa.Column("source_attempt_id", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
    )
    op.create_table(
        "company_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("work_id", sa.String(), nullable=False),
        sa.Column("node_id", sa.String(), nullable=True),
        sa.Column("attempt_id", sa.String(), nullable=True),
        sa.Column("source_sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.UniqueConstraint("attempt_id", "source_sequence"),
    )


def downgrade() -> None:
    op.drop_table("company_events")
    op.drop_table("artifact_references")
    op.drop_table("execution_links")
    op.drop_table("work_nodes")
    op.drop_table("work_graph_revisions")
    op.drop_table("works")
