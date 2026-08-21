from typing import NewType
from uuid import uuid4

WorkspaceId = NewType("WorkspaceId", str)
EmployeeId = NewType("EmployeeId", str)
EmployeeRevisionId = NewType("EmployeeRevisionId", str)
CapabilityGrantId = NewType("CapabilityGrantId", str)
EmployeeAgentBindingId = NewType("EmployeeAgentBindingId", str)
WorkId = NewType("WorkId", str)
WorkGraphRevisionId = NewType("WorkGraphRevisionId", str)
WorkNodeId = NewType("WorkNodeId", str)
ExecutionLinkId = NewType("ExecutionLinkId", str)
AttemptId = NewType("AttemptId", str)
CompanyEventId = NewType("CompanyEventId", str)
ArtifactReferenceId = NewType("ArtifactReferenceId", str)
ApprovalId = NewType("ApprovalId", str)
DelegationId = NewType("DelegationId", str)


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"
