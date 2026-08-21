from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .models import Base


class WorkRow(Base):
    __tablename__ = "works"
    __table_args__ = (UniqueConstraint("workspace_id", "command_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    command_id: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_graph_revision_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    graph_revisions: Mapped[list["WorkGraphRevisionRow"]] = relationship(back_populates="work")
    nodes: Mapped[list["WorkNodeRow"]] = relationship(back_populates="work")
    events: Mapped[list["CompanyEventRow"]] = relationship(back_populates="work")


class OrchestrationCapacityRow(Base):
    __tablename__ = "orchestration_capacity"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkGraphRevisionRow(Base):
    __tablename__ = "work_graph_revisions"
    __table_args__ = (UniqueConstraint("work_id", "revision_number"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    work: Mapped[WorkRow] = relationship(back_populates="graph_revisions")
    nodes: Mapped[list["WorkNodeRow"]] = relationship(back_populates="graph_revision")


class WorkGraphNodeRow(Base):
    __tablename__ = "work_graph_nodes"
    __table_args__ = (
        UniqueConstraint("graph_revision_id", "node_id"),
        UniqueConstraint("graph_revision_id", "position"),
    )

    graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("work_graph_revisions.id"), primary_key=True
    )
    node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class WorkEdgeRow(Base):
    __tablename__ = "work_edges"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("work_graph_revisions.id"), nullable=False
    )
    from_node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), nullable=False)
    to_node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)


class WorkNodeRow(Base):
    __tablename__ = "work_nodes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("work_graph_revisions.id"), nullable=False
    )
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria_json: Mapped[str] = mapped_column(Text, nullable=False)
    required_actions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    resource_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    input_references_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_references_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    assigned_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    employee_revision_id: Mapped[str] = mapped_column(
        ForeignKey("employee_revisions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    active_attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    work: Mapped[WorkRow] = relationship(back_populates="nodes")
    graph_revision: Mapped[WorkGraphRevisionRow] = relationship(back_populates="nodes")
    execution_links: Mapped[list["ExecutionLinkRow"]] = relationship(back_populates="node")


class ExecutionLinkRow(Base):
    __tablename__ = "execution_links"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    command_id: Mapped[str] = mapped_column(String, nullable=False)
    dsh_session_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    diagnostic_code: Mapped[str | None] = mapped_column(String, nullable=True)
    node: Mapped[WorkNodeRow] = relationship(back_populates="execution_links")


class ArtifactReferenceRow(Base):
    __tablename__ = "artifact_references"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    source_session_id: Mapped[str] = mapped_column(String, nullable=False)
    source_attempt_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class CompanyEventRow(Base):
    __tablename__ = "company_events"
    __table_args__ = (UniqueConstraint("attempt_id", "source_sequence"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(nullable=False)
    work: Mapped[WorkRow] = relationship(back_populates="events")
