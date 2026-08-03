"""Canonical snapshot serialization + snapshot resume — the conformance
oracle (#20).

One canonical JSON document (serialized by :mod:`cadintent.canonical`):

- ``spec`` — the spec version the snapshot document conforms to;
- ``project`` / ``head`` — identity and the log entry folded to;
- ``log_hash`` — the chained content hash of the source log (see
  canonical.log_hash);
- ``declarations`` — fixed shape: ``units`` and ``crs`` ({seq, value} or
  null), ``imports`` (list in log order, each {seq, family, value}), and
  ``rules`` (project-local rule entries in log order, each {seq, name,
  params, result, semantics[, value], verification[, verified_by]});
- ``objects`` — keyed by ULID; each object's ``facts`` map fact path
  ("type", "geometry", "ends", "networks", "criteria", "attrs.<name>") to
  {seq, value}; selection objects additionally carry a ``derivation`` record:
  {seq, objects, groups} — membership resolved at fold (existing criteria
  members, sorted).

Resume (#20 law 4): :func:`fold_from` continues a fold from a snapshot and
MUST byte-equal full replay. A stale snapshot refuses rather than serves —
spec-stamp or prefix mismatches raise :class:`StaleSnapshot`, a typed error
carrying the re-index hint (fold the full log from seq 1).
"""

from __future__ import annotations

import json
from typing import Any

from . import canonical, spec
from .fold import Fact, Model, ObjectState, fold, fold_into

_REINDEX_HINT = "re-index by folding the full log from seq 1"


class StaleSnapshot(Exception):
    """The snapshot does not match its log (or spec): refuse, never serve."""

    code = "stale_snapshot"

    def __init__(self, message: str) -> None:
        self.message = f"{message}; {_REINDEX_HINT}"
        super().__init__(f"[{self.code}] {self.message}")


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


def snapshot_doc(model: Model, log_hash: str) -> dict[str, Any]:
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
        "log_hash": log_hash,
        "declarations": {
            "units": _fact(model.units) if model.units else None,
            "crs": _fact(model.crs) if model.crs else None,
            "imports": model.imports,
            "rules": model.rules,
        },
        "objects": objects,
    }


def snapshot_bytes(log: list[dict[str, Any]]) -> bytes:
    """Fold a log and serialize the canonical snapshot. Raises FoldHalt."""
    return canonical.canonical_bytes(snapshot_doc(fold(log), canonical.log_hash(log)))


# ---------------------------------------------------------------------------
# Resume


def model_from_doc(doc: dict[str, Any]) -> Model:
    """Reconstruct fold state from a parsed canonical snapshot document."""
    declarations = doc["declarations"]
    model = Model(
        project=doc["project"],
        head=doc["head"],
        units=Fact(**declarations["units"]) if declarations["units"] else None,
        crs=Fact(**declarations["crs"]) if declarations["crs"] else None,
        imports=list(declarations["imports"]),
        rules=[dict(rule) for rule in declarations["rules"]],
    )
    for ulid, entry in doc["objects"].items():
        obj = ObjectState()
        obj.facts = {
            path: Fact(fact["seq"], fact["value"])
            for path, fact in entry["facts"].items()
        }
        model.objects[ulid] = obj
    return model


def _parse_snapshot(snapshot: bytes) -> dict[str, Any]:
    try:
        doc = json.loads(snapshot)
    except (ValueError, UnicodeDecodeError) as exc:
        raise StaleSnapshot(f"snapshot is not parseable JSON ({exc})") from exc
    if not isinstance(doc, dict) or "spec" not in doc:
        raise StaleSnapshot("snapshot carries no spec stamp")
    if doc["spec"] != spec.SPEC_VERSION:
        raise StaleSnapshot(
            f"snapshot spec {doc['spec']!r} does not match supported spec "
            f"{spec.SPEC_VERSION!r}"
        )
    return doc


def verify_snapshot(snapshot: bytes, log: list[dict[str, Any]]) -> dict[str, Any]:
    """Check a snapshot against its claimed log prefix; stale refuses.

    Returns the parsed snapshot document when the spec stamp is supported,
    ``head`` names an existing prefix of ``log``, and the recorded chained
    ``log_hash`` matches that prefix's content hash.
    """
    doc = _parse_snapshot(snapshot)
    head = doc["head"]
    if head > len(log):
        raise StaleSnapshot(
            f"snapshot head {head} is beyond the log's head {len(log)}"
        )
    prefix_hash = canonical.log_hash(log[:head])
    if doc["log_hash"] != prefix_hash:
        raise StaleSnapshot(
            f"snapshot log_hash {doc['log_hash']} does not match the content "
            f"hash of log entries 1..{head} ({prefix_hash})"
        )
    return doc


def fold_from(snapshot: bytes, commands: list[dict[str, Any]]) -> bytes:
    """Resume a fold from a snapshot; byte-equals full replay (#20 law 4).

    ``commands`` are the envelope-complete log entries after the snapshot's
    head. A snapshot whose spec stamp is unsupported, or whose head does not
    meet the first resumed entry, raises :class:`StaleSnapshot`.
    """
    doc = _parse_snapshot(snapshot)
    if commands and commands[0].get("seq") != doc["head"] + 1:
        raise StaleSnapshot(
            f"resume commands start at seq {commands[0].get('seq')!r} but the "
            f"snapshot's head is {doc['head']}"
        )
    model = fold_into(model_from_doc(doc), commands)
    log_hash = canonical.extend_log_hash(doc["log_hash"], commands)
    return canonical.canonical_bytes(snapshot_doc(model, log_hash))
