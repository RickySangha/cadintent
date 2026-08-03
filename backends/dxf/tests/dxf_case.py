"""Shared fixtures: a small storm run (MH1 --C1(10 m)--> MH2) plus a sample
presentation pack, built through the real kernel submit/fold pipeline."""

from __future__ import annotations

import json
from typing import Any

from cadintent import snapshot_bytes, submit as kernel_submit
from cadintent.presentation import pack_hash
from cadintent.ulid import encode

SPEC = "0.1.0"
ENGINEER = "engineer:test"

PROJECT = encode(900)
NET, MH1, MH2, C1 = encode(901), encode(902), encode(903), encode(904)


def command(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "author": ENGINEER,
        "kind": kind,
        "payload": payload,
        "basis": [],
        "spec": SPEC,
    }


def _elev(value: str) -> dict[str, Any]:
    return {
        "kind": "elevation",
        "value": {
            "value": value,
            "kind": "surveyed",
            "sources": [{"kind": "statement", "text": "survey"}],
        },
    }


def sample_pack(
    *,
    symbol_layer: str | None = "V-NODE",
    rotation: dict[str, Any] | None = None,
    pack_id: str = "sample",
    version: str = "0.1.0",
) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "when": {"kind": "civil.manhole"},
        "symbol": "manhole",
        "rotation": rotation or {"source": "fixed", "angle": "0"},
    }
    if symbol_layer is not None:
        mapping["layer"] = symbol_layer
    plain_m = {"unit": "m", "quantum": "0.01", "rounding": "ROUND_HALF_UP", "style": "plain"}
    return {
        "id": pack_id,
        "version": version,
        "text_styles": [
            {
                "name": "note",
                "layer": "V-ANNO",
                "font": "isocp.shx",
                "height": "2.5",
                "width_factor": "1",
                "justification": "middle_left",
                "rotation": "0",
            }
        ],
        "label_rules": [
            {
                "id": "civil.conduit_label",
                "selector": {"kind": "civil.conduit", "system": "storm"},
                "applicability": {
                    "kind": "civil.conduit",
                    "where": [{"field": "attrs.diameter", "op": "exists"}],
                },
                "content": [
                    {
                        "segment": "field",
                        "source": "attrs.diameter",
                        "format": {
                            "unit": "mm",
                            "quantum": "1",
                            "rounding": "ROUND_HALF_UP",
                            "style": "plain",
                        },
                    },
                    {"segment": "literal", "text": " "},
                    {
                        "segment": "field",
                        "source": "attrs.material",
                        "format": {
                            "unit": "1",
                            "quantum": "1",
                            "rounding": "ROUND_HALF_UP",
                            "style": "plain",
                        },
                    },
                    {"segment": "literal", "text": " L="},
                    {"segment": "field", "source": "derived.length", "format": plain_m},
                    {"segment": "literal", "text": "m S="},
                    {
                        "segment": "field",
                        "source": "derived.slope",
                        "format": {
                            "unit": "1",
                            "quantum": "0.01",
                            "rounding": "ROUND_HALF_UP",
                            "style": "percent",
                        },
                    },
                ],
                "text_style": "note",
                "placement": {
                    "anchor": "edge_midpoint",
                    "offset": {"dx": "2", "dy": "2"},
                },
            }
        ],
        "symbols": [
            {"name": "manhole", "tags": ["NAME", "RIM"], "size_mode": "paper", "size": "3"}
        ],
        "symbol_mappings": [mapping],
        "linework": [
            {
                "when": {"kind": "civil.conduit"},
                "layer": "V-PIPE",
                "orient_geometry_to_flow": True,
            }
        ],
        "tag_fills": [
            {
                "when": {"kind": "civil.manhole"},
                "tag": "NAME",
                "value": {"kind": "literal", "text": "MH"},
            },
            {
                "when": {"kind": "civil.manhole"},
                "tag": "RIM",
                "value": {
                    "kind": "derived",
                    "source": "attrs.rim_elevation",
                    "format": plain_m,
                },
            },
        ],
    }


def sample_log(pack_doc: dict[str, Any]) -> list[dict[str, Any]]:
    commands = [
        command("project.units", {"system": {"kind": "metric"}}),
        command(
            "presentation.import",
            {
                "pack": {
                    "id": pack_doc["id"],
                    "version": pack_doc["version"],
                    "content_hash": pack_hash(pack_doc),
                }
            },
        ),
        command(
            "object.create",
            {
                "object": NET,
                "type": "civil.network",
                "attrs": {"system": {"kind": "string", "value": "storm"}},
            },
        ),
        command(
            "object.create",
            {
                "object": MH1,
                "type": "civil.manhole",
                "geometry": {"kind": "point", "point": {"x": "0.000", "y": "0.000"}},
                "networks": [NET],
                "attrs": {"rim_elevation": _elev("102.00")},
            },
        ),
        command(
            "object.create",
            {
                "object": MH2,
                "type": "civil.manhole",
                "geometry": {"kind": "point", "point": {"x": "10.000", "y": "0.000"}},
                "networks": [NET],
                "attrs": {"rim_elevation": _elev("101.50")},
            },
        ),
        command(
            "object.create",
            {
                "object": C1,
                "type": "civil.conduit",
                "geometry": {
                    "kind": "polyline",
                    "vertices": [
                        {"point": {"x": "0.000", "y": "0.000"}},
                        {"point": {"x": "10.000", "y": "0.000"}},
                    ],
                    "closed": False,
                },
                "ends": {
                    "end_a": {"kind": "node", "node": MH1},
                    "end_b": {"kind": "node", "node": MH2},
                },
                "networks": [NET],
                "attrs": {
                    "invert_a": _elev("100.00"),
                    "invert_b": _elev("99.90"),
                    "shape": {"kind": "string", "value": "circular"},
                    "diameter": {"kind": "quantity", "value": "0.200"},
                    "material": {"kind": "string", "value": "pvc"},
                    "flow_direction": {"kind": "string", "value": "a_to_b"},
                },
            },
        ),
    ]
    result = kernel_submit(
        [],
        {
            "project": PROJECT,
            "head": 0,
            "scope": [{"kind": "project"}],
            "commands": commands,
        },
    )
    assert not hasattr(result, "refusal"), getattr(result, "refusal", None)
    return result.log


def sample_snapshot(pack_doc: dict[str, Any]) -> dict[str, Any]:
    return json.loads(snapshot_bytes(sample_log(pack_doc)))
