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
    rules: list[dict[str, Any]] = field(default_factory=list)
    objects: dict[str, ObjectState] = field(default_factory=dict)
    #: each base citation in log order: {seq, name, content_hash, format}
    base_citations: list[dict[str, Any]] = field(default_factory=list)
    #: base content hash -> native entity reference -> the edits made to it
    base_entities: dict[str, dict[str, ObjectState]] = field(default_factory=dict)

    def copy(self) -> "Model":
        return copy.deepcopy(self)

    def base_name(self, content_hash: str) -> str | None:
        """The drawing name a base hash was cited under, if any."""
        for citation in self.base_citations:
            if citation["content_hash"] == content_hash:
                return citation["name"]
        return None

    def current_base(self, name: str) -> str | None:
        """The latest base hash cited under a drawing name, if any."""
        for citation in reversed(self.base_citations):
            if citation["name"] == name:
                return citation["content_hash"]
        return None

    def is_current_base(self, content_hash: str) -> bool:
        name = self.base_name(content_hash)
        return name is not None and self.current_base(name) == content_hash

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


#: the ``type`` fact of an object made by ``base.clone``
CLONE_TYPE = "base.clone"


def entity_key(content_hash: str, entity: str) -> str:
    """The key a base entity is tracked under: '<content hash>#<entity>'."""
    return f"{content_hash}#{entity}"


def split_entity_key(key: str) -> tuple[str, str]:
    content_hash, _, entity = key.partition("#")
    return content_hash, entity


def is_entity_key(key: str) -> bool:
    return "#" in key


def resolve_members(model: Model, ref: str) -> list[str]:
    """Expand a Ref to concrete members against the current state.

    A plain object ULID resolves to itself. A selection ULID resolves to its
    members; ``#group`` narrows to the named group. Explicit membership is the
    criteria objects that currently exist (a removed member simply no longer
    resolves). A base selection resolves to entity keys, from its recorded
    list. Raises ApplyError(unknown_reference) when the target does not resolve.
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
    is_base = criteria["kind"] == "base"
    members_key = "entities" if is_base else "objects"
    if group is None:
        members = criteria[members_key]
    else:
        for g in criteria.get("groups", []):
            if g["name"] == group:
                members = g[members_key]
                break
        else:
            raise ApplyError(
                "unknown_reference", "", f"selection {ulid!r} has no group {group!r}"
            )
    if is_base:
        return [entity_key(criteria["content_hash"], m) for m in members]
    return [m for m in members if m in model.objects]


_BASE_WHERE_LISTS = ("layers", "blocks", "types")


def _normalize_criteria(criteria: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a selection-criteria payload (order is non-semantic)."""
    if criteria["kind"] == "base":
        base: dict[str, Any] = {
            "kind": "base",
            "content_hash": criteria["content_hash"],
            "where": {
                key: sorted(value) if key in _BASE_WHERE_LISTS else value
                for key, value in criteria["where"].items()
            },
            "entities": sorted(criteria["entities"]),
        }
        if "groups" in criteria:
            base["groups"] = sorted(
                (
                    {"name": g["name"], "entities": sorted(g["entities"])}
                    for g in criteria["groups"]
                ),
                key=lambda g: g["name"],
            )
        return base
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

    if kind == "rule.define":
        entry: dict[str, Any] = {
            "seq": seq,
            "name": payload["name"],
            "params": payload["params"],
            "result": payload["result"],
            "semantics": payload["semantics"],
            "verification": "unverified",
        }
        if "value" in payload:
            entry["value"] = payload["value"]
        model.rules.append(entry)
        return
    if kind == "rule.verify":
        for rule in reversed(model.rules):
            if rule["name"] == payload["name"]:
                rule["verification"] = "verified"
                rule["verified_by"] = seq
                return
        raise ApplyError(
            "unknown_reference",
            "/name",
            f"no project-local rule {payload['name']!r} to verify",
        )

    if kind == "base.cite":
        content_hash, name = payload["content_hash"], payload["name"]
        cited_as = model.base_name(content_hash)
        if cited_as is not None and cited_as != name:
            raise ApplyError(
                "id_collision",
                "/content_hash",
                f"base {content_hash} is already cited as {cited_as!r}",
            )
        if model.current_base(name) == content_hash:
            raise ApplyError(
                "id_collision",
                "/content_hash",
                f"base {content_hash} is already the current citation of {name!r}",
            )
        model.base_citations.append(
            {
                "seq": seq,
                "name": name,
                "content_hash": content_hash,
                "format": payload["format"],
            }
        )
        return

    if kind in _BASE_EDIT_KINDS:
        if kind == "base.set_points" and payload["target"]["kind"] == "selection":
            raise ApplyError(
                "schema_violation",
                "/target",
                "one vertex list cannot be written to every member of a selection",
            )
        for key in _base_keys(model, payload["target"]):
            obj = _edit_state(model, key)
            if "deleted" in obj.facts:
                raise ApplyError(
                    "unknown_reference",
                    "/target",
                    f"{key!r} is deleted; revert it before editing it",
                )
            _write_base_fields(obj, seq, payload, key, touch)
        return

    if kind == "base.delete":
        for key in _base_keys(model, payload["target"]):
            if not is_entity_key(key):
                del model.objects[key]
                touch(key, "@removed")
                continue
            obj = _edit_state(model, key)
            if "deleted" in obj.facts:
                raise ApplyError("unknown_reference", "/target", f"{key!r} is already deleted")
            obj.facts["deleted"] = Fact(seq, True)
            touch(key, "deleted")
        return

    if kind == "base.revert":
        if payload["target"]["kind"] == "clone":
            raise ApplyError(
                "unknown_reference", "/target", "a clone has no base state to revert to"
            )
        reverted = False
        fields = payload.get("fields")
        for key in _base_keys(model, payload["target"]):
            content_hash, entity = split_entity_key(key)
            edited = model.base_entities.get(content_hash, {})
            obj = edited.get(entity)
            if obj is None:
                continue
            for path in [p for p in obj.facts if not fields or p.split(".", 1)[0] in fields]:
                del obj.facts[path]
                touch(key, path)
                reverted = True
            if not obj.facts:
                del edited[entity]
            if not edited:
                del model.base_entities[content_hash]
        if not reverted:
            raise ApplyError("unknown_reference", "/target", "nothing to revert")
        return

    if kind == "base.clone":
        ulid = payload["object"]
        if ulid in model.objects:
            raise ApplyError("id_collision", "/object", f"ULID {ulid!r} already exists")
        _require_current_base(model, payload["source"]["content_hash"], "/source/content_hash")
        obj = ObjectState()
        obj.facts["type"] = Fact(seq, CLONE_TYPE)
        obj.facts["clone_of"] = Fact(seq, payload["source"])
        touch(ulid, "@created", "type", "clone_of")
        _write_base_fields(obj, seq, payload, ulid, touch)
        model.objects[ulid] = obj
        return

    if kind == "selection.define":
        ulid = payload["object"]
        if payload["criteria"]["kind"] == "base":
            _require_current_base(
                model, payload["criteria"]["content_hash"], "/criteria/content_hash"
            )
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
            if "clone_of" in obj.facts:
                raise ApplyError(
                    "unknown_reference",
                    "/target",
                    f"{ulid!r} is a clone; edit it with base.* commands",
                )
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


def _is_base_selection(obj: ObjectState | None) -> bool:
    return (
        obj is not None
        and obj.is_selection
        and obj.facts["criteria"].value["kind"] == "base"
    )


def _resolve_target(model: Model, ref: str) -> list[str]:
    if _is_base_selection(model.objects.get(split_ref(ref)[0])):
        raise ApplyError(
            "unknown_reference", "/target", f"{ref!r} selects base entities; use base.* commands"
        )
    try:
        return resolve_members(model, ref)
    except ApplyError as exc:
        raise ApplyError(exc.code, "/target", exc.message, exc.objects) from exc


_BASE_EDIT_KINDS = frozenset(
    {"base.set_points", "base.set_text", "base.set_tags", "base.transform"}
)


def _require_current_base(model: Model, content_hash: str, path: str) -> None:
    if not model.is_current_base(content_hash):
        raise ApplyError(
            "unknown_reference", path, f"{content_hash} is not a current base citation"
        )


def _base_keys(model: Model, target: dict[str, Any]) -> list[str]:
    """Expand a base target to the entity keys, or clone ULID, it names."""
    if target["kind"] == "entity":
        _require_current_base(model, target["content_hash"], "/target/content_hash")
        return [entity_key(target["content_hash"], target["entity"])]
    if target["kind"] == "clone":
        ulid = target["object"]
        obj = model.objects.get(ulid)
        if obj is None or "clone_of" not in obj.facts:
            raise ApplyError("unknown_reference", "/target/object", f"no clone {ulid!r}")
        _require_current_base(model, obj.facts["clone_of"].value["content_hash"], "/target/object")
        return [ulid]
    ref = target["selection"]
    selection = model.objects.get(split_ref(ref)[0])
    if not _is_base_selection(selection):
        raise ApplyError(
            "unknown_reference", "/target/selection", f"{ref!r} does not name a base selection"
        )
    _require_current_base(
        model, selection.facts["criteria"].value["content_hash"], "/target/selection"
    )
    try:
        members = resolve_members(model, ref)
    except ApplyError as exc:
        raise ApplyError(exc.code, "/target/selection", exc.message) from exc
    if not members:
        raise ApplyError("unknown_reference", "/target/selection", f"{ref!r} selects no entities")
    return members


def _edit_state(model: Model, key: str) -> ObjectState:
    """The state holding a key's edits, created on first edit."""
    if not is_entity_key(key):
        return model.objects[key]
    content_hash, entity = split_entity_key(key)
    return model.base_entities.setdefault(content_hash, {}).setdefault(entity, ObjectState())


def _write_base_fields(
    obj: ObjectState, seq: int, payload: dict[str, Any], key: str, touch
) -> None:
    if "vertices" in payload:
        obj.facts["points"] = Fact(seq, payload["vertices"])
        touch(key, "points")
    for name in ("text", "transform"):
        if name in payload:
            obj.facts[name] = Fact(seq, payload[name])
            touch(key, name)
    for tag, value in payload.get("tags", {}).items():
        obj.facts[f"tags.{tag}"] = Fact(seq, value)
        touch(key, f"tags.{tag}")


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


def fold_into(model: Model, entries: list[dict[str, Any]]) -> Model:
    """Replay ``entries`` (continuing at ``model.head + 1``) into ``model``.

    The shared core of full replay and snapshot resume: total — raises
    FoldHalt, never partial. The resume point counts as a batch boundary
    (a snapshot's integrity was checked when it was folded).
    """
    prev_batch: str | None = None
    for entry in entries:
        seq = model.head + 1
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
    _check_integrity(model, model.head)
    return model


def fold(log: list[dict[str, Any]]) -> Model:
    """Replay a log into model state; total — raises FoldHalt, never partial."""
    return fold_into(Model(), log)


def _check_integrity(model: Model, at_seq: int) -> None:
    violations = integrity_violations(model)
    if violations:
        referrer, path, missing = violations[0]
        raise FoldHalt(
            at_seq,
            "dangling_reference",
            f"object {referrer!r} ({path}) references missing {missing!r}",
        )
