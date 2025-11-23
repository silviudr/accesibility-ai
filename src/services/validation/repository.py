"""Repository abstraction over the SQLite dataset for validation needs."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Optional

from .models import ServiceMetadata


class ServiceRepository:
    """Loads and caches service metadata from the ingested SQLite database."""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)
        self._cache: Dict[str, ServiceMetadata] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _truthy(self, value: object | None) -> bool:
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {"y", "yes", "true", "1", "oui"}

    def _parse_channels(self, raw_channels: object | None) -> list[str]:
        if not raw_channels:
            return []
        return [channel.strip().lower() for channel in str(raw_channels).split(",") if channel.strip()]

    def _ensure_cache(self) -> None:
        if self._cache:
            return
        with self._connect() as conn:
            service_rows = conn.execute(
                """
                SELECT service_id, service_name_en, service_name_fr, client_feedback_channel,
                       owner_org, owner_org_title, fiscal_yr
                FROM service
                ORDER BY service_id, fiscal_yr DESC
                """
            ).fetchall()

            inventory_rows = conn.execute(
                """
                SELECT service_id, department_name_en, department_name_fr, service_type, service_scope,
                       client_target_groups, use_of_sin_number, use_of_cra_number, fiscal_yr
                FROM service_inventory_2018_2023
                ORDER BY service_id, fiscal_yr DESC
                """
            ).fetchall()

        latest_inventory: Dict[str, sqlite3.Row] = {}
        for row in inventory_rows:
            service_id = row["service_id"]
            if service_id not in latest_inventory:
                latest_inventory[service_id] = row

        latest_service_row: Dict[str, sqlite3.Row] = {}
        for row in service_rows:
            service_id = row["service_id"]
            if service_id not in latest_service_row:
                latest_service_row[service_id] = row

        for service_id, service_row in latest_service_row.items():
            inventory_row = latest_inventory.get(service_id)
            metadata = ServiceMetadata(
                service_id=service_id,
                service_name_en=service_row["service_name_en"],
                service_name_fr=service_row["service_name_fr"],
                channels=self._parse_channels(service_row["client_feedback_channel"]),
                fiscal_year=service_row["fiscal_yr"],
                requires_sin=False,
                requires_cra=False,
            )

            if inventory_row is not None:
                metadata.department_name_en = inventory_row["department_name_en"]
                metadata.department_name_fr = inventory_row["department_name_fr"]
                metadata.service_type = inventory_row["service_type"]
                metadata.service_scope = inventory_row["service_scope"]
                metadata.client_target_groups = inventory_row["client_target_groups"]
                metadata.requires_sin = self._truthy(inventory_row["use_of_sin_number"])
                metadata.requires_cra = self._truthy(inventory_row["use_of_cra_number"])
                if not metadata.fiscal_year:
                    metadata.fiscal_year = inventory_row["fiscal_yr"]

            self._cache[service_id] = metadata

    def get_metadata(self, service_id: str) -> Optional[ServiceMetadata]:
        self._ensure_cache()
        return self._cache.get(service_id)

    def list_services(self) -> list[ServiceMetadata]:
        self._ensure_cache()
        return list(self._cache.values())
