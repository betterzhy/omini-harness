from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class SchemaValidationError(ValueError):
    def __init__(self, schema_path: str, errors: list[str]):
        self.schema_path = schema_path
        self.errors = errors
        super().__init__(f"schema validation failed for {schema_path}: " + "; ".join(errors))


class SchemaStore:
    def __init__(self, repository_root: Path):
        self.repository_root = Path(repository_root)
        self._schemas: dict[str, dict[str, Any]] = {}
        self._registry = self._build_registry()

    def _build_registry(self) -> Registry:
        registry = Registry()
        for path in sorted(self.repository_root.glob("**/*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            key = path.relative_to(self.repository_root).as_posix()
            self._schemas[key] = schema
            schema_id = schema.get("$id")
            if schema_id:
                registry = registry.with_resource(schema_id, Resource.from_contents(schema))
        return registry

    def load(self, schema_path: str) -> dict[str, Any]:
        if schema_path not in self._schemas:
            path = self.repository_root / schema_path
            if not path.exists():
                raise FileNotFoundError(schema_path)
            self._schemas[schema_path] = json.loads(path.read_text(encoding="utf-8"))
        return self._schemas[schema_path]

    def validate(self, schema_path: str, instance: Any) -> None:
        schema = self.load(schema_path)
        validator = Draft202012Validator(schema, registry=self._registry)
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
        if errors:
            rendered = []
            for error in errors:
                loc = ".".join(str(p) for p in error.absolute_path) or "$"
                rendered.append(f"{loc}: {error.message}")
            raise SchemaValidationError(schema_path, rendered)
