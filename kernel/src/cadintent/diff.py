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
  "change": "value" | "provenance-only"}``.

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

    created: dict[str, Any] = {}
    removed: dict[str, Any] = {}
    modified: dict[str, Any] = {}
    objects_a, objects_b = a["objects"], b["objects"]
    for ulid in sorted(set(objects_a) | set(objects_b)):
        if ulid not in objects_a:
            created[ulid] = objects_b[ulid]
        elif ulid not in objects_b:
            removed[ulid] = objects_a[ulid]
        elif objects_a[ulid] != objects_b[ulid]:
            paths_a = _object_paths(objects_a[ulid])
            paths_b = _object_paths(objects_b[ulid])
            modified[ulid] = {
                path: _change(paths_a.get(path), paths_b.get(path))
                for path in sorted(set(paths_a) | set(paths_b))
                if paths_a.get(path) != paths_b.get(path)
            }

    return {
        "spec": spec.SPEC_VERSION,
        "meta": meta,
        "declarations": declarations,
        "created": created,
        "modified": modified,
        "removed": removed,
    }


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
