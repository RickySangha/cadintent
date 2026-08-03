"""Submit: the acceptance pipeline (#17, #19, #27, #29).

Order: schema -> stale head -> kind/author-role/basis/spec -> reference
resolution -> id/name collision -> declaration ordering -> apply (trial fold)
-> post-fold referential integrity -> scope audit. A refusal is total: every
error is reported at once where computable and the log is left untouched.
Acceptance extends the log with envelope-complete commands (kernel-stamped
seq, batch ULID, created_at).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from . import spec, ulid as ulid_mod
from .fold import (
    ApplyError,
    Model,
    apply_command,
    fold,
    integrity_violations,
    resolve_members,
    split_ref,
    static_errors,
)

# ---------------------------------------------------------------------------
# Results


@dataclass
class Accepted:
    log: list[dict[str, Any]]
    batch: str


@dataclass
class Refused:
    refusal: dict[str, Any]


def _err(
    code: str,
    command: int | None,
    path: str,
    message: str,
    objects: list[str] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "command": command,
        "path": path,
        "message": message,
    }
    if objects:
        error["objects"] = sorted(set(objects))
    return error


def _sort_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Canonical order per #23: command index (submission-level first), path, code.
    return sorted(
        errors,
        key=lambda e: (
            -1 if e["command"] is None else e["command"],
            e["path"],
            e["code"],
        ),
    )


# ---------------------------------------------------------------------------
# Validate (deliverable: schema validation with command position + field path)


def validate_submission(document: Any) -> list[dict[str, Any]]:
    """Structural + per-kind payload schema validation of a submission document.

    Returns refusal-error dicts (empty when valid). Command position and field
    path attached wherever the error can be located under a command.
    """
    errors = _structural_errors(document)
    if not errors and isinstance(document, dict):
        for i, command in enumerate(document.get("commands", [])):
            for code, path, message in static_errors(command):
                if code in ("schema_violation", "unknown_kind"):
                    errors.append(_err(code, i, path, message))
    return _sort_errors(errors)


def _structural_errors(document: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for error in spec.validator("submission.json#/$defs/Submission").iter_errors(
        document
    ):
        leaf = error
        while leaf.context:
            import jsonschema

            leaf = jsonschema.exceptions.best_match(leaf.context) or leaf.context[0]
        parts = list(leaf.absolute_path)
        if len(parts) >= 2 and parts[0] == "commands" and isinstance(parts[1], int):
            command, rel = parts[1], parts[2:]
        else:
            command, rel = None, parts
        errors.append(
            _err("schema_violation", command, spec.pointer(tuple(rel)), leaf.message)
        )
    return errors


# ---------------------------------------------------------------------------
# Reference resolution helpers


def _iter_payload_refs(kind: str, payload: dict[str, Any]):
    """Yield (path, ulid) for every ULID reference the payload makes to an
    existing (or earlier-minted) object. The target Ref of set_attrs/remove is
    handled separately (selection expansion)."""
    if kind == "selection.define":
        for i, member in enumerate(payload["criteria"].get("objects", [])):
            yield f"/criteria/objects/{i}", member
        for gi, group in enumerate(payload["criteria"].get("groups", [])):
            for oi, member in enumerate(group["objects"]):
                yield f"/criteria/groups/{gi}/objects/{oi}", member
    if kind in ("object.create", "object.set_attrs"):
        ends = payload.get("ends")
        if ends is not None:
            for end in ("end_a", "end_b"):
                binding = ends[end]
                if binding["kind"] == "node":
                    yield f"/ends/{end}/node", binding["node"]
                else:
                    yield f"/ends/{end}/edge", binding["edge"]
        for i, net in enumerate(payload.get("networks", [])):
            yield f"/networks/{i}", net
        for name, value in payload.get("attrs", {}).items():
            if value.get("kind") == "reference":
                yield f"/attrs/{name}/value", value["value"]


# ---------------------------------------------------------------------------
# Scope audit (#27)


def _defining_points(geometry: dict[str, Any]):
    kind = geometry["kind"]
    if kind == "point":
        yield geometry["point"]
    elif kind == "polyline":
        for v in geometry["vertices"]:
            yield v["point"]
    elif kind == "arc":
        yield geometry["start"]
        yield geometry["end"]
    elif kind == "circle":
        yield geometry["center"]


def _point_in_region(point: dict[str, str], region: dict[str, Any]) -> bool:
    """Even-odd point-in-polygon over the region's vertices (bulges treated as
    chords in v0), boundary-inclusive, exact Decimal arithmetic."""
    x, y = Decimal(point["x"]), Decimal(point["y"])
    verts = [
        (Decimal(v["point"]["x"]), Decimal(v["point"]["y"]))
        for v in region["vertices"]
    ]
    inside = False
    for (x1, y1), (x2, y2) in zip(verts, verts[1:] + verts[:1]):
        # Boundary check: collinear and within the segment's bounding box.
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if (
            cross == 0
            and min(x1, x2) <= x <= max(x1, x2)
            and min(y1, y2) <= y <= max(y1, y2)
        ):
            return True
        if (y1 > y) != (y2 > y):
            x_int = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x_int > x:
                inside = not inside
    return inside


def _region_covers(region: dict[str, Any], obj_states: list[Any]) -> bool:
    for state in obj_states:
        if state is None:
            continue
        geometry = state.facts.get("geometry")
        if geometry is None:
            continue
        for point in _defining_points(geometry.value):
            if _point_in_region(point, region):
                return True
    return False


def _network_members(model: Model, network: str) -> set[str]:
    return {
        ulid
        for ulid, obj in model.objects.items()
        if "networks" in obj.facts and network in obj.facts["networks"].value
    }


class _ScopeIndex:
    """Resolved scope terms; answers 'is this touched object in scope?'."""

    def __init__(
        self,
        terms: list[dict[str, Any]],
        pre: Model,
        post: Model,
        errors: list[dict[str, Any]],
        minted: set[str],
    ) -> None:
        self.whole_project = False
        self.covered: set[str] = set()
        self.regions: list[dict[str, Any]] = []
        self.pre, self.post = pre, post
        for i, term in enumerate(terms):
            kind = term["kind"]
            if kind == "project":
                self.whole_project = True
            elif kind == "object":
                self.covered.add(term["object"])
            elif kind == "selection":
                sel_ulid, _ = split_ref(term["selection"])
                if sel_ulid not in pre.objects:
                    errors.append(
                        _err(
                            "unknown_reference",
                            None,
                            f"/scope/{i}/selection",
                            f"scope selection {term['selection']!r} does not resolve "
                            "against the declared head",
                        )
                    )
                    continue
                try:
                    self.covered.update(resolve_members(pre, term["selection"]))
                except ApplyError as exc:
                    errors.append(
                        _err(
                            "unknown_reference",
                            None,
                            f"/scope/{i}/selection",
                            exc.message,
                        )
                    )
            elif kind == "network":
                net = term["network"]
                if net not in pre.objects and net not in minted:
                    errors.append(
                        _err(
                            "unknown_reference",
                            None,
                            f"/scope/{i}/network",
                            f"scope network {net!r} does not resolve",
                        )
                    )
                    continue
                self.covered.add(net)
                self.covered.update(_network_members(pre, net))
                self.covered.update(_network_members(post, net))
            elif kind == "region":
                self.regions.append(term["region"])

    def contains(self, ulid: str) -> bool:
        if self.whole_project or ulid in self.covered:
            return True
        return any(
            _region_covers(
                region, [self.pre.objects.get(ulid), self.post.objects.get(ulid)]
            )
            for region in self.regions
        )


# ---------------------------------------------------------------------------
# Submit


def submit(log: list[dict[str, Any]], document: Any) -> Accepted | Refused:
    """Apply one submission to a log: extended log or total refusal."""
    model = fold(log)  # the caller's stored log must fold; FoldHalt propagates

    project = model.project
    declared_head: int | None = None
    if isinstance(document, dict):
        if isinstance(document.get("head"), int) and document["head"] >= 0:
            declared_head = document["head"]
        doc_project = document.get("project")
        if project is None and isinstance(doc_project, str):
            project = doc_project

    def refuse(errors: list[dict[str, Any]]) -> Refused:
        return Refused(
            {
                "project": project,
                "declared_head": declared_head,
                "errors": _sort_errors(errors),
            }
        )

    # 1. Schema (structural). Structural damage blocks the semantic stages.
    errors = _structural_errors(document)
    if errors:
        return refuse(errors)
    if isinstance(document.get("project"), str) and model.project is None:
        project = document["project"]
    elif model.project is not None and document["project"] != model.project:
        return refuse(
            [
                _err(
                    "schema_violation",
                    None,
                    "/project",
                    "submission targets another project's log",
                )
            ]
        )

    # 2. Stale head. State-dependent checks are meaningless against a stale head.
    if document["head"] != model.head:
        return refuse(
            [
                _err(
                    "stale_head",
                    None,
                    "/head",
                    f"declared head {document['head']} but the log's head is {model.head}",
                )
            ]
        )

    commands: list[dict[str, Any]] = document["commands"]

    # 3. Kind / spec / author-role / basis / payload schema (per command).
    bad: set[int] = set()
    for i, command in enumerate(commands):
        static = static_errors(command)
        for code, path, message in static:
            errors.append(_err(code, i, path, message))
        if static:
            bad.add(i)

    # 4. Reference resolution + id collision, in submission order.
    minted: set[str] = set()
    minted_selections: dict[str, dict[str, Any]] = {}
    imports_in_submission: list[tuple[str, str, str]] = []

    def exists(candidate: str) -> bool:
        return candidate in model.objects or candidate in minted

    for i, command in enumerate(commands):
        if i in bad:
            continue
        kind, payload = command["kind"], command["payload"]
        for path, target in _iter_payload_refs(kind, payload):
            if not exists(target):
                errors.append(
                    _err(
                        "unknown_reference",
                        i,
                        f"/payload{path}",
                        f"no such object {target!r}",
                    )
                )
        if kind in ("object.set_attrs", "object.remove"):
            target_ulid, group = split_ref(payload["target"])
            if target_ulid in minted_selections:
                criteria = minted_selections[target_ulid]
                groups = {g["name"] for g in criteria.get("groups", [])}
                if group is not None and group not in groups:
                    errors.append(
                        _err(
                            "unknown_reference",
                            i,
                            "/payload/target",
                            f"selection {target_ulid!r} has no group {group!r}",
                        )
                    )
            elif not exists(target_ulid):
                errors.append(
                    _err(
                        "unknown_reference",
                        i,
                        "/payload/target",
                        f"no such object {target_ulid!r}",
                    )
                )
            elif group is not None:
                pre_obj = model.objects.get(target_ulid)
                if pre_obj is None or not pre_obj.is_selection:
                    errors.append(
                        _err(
                            "unknown_reference",
                            i,
                            "/payload/target",
                            f"{payload['target']!r} does not name a selection group",
                        )
                    )
                else:
                    groups = {
                        g["name"]
                        for g in pre_obj.facts["criteria"].value.get("groups", [])
                    }
                    if group not in groups:
                        errors.append(
                            _err(
                                "unknown_reference",
                                i,
                                "/payload/target",
                                f"selection {target_ulid!r} has no group {group!r}",
                            )
                        )
        if kind in ("object.create", "selection.define"):
            new_ulid = payload["object"]
            collides = (
                new_ulid in minted
                or (
                    new_ulid in model.objects
                    and not (
                        kind == "selection.define"
                        and model.objects[new_ulid].is_selection
                    )
                )
            )
            if collides:
                errors.append(
                    _err(
                        "id_collision",
                        i,
                        "/payload/object",
                        f"ULID {new_ulid!r} already exists",
                    )
                )
            else:
                minted.add(new_ulid)
                if kind == "selection.define":
                    minted_selections[new_ulid] = payload["criteria"]
        if kind in ("registry.import", "presentation.import"):
            key = "registry" if kind == "registry.import" else "pack"
            family = "registry" if kind == "registry.import" else "presentation"
            imports_in_submission.append(
                (family, payload[key]["id"], payload[key]["version"])
            )
        for bi, citation in enumerate(command["basis"]):
            if citation["kind"] == "command":
                cited = citation["seq"]
                if not 1 <= cited <= model.head + i:
                    errors.append(
                        _err(
                            "unknown_reference",
                            i,
                            f"/basis/{bi}/seq",
                            f"basis cites seq {cited}, not an earlier log entry",
                        )
                    )
            elif citation["kind"] == "rule":
                pin = ("registry", citation["registry"], citation["version"])
                if (
                    not model.has_import(*pin)
                    and pin not in imports_in_submission
                ):
                    errors.append(
                        _err(
                            "unknown_reference",
                            i,
                            f"/basis/{bi}",
                            f"rule cites unimported registry "
                            f"{citation['registry']!r} version {citation['version']!r}",
                        )
                    )

    # 5. Declaration ordering (#29), tracked across the submission.
    units_declared = model.units is not None
    for i, command in enumerate(commands):
        if i in bad:
            continue
        kind = command["kind"]
        if kind == "project.units":
            if units_declared:
                errors.append(
                    _err(
                        "immutable_declaration",
                        i,
                        "/payload",
                        "the unit system is declared exactly once and is immutable",
                    )
                )
            else:
                units_declared = True
        elif kind not in spec.DECLARATION_KINDS and not units_declared:
            errors.append(
                _err(
                    "missing_declaration",
                    i,
                    "",
                    "design content requires a landed project.units declaration",
                )
            )

    if errors:
        return refuse(errors)

    # 6. Apply — trial fold against a copy; the stored log is never touched.
    trial = model.copy()
    touched_by_command: list[dict[str, set[str]]] = []
    removed_by: dict[str, int] = {}
    for i, command in enumerate(commands):
        seq = model.head + 1 + i
        touched: dict[str, set[str]] = {}
        try:
            apply_command(trial, seq, command["kind"], command["payload"], touched)
        except ApplyError as exc:
            return refuse(
                errors
                + [_err(exc.code, i, "/payload" + exc.path, exc.message, exc.objects)]
            )
        touched_by_command.append(touched)
        for obj_ulid, paths in touched.items():
            if "@removed" in paths:
                removed_by[obj_ulid] = i
        trial.head = seq

    # 7. Post-fold referential integrity (#19): dangling_reference names the
    # dependents still pointing at each removal target.
    dangling: dict[int, list[str]] = {}
    for referrer, _path, missing in integrity_violations(trial):
        index = removed_by.get(missing)
        command_index = index if index is not None else None
        dangling.setdefault(
            command_index if command_index is not None else -1, []
        ).append(referrer)
    for command_index, referrers in sorted(dangling.items()):
        errors.append(
            _err(
                "dangling_reference",
                None if command_index < 0 else command_index,
                "/payload/target" if command_index >= 0 else "",
                "removal leaves objects with unresolved topology references",
                referrers,
            )
        )

    # 7b. Derived-name uniqueness: the 'name' attr (string kind) is the derived
    # name, unique per object type within the project (#17 decision 6).
    names: dict[tuple[str, str], list[str]] = {}
    for obj_ulid, obj in trial.objects.items():
        name_fact = obj.facts.get("attrs.name")
        type_fact = obj.facts.get("type")
        if (
            name_fact is not None
            and type_fact is not None
            and name_fact.value.get("kind") == "string"
        ):
            names.setdefault(
                (type_fact.value, name_fact.value["value"]), []
            ).append(obj_ulid)
    for (type_name, name), holders in sorted(names.items()):
        if len(holders) < 2:
            continue
        writer_indices = sorted(
            trial.objects[h].facts["attrs.name"].seq - model.head - 1
            for h in holders
            if trial.objects[h].facts["attrs.name"].seq > model.head
        )
        if writer_indices:
            errors.append(
                _err(
                    "name_collision",
                    writer_indices[-1],
                    "/payload",
                    f"derived name {name!r} is already taken for type {type_name!r}",
                    holders,
                )
            )

    # 8. Scope audit (#27). Declaration commands require the explicit
    # whole-project term; touched objects must match a declared term.
    scope_index = _ScopeIndex(document["scope"], model, trial, errors, minted)
    has_project_term = scope_index.whole_project
    for i, command in enumerate(commands):
        if command["kind"] in spec.DECLARATION_KINDS and not has_project_term:
            errors.append(
                _err(
                    "scope_violation",
                    i,
                    "",
                    "project declarations require the explicit whole-project "
                    "scope term",
                )
            )
    all_touched: dict[str, set[str]] = {}
    for touched in touched_by_command:
        for obj_ulid, paths in touched.items():
            all_touched.setdefault(obj_ulid, set()).update(paths)
    for obj_ulid in sorted(all_touched):
        if not scope_index.contains(obj_ulid):
            fields = sorted(p for p in all_touched[obj_ulid] if not p.startswith("@"))
            markers = sorted(p for p in all_touched[obj_ulid] if p.startswith("@"))
            errors.append(
                _err(
                    "scope_violation",
                    None,
                    "/scope",
                    f"object {obj_ulid!r} ({', '.join(markers + fields) or 'touched'}) "
                    "matches no declared scope term",
                    [obj_ulid],
                )
            )

    if errors:
        return refuse(errors)

    # 9. Accept: stamp and extend (a new list; the input log is untouched).
    batch = ulid_mod.mint()
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_entries = [
        {
            "project": document["project"],
            "seq": model.head + 1 + i,
            "batch": batch,
            "author": command["author"],
            "kind": command["kind"],
            "payload": command["payload"],
            "basis": command["basis"],
            "created_at": created_at,
            "spec": command["spec"],
        }
        for i, command in enumerate(commands)
    ]
    return Accepted(log=list(log) + new_entries, batch=batch)
