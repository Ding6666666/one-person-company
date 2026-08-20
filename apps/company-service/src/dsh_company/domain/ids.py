from typing import NewType
from uuid import uuid4

WorkspaceId = NewType("WorkspaceId", str)
EmployeeId = NewType("EmployeeId", str)
EmployeeRevisionId = NewType("EmployeeRevisionId", str)
CapabilityGrantId = NewType("CapabilityGrantId", str)
EmployeeAgentBindingId = NewType("EmployeeAgentBindingId", str)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
