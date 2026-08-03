"""Canonical snapshot serialization — the conformance oracle (#20).

One canonical JSON document (serialized by :mod:`cadintent.canonical`):

- ``spec`` — the spec version the snapshot document conforms to;
- ``project`` / ``head`` — identity and the log entry folded to;
- ``log_hash`` — the content hash of the source log (see canonical.log_hash);
- ``declarations`` — fixed shape: ``units`` and ``crs`` ({seq, value} or
  null), ``imports`` (list in log order, each {seq, family, value});
- ``objects`` — keyed by ULID; each object's ``facts`` map fact path
  ("type", "geometry", "ends", "networks", "criteria", "attrs.<name>") to
  {seq, value}; selection objects additionally carry a ``derivation`` record:
  {seq, objects, groups} — membership resolved at fold (existing criteria
  members, sorted).
"""

from __future__ import annotations

from typing import Any

from . import canonical, spec
from .fold import Fact, Model, fold


def _fact(fact: Fact) -> dict[str, Any]:
    return {"seq": fact.seq, "value": fact.value}


def _derivation(model: Model, criteria_fact: Fact) -> dict[str, Any]:
    criteria = criteria_fact.value
    return {
        "seq": criteria_fact.seq,
        "objects": sorted(m for m in criteria["objects"] if m in model.objects),
        "groups": {
            g["name"]: sorted(m for m in g["objects"] if m in model.objects)
            for g in criteria.get("groups", [])
        },
    }


def snapshot_doc(model: Model, log: list[dict[str, Any]]) -> dict[str, Any]:
    objects: dict[str, Any] = {}
    for ulid, obj in model.objects.items():
        entry: dict[str, Any] = {
            "facts": {path: _fact(f) for path, f in obj.facts.items()}
        }
        if obj.is_selection:
            entry["derivation"] = _derivation(model, obj.facts["criteria"])
        objects[ulid] = entry
    return {
        "spec": spec.SPEC_VERSION,
        "project": model.project,
        "head": model.head,
        "log_hash": canonical.log_hash(log),
        "declarations": {
            "units": _fact(model.units) if model.units else None,
            "crs": _fact(model.crs) if model.crs else None,
            "imports": model.imports,
        },
        "objects": objects,
    }


def snapshot_bytes(log: list[dict[str, Any]]) -> bytes:
    """Fold a log and serialize the canonical snapshot. Raises FoldHalt."""
    return canonical.canonical_bytes(snapshot_doc(fold(log), log))
