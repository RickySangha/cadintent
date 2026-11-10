"""Canonical diff of two snapshots (#20).

One spec'd canonical field-level document, serialized by
:mod:`cadintent.canonical` (so canonical ordering — ULID, then path — falls
out of key sorting):

- ``spec`` — the spec version of the diff document;
- ``meta`` — snapshot-header changes (``project``, ``head``, ``log_hash``,
  ``spec``), each ``{"before": ..., "after": ...}``. Present so equality is
  coherent: bytes-equal ⟺ diff-empty ⟺ states-equal (law 10);
- ``declarations`` — changed declaration slots (``units``, ``crs``,
  ``imports``, ``rules``), each ``{"before", "after", "change"}``;
- ``created`` / ``removed`` — full object entries keyed by ULID, exactly as
  they appear in the target / base snapshot;
- ``modified`` — per object ULID, changed field paths (facts plus a
  selection's ``derivation``) in fixed order, each
  ``{"before": {seq, value} | null, "after": {seq, value} | null,
  "change": "value" | "provenance-only"}``;
- ``base`` — present only when a base citation or a base entity's edits
  changed: ``citations`` (one change record, or null) plus ``created`` /
  ``modified`` / ``removed`` keyed '<content hash>#<entity>'. A base entity is
  "created" when it is first edited and "removed" when fully reverted.

Every field change carries a tag: ``value`` when the value differs,
``provenance-only`` when a fact was rewritten to the same value (only its
writing seq changed). Equality is exact everywhere — no epsilon, no
tolerance; values are quantized at write time, so comparison is canonical
string equality. diff(S, S) is the single canonical empty document
(:func:`empty_diff_bytes`), independent of S.
"""

from __future__ import annotations

import json
from typing import Any

from . import canonical, spec

_META_KEYS = ("head", "log_hash", "project", "spec")
_DECLARATION_KEYS = ("crs", "imports", "rules", "units")

VALUE = "value"
PROVENANCE_ONLY = "provenance-only"


def _strip_provenance(value: Any) -> Any:
    """Drop the provenance-carrying keys (seq / verified_by) for tag decisions.

    Strips only the record's own top-level keys (descending through lists of
    records) — never inside stored values, where e.g. a command citation's
    ``seq`` is content, not provenance.
    """
    if isinstance(value, list):
        return [_strip_provenance(item) for item in value]
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in ("seq", "verified_by")}
    return value


def _change(before: Any, after: Any) -> dict[str, Any]:
    tag = (
        PROVENANCE_ONLY
        if before is not None
        and after is not None
        and _strip_provenance(before) == _strip_provenance(after)
        else VALUE
    )
    return {"before": before, "after": after, "change": tag}


def _object_paths(entry: dict[str, Any]) -> dict[str, Any]:
    paths = dict(entry["facts"])
    if "derivation" in entry:
        paths["derivation"] = entry["derivation"]
    return paths


def _diff_entries(
    entries_a: dict[str, Any], entries_b: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(created, modified, removed) between two keyed sets of entries."""
    created: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    modified: dict[str, Any] = {}
    for key in sorted(set(entries_a) | set(entries_b)):
        if key not in entries_a:
            created[key] = entries_b[key]
        elif key not in entries_b:
            removed[key] = entries_a[key]
        elif entries_a[key] != entries_b[key]:
            paths_a = _object_paths(entries_a[key])
            paths_b = _object_paths(entries_b[key])
            modified[key] = {
                path: _change(paths_a.get(path), paths_b.get(path))
                for path in sorted(set(paths_a) | set(paths_b))
                if paths_a.get(path) != paths_b.get(path)
            }
    return created, modified, removed


def _flat_entities(doc: dict[str, Any]) -> dict[str, Any]:
    """A snapshot's base entities keyed '<content hash>#<entity>'."""
    return {
        f"{content_hash}#{entity}": entry
        for content_hash, entities in doc.get("base", {}).get("entities", {}).items()
        for entity, entry in entities.items()
    }


def _base_diff(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    citations_a = a.get("base", {}).get("citations", [])
    citations_b = b.get("base", {}).get("citations", [])
    created, modified, removed = _diff_entries(_flat_entities(a), _flat_entities(b))
    if citations_a == citations_b and not (created or modified or removed):
        return None
    return {
        "citations": _change(citations_a, citations_b) if citations_a != citations_b else None,
        "created": created,
        "modified": modified,
        "removed": removed,
    }


def diff_doc(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The canonical diff document between two parsed snapshot documents."""
    meta = {
        key: {"before": a[key], "after": b[key]}
        for key in _META_KEYS
        if a[key] != b[key]
    }
    declarations = {
        key: _change(a["declarations"][key], b["declarations"][key])
        for key in _DECLARATION_KEYS
        if a["declarations"][key] != b["declarations"][key]
    }

    created, modified, removed = _diff_entries(a["objects"], b["objects"])
    doc: dict[str, Any] = {
        "spec": spec.SPEC_VERSION,
        "meta": meta,
        "declarations": declarations,
        "created": created,
        "modified": modified,
        "removed": removed,
    }
    base = _base_diff(a, b)
    if base is not None:
        doc["base"] = base
    return doc


def diff_bytes(a: bytes, b: bytes) -> bytes:
    """Canonical diff bytes between two canonical snapshot byte documents."""
    return canonical.canonical_bytes(diff_doc(json.loads(a), json.loads(b)))


def empty_diff_bytes() -> bytes:
    """The single canonical empty diff document — diff(S, S) for every S."""
    return canonical.canonical_bytes(
        {
            "spec": spec.SPEC_VERSION,
            "meta": {},
            "declarations": {},
            "created": {},
            "modified": {},
            "removed": {},
        }
    )
