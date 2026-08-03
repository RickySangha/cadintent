"""Fold: deterministic replay of a command log into model state.

Total per #20: fold yields a complete model or raises :class:`FoldHalt` naming
the entry it stopped at — never a partial result. ``created_at`` is ignored;
replay is determined by content and order only. Referential integrity is
checked at every batch boundary (the invariant is "after every submission
folds, every topology reference resolves").
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from . import spec

# ---------------------------------------------------------------------------
# Model state


@dataclass
class Fact:
    """One fact on an object: its value and the seq that wrote it."""

    seq: int
    value: Any


@dataclass
class ObjectState:
    facts: dict[str, Fact] = field(default_factory=dict)

    @property
    def is_selection(self) -> bool:
        return "criteria" in self.facts


@dataclass
class Model:
    project: str | None = None
    head: int = 0
    units: Fact | None = None
    crs: Fact | None = None
    imports: list[dict[str, Any]] = field(default_factory=list)
    objects: dict[str, ObjectState] = field(default_factory=dict)

    def copy(self) -> "Model":
        return copy.deepcopy(self)

    def has_import(self, family: str, artifact_id: str, version: str) -> bool:
        return any(
            imp["family"] == family
            and imp["value"]["id"] == artifact_id
            and imp["value"]["version"] == version
            for imp in self.imports
        )


class FoldHalt(Exception):
    """Fold stopped: a typed error naming the offending log entry."""

    def __init__(self, seq: int, code: str, message: str) -> None:
        self.seq = seq
        self.code = code
        self.message = message
        super().__init__(f"fold halted at seq {seq} [{code}]: {message}")


class ApplyError(Exception):
    """A command could not be applied to the current state."""

    def __init__(
        self, code: str, path: str, message: str, objects: list[str] | None = None
    ) -> None:
        self.code = code
        self.path = path
        self.message = message
        self.objects = objects or []
        super().__init__(f"[{code}] {path}: {message}")


# ---------------------------------------------------------------------------
# Shared per-command checks (used by fold and by the submit pipeline)

_IMPORT_FAMILY = {"registry.import": "registry", "presentation.import": "presentation"}


def static_errors(command: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Kind/spec/role/basis/payload-schema checks needing no model state.

    Returns [(code, path, message)]. ``command`` carries at least
    author/kind/payload/basis/spec (envelope or submitted-command shaped).
    """
    errors: list[tuple[str, str, str]] = []
    kind = command["kind"]
    if command["spec"] != spec.SPEC_VERSION:
        errors.append(
            ("spec_unsupported", "/spec", f"spec {command['spec']!r} is not supported")
        )
    meta = spec.commands().get(kind)
    if meta is None:
        errors.append(("unknown_kind", "/kind", f"unknown command kind {kind!r}"))
        return errors
    role = command["author"].split(":", 1)[0]
    if role not in meta["roles"]:
        errors.append(
            (
                "author_role_violation",
                "/author",
                f"role {role!r} may not author {kind!r}",
            )
        )
    if meta["basis"] == "required" and not command["basis"]:
        errors.append(("missing_basis", "/basis", f"{kind!r} requires a non-empty basis"))
    for path, message in spec.schema_errors(
        f"commands.json#/$defs/{meta['def']}", command["payload"]
    ):
        errors.append(("schema_violation", "/payload" + path, message))
    return errors


def ordering_error(model: Model, kind: str) -> tuple[str, str, str] | None:
    """Declaration ordering per #29: units first, once, immutable."""
    if kind == "project.units":
        if model.units is not None:
            return (
                "immutable_declaration",
                "/payload",
                "the unit system is declared exactly once and is immutable",
            )
        return None
    if kind in spec.DECLARATION_KINDS:
        return None
    if model.units is None:
        return (
            "missing_declaration",
            "",
            "design content requires a landed project.units declaration",
        )
    return None


# ---------------------------------------------------------------------------
# Target / reference expansion


def split_ref(ref: str) -> tuple[str, str | None]:
    ulid, _, group = ref.partition("#")
    return ulid, (group or None)


def resolve_members(model: Model, ref: str) -> list[str]:
    """Expand a Ref to concrete object ULIDs against the current state.

    A plain object ULID resolves to itself. A selection ULID resolves to its
    members; ``#group`` narrows to the named group. Membership is the criteria
    objects that currently exist (a removed member simply no longer resolves).
    Raises ApplyError(unknown_reference) when the target does not resolve.
    """
    ulid, group = split_ref(ref)
    obj = model.objects.get(ulid)
    if obj is None:
        raise ApplyError("unknown_reference", "", f"no such object {ulid!r}")
    if not obj.is_selection:
        if group is not None:
            raise ApplyError(
                "unknown_reference", "", f"{ulid!r} is not a selection; no group {group!r}"
            )
        return [ulid]
    criteria = obj.facts["criteria"].value
    if group is None:
        members = criteria["objects"]
    else:
        for g in criteria.get("groups", []):
            if g["name"] == group:
                members = g["objects"]
                break
        else:
            raise ApplyError(
                "unknown_reference", "", f"selection {ulid!r} has no group {group!r}"
            )
    return [m for m in members if m in model.objects]


def _normalize_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize the explicit-criteria payload (order is non-semantic)."""
    out: dict[str, Any] = {"kind": criteria["kind"], "objects": sorted(criteria["objects"])}
    if "groups" in criteria:
        out["groups"] = sorted(
            (
                {"name": g["name"], "objects": sorted(g["objects"])}
                for g in criteria["groups"]
            ),
            key=lambda g: g["name"],
        )
    return out


# ---------------------------------------------------------------------------
# Apply


def apply_command(
    model: Model,
    seq: int,
    kind: str,
    payload: dict[str, Any],
    touched: dict[str, set[str]] | None = None,
) -> None:
    """Apply one validated command to the model in place.

    ``touched`` (ulid -> fact paths, plus "@created"/"@removed" markers)
    collects the command's actual effect for the scope audit. Raises
    ApplyError when the command cannot apply to the current state.
    """

    def touch(ulid: str, *paths: str) -> None:
        if touched is not None:
            touched.setdefault(ulid, set()).update(paths)

    if kind == "project.units":
        model.units = Fact(seq, payload["system"])
        return
    if kind == "project.crs":
        model.crs = Fact(seq, payload["crs"])
        return
    if kind in _IMPORT_FAMILY:
        family = _IMPORT_FAMILY[kind]
        key = "registry" if family == "registry" else "pack"
        model.imports.append({"seq": seq, "family": family, "value": payload[key]})
        return

    if kind == "selection.define":
        ulid = payload["object"]
        existing = model.objects.get(ulid)
        if existing is not None and not existing.is_selection:
            raise ApplyError(
                "id_collision", "/object", f"ULID {ulid!r} already names a design object"
            )
        if existing is None:
            model.objects[ulid] = existing = ObjectState()
        existing.facts["criteria"] = Fact(seq, _normalize_criteria(payload["criteria"]))
        # selection.define mutates no design fact; its touch is scope-audit
        # exempt and deliberately not recorded in ``touched``.
        return

    if kind == "object.create":
        ulid = payload["object"]
        if ulid in model.objects:
            raise ApplyError("id_collision", "/object", f"ULID {ulid!r} already exists")
        obj = ObjectState()
        obj.facts["type"] = Fact(seq, payload["type"])
        touch(ulid, "@created", "type")
        _write_fields(obj, seq, payload, ulid, touch)
        model.objects[ulid] = obj
        return

    if kind == "object.set_attrs":
        for ulid in _resolve_target(model, payload["target"]):
            obj = model.objects[ulid]
            _write_fields(obj, seq, payload, ulid, touch)
        return

    if kind == "object.remove":
        members = _resolve_target(model, payload["target"])
        if not members:
            raise ApplyError(
                "unknown_reference",
                "/target",
                f"target {payload['target']!r} resolves to no objects",
            )
        for ulid in members:
            del model.objects[ulid]
            touch(ulid, "@removed")
        return

    raise ApplyError("unknown_kind", "", f"unknown command kind {kind!r}")


def _resolve_target(model: Model, ref: str) -> list[str]:
    try:
        return resolve_members(model, ref)
    except ApplyError as exc:
        raise ApplyError(exc.code, "/target", exc.message, exc.objects) from exc


def _write_fields(
    obj: ObjectState, seq: int, payload: dict[str, Any], ulid: str, touch
) -> None:
    if "geometry" in payload:
        obj.facts["geometry"] = Fact(seq, payload["geometry"])
        touch(ulid, "geometry")
    if "ends" in payload:
        obj.facts["ends"] = Fact(seq, payload["ends"])
        touch(ulid, "ends")
    if "networks" in payload:
        obj.facts["networks"] = Fact(seq, sorted(payload["networks"]))
        touch(ulid, "networks")
    for name, value in payload.get("attrs", {}).items():
        obj.facts[f"attrs.{name}"] = Fact(seq, value)
        touch(ulid, f"attrs.{name}")


# ---------------------------------------------------------------------------
# Referential integrity


def integrity_violations(model: Model) -> list[tuple[str, str, str]]:
    """[(referrer_ulid, fact_path, missing_ulid)] for every unresolved
    topology reference (edge ends, network memberships)."""
    out: list[tuple[str, str, str]] = []
    for ulid, obj in sorted(model.objects.items()):
        ends = obj.facts.get("ends")
        if ends is not None:
            for end_name in ("end_a", "end_b"):
                binding = ends.value[end_name]
                target = binding["node"] if binding["kind"] == "node" else binding["edge"]
                if target not in model.objects:
                    out.append((ulid, f"ends.{end_name}", target))
        networks = obj.facts.get("networks")
        if networks is not None:
            for net in networks.value:
                if net not in model.objects:
                    out.append((ulid, "networks", net))
    return out


# ---------------------------------------------------------------------------
# Fold


def fold(log: list[dict[str, Any]]) -> Model:
    """Replay a log into model state; total — raises FoldHalt, never partial."""
    model = Model()
    prev_batch: str | None = None
    for index, entry in enumerate(log):
        seq = index + 1
        errors = spec.schema_errors("envelope.json#/$defs/Envelope", entry)
        if errors:
            path, message = errors[0]
            raise FoldHalt(seq, "schema_violation", f"{path or '/'}: {message}")
        if entry["seq"] != seq:
            raise FoldHalt(
                seq, "schema_violation", f"expected seq {seq}, entry claims {entry['seq']}"
            )
        if model.project is None:
            model.project = entry["project"]
        elif entry["project"] != model.project:
            raise FoldHalt(seq, "schema_violation", "entry belongs to another project")
        if prev_batch is not None and entry["batch"] != prev_batch:
            _check_integrity(model, seq - 1)
        prev_batch = entry["batch"]
        for code, path, message in static_errors(entry):
            raise FoldHalt(seq, code, f"{path or '/'}: {message}")
        ordering = ordering_error(model, entry["kind"])
        if ordering is not None:
            raise FoldHalt(seq, ordering[0], ordering[2])
        try:
            apply_command(model, seq, entry["kind"], entry["payload"])
        except ApplyError as exc:
            raise FoldHalt(seq, exc.code, exc.message) from exc
        model.head = seq
    _check_integrity(model, len(log))
    return model


def _check_integrity(model: Model, at_seq: int) -> None:
    violations = integrity_violations(model)
    if violations:
        referrer, path, missing = violations[0]
        raise FoldHalt(
            at_seq,
            "dangling_reference",
            f"object {referrer!r} ({path}) references missing {missing!r}",
        )
