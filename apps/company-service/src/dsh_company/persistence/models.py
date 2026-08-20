from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    binding: Mapped["EmployeeAgentBindingRow | None"] = relationship(
        back_populates="employee"
    )


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


class CapabilityGrantRow(Base):
    __tablename__ = "capability_grants"
    __table_args__ = (
        Index("ix_capability_grants_employee_revision_id", "employee_revision_id"),
    )

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
