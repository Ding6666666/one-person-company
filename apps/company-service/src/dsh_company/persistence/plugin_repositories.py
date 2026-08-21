from datetime import UTC

from dsh_company.business_plugins.manifest import (
    BusinessPluginManifest,
    BusinessPluginRegistration,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import BusinessPluginRegistrationRow


class BusinessPluginRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, registration: BusinessPluginRegistration) -> None:
        self._session.add(
            BusinessPluginRegistrationRow(
                plugin_id=registration.plugin_id,
                version=registration.version,
                display_name=registration.display_name,
                manifest_json=registration.manifest.model_dump_json(),
                registered_at=registration.registered_at,
            )
        )

    def get(self, plugin_id: str) -> BusinessPluginRegistration | None:
        row = self._session.get(BusinessPluginRegistrationRow, plugin_id)
        return None if row is None else self._registration(row)

    def list(self) -> tuple[BusinessPluginRegistration, ...]:
        rows = self._session.scalars(
            select(BusinessPluginRegistrationRow).order_by(
                BusinessPluginRegistrationRow.plugin_id
            )
        )
        return tuple(self._registration(row) for row in rows)

    @staticmethod
    def _registration(row: BusinessPluginRegistrationRow) -> BusinessPluginRegistration:
        return BusinessPluginRegistration(
            plugin_id=row.plugin_id,
            version=row.version,
            display_name=row.display_name,
            manifest=BusinessPluginManifest.model_validate_json(row.manifest_json),
            registered_at=row.registered_at.replace(tzinfo=UTC),
        )
