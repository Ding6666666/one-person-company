from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError

from dsh_company.application.ports import GovernanceUnitOfWorkFactory
from dsh_company.domain.policy import (
    ACTION_LEVELS,
    ActionCatalog,
    ActionDefinition,
)
from dsh_company.policy.runtime_profiles import core_action_catalog

from .manifest import (
    BusinessPluginManifest,
    BusinessPluginRegistration,
    WorkTemplate,
)


class InvalidPluginManifest(ValueError):
    """A business plugin attempted to cross its declarative namespace boundary."""


class BusinessPluginRegistry:
    def __init__(self, uow_factory: GovernanceUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def register(self, manifest: BusinessPluginManifest) -> BusinessPluginRegistration:
        prefix = f"{manifest.plugin_id}."
        if any(not action.action.startswith(prefix) for action in manifest.capability_actions):
            raise InvalidPluginManifest("action_namespace")
        if any(action.action in ACTION_LEVELS for action in manifest.capability_actions):
            raise InvalidPluginManifest("core_action_replacement")
        declared_actions = set(ACTION_LEVELS).union(
            action.action for action in manifest.capability_actions
        )
        if any(
            action not in declared_actions
            for template in manifest.templates
            for node in template.nodes
            for action in node.required_actions
        ):
            raise InvalidPluginManifest("unknown_template_action")
        if any(self._has_cycle(template) for template in manifest.templates):
            raise InvalidPluginManifest("template_cycle")
        try:
            with self._uow_factory() as uow:
                existing = uow.business_plugins.get(manifest.plugin_id)
                if existing is not None:
                    return self._resolve_existing(existing, manifest)
                registration = BusinessPluginRegistration(
                    plugin_id=manifest.plugin_id,
                    version=manifest.version,
                    display_name=manifest.display_name,
                    manifest=manifest,
                    registered_at=datetime.now(UTC),
                )
                uow.business_plugins.add(registration)
                uow.commit()
                return registration
        except IntegrityError as error:
            if not self._is_plugin_id_conflict(error):
                raise
        with self._uow_factory() as uow:
            winner = uow.business_plugins.get(manifest.plugin_id)
        if winner is None:
            raise RuntimeError("plugin registration winner was not persisted")
        return self._resolve_existing(winner, manifest)

    def list(self) -> tuple[BusinessPluginRegistration, ...]:
        with self._uow_factory() as uow:
            return uow.business_plugins.list()

    def get(self, plugin_id: str) -> BusinessPluginRegistration | None:
        with self._uow_factory() as uow:
            return uow.business_plugins.get(plugin_id)

    def templates(self, plugin_id: str) -> tuple[WorkTemplate, ...]:
        registration = self.get(plugin_id)
        if registration is None:
            raise LookupError("business plugin not found")
        return registration.manifest.templates

    def action_catalog(self) -> ActionCatalog:
        core = core_action_catalog()
        plugin_definitions = (
            ActionDefinition(
                action=action.action,
                level=action.level,
                runtime_profiles=frozenset(action.runtime_profiles),
            )
            for registration in self.list()
            for action in registration.manifest.capability_actions
        )
        return ActionCatalog((*core.definitions, *plugin_definitions))

    @staticmethod
    def _resolve_existing(
        existing: BusinessPluginRegistration,
        manifest: BusinessPluginManifest,
    ) -> BusinessPluginRegistration:
        if existing.manifest == manifest:
            return existing
        if existing.version != manifest.version:
            raise InvalidPluginManifest("version_conflict")
        raise InvalidPluginManifest("duplicate_manifest_conflict")

    @staticmethod
    def _is_plugin_id_conflict(error: IntegrityError) -> bool:
        message = str(error.orig).lower()
        return (
            "unique constraint failed" in message
            and "business_plugin_registrations.plugin_id" in message
        )

    @staticmethod
    def _has_cycle(template: WorkTemplate) -> bool:
        outgoing = {node.key: [] for node in template.nodes}
        indegrees = dict.fromkeys(outgoing, 0)
        for edge in template.edges:
            outgoing[edge.from_key].append(edge.to_key)
            indegrees[edge.to_key] += 1
        ready = sorted(key for key, degree in indegrees.items() if degree == 0)
        visited = 0
        while ready:
            key = ready.pop(0)
            visited += 1
            for target in sorted(outgoing[key]):
                indegrees[target] -= 1
                if indegrees[target] == 0:
                    ready.append(target)
                    ready.sort()
        return visited != len(indegrees)
