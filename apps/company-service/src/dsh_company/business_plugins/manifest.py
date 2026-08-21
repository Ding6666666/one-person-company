from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from dsh_company.domain.capabilities import CapabilityLevel
from dsh_company.domain.work import WorkEdgeKind

PluginId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,63}$")]
Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
DisplayName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]
Objective = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
Criterion = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class _PluginModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PluginAction(_PluginModel):
    action: Identifier
    level: CapabilityLevel
    runtime_profiles: tuple[
        Literal["workspace_read", "workspace_write", "network_denied"], ...
    ] = ()


class EmployeeSlot(_PluginModel):
    slot_id: Identifier


class TemplateNode(_PluginModel):
    key: Identifier
    employee_slot: Identifier
    objective: Objective
    acceptance_criteria: tuple[Criterion, ...] = Field(min_length=1, max_length=50)
    required_actions: tuple[Identifier, ...] = Field(default=(), max_length=16)
    resource_kinds: tuple[Identifier, ...] = Field(default=(), max_length=16)
    resource_values: tuple[Identifier, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def validate_policy_shape(self) -> "TemplateNode":
        if len(self.required_actions) != len(self.resource_kinds):
            raise ValueError("resource kinds must align with required actions")
        if len(self.required_actions) != len(set(self.required_actions)):
            raise ValueError("required actions must be unique")
        return self


class TemplateEdge(_PluginModel):
    from_key: Identifier
    to_key: Identifier
    kind: WorkEdgeKind


class WorkTemplate(_PluginModel):
    template_id: Identifier
    display_name: DisplayName
    employee_slots: tuple[EmployeeSlot, ...] = Field(min_length=1, max_length=32)
    nodes: tuple[TemplateNode, ...] = Field(min_length=1, max_length=32)
    edges: tuple[TemplateEdge, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_declarative_references(self) -> "WorkTemplate":
        slot_ids = tuple(slot.slot_id for slot in self.employee_slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("duplicate employee slot")
        node_keys = tuple(node.key for node in self.nodes)
        if len(node_keys) != len(set(node_keys)):
            raise ValueError("duplicate template node key")
        unknown_slot = next(
            (node.employee_slot for node in self.nodes if node.employee_slot not in slot_ids),
            None,
        )
        if unknown_slot is not None:
            raise ValueError(f"unknown employee slot: {unknown_slot}")
        edge_ids = tuple((edge.from_key, edge.to_key, edge.kind) for edge in self.edges)
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("duplicate template edge")
        known_keys = set(node_keys)
        unknown_endpoint = next(
            (
                endpoint
                for edge in self.edges
                for endpoint in (edge.from_key, edge.to_key)
                if endpoint not in known_keys
            ),
            None,
        )
        if unknown_endpoint is not None:
            raise ValueError(f"unknown edge endpoint: {unknown_endpoint}")
        return self


class BusinessPluginManifest(_PluginModel):
    plugin_id: PluginId
    version: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
    ]
    display_name: DisplayName
    capability_actions: tuple[PluginAction, ...] = ()
    templates: tuple[WorkTemplate, ...] = ()

    @model_validator(mode="after")
    def validate_unique_catalog(self) -> "BusinessPluginManifest":
        actions = tuple(item.action for item in self.capability_actions)
        if len(actions) != len(set(actions)):
            raise ValueError("duplicate capability action")
        templates = tuple(item.template_id for item in self.templates)
        if len(templates) != len(set(templates)):
            raise ValueError("duplicate template id")
        return self


class BusinessPluginRegistration(_PluginModel):
    plugin_id: PluginId
    version: str
    display_name: str
    manifest: BusinessPluginManifest
    registered_at: datetime
