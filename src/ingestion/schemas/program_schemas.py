"""Program schema definitions loaded from config/program_schemas.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class ProgramField:
    key: str
    type: str
    label_en: str
    label_fr: str
    prompt_en: str
    prompt_fr: str
    options: Optional[List[str]] = None


@dataclass
class ProgramSchema:
    service_id: str
    fields: List[ProgramField]


class ProgramSchemaRepository:
    """Loads program schema definitions stored in JSON."""

    def __init__(self, config_path: Path | str = "config/program_schemas.json") -> None:
        self.config_path = Path(config_path)
        self._cache: Dict[str, ProgramSchema] = {}
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for entry in payload:
            fields = [
                ProgramField(
                    key=field["key"],
                    type=field.get("type", "text"),
                    label_en=field.get("label_en", field["key"]),
                    label_fr=field.get("label_fr", field["key"]),
                    prompt_en=field.get("prompt_en", ""),
                    prompt_fr=field.get("prompt_fr", ""),
                    options=field.get("options"),
                )
                for field in entry.get("fields", [])
            ]
            schema = ProgramSchema(service_id=entry["service_id"], fields=fields)
            self._cache[entry["service_id"]] = schema

    def get(self, service_id: str) -> Optional[ProgramSchema]:
        return self._cache.get(service_id)

    def list_all(self) -> List[ProgramSchema]:
        return list(self._cache.values())
