"""DXF backend contract tests (#24): honest round-trip, visible findings,
report shape, and the opt-in external oracle."""

from __future__ import annotations

import json
from decimal import Decimal

import ezdxf
import pytest

from cadintent.presentation import PackStore
from cadintent.snapshot import model_from_doc
from cadintent.spec import schema_errors
from cadintent_dxf.oracle import ENV_VAR, external_oracle
from cadintent_dxf.render import DXF_VERSION, UNSTYLED_LAYER, render
from cadintent_dxf.roundtrip import verify_roundtrip

from dxf_case import C1, MH1, MH2, sample_pack, sample_snapshot

SCALE = Decimal("500")


def resolve(pack_doc, snapshot_doc):
    store = PackStore()
    store.add(pack_doc)
    return store.resolve(model_from_doc(snapshot_doc))


def do_render(tmp_path, pack_doc, template=None):
    snapshot_doc = sample_snapshot(pack_doc)
    resolved = resolve(pack_doc, snapshot_doc)
    out = tmp_path / "out.dxf"
    report = render(snapshot_doc, resolved, SCALE, str(out), template)
    return snapshot_doc, resolved, out, report


def make_template(tmp_path):
    doc = ezdxf.new(DXF_VERSION)
    block = doc.blocks.new("manhole")
    block.add_circle((0.0, 0.0), radius=0.5)
    block.add_attdef("NAME", insert=(0.0, 0.6), dxfattribs={"height": 0.25})
    block.add_attdef("RIM", insert=(0.0, -0.6), dxfattribs={"height": 0.25})
    path = tmp_path / "template.dxf"
    doc.saveas(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# The acceptance round-trip (#24 decision 5): fresh readfile, zero-error
# audit, exact re-derivation of every derived string.


def test_roundtrip_fresh_read_audit_and_exact_strings(tmp_path):
    pack_doc = sample_pack()
    snapshot_doc, resolved, out, report = do_render(tmp_path, pack_doc)
    result = verify_roundtrip(str(out), snapshot_doc, resolved, SCALE)
    assert result["audit_errors"] == []
    assert result["mismatches"] == []
    assert result["derived_checked"] >= 3  # RIM x2 + conduit label
    # literal tag values are present-but-unverifiable — visible, never a pass
    assert any(e["tag"] == "NAME" for e in result["literal_unverified"])


def test_saved_file_is_r2010_with_expected_entities(tmp_path):
    pack_doc = sample_pack()
    _, _, out, _ = do_render(tmp_path, pack_doc)
    doc = ezdxf.readfile(str(out))
    assert doc.dxfversion == "AC1024"
    msp = doc.modelspace()
    inserts = msp.query("INSERT")
    assert len(inserts) == 2 and all(i.dxf.layer == "V-NODE" for i in inserts)
    plines = msp.query("LWPOLYLINE")
    assert len(plines) == 1 and plines[0].dxf.layer == "V-PIPE"
    mtexts = msp.query("MTEXT")
    assert len(mtexts) == 1
    assert mtexts[0].dxf.text == "200 pvc L=10.00m S=1.00%"
    assert len(msp.query("TEXT")) == 0  # never TEXT (#24 decision 2)
    # paper-mm text height x scale: 2.5 mm at 1:500 = 1.25 m model
    assert mtexts[0].dxf.char_height == pytest.approx(1.25)


def test_derived_label_formatting_is_decimal_quantized(tmp_path):
    # 0.200 m diameter -> "200" mm; slope 0.01 -> "1.00%" ROUND_HALF_UP
    pack_doc = sample_pack()
    snapshot_doc = sample_snapshot(pack_doc)
    resolved = resolve(pack_doc, snapshot_doc)
    from cadintent_dxf.render import build_plan

    plan = build_plan(model_from_doc(snapshot_doc), resolved, SCALE)
    assert [l.text for l in plan.labels] == ["200 pvc L=10.00m S=1.00%"]
    rims = {
        (a.tag, a.text) for i in plan.inserts for a in i.attribs if a.derived
    }
    assert rims == {("RIM", "102.00"), ("RIM", "101.50")}


# ---------------------------------------------------------------------------
# Visible degradation paths


def test_missing_block_gets_placeholder_and_finding(tmp_path):
    pack_doc = sample_pack()
    _, _, out, report = do_render(tmp_path, pack_doc)  # no template
    placeholder = [
        f for f in report["findings"] if f["check"] == "render.placeholder_block"
    ]
    assert len(placeholder) == 1
    assert placeholder[0]["subjects"] == sorted([MH1, MH2])
    assert placeholder[0]["values"]["symbol"] == "manhole"
    # the placeholder still renders: block exists, carries the declared tags
    doc = ezdxf.readfile(str(out))
    block = doc.blocks["manhole"]
    assert {a.dxf.tag for a in block.query("ATTDEF")} == {"NAME", "RIM"}
    assert len(block.query("CIRCLE")) == 1


def test_template_block_suppresses_placeholder_finding(tmp_path):
    pack_doc = sample_pack()
    template = make_template(tmp_path)
    _, _, out, report = do_render(tmp_path, pack_doc, template)
    assert not [
        f for f in report["findings"] if f["check"] == "render.placeholder_block"
    ]
    doc = ezdxf.readfile(str(out))
    inserts = doc.modelspace().query("INSERT")
    assert {a.dxf.tag for i in inserts for a in i.attribs} == {"NAME", "RIM"}


def test_missing_layer_lands_on_unstyled_with_finding(tmp_path):
    pack_doc = sample_pack(symbol_layer=None)
    _, _, out, report = do_render(tmp_path, pack_doc)
    unstyled = [
        f for f in report["findings"] if f["check"] == "render.unstyled_layer"
    ]
    assert len(unstyled) == 2  # both manholes
    assert all(f["values"]["layer"] == UNSTYLED_LAYER for f in unstyled)
    doc = ezdxf.readfile(str(out))
    assert UNSTYLED_LAYER in doc.layers
    inserts = doc.modelspace().query("INSERT")
    assert all(i.dxf.layer == UNSTYLED_LAYER for i in inserts)


def test_rotation_fallback_emits_finding_and_flow_resolves_where_it_can(tmp_path):
    pack_doc = sample_pack(
        rotation={"source": "from_flow_out", "fallback_angle": "45"}
    )
    snapshot_doc = sample_snapshot(pack_doc)
    resolved = resolve(pack_doc, snapshot_doc)
    from cadintent_dxf.render import build_plan

    plan = build_plan(model_from_doc(snapshot_doc), resolved, SCALE)
    by_ulid = {i.ulid: i for i in plan.inserts}
    # flow a_to_b leaves MH1: outgoing tangent resolves (0 degrees, no fallback)
    assert by_ulid[MH1].rotation == pytest.approx(0.0)
    # nothing leaves MH2: mandatory fallback + finding, never a silent 0
    assert by_ulid[MH2].rotation == pytest.approx(45.0)
    fallbacks = [
        f for f in plan.findings if f["check"] == "render.rotation_fallback"
    ]
    assert [f["subjects"] for f in fallbacks] == [[MH2]]


def test_orient_geometry_to_flow_reverses_declared_b_to_a(tmp_path):
    pack_doc = sample_pack()
    snapshot_doc = sample_snapshot(pack_doc)
    # flip the declared flow in the snapshot (facts are plain JSON)
    snapshot_doc["objects"][C1]["facts"]["attrs.flow_direction"]["value"][
        "value"
    ] = "b_to_a"
    resolved = resolve(pack_doc, snapshot_doc)
    from cadintent_dxf.render import build_plan

    plan = build_plan(model_from_doc(snapshot_doc), resolved, SCALE)
    assert plan.polylines[0].vertices[0][:2] == (10.0, 0.0)


# ---------------------------------------------------------------------------
# Render report (#24 decision 7)


def test_report_shape_and_finding_schema(tmp_path):
    pack_doc = sample_pack()
    snapshot_doc, _, _, report = do_render(tmp_path, pack_doc)
    assert schema_errors("presentation.json#/$defs/RenderReport", report) == []
    assert report["spec"] == snapshot_doc["spec"]
    assert report["head"] == snapshot_doc["head"]
    assert report["log_hash"] == snapshot_doc["log_hash"]
    assert report["scale"] == "500"
    (pack_ref,) = report["packs"]
    from cadintent.presentation import pack_hash

    assert pack_ref == {
        "id": "sample",
        "version": "0.1.0",
        "content_hash": pack_hash(pack_doc),
    }


def test_clean_render_report_is_empty(tmp_path):
    pack_doc = sample_pack()
    template = make_template(tmp_path)
    _, _, _, report = do_render(tmp_path, pack_doc, template)
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# External oracle: opt-in, could-not-run visibility, never claimed in CI


def test_external_oracle_skips_with_reason_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    result = external_oracle(str(tmp_path / "any.dxf"))
    assert result["status"] == "skipped"
    assert ENV_VAR in result["reason"]


def test_external_oracle_could_not_run_is_never_a_pass(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "no-such-accoreconsole"))
    result = external_oracle(str(tmp_path / "any.dxf"))
    assert result["status"] == "could_not_run"
    assert "failed" in result["reason"]
