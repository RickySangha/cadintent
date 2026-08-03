"""Shared derivation semantics: predicates, field values, formatting, geometry.

Everything here is used twice — once by the renderer to emit strings and
placements, and once by the round-trip verifier to re-derive every derived
string freshly and compare exact bytes (#24 decision 5c). One code path for
both would let the build be its own witness; instead the *verifier re-reads
the saved DXF fresh* and only the string derivation (model facts + format
objects) is shared, exactly as #22 decision 7 specifies: derived strings are
re-derived against source + format and compared as exact formatted strings.

Formatting is part of the contract (#22 decision 2): display unit conversion
from SI metres, display quantum, decimal ROUND_HALF_UP — the only rendering
path; no float formatting.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from cadintent.checks import derived_length
from cadintent.fold import Model, ObjectState

# SI metres -> display unit (Decimal-exact divisors; '1' is dimensionless).
_UNIT_DIVISORS = {
    "m": Decimal("1"),
    "mm": Decimal("0.001"),
    "ft": Decimal("0.3048"),
    "in": Decimal("0.0254"),
    "1": Decimal("1"),
}


class DeriveError(Exception):
    """A derived value could not be produced (missing fact, bad source)."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        self.message = message
        super().__init__(f"{source}: {message}")


# ---------------------------------------------------------------------------
# Fact access


def attr_scalar(obj: ObjectState, name: str) -> Any:
    """The scalar payload of a typed attr ({kind, value}), else None."""
    fact = obj.facts.get(f"attrs.{name}")
    if fact is None:
        return None
    value = fact.value
    if isinstance(value, dict) and "kind" in value:
        if value["kind"] == "elevation":
            return value["value"]["value"]
        return value["value"]
    return value


def field_value(model: Model, ulid: str, obj: ObjectState, source: str) -> Any:
    """Resolve a FieldSource ('attrs.<name>' | 'derived.length' |
    'derived.slope') to its scalar value. Raises DeriveError when missing."""
    if source.startswith("attrs."):
        value = attr_scalar(obj, source.removeprefix("attrs."))
        if value is None:
            raise DeriveError(source, "the object carries no such fact")
        return value
    geometry = obj.facts.get("geometry")
    if geometry is None:
        raise DeriveError(source, "the object carries no geometry")
    length = derived_length(geometry.value)
    if length is None or length == 0.0:
        raise DeriveError(source, "no plan length is derivable from the geometry")
    if source == "derived.length":
        return Decimal(repr(length))
    if source == "derived.slope":
        inv_a = attr_scalar(obj, "invert_a")
        inv_b = attr_scalar(obj, "invert_b")
        if inv_a is None or inv_b is None:
            raise DeriveError(source, "slope requires both end inverts")
        slope = abs(float(Decimal(inv_a)) - float(Decimal(inv_b))) / length
        return Decimal(repr(slope))
    raise DeriveError(source, "unknown derived view")


# ---------------------------------------------------------------------------
# Formatting (#22 decision 2 — the only rendering path)


def format_value(value: Any, fmt: dict[str, Any]) -> str:
    """Render one field value through its mandatory format object.

    Non-numeric stored facts (e.g. a material string) render verbatim; the
    numeric path converts SI -> display unit, quantizes to the display
    quantum with ROUND_HALF_UP, and applies the closed style enum.
    """
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except ArithmeticError:
            return value
    elif isinstance(value, Decimal):
        number = value
    else:
        return str(value)
    converted = number / _UNIT_DIVISORS[fmt["unit"]]
    quantum = Decimal(fmt["quantum"])
    style = fmt["style"]
    if style == "plain":
        return str(converted.quantize(quantum, rounding=ROUND_HALF_UP))
    if style == "percent":
        return str((converted * 100).quantize(quantum, rounding=ROUND_HALF_UP)) + "%"
    if style == "ratio":
        if converted == 0:
            raise DeriveError("ratio", "a zero value has no ratio form")
        return "1:" + str((1 / converted).quantize(quantum, rounding=ROUND_HALF_UP))
    if style == "feet_inches":
        # value is expected in feet; whole feet + quantized inches, plain
        # characters only (no stacked-text codes, #24 decision 2).
        sign = "-" if converted < 0 else ""
        magnitude = abs(converted)
        feet = int(magnitude)
        inches = ((magnitude - feet) * 12).quantize(quantum, rounding=ROUND_HALF_UP)
        if inches >= 12:
            feet += 1
            inches = (inches - 12).quantize(quantum, rounding=ROUND_HALF_UP)
        return f"{sign}{feet}'-{inches}\""
    raise DeriveError("format", f"unknown style {style!r}")  # pragma: no cover


def label_text(
    model: Model, ulid: str, obj: ObjectState, content: list[dict[str, Any]]
) -> str:
    """The full label string for one subject from ordered segments."""
    parts: list[str] = []
    for segment in content:
        if segment["segment"] == "literal":
            parts.append(segment["text"])
        else:
            value = field_value(model, ulid, obj, segment["source"])
            parts.append(format_value(value, segment["format"]))
    return "".join(parts)


# ---------------------------------------------------------------------------
# Predicates (#22 decision 4)


def _networks_of(obj: ObjectState) -> list[str]:
    fact = obj.facts.get("networks")
    return list(fact.value) if fact is not None else []


def _clause_scalar(model: Model, obj: ObjectState, path: str) -> Any:
    if path == "type":
        fact = obj.facts.get("type")
        return None if fact is None else fact.value
    if path in ("geometry", "ends", "networks"):
        fact = obj.facts.get(path)
        return None if fact is None else fact.value
    return attr_scalar(obj, path.removeprefix("attrs."))


def predicate_matches(
    model: Model, ulid: str, obj: ObjectState, predicate: dict[str, Any]
) -> bool:
    """Evaluate a structural predicate against one object."""
    type_fact = obj.facts.get("type")
    if type_fact is None or type_fact.value != predicate["kind"]:
        return False
    system = predicate.get("system")
    if system is not None:
        member_systems = set()
        for net in _networks_of(obj):
            network = model.objects.get(net)
            if network is not None:
                declared = attr_scalar(network, "system")
                if declared is not None:
                    member_systems.add(declared)
        if system not in member_systems:
            return False
    for clause in predicate.get("where", []):
        value = _clause_scalar(model, obj, clause["field"])
        op = clause["op"]
        if op == "exists":
            if value is None:
                return False
        elif op == "absent":
            if value is not None:
                return False
        elif op == "eq":
            if value != clause["value"]:
                return False
        elif op == "in":
            if value not in clause["value"]:
                return False
    return True


# ---------------------------------------------------------------------------
# Geometry helpers (naive placement, chords only — charter #4)


def point_of(geometry: dict[str, Any]) -> tuple[float, float] | None:
    if geometry.get("kind") == "point":
        p = geometry["point"]
        return float(Decimal(p["x"])), float(Decimal(p["y"]))
    return None


def path_vertices(geometry: dict[str, Any]) -> list[tuple[float, float, float]]:
    """(x, y, bulge) triples of a polyline/arc geometry, in vertex order.
    The bulge on a vertex belongs to the segment leaving it."""
    kind = geometry.get("kind")
    if kind == "polyline":
        out = []
        for vertex in geometry["vertices"]:
            p = vertex["point"]
            bulge = float(Decimal(vertex.get("bulge", "0")))
            out.append((float(Decimal(p["x"])), float(Decimal(p["y"])), bulge))
        return out
    if kind == "arc":
        s, e = geometry["start"], geometry["end"]
        return [
            (float(Decimal(s["x"])), float(Decimal(s["y"])), float(Decimal(geometry["bulge"]))),
            (float(Decimal(e["x"])), float(Decimal(e["y"])), 0.0),
        ]
    return []


def reverse_path(
    vertices: list[tuple[float, float, float]]
) -> list[tuple[float, float, float]]:
    """Reverse vertex order; each segment's bulge flips sign and re-attaches
    to the segment's new starting vertex."""
    n = len(vertices)
    out = []
    for i in range(n - 1, -1, -1):
        x, y, _ = vertices[i]
        bulge = -vertices[i - 1][2] if i > 0 else 0.0
        out.append((x, y, bulge))
    return out


def path_midpoint(vertices: list[tuple[float, float, float]]) -> tuple[float, float]:
    """The point at half the chord length along the path (naive: chords)."""
    lengths = [
        math.hypot(b[0] - a[0], b[1] - a[1])
        for a, b in zip(vertices, vertices[1:])
    ]
    total = sum(lengths)
    if total == 0.0:
        return vertices[0][0], vertices[0][1]
    target = total / 2.0
    walked = 0.0
    for (a, b), seg in zip(zip(vertices, vertices[1:]), lengths):
        if walked + seg >= target and seg > 0.0:
            t = (target - walked) / seg
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        walked += seg
    return vertices[-1][0], vertices[-1][1]


def bearing_degrees(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Degrees counter-clockwise from +X of the a->b chord."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 360.0


def end_tangent(
    vertices: list[tuple[float, float, float]], end: str, outward: bool
) -> float | None:
    """Chord bearing at one end. ``outward=True`` points away from the end's
    node into the conduit; ``outward=False`` points into the node."""
    if len(vertices) < 2:
        return None
    if end == "a":
        p0 = (vertices[0][0], vertices[0][1])
        p1 = (vertices[1][0], vertices[1][1])
        return bearing_degrees(p0, p1) if outward else bearing_degrees(p1, p0)
    p0 = (vertices[-2][0], vertices[-2][1])
    p1 = (vertices[-1][0], vertices[-1][1])
    return bearing_degrees(p1, p0) if outward else bearing_degrees(p0, p1)


# ---------------------------------------------------------------------------
# Rotation sources (#22 decision 6)


def _conduits_at_node(model: Model, node: str) -> list[tuple[str, str, ObjectState]]:
    """(conduit_ulid, end, obj) for every edge end node-bound to ``node``,
    sorted by conduit ULID (the deterministic tie-break)."""
    out = []
    for ulid in sorted(model.objects):
        obj = model.objects[ulid]
        ends = obj.facts.get("ends")
        if ends is None:
            continue
        for end in ("a", "b"):
            binding = ends.value[f"end_{end}"]
            if binding["kind"] == "node" and binding["node"] == node:
                out.append((ulid, end, obj))
    return out


def resolve_rotation(
    model: Model, node: str, rotation: dict[str, Any]
) -> tuple[float, bool]:
    """(angle_degrees, used_fallback). Declared flow only, never
    invert-derived; ties break by lowest conduit ULID."""
    source = rotation["source"]
    if source == "fixed":
        return float(Decimal(rotation["angle"])), False
    for ulid, end, obj in _conduits_at_node(model, node):
        vertices = path_vertices(obj.facts["geometry"].value) if "geometry" in obj.facts else []
        if source == "from_edge_tangent":
            angle = end_tangent(vertices, end, outward=True)
            if angle is not None:
                return angle, False
            continue
        declared = attr_scalar(obj, "flow_direction")
        if declared not in ("a_to_b", "b_to_a"):
            continue
        leaves = (declared == "a_to_b" and end == "a") or (
            declared == "b_to_a" and end == "b"
        )
        if source == "from_flow_out" and leaves:
            angle = end_tangent(vertices, end, outward=True)
            if angle is not None:
                return angle, False
        if source == "from_flow_in" and not leaves:
            angle = end_tangent(vertices, end, outward=False)
            if angle is not None:
                return angle, False
    return float(Decimal(rotation["fallback_angle"])), True
