"""Presentation-pack resolution (#22 decision 8).

Presentation packs (text styles + label rules + symbol catalog together) are
versioned, content-hashed data artifacts (spec/schemas/presentation.json)
imported by a logged ``presentation.import`` declaration — the exact rule-
registry machinery (#28), no second mechanism.

Resolution is **nearest-first, whole-entry replacement**, per named entry
(style name, label-rule id, symbol name): the nearest layer's entry replaces
the farther one entirely — no field-level deep merge, so every resolved entry
is attributable to exactly one pack version. A nearer entry may be
``{disabled: true}`` to suppress a farther one. Nearest-first order is
**reverse import order**: the pack imported last is nearest (a project
imports its defaults first, its office pack next, its project pack last).

The ordered lists (symbol mappings, linework, tag fills) carry no entry
names; they are resolved wholesale — the nearest pack declaring a non-empty
list provides it entirely, attributed to that pack version (documented
within-space choice on #35).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from . import canonical, spec
from .fold import Model


class PresentationError(Exception):
    """A presentation pack could not be loaded, trusted, or resolved."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def pack_hash(doc: dict[str, Any]) -> str:
    """'sha256:<hex>' over the artifact's canonical bytes."""
    return "sha256:" + hashlib.sha256(canonical.canonical_bytes(doc)).hexdigest()


@dataclass(frozen=True)
class PackRef:
    """One pack version an entry or list is attributed to."""

    id: str
    version: str
    content_hash: str

    def as_doc(self) -> dict[str, str]:
        return {
            "id": self.id,
            "version": self.version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class ResolvedEntry:
    """One resolved named entry and the single pack version that authored it."""

    pack: PackRef
    entry: dict[str, Any]


@dataclass
class ResolvedPresentation:
    """The nearest-first resolution outcome over every imported pack."""

    packs: list[PackRef] = field(default_factory=list)  # nearest first
    text_styles: dict[str, ResolvedEntry] = field(default_factory=dict)
    label_rules: dict[str, ResolvedEntry] = field(default_factory=dict)
    symbols: dict[str, ResolvedEntry] = field(default_factory=dict)
    symbol_mappings: tuple[PackRef, list[dict[str, Any]]] | None = None
    linework: tuple[PackRef, list[dict[str, Any]]] | None = None
    tag_fills: tuple[PackRef, list[dict[str, Any]]] | None = None


class PackStore:
    """Loaded pack artifacts, keyed (id, version), schema- and hash-checked."""

    def __init__(self) -> None:
        self._artifacts: dict[tuple[str, str], dict[str, Any]] = {}
        self._hashes: dict[tuple[str, str], str] = {}

    def add(self, doc: dict[str, Any]) -> str:
        """Load one pack artifact; returns its content hash."""
        errors = spec.schema_errors("presentation.json#/$defs/PackArtifact", doc)
        if errors:
            path, message = errors[0]
            raise PresentationError(
                "schema_violation",
                f"presentation pack invalid at {path or '/'}: {message}",
            )
        key = (doc["id"], doc["version"])
        self._artifacts[key] = doc
        self._hashes[key] = pack_hash(doc)
        return self._hashes[key]

    def _pinned(self, declared: dict[str, Any]) -> tuple[PackRef, dict[str, Any]]:
        pin = declared["value"]
        key = (pin["id"], pin["version"])
        if key not in self._artifacts:
            raise PresentationError(
                "unresolvable_pack",
                f"presentation pack {pin['id']!r} version {pin['version']!r} is "
                "imported but no artifact with that id/version is loaded",
            )
        if self._hashes[key] != pin["content_hash"]:
            raise PresentationError(
                "pack_hash_mismatch",
                f"presentation pack {pin['id']!r} version {pin['version']!r}: "
                f"loaded artifact hash {self._hashes[key]} does not match the "
                f"imported pin {pin['content_hash']}",
            )
        ref = PackRef(pin["id"], pin["version"], self._hashes[key])
        return ref, self._artifacts[key]

    def resolve(self, model: Model) -> ResolvedPresentation:
        """Resolve every imported pack nearest-first (reverse import order)."""
        imports = [imp for imp in model.imports if imp["family"] == "presentation"]
        if not imports:
            raise PresentationError(
                "missing_declaration",
                "no presentation pack is imported into this project "
                "(presentation.import)",
            )
        resolved = ResolvedPresentation()
        for declared in reversed(imports):  # nearest (latest import) first
            ref, artifact = self._pinned(declared)
            resolved.packs.append(ref)
            for kind, target in (
                ("text_styles", resolved.text_styles),
                ("label_rules", resolved.label_rules),
                ("symbols", resolved.symbols),
            ):
                name_key = "id" if kind == "label_rules" else "name"
                for entry in artifact.get(kind, []):
                    name = entry[name_key]
                    if name in target:
                        continue  # a nearer entry (or disabled marker) already won
                    target[name] = ResolvedEntry(ref, entry)
            for kind in ("symbol_mappings", "linework", "tag_fills"):
                if getattr(resolved, kind) is None and artifact.get(kind):
                    setattr(resolved, kind, (ref, artifact[kind]))
        # Disabled markers suppress; drop them from the resolved views.
        for target in (resolved.text_styles, resolved.label_rules, resolved.symbols):
            for name in [n for n, e in target.items() if e.entry.get("disabled")]:
                del target[name]
        return resolved
