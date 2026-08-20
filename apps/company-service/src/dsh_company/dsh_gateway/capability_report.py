from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    CONSTRAINED = "constrained"
    NOT_EXPOSED = "not_exposed"


class CapabilityObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: str
    state: CapabilityState
    evidence: str


class DshCapabilityReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    dsh_revision: str
    observations: tuple[CapabilityObservation, ...]

    def by_name(self) -> dict[str, CapabilityObservation]:
        return {item.capability: item for item in self.observations}
