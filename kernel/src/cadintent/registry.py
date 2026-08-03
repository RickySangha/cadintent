"""Rule-registry resolution (#28).

Registries are versioned, content-hashed, no-eval data artifacts
(spec/schemas/registry.json). A project brings one into scope with a
``registry.import`` declaration pinning {id, version, content_hash}; rule
citations pin {registry, version, name, params} against the imported version.
Project-local entries (``rule.define`` commands) live in the fold state and
are cited as {registry: "project", version: <seq of the defining command>,
name, params} — the same citation shape, pinned by the log itself.

Verification semantics: only ``verified`` entries can back a compliance pass;
a judgement against an ``unverified`` entry is visibly so; a missing required
value is a finding/refusal, never a silently invented default (the checks
enforce the latter — this module only resolves).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import jsonschema

from . import canonical, spec
from .fold import Model


class RegistryError(Exception):
    """A registry artifact could not be loaded or trusted."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def artifact_hash(doc: dict[str, Any]) -> str:
    """'sha256:<hex>' over the artifact's canonical bytes."""
    return "sha256:" + hashlib.sha256(canonical.canonical_bytes(doc)).hexdigest()


@dataclass(frozen=True)
class ResolvedRule:
    """One resolved rule entry and the citation coordinates that pin it."""

    registry: str  # registry id, or "project" for log-defined entries
    version: str  # registry version, or the defining command's seq as string
    entry: dict[str, Any]

    @property
    def name(self) -> str:
        return self.entry["name"]

    @property
    def verification(self) -> str:
        return self.entry["verification"]

    def judgement(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """The finding-document judgement record naming this entry."""
        record: dict[str, Any] = {
            "kind": "rule",
            "registry": self.registry,
            "version": self.version,
            "name": self.name,
            "verification": self.verification,
        }
        if params is not None:
            record["params"] = params
        return record


class RegistryStore:
    """Loaded registry artifacts, keyed (id, version), hash-checked on load."""

    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], dict[str, Any]] = {}
        self._hashes: dict[tuple[str, str], str] = {}

    def add(self, doc: dict[str, Any]) -> str:
        """Load one artifact; returns its content hash. Schema-validated."""
        errors = spec.schema_errors("registry.json#/$defs/RegistryArtifact", doc)
        if errors:
            path, message = errors[0]
            raise RegistryError(
                "schema_violation", f"registry artifact invalid at {path or '/'}: {message}"
            )
        key = (doc["id"], doc["version"])
        content_hash = artifact_hash(doc)
        self._artifacts[key] = doc
        self._hashes[key] = content_hash
        return content_hash

    def _imported(self, model: Model, registry: str, version: str) -> dict[str, Any]:
        """The loaded artifact for an imported (id, version), hash-enforced."""
        declared = next(
            (
                imp
                for imp in model.imports
                if imp["family"] == "registry"
                and imp["value"]["id"] == registry
                and imp["value"]["version"] == version
            ),
            None,
        )
        if declared is None:
            raise RegistryError(
                "unknown_reference",
                f"registry {registry!r} version {version!r} is not imported "
                "into this project",
            )
        key = (registry, version)
        if key not in self._artifacts:
            raise RegistryError(
                "unresolvable_registry",
                f"registry {registry!r} version {version!r} is imported but "
                "no artifact with that id/version is loaded",
            )
        if self._hashes[key] != declared["value"]["content_hash"]:
            raise RegistryError(
                "registry_hash_mismatch",
                f"registry {registry!r} version {version!r}: loaded artifact "
                f"hash {self._hashes[key]} does not match the imported pin "
                f"{declared['value']['content_hash']}",
            )
        return self._artifacts[key]

    def resolve(self, model: Model, registry: str, version: str, name: str) -> ResolvedRule:
        """Resolve one rule citation; raises RegistryError when unresolvable."""
        if registry == "project":
            for rule in model.rules:
                if rule["name"] == name and str(rule["seq"]) == version:
                    return ResolvedRule("project", version, rule)
            raise RegistryError(
                "unknown_reference",
                f"no project-local rule {name!r} defined at seq {version}",
            )
        artifact = self._imported(model, registry, version)
        for entry in artifact["entries"]:
            if entry["name"] == name:
                return ResolvedRule(registry, version, entry)
        raise RegistryError(
            "unknown_reference",
            f"registry {registry!r} version {version!r} has no entry {name!r}",
        )

    def entries_named(self, model: Model, name: str) -> list[ResolvedRule]:
        """Every resolvable entry with this name: imported registries (in
        import order), then project-local definitions (in log order)."""
        resolved: list[ResolvedRule] = []
        for imp in model.imports:
            if imp["family"] != "registry":
                continue
            key = (imp["value"]["id"], imp["value"]["version"])
            if key not in self._artifacts:
                continue  # not loaded: nothing to consult (checks stay not_run)
            artifact = self._imported(model, *key)
            for entry in artifact["entries"]:
                if entry["name"] == name:
                    resolved.append(ResolvedRule(key[0], key[1], entry))
        for rule in model.rules:
            if rule["name"] == name:
                resolved.append(ResolvedRule("project", str(rule["seq"]), rule))
        return resolved


def params_apply(entry: dict[str, Any], params: dict[str, Any]) -> bool:
    """Whether a parameter object validates against the entry's params schema
    (the schema doubles as a check's applicability predicate)."""
    try:
        jsonschema.Draft202012Validator(entry["params"]).validate(params)
    except jsonschema.ValidationError:
        return False
    return True
