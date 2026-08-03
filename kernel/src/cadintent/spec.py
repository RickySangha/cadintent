"""Spec loading: JSON Schemas, the schema registry, and per-kind command metadata.

The kernel enforces the ``x-cadintent-command`` annotations carried by the
payload defs in ``commands.json`` (allowed author roles, basis requiredness,
declaration class, scope-audit exemption) — they are kernel semantics, not
instance validation.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

SPEC_VERSION = "0.1.0"

SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "spec" / "schemas"

#: Command kinds that are project declarations (#29): not design content.
DECLARATION_KINDS = frozenset(
    {"project.units", "project.crs", "registry.import", "presentation.import"}
)


@lru_cache(maxsize=1)
def schemas() -> dict[str, Any]:
    return {
        path.name: json.loads(path.read_text())
        for path in sorted(SCHEMAS_DIR.glob("*.json"))
    }


@lru_cache(maxsize=1)
def registry() -> Registry:
    return Registry().with_resources(
        (name, Resource.from_contents(doc)) for name, doc in schemas().items()
    )


@lru_cache(maxsize=1)
def commands() -> dict[str, dict[str, Any]]:
    """Per-kind metadata from the x-cadintent-command annotations.

    kind -> {"def": defs-name, "roles": [...], "basis": "optional"|"required",
             "declaration_class": str|None, "scope_audit_exempt": bool}
    """
    table: dict[str, dict[str, Any]] = {}
    for def_name, def_schema in schemas()["commands.json"]["$defs"].items():
        annotation = def_schema.get("x-cadintent-command")
        if annotation is None:
            continue
        table[annotation["kind"]] = {
            "def": def_name,
            "roles": frozenset(annotation["authorRoles"]),
            "basis": annotation["basis"],
            "declaration_class": annotation.get("declarationClass"),
            "scope_audit_exempt": bool(annotation.get("scopeAuditExempt", False)),
        }
    return table


def _validator(schema_ref: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator({"$ref": schema_ref}, registry=registry())


@lru_cache(maxsize=64)
def validator(schema_ref: str) -> jsonschema.Draft202012Validator:
    return _validator(schema_ref)


def payload_validator(kind: str) -> jsonschema.Draft202012Validator:
    meta = commands()[kind]
    return validator(f"commands.json#/$defs/{meta['def']}")


def pointer(parts: tuple[Any, ...] | list[Any]) -> str:
    """Encode a jsonschema error path as a JSON Pointer string."""
    if not parts:
        return ""
    return "/" + "/".join(
        str(p).replace("~", "~0").replace("/", "~1") for p in parts
    )


def _leaf(error: jsonschema.ValidationError) -> jsonschema.ValidationError:
    """Descend into oneOf branch contexts, picking the best (deepest) match."""
    while error.context:
        error = jsonschema.exceptions.best_match(error.context) or error.context[0]
    return error


def schema_errors(schema_ref: str, document: Any) -> list[tuple[str, str]]:
    """Validate; return [(json_pointer, message)] using best-match leaf errors."""
    out: list[tuple[str, str]] = []
    for error in validator(schema_ref).iter_errors(document):
        leaf = _leaf(error)
        out.append((pointer(tuple(leaf.absolute_path)), leaf.message))
    return sorted(set(out))
