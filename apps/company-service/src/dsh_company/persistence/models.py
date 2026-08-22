from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    employees: Mapped[list["EmployeeRow"]] = relationship(back_populates="workspace")


class EmployeeRow(Base):
    __tablename__ = "employees"
    __table_args__ = (Index("ix_employees_workspace_id", "workspace_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_revision_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    workspace: Mapped[WorkspaceRow | None] = relationship(back_populates="employees")
    revisions: Mapped[list["EmployeeRevisionRow"]] = relationship(back_populates="employee")
    binding: Mapped["EmployeeAgentBindingRow | None"] = relationship(back_populates="employee")


class EmployeeRevisionRow(Base):
    __tablename__ = "employee_revisions"
    __table_args__ = (
        UniqueConstraint("employee_id", "revision_number"),
        Index("ix_employee_revisions_employee_id", "employee_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    responsibility: Mapped[str] = mapped_column(Text, nullable=False)
    runtime_profile: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    employee: Mapped[EmployeeRow] = relationship(back_populates="revisions")
    grants: Mapped[list["CapabilityGrantRow"]] = relationship(back_populates="revision")
    profile: Mapped["EmployeeRevisionProfileRow | None"] = relationship(
        back_populates="revision", uselist=False
    )


class EmployeeRevisionProfileRow(Base):
    __tablename__ = "employee_revision_profiles"

    employee_revision_id: Mapped[str] = mapped_column(
        ForeignKey("employee_revisions.id"), primary_key=True
    )
    role_template_key: Mapped[str] = mapped_column(String, nullable=False)
    work_type: Mapped[str] = mapped_column(String, nullable=False)
    avatar_key: Mapped[str] = mapped_column(String, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    skill_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    tool_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[EmployeeRevisionRow] = relationship(back_populates="profile")


class CapabilityGrantRow(Base):
    __tablename__ = "capability_grants"
    __table_args__ = (Index("ix_capability_grants_employee_revision_id", "employee_revision_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_revision_id: Mapped[str] = mapped_column(
        ForeignKey("employee_revisions.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_kind: Mapped[str] = mapped_column(String, nullable=False)
    resource_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[EmployeeRevisionRow] = relationship(back_populates="grants")


class EmployeeAgentBindingRow(Base):
    __tablename__ = "employee_agent_bindings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id"), nullable=False, unique=True
    )
    dsh_agent_id: Mapped[str] = mapped_column(String, nullable=False)
    dsh_session_id: Mapped[str] = mapped_column(String, nullable=False)
    memory_scope_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    employee: Mapped[EmployeeRow] = relationship(back_populates="binding")


class WorkspaceCapabilityGrantRow(Base):
    __tablename__ = "workspace_capability_grants"

    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    action: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_kind: Mapped[str] = mapped_column(String, nullable=False)
    resource_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)


class NodeCapabilityGrantRow(Base):
    __tablename__ = "node_capability_grants"

    node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), primary_key=True)
    action: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_kind: Mapped[str] = mapped_column(String, nullable=False)
    resource_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (CheckConstraint("length(reason) <= 500"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), nullable=False)
    node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    resources_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)


class DelegationRow(Base):
    __tablename__ = "delegations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    work_id: Mapped[str] = mapped_column(ForeignKey("works.id"), nullable=False)
    source_node_id: Mapped[str] = mapped_column(ForeignKey("work_nodes.id"), nullable=False)
    target_node_id: Mapped[str | None] = mapped_column(ForeignKey("work_nodes.id"), nullable=True)
    proposer_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), nullable=False)
    target_employee_id: Mapped[str] = mapped_column(String, nullable=False)
    graph_revision_id: Mapped[str] = mapped_column(
        ForeignKey("work_graph_revisions.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


class BusinessPluginRegistrationRow(Base):
    __tablename__ = "business_plugin_registrations"

    plugin_id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(nullable=False)
