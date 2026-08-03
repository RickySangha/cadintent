"""The check runner and the civil pack's five v0 checks (#21, as amended).

Checks judge the folded model and emit the shared typed finding shape
(spec/schemas/finding.json). Everything the kernel refuses to do lives here:
tolerances, "close enough", derived-vs-declared comparisons. Every finding
names the rule/tolerance it was judged against; a check whose required values
are missing reports visibly ``not_run`` (never a silently invented default);
a vacuous pass (nothing to judge) is distinguishable from a real one; and a
clean result resting on an unverified rule entry reports
``unverified_consistent`` — never compliance.

The five checks (``invert_continuity`` was removed per the #21 amendment:
drop standards are municipality-specific rule data, not spec comparisons):

- ``civil.flow_vs_invert`` — declared flow vs the invert-derived direction;
  disagreement, flat, or adverse grade is a finding carrying both values;
- ``civil.min_slope`` — derived slope vs municipal minima resolved from rule
  registries (entries named ``civil.min_slope``, params schema as the
  applicability predicate). No default minima;
- ``civil.rim_sump_envelope`` — every conduit-end invert at a structure lies
  between that structure's sump and rim, where those facts exist;
- ``civil.vocabulary`` — material values vs the pack's versioned vocabulary;
  off-list is a finding, never a refusal;
- ``civil.completeness`` — per-kind expected facts (incl. shape-driven size
  facts) reported as findings.
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any

from . import spec
from .fold import Model, ObjectState
from .registry import RegistryStore, params_apply

MIN_SLOPE_RULE = "civil.min_slope"

_RATIO_FORMAT = "{:.9f}"  # the ratio quantum (0.000000001)


def _pack() -> dict[str, Any]:
    return spec.schemas()["civil.json"]["x-cadintent-pack"]


def _schema_judgement(rule: str) -> dict[str, Any]:
    pack = _pack()
    return {
        "kind": "schema",
        "pack": pack["id"],
        "version": pack["version"],
        "rule": rule,
    }


def _attr(obj: ObjectState, name: str) -> dict[str, Any] | None:
    fact = obj.facts.get(f"attrs.{name}")
    return None if fact is None else fact.value


def _elevation(obj: ObjectState, name: str) -> Decimal | None:
    attr = _attr(obj, name)
    if attr is None or attr.get("kind") != "elevation":
        return None
    return Decimal(attr["value"]["value"])


def _string(obj: ObjectState, name: str) -> str | None:
    attr = _attr(obj, name)
    if attr is None or attr.get("kind") != "string":
        return None
    return attr["value"]


def _quantity(obj: ObjectState, name: str) -> str | None:
    attr = _attr(obj, name)
    if attr is None or attr.get("kind") != "quantity":
        return None
    return attr["value"]


def _of_type(model: Model, kinds: set[str]) -> list[tuple[str, ObjectState]]:
    return sorted(
        (ulid, obj)
        for ulid, obj in model.objects.items()
        if "type" in obj.facts and obj.facts["type"].value in kinds
    )


def _result(
    check: str,
    status: str,
    evaluated: int,
    findings: list[dict[str, Any]],
    consulted: list[dict[str, Any]] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "check": check,
        "status": status,
        "evaluated": evaluated,
        "vacuous": evaluated == 0,
        "findings": findings,
    }
    if consulted is not None:
        result["consulted"] = consulted
    if reason is not None:
        result["reason"] = reason
    return result


def _finding(
    check: str,
    subjects: list[str],
    values: dict[str, Any],
    judged_against: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    return {
        "check": check,
        "subjects": subjects,
        "values": values,
        "judged_against": judged_against,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Derived length (never stored — #21 decision 6)


def _segment_length(p1: dict[str, str], p2: dict[str, str], bulge: str | None) -> float:
    x1, y1 = float(Decimal(p1["x"])), float(Decimal(p1["y"]))
    x2, y2 = float(Decimal(p2["x"])), float(Decimal(p2["y"]))
    chord = math.hypot(x2 - x1, y2 - y1)
    b = float(Decimal(bulge)) if bulge is not None else 0.0
    if b == 0.0 or chord == 0.0:
        return chord
    sweep = 4.0 * math.atan(abs(b))
    radius = chord / (2.0 * math.sin(sweep / 2.0))
    return radius * sweep


def derived_length(geometry: dict[str, Any]) -> float | None:
    """Plan length of a conduit's geometry (polyline or arc), else None."""
    kind = geometry.get("kind")
    if kind == "polyline":
        vertices = geometry["vertices"]
        total = 0.0
        pairs = list(zip(vertices, vertices[1:]))
        if geometry.get("closed"):
            pairs.append((vertices[-1], vertices[0]))
        for v1, v2 in pairs:
            total += _segment_length(v1["point"], v2["point"], v1.get("bulge"))
        return total
    if kind == "arc":
        return _segment_length(geometry["start"], geometry["end"], geometry["bulge"])
    return None


# ---------------------------------------------------------------------------
# The five checks


def check_flow_vs_invert(model: Model, store: RegistryStore | None) -> dict[str, Any]:
    check = "civil.flow_vs_invert"
    judged = _schema_judgement(
        "declared flow_direction must match the invert-derived direction; "
        "flat or adverse grade is a finding; tolerance 0"
    )
    findings: list[dict[str, Any]] = []
    evaluated = 0
    for ulid, obj in _of_type(model, set(_pack()["edgeKinds"])):
        inv_a = _elevation(obj, "invert_a")
        inv_b = _elevation(obj, "invert_b")
        declared = _string(obj, "flow_direction")
        if inv_a is None or inv_b is None or declared is None:
            continue  # missing facts are civil.completeness findings
        evaluated += 1
        derived = "flat" if inv_a == inv_b else ("a_to_b" if inv_a > inv_b else "b_to_a")
        values = {
            "declared": declared,
            "derived": derived,
            "invert_a": str(inv_a),
            "invert_b": str(inv_b),
        }
        if declared not in ("a_to_b", "b_to_a"):
            findings.append(
                _finding(
                    check,
                    [ulid],
                    values,
                    judged,
                    f"declared flow_direction {declared!r} is not a recognized "
                    "declaration (a_to_b | b_to_a)",
                )
            )
        elif derived == "flat":
            findings.append(
                _finding(
                    check,
                    [ulid],
                    values,
                    judged,
                    "end inverts are equal: grade is flat, direction cannot be "
                    "derived to confirm the declaration",
                )
            )
        elif derived != declared:
            findings.append(
                _finding(
                    check,
                    [ulid],
                    values,
                    judged,
                    "declared flow disagrees with the invert-derived direction "
                    "(adverse grade along the declared flow)",
                )
            )
    return _result(
        check,
        "findings" if findings else "pass",
        evaluated,
        findings,
        consulted=[judged],
    )


def check_min_slope(model: Model, store: RegistryStore | None) -> dict[str, Any]:
    check = MIN_SLOPE_RULE
    resolved = store.entries_named(model, MIN_SLOPE_RULE) if store is not None else []
    if not resolved:
        return _result(
            check,
            "not_run",
            0,
            [],
            reason=(
                "no minimum-slope values are declared for this project — the "
                "spec ships no default minima; import a rule registry with "
                f"{MIN_SLOPE_RULE!r} entries or define project-local ones "
                "(rule.define)"
            ),
        )
    findings: list[dict[str, Any]] = []
    consulted = [r.judgement() for r in resolved]
    evaluated = 0
    judged_unverified = False
    for ulid, obj in _of_type(model, set(_pack()["edgeKinds"])):
        inv_a = _elevation(obj, "invert_a")
        inv_b = _elevation(obj, "invert_b")
        geometry_fact = obj.facts.get("geometry")
        if inv_a is None or inv_b is None or geometry_fact is None:
            continue
        length = derived_length(geometry_fact.value)
        if length is None or length == 0.0:
            continue
        params: dict[str, Any] = {}
        material = _string(obj, "material")
        if material is not None:
            params["material"] = material
        diameter = _quantity(obj, "diameter")
        if diameter is not None:
            params["diameter"] = diameter
        applicable = [r for r in resolved if params_apply(r.entry, params)]
        if not applicable:
            continue
        evaluated += 1
        slope = abs(float(inv_a) - float(inv_b)) / length
        for rule in applicable:
            judgement = rule.judgement(params)
            if rule.verification == "unverified":
                judged_unverified = True
            if "value" not in rule.entry:
                findings.append(
                    _finding(
                        check,
                        [ulid],
                        {
                            "slope": _RATIO_FORMAT.format(slope),
                            "length": f"{length:.3f}",
                            "minimum": None,
                        },
                        judgement,
                        "the resolved minimum-slope entry carries no value; a "
                        "missing required value is a finding, never a default",
                    )
                )
                continue
            minimum = float(Decimal(rule.entry["value"]))
            if slope < minimum:
                findings.append(
                    _finding(
                        check,
                        [ulid],
                        {
                            "slope": _RATIO_FORMAT.format(slope),
                            "minimum": rule.entry["value"],
                            "length": f"{length:.3f}",
                            "invert_a": str(inv_a),
                            "invert_b": str(inv_b),
                        },
                        judgement,
                        "derived slope is below the declared minimum",
                    )
                )
    if findings:
        status = "findings"
    elif judged_unverified and evaluated:
        status = "unverified_consistent"
    else:
        status = "pass"
    return _result(check, status, evaluated, findings, consulted=consulted)


def check_rim_sump_envelope(model: Model, store: RegistryStore | None) -> dict[str, Any]:
    check = "civil.rim_sump_envelope"
    judged = _schema_judgement(
        "every conduit-end invert at a structure lies between that "
        "structure's sump_elevation and rim_elevation, where those facts "
        "exist; tolerance 0"
    )
    node_kinds = set(_pack()["nodeKinds"])
    findings: list[dict[str, Any]] = []
    evaluated = 0
    for ulid, obj in _of_type(model, set(_pack()["edgeKinds"])):
        ends_fact = obj.facts.get("ends")
        if ends_fact is None:
            continue
        for end in ("a", "b"):
            binding = ends_fact.value[f"end_{end}"]
            if binding["kind"] != "node":
                continue
            node = model.objects.get(binding["node"])
            if node is None or "type" not in node.facts:
                continue
            if node.facts["type"].value not in node_kinds:
                continue
            invert = _elevation(obj, f"invert_{end}")
            rim = _elevation(node, "rim_elevation")
            sump = _elevation(node, "sump_elevation")
            if invert is None or (rim is None and sump is None):
                continue
            evaluated += 1
            values = {
                "end": end,
                "invert": str(invert),
                "rim_elevation": None if rim is None else str(rim),
                "sump_elevation": None if sump is None else str(sump),
            }
            if rim is not None and invert > rim:
                findings.append(
                    _finding(
                        check,
                        [ulid, binding["node"]],
                        values,
                        judged,
                        f"end {end} invert is above the structure's rim",
                    )
                )
            if sump is not None and invert < sump:
                findings.append(
                    _finding(
                        check,
                        [ulid, binding["node"]],
                        values,
                        judged,
                        f"end {end} invert is below the structure's sump",
                    )
                )
    return _result(
        check,
        "findings" if findings else "pass",
        evaluated,
        findings,
        consulted=[judged],
    )


def check_vocabulary(model: Model, store: RegistryStore | None) -> dict[str, Any]:
    check = "civil.vocabulary"
    pack = _pack()
    vocabulary = pack["vocabularies"]["material"]
    judged = {
        "kind": "vocabulary",
        "vocabulary": vocabulary["id"],
        "version": vocabulary["version"],
    }
    kinds = set(pack["nodeKinds"]) | set(pack["edgeKinds"])
    findings: list[dict[str, Any]] = []
    evaluated = 0
    for ulid, obj in _of_type(model, kinds):
        material = _string(obj, "material")
        if material is None:
            continue
        evaluated += 1
        if material not in vocabulary["values"]:
            findings.append(
                _finding(
                    check,
                    [ulid],
                    {"material": material, "recommended": vocabulary["values"]},
                    judged,
                    "material is not in the pack's recommended vocabulary — a "
                    "finding, never a refusal; municipalities own this list",
                )
            )
    return _result(
        check,
        "findings" if findings else "pass",
        evaluated,
        findings,
        consulted=[judged],
    )


def check_completeness(model: Model, store: RegistryStore | None) -> dict[str, Any]:
    check = "civil.completeness"
    pack = _pack()
    expected_by_kind: dict[str, list[str]] = pack["expectedFacts"]
    shape_sizes: dict[str, list[str]] = pack["shapeSizeFacts"]
    findings: list[dict[str, Any]] = []
    evaluated = 0
    for ulid, obj in _of_type(model, set(expected_by_kind)):
        kind = obj.facts["type"].value
        evaluated += 1
        expected = list(expected_by_kind[kind])
        shape = _string(obj, "shape")
        if shape is not None and shape in shape_sizes:
            expected.extend(shape_sizes[shape])
        missing = [path for path in expected if path not in obj.facts]
        if missing:
            findings.append(
                _finding(
                    check,
                    [ulid],
                    {"kind": kind, "missing": missing},
                    _schema_judgement(
                        f"expected facts for {kind} per the civil pack schema "
                        "(missing facts are findings, never refusals)"
                    ),
                    "the object is missing facts the pack expects a complete "
                    "design to carry",
                )
            )
    return _result(
        check,
        "findings" if findings else "pass",
        evaluated,
        findings,
        consulted=[_schema_judgement("per-kind expected-fact lists (x-cadintent-pack)")],
    )


# ---------------------------------------------------------------------------
# Runner

_CHECKS = (
    check_flow_vs_invert,
    check_min_slope,
    check_rim_sump_envelope,
    check_vocabulary,
    check_completeness,
)


def run_checks(model: Model, store: RegistryStore | None = None) -> dict[str, Any]:
    """Run the civil pack's checks over a folded model; one CheckRun document
    (spec/schemas/finding.json), canonical-serializable."""
    pack = _pack()
    return {
        "spec": spec.SPEC_VERSION,
        "project": model.project,
        "head": model.head,
        "pack": {"id": pack["id"], "version": pack["version"]},
        "results": [check(model, store) for check in _CHECKS],
    }
