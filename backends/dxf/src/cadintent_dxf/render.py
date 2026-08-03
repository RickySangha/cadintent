"""The ezdxf DXF backend (#24): R2010, naive placement, model space only.

Mapping table (#24 decision 2):

- structure (node) -> block INSERT chosen by the pack's ordered first-match
  symbol mapping, attribute tags filled per the tag-fill entries;
- conduit (edge) -> LWPOLYLINE with bulge segments (exact arcs, no
  tessellation loss); vertex order follows declared flow when the linework
  entry sets ``orient_geometry_to_flow`` (declared flow only);
- symbol-owned text -> ATTRIB; free label-rule text -> a single MTEXT (never
  TEXT, no stacked-text codes);
- network -> no entity.

Block definitions come from an optional presentation-only template DXF; a
symbol with no definition there gets a deterministic generated placeholder
(circle at nominal size carrying the declared attribute tags) plus a render
finding. Template blocks are assumed drawn at unit nominal size (a 1-unit
diameter); the insert scale is the symbol's resolved model size.

Layers come verbatim from resolved presentation entries; an entry naming no
layer lands its entity on the reserved ``CADINTENT-UNSTYLED`` layer with a
finding — never a silent drop onto layer 0. Drawing scale is a render
parameter recorded in the report; model text height = paper mm x scale.

Render findings use the shared finding schema (finding.json) and land in the
per-render report written beside the DXF (``<out>.render.json``, canonical
bytes). Findings that concern no single design object cite the project ULID.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import ezdxf
from ezdxf.addons.importer import Importer

from cadintent.fold import Model
from cadintent.presentation import ResolvedPresentation
from cadintent.snapshot import model_from_doc

from . import __version__
from .derive import (
    DeriveError,
    field_value,
    format_value,
    label_text,
    path_midpoint,
    path_vertices,
    point_of,
    predicate_matches,
    resolve_rotation,
    reverse_path,
)

DXF_VERSION = "R2010"  # AC1024
UNSTYLED_LAYER = "CADINTENT-UNSTYLED"
BACKEND_ID = "cadintent-dxf"

_ATTACHMENT = {
    "top_left": 1, "top_center": 2, "top_right": 3,
    "middle_left": 4, "middle_center": 5, "middle_right": 6,
    "bottom_left": 7, "bottom_center": 8, "bottom_right": 9,
}


def _backend_judgement(rule: str) -> dict[str, Any]:
    return {"kind": "schema", "pack": BACKEND_ID, "version": __version__, "rule": rule}


def _pack_judgement(pack, rule: str) -> dict[str, Any]:
    return {"kind": "schema", "pack": pack.id, "version": pack.version, "rule": rule}


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
# The render plan: every derived string and placement, computed before any
# ezdxf emission so the round-trip verifier shares exactly this derivation.


@dataclass
class PlannedAttrib:
    tag: str
    text: str
    derived: bool  # derived (byte-verifiable) vs literal (present-but-unverifiable)


@dataclass
class PlannedInsert:
    ulid: str
    symbol: str
    tags: list[str]
    point: tuple[float, float]
    rotation: float
    scale: float
    layer: str
    attribs: list[PlannedAttrib]


@dataclass
class PlannedPolyline:
    ulid: str
    vertices: list[tuple[float, float, float]]
    closed: bool
    layer: str


@dataclass
class PlannedLabel:
    ulid: str
    rule: str
    text: str
    derived: bool  # any field segment present -> byte-verifiable content
    point: tuple[float, float]
    style: dict[str, Any]
    layer: str


@dataclass
class RenderPlan:
    inserts: list[PlannedInsert] = field(default_factory=list)
    polylines: list[PlannedPolyline] = field(default_factory=list)
    labels: list[PlannedLabel] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)


def _paper_mm_to_model(mm: Decimal, scale: Decimal) -> float:
    return float(mm * scale / Decimal("1000"))


def _layer_or_fallback(
    plan: RenderPlan, ulid: str, layer: str | None, pack, entry_name: str
) -> str:
    if layer:
        return layer
    plan.findings.append(
        _finding(
            "render.unstyled_layer",
            [ulid],
            {"entry": entry_name, "layer": UNSTYLED_LAYER},
            _pack_judgement(
                pack, "every emitted entity takes its layer verbatim from the "
                "resolved presentation entry (#24 decision 4)"
            ),
            f"resolved entry {entry_name!r} names no layer; the entity lands "
            f"on the reserved fallback layer {UNSTYLED_LAYER}",
        )
    )
    return UNSTYLED_LAYER


def _plan_inserts(
    model: Model, resolved: ResolvedPresentation, scale: Decimal, plan: RenderPlan
) -> None:
    if resolved.symbol_mappings is None:
        return
    map_pack, mappings = resolved.symbol_mappings
    fills = resolved.tag_fills[1] if resolved.tag_fills else []
    fills_pack = resolved.tag_fills[0] if resolved.tag_fills else map_pack
    for ulid in sorted(model.objects):
        obj = model.objects[ulid]
        geometry = obj.facts.get("geometry")
        point = point_of(geometry.value) if geometry else None
        if point is None:
            continue  # symbols place at point geometry only
        mapping = next(
            (m for m in mappings if predicate_matches(model, ulid, obj, m["when"])),
            None,
        )
        if mapping is None:
            continue  # first-match list matched nothing: not drawn
        symbol = resolved.symbols.get(mapping["symbol"])
        if symbol is None:
            plan.findings.append(
                _finding(
                    "render.unknown_symbol",
                    [ulid],
                    {"symbol": mapping["symbol"]},
                    _pack_judgement(
                        map_pack,
                        "a symbol mapping must name a resolvable catalog entry",
                    ),
                    f"the matched mapping names symbol {mapping['symbol']!r} "
                    "but no catalog entry with that name resolves; the node "
                    "is not drawn",
                )
            )
            continue
        rotation, used_fallback = resolve_rotation(model, ulid, mapping["rotation"])
        if used_fallback:
            plan.findings.append(
                _finding(
                    "render.rotation_fallback",
                    [ulid],
                    {
                        "source": mapping["rotation"]["source"],
                        "fallback_angle": mapping["rotation"]["fallback_angle"],
                    },
                    _pack_judgement(
                        map_pack,
                        "computed rotation resolves via declared flow / edge "
                        "tangent; unresolvable uses the mandatory fallback "
                        "angle visibly (#22 decision 6)",
                    ),
                    "no rotation source resolved at this node; the mandatory "
                    "fallback angle was used — visible degradation, never a "
                    "silent 0",
                )
            )
        entry = symbol.entry
        size = Decimal(entry["size"])
        scale_factor = (
            _paper_mm_to_model(size, scale)
            if entry["size_mode"] == "paper"
            else float(size)
        )
        attribs: list[PlannedAttrib] = []
        for tag in entry["tags"]:
            fill = next(
                (
                    f
                    for f in fills
                    if f["tag"] == tag and predicate_matches(model, ulid, obj, f["when"])
                ),
                None,
            )
            if fill is None:
                continue
            value = fill["value"]
            if value["kind"] == "literal":
                attribs.append(PlannedAttrib(tag, value["text"], derived=False))
                continue
            try:
                scalar = field_value(model, ulid, obj, value["source"])
            except DeriveError as exc:
                plan.findings.append(
                    _finding(
                        "render.missing_field",
                        [ulid],
                        {"tag": tag, "source": value["source"]},
                        _pack_judgement(
                            fills_pack, "a derived tag value re-derives from "
                            "source + format (#22 decision 7)"
                        ),
                        f"tag {tag!r} could not derive: {exc.message}",
                    )
                )
                continue
            attribs.append(
                PlannedAttrib(tag, format_value(scalar, value["format"]), derived=True)
            )
        layer = _layer_or_fallback(
            plan, ulid, mapping.get("layer"), map_pack, f"symbol_mapping:{mapping['symbol']}"
        )
        plan.inserts.append(
            PlannedInsert(
                ulid=ulid,
                symbol=entry["name"],
                tags=list(entry["tags"]),
                point=point,
                rotation=rotation,
                scale=scale_factor,
                layer=layer,
                attribs=attribs,
            )
        )


def _plan_polylines(model: Model, resolved: ResolvedPresentation, plan: RenderPlan) -> None:
    if resolved.linework is None:
        return
    pack, entries = resolved.linework
    for ulid in sorted(model.objects):
        obj = model.objects[ulid]
        geometry = obj.facts.get("geometry")
        if geometry is None or geometry.value.get("kind") not in ("polyline", "arc"):
            continue
        entry = next(
            (e for e in entries if predicate_matches(model, ulid, obj, e["when"])),
            None,
        )
        if entry is None:
            continue
        vertices = path_vertices(geometry.value)
        if len(vertices) < 2:
            continue
        if entry.get("orient_geometry_to_flow"):
            fact = obj.facts.get("attrs.flow_direction")
            declared = fact.value.get("value") if fact and isinstance(fact.value, dict) else None
            if declared == "b_to_a":
                vertices = reverse_path(vertices)
        layer = _layer_or_fallback(
            plan, ulid, entry.get("layer"), pack, "linework"
        )
        plan.polylines.append(
            PlannedPolyline(
                ulid=ulid,
                vertices=vertices,
                closed=bool(geometry.value.get("closed", False)),
                layer=layer,
            )
        )


def _anchor_point(
    obj_geometry: dict[str, Any], anchor: str
) -> tuple[float, float] | None:
    if anchor == "node_location":
        return point_of(obj_geometry)
    vertices = path_vertices(obj_geometry)
    if len(vertices) < 2:
        return None
    if anchor == "edge_midpoint":
        return path_midpoint(vertices)
    if anchor == "edge_end_a":
        return vertices[0][0], vertices[0][1]
    return vertices[-1][0], vertices[-1][1]


def _plan_labels(
    model: Model, resolved: ResolvedPresentation, scale: Decimal, plan: RenderPlan
) -> None:
    for rule_id in sorted(resolved.label_rules):
        entry = resolved.label_rules[rule_id]
        rule = entry.entry
        style_entry = resolved.text_styles.get(rule["text_style"])
        for ulid in sorted(model.objects):
            obj = model.objects[ulid]
            if not predicate_matches(model, ulid, obj, rule["selector"]):
                continue
            applicability = rule.get("applicability")
            if applicability is not None and not predicate_matches(
                model, ulid, obj, applicability
            ):
                continue
            if style_entry is None:
                plan.findings.append(
                    _finding(
                        "render.unknown_text_style",
                        [ulid],
                        {"rule": rule_id, "text_style": rule["text_style"]},
                        _pack_judgement(
                            entry.pack,
                            "a label rule must name a resolvable text style",
                        ),
                        f"label rule {rule_id!r} names text style "
                        f"{rule['text_style']!r} but no entry with that name "
                        "resolves; the label is not drawn",
                    )
                )
                continue
            geometry = obj.facts.get("geometry")
            anchor = (
                _anchor_point(geometry.value, rule["placement"]["anchor"])
                if geometry
                else None
            )
            if anchor is None:
                plan.findings.append(
                    _finding(
                        "render.unplaceable_label",
                        [ulid],
                        {"rule": rule_id, "anchor": rule["placement"]["anchor"]},
                        _pack_judgement(
                            entry.pack,
                            "naive placement anchors resolve against the "
                            "subject's geometry (#22 decision 4)",
                        ),
                        f"anchor {rule['placement']['anchor']!r} does not "
                        "resolve against this object's geometry; the label is "
                        "not drawn",
                    )
                )
                continue
            try:
                text = label_text(model, ulid, obj, rule["content"])
            except DeriveError as exc:
                plan.findings.append(
                    _finding(
                        "render.missing_field",
                        [ulid],
                        {"rule": rule_id, "source": exc.source},
                        _pack_judgement(
                            entry.pack,
                            "a field segment renders its source through its "
                            "format object (#22 decisions 1-2)",
                        ),
                        f"label rule {rule_id!r} could not derive "
                        f"{exc.source!r}: {exc.message}; the label is not drawn",
                    )
                )
                continue
            offset = rule["placement"]["offset"]
            point = (
                anchor[0] + _paper_mm_to_model(Decimal(offset["dx"]), scale),
                anchor[1] + _paper_mm_to_model(Decimal(offset["dy"]), scale),
            )
            style = style_entry.entry
            layer = _layer_or_fallback(
                plan, ulid, style.get("layer"), style_entry.pack,
                f"text_style:{style['name']}",
            )
            derived = any(s["segment"] == "field" for s in rule["content"])
            plan.labels.append(
                PlannedLabel(
                    ulid=ulid,
                    rule=rule_id,
                    text=text,
                    derived=derived,
                    point=point,
                    style=style,
                    layer=layer,
                )
            )


def build_plan(
    model: Model, resolved: ResolvedPresentation, scale: Decimal
) -> RenderPlan:
    """Derive every string, placement, and plan-time finding — no ezdxf."""
    plan = RenderPlan()
    _plan_inserts(model, resolved, scale, plan)
    _plan_polylines(model, resolved, plan)
    _plan_labels(model, resolved, scale, plan)
    return plan


# ---------------------------------------------------------------------------
# Emission


def _sanitize_styles(doc) -> int:
    """Remove empty-name STYLE records (the 26003 incident class).
    Idempotent; returns how many records were removed."""
    removed = 0
    table = doc.styles
    for style in list(table):
        if not style.dxf.name.strip():
            try:
                table.discard(style.dxf.name)
                removed += 1
            except Exception:  # pragma: no cover — table refuses: nothing to do
                pass
    return removed


def _ensure_layer(doc, name: str) -> None:
    if name not in doc.layers:
        doc.layers.new(name)


def _placeholder_block(doc, symbol: str, tags: list[str]) -> None:
    """The deterministic generated placeholder: a unit-diameter circle
    carrying the declared attribute tags as ATTDEFs."""
    block = doc.blocks.new(name=symbol)
    block.add_circle((0.0, 0.0), radius=0.5)
    for index, tag in enumerate(tags):
        block.add_attdef(
            tag,
            insert=(0.0, -0.25 - 0.3 * index),
            dxfattribs={"height": 0.25, "prompt": tag, "text": ""},
        )


def render(
    snapshot_doc: dict[str, Any],
    resolved: ResolvedPresentation,
    scale: Decimal,
    out_path: str,
    template_path: str | None = None,
) -> dict[str, Any]:
    """Render a canonical snapshot to R2010 DXF; returns the render report
    document (spec/schemas/presentation.json RenderReport). The DXF is
    written atomically to ``out_path``; the caller writes the report."""
    model = model_from_doc(snapshot_doc)
    plan = build_plan(model, resolved, scale)
    project = snapshot_doc.get("project")

    doc = ezdxf.new(DXF_VERSION, setup=False)
    msp = doc.modelspace()

    # Template DXF: presentation resources only, never design facts.
    template = None
    if template_path is not None:
        template = ezdxf.readfile(template_path)
        _sanitize_styles(template)

    # Text styles -> TEXTSTYLE records (names map; fonts referenced, never
    # shipped — see LIMITATIONS.md).
    for name in sorted(resolved.text_styles):
        style = resolved.text_styles[name].entry
        if name not in doc.styles:
            doc.styles.new(
                name,
                dxfattribs={"font": style["font"], "width": float(Decimal(style["width_factor"]))},
            )

    # Block definitions: template first, deterministic placeholder + finding
    # for every symbol the template does not define.
    needed: dict[str, list[str]] = {}
    users: dict[str, list[str]] = {}
    for insert in plan.inserts:
        needed.setdefault(insert.symbol, insert.tags)
        users.setdefault(insert.symbol, []).append(insert.ulid)
    to_import = [
        name for name in sorted(needed)
        if template is not None and name in template.blocks
    ]
    if to_import:
        importer = Importer(template, doc)
        for name in to_import:
            importer.import_block(name, rename=False)
        importer.finalize()
    for name in sorted(needed):
        if name in doc.blocks:
            continue
        _placeholder_block(doc, name, needed[name])
        plan.findings.append(
            _finding(
                "render.placeholder_block",
                sorted(users[name]),
                {"symbol": name, "template": template_path},
                _backend_judgement(
                    "block definitions come from the presentation-only "
                    "template DXF; an absent definition gets a deterministic "
                    "placeholder, never a crash and never silence (#24 "
                    "decision 3)"
                ),
                f"no block definition for symbol {name!r} "
                + ("in the template" if template_path else "(no template given)")
                + "; a deterministic placeholder was generated",
            )
        )

    # Entities.
    for planned in plan.polylines:
        _ensure_layer(doc, planned.layer)
        pline = msp.add_lwpolyline(
            planned.vertices,
            format="xyb",
            dxfattribs={"layer": planned.layer},
        )
        pline.closed = planned.closed
    for planned in plan.inserts:
        _ensure_layer(doc, planned.layer)
        blockref = msp.add_blockref(
            planned.symbol,
            insert=planned.point,
            dxfattribs={
                "layer": planned.layer,
                "rotation": planned.rotation,
                "xscale": planned.scale,
                "yscale": planned.scale,
            },
        )
        values = {a.tag: a.text for a in planned.attribs}
        attdef_tags = {
            attdef.dxf.tag
            for attdef in doc.blocks[planned.symbol].query("ATTDEF")
        }
        auto = {tag: text for tag, text in values.items() if tag in attdef_tags}
        if auto:
            blockref.add_auto_attribs(auto)
        for tag in sorted(set(values) - attdef_tags):
            blockref.add_attrib(
                tag,
                values[tag],
                insert=planned.point,
                dxfattribs={
                    "layer": planned.layer,
                    "height": _paper_mm_to_model(Decimal("2.5"), scale),
                },
            )
    for planned in plan.labels:
        _ensure_layer(doc, planned.layer)
        style = planned.style
        msp.add_mtext(
            planned.text,
            dxfattribs={
                "layer": planned.layer,
                "style": style["name"],
                "char_height": _paper_mm_to_model(Decimal(style["height"]), scale),
                "attachment_point": _ATTACHMENT[style["justification"]],
                "rotation": float(Decimal(style["rotation"])),
                "insert": planned.point,
            },
        )

    # Always-on, idempotent, reported sanitize step (#24 decision 5d).
    removed = _sanitize_styles(doc)
    if removed and project is not None:
        plan.findings.append(
            _finding(
                "render.style_sanitized",
                [project],
                {"removed": removed},
                _backend_judgement(
                    "the export path removes known poison patterns, starting "
                    "with empty-name STYLE records (#24 decision 5d)"
                ),
                f"{removed} empty-name STYLE record(s) removed by the "
                "always-on sanitize step",
            )
        )

    # Atomic save.
    directory = os.path.dirname(os.path.abspath(out_path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cadintent-dxf-", suffix=".dxf")
    os.close(fd)
    try:
        doc.saveas(tmp)
        os.replace(tmp, out_path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    return {
        "spec": snapshot_doc["spec"],
        "project": project,
        "head": snapshot_doc["head"],
        "log_hash": snapshot_doc["log_hash"],
        "scale": str(scale),
        "packs": [ref.as_doc() for ref in resolved.packs],
        "findings": plan.findings,
    }
