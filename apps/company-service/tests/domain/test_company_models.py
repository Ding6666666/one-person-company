import pytest
from dsh_company.domain.capabilities import CapabilityLevel, default_employee_grants
from dsh_company.domain.employee import Employee, EmployeeAgentBinding
from dsh_company.domain.ids import EmployeeId, WorkspaceId
from dsh_company.domain.workspace import Workspace


def test_workspace_name_is_required() -> None:
    with pytest.raises(ValueError, match="workspace name"):
        Workspace.create(WorkspaceId("ws-1"), "   ")


def test_employee_creation_freezes_revision_and_stable_dsh_identity() -> None:
    employee, revision, binding = Employee.create(
        employee_id=EmployeeId("emp-1"),
        workspace_id=WorkspaceId("ws-1"),
        display_name="内容编辑",
        responsibility="撰写并校对新闻内容",
        runtime_profile="workspace_read",
        model="deepseek-v4-flash",
        role_template_key="product-manager",
        work_type="产品管理",
        avatar_key="product-manager",
        skill_refs=(),
        tool_refs=(),
    )

    assert revision.revision_number == 1
    assert employee.current_revision_id == revision.id
    assert binding.dsh_agent_id == "employee-emp-1"
    assert binding.dsh_session_id == "employee-emp-1"
    assert binding.memory_scope_id == "dsh-session:employee-emp-1"
    assert revision.role_template_key == "product-manager"
    assert revision.work_type == "产品管理"
    assert revision.avatar_key == "product-manager"
    assert revision.skill_refs == ()
    assert revision.tool_refs == ()


def test_default_tools_are_present_but_not_high_risk() -> None:
    grants = default_employee_grants(WorkspaceId("ws-1"))

    assert {(grant.action, grant.level) for grant in grants} == {
        ("conversation.respond", CapabilityLevel.L0),
        ("workspace.read", CapabilityLevel.L1),
        ("session.history.read", CapabilityLevel.L1),
    }
    assert all(grant.requires_approval is False for grant in grants)


def test_binding_rejects_different_agent_and_session_ids() -> None:
    with pytest.raises(ValueError, match="Agent ID must equal Session ID"):
        EmployeeAgentBinding.create(
            employee_id=EmployeeId("emp-1"),
            dsh_agent_id="agent-1",
            dsh_session_id="session-1",
        )
