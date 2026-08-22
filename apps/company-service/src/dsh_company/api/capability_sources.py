from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from dsh_company.capability_sources.contracts import CapabilityEntry as DomainEntry
from dsh_company.capability_sources.contracts import CapabilitySourceDescriptor

from .errors import ResourceNotFoundError

router = APIRouter()
CapabilityKind = Literal["skill", "tool"]


class CapabilitySourceView(BaseModel):
    id: str
    kind: CapabilityKind
    display_name: str

    @classmethod
    def from_domain(cls, source: CapabilitySourceDescriptor) -> "CapabilitySourceView":
        return cls(id=source.id, kind=source.kind, display_name=source.display_name)


class CapabilityEntryView(BaseModel):
    ref: str
    source_id: str
    kind: CapabilityKind
    name: str
    description: str
    version: str
    required_actions: list[str]

    @classmethod
    def from_domain(cls, entry: DomainEntry) -> "CapabilityEntryView":
        return cls(
            ref=entry.ref,
            source_id=entry.source_id,
            kind=entry.kind,
            name=entry.name,
            description=entry.description,
            version=entry.version,
            required_actions=list(entry.required_actions),
        )


class CapabilityImport(BaseModel):
    kind: CapabilityKind
    source_id: Annotated[str, Field(min_length=1, max_length=120)]
    external_id: Annotated[str, Field(min_length=1, max_length=240)]


@router.get("/capability-sources", response_model=list[CapabilitySourceView])
def list_sources(
    request: Request, kind: Annotated[CapabilityKind, Query()]
) -> list[CapabilitySourceView]:
    return [
        CapabilitySourceView.from_domain(source)
        for source in request.app.state.assembly.capability_sources.list_sources(kind)
    ]


@router.get("/capability-entries", response_model=list[CapabilityEntryView])
def list_entries(
    request: Request, kind: Annotated[CapabilityKind, Query()]
) -> list[CapabilityEntryView]:
    return [
        CapabilityEntryView.from_domain(entry)
        for entry in request.app.state.assembly.capability_sources.list_entries(kind)
    ]


@router.post("/capability-imports", response_model=CapabilityEntryView)
def import_entry(request: Request, body: CapabilityImport) -> CapabilityEntryView:
    try:
        entry = request.app.state.assembly.capability_sources.import_entry(
            body.kind, body.source_id, body.external_id
        )
    except LookupError as error:
        raise ResourceNotFoundError("capability_source") from error
    return CapabilityEntryView.from_domain(entry)
