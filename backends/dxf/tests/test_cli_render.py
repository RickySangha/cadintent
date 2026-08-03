"""CLI ``render`` contract (#25/#30): subprocess invocation, exact exit
codes, report path on stdout, report written beside the DXF."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import ezdxf
import pytest

from cadintent import canonical

from dxf_case import sample_log, sample_pack

CADINTENT = shutil.which("cadintent")
CLI = [CADINTENT] if CADINTENT else [sys.executable, "-m", "cadintent.cli"]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*CLI, *args], capture_output=True)


@pytest.fixture()
def workspace(tmp_path):
    pack_doc = sample_pack()
    pack_path = tmp_path / "pack.json"
    pack_path.write_bytes(canonical.canonical_bytes(pack_doc))
    log = sample_log(pack_doc)
    snap_path = tmp_path / "snap.json"
    from cadintent import snapshot_bytes

    snap_path.write_bytes(snapshot_bytes(log))
    template = ezdxf.new("R2010")
    block = template.blocks.new("manhole")
    block.add_circle((0.0, 0.0), radius=0.5)
    block.add_attdef("NAME", insert=(0.0, 0.6), dxfattribs={"height": 0.25})
    block.add_attdef("RIM", insert=(0.0, -0.6), dxfattribs={"height": 0.25})
    template_path = tmp_path / "template.dxf"
    template.saveas(str(template_path))
    return tmp_path, snap_path, pack_path, template_path


def test_render_clean_exits_0_report_beside_dxf(workspace):
    tmp_path, snap, pack, template = workspace
    out = tmp_path / "plan.dxf"
    proc = run_cli(
        "render", str(snap), "--scale", "500", "--pack", str(pack),
        "--template", str(template), "-o", str(out),
    )
    assert proc.returncode == 0, proc.stderr
    report_path = tmp_path / "plan.dxf.render.json"
    assert proc.stdout.decode().strip() == str(report_path)
    assert out.exists()
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    assert report_bytes == canonical.canonical_bytes(report)  # canonical
    assert report["findings"] == [] and report["scale"] == "500"


def test_render_findings_exit_1_report_still_written(workspace):
    tmp_path, snap, pack, _ = workspace
    out = tmp_path / "plan.dxf"
    proc = run_cli(
        "render", str(snap), "--scale", "500", "--pack", str(pack),
        "-o", str(out),  # no template: placeholder finding expected
    )
    assert proc.returncode == 1
    report = json.loads((tmp_path / "plan.dxf.render.json").read_bytes())
    checks = {f["check"] for f in report["findings"]}
    assert "render.placeholder_block" in checks
    assert b"render.placeholder_block" in proc.stderr
    assert out.exists()  # the DXF is still produced — degradation is visible


def test_render_quiet_suppresses_stderr_only(workspace):
    tmp_path, snap, pack, _ = workspace
    out = tmp_path / "plan.dxf"
    proc = run_cli(
        "render", str(snap), "--scale", "500", "--pack", str(pack),
        "-o", str(out), "--quiet",
    )
    assert proc.returncode == 1
    assert proc.stderr == b""
    assert proc.stdout.decode().strip() == str(tmp_path / "plan.dxf.render.json")


def test_render_unloaded_pack_is_3(workspace):
    tmp_path, snap, _, _ = workspace
    proc = run_cli(
        "render", str(snap), "--scale", "500", "-o", str(tmp_path / "plan.dxf")
    )
    assert proc.returncode == 3
    doc = json.loads(proc.stdout)
    assert doc["error"]["code"] == "unresolvable_pack"


def test_render_tampered_pack_hash_is_3(workspace):
    tmp_path, snap, pack, _ = workspace
    tampered = json.loads(pack.read_bytes())
    tampered["text_styles"][0]["layer"] = "TAMPERED"
    pack.write_bytes(canonical.canonical_bytes(tampered))
    proc = run_cli(
        "render", str(snap), "--scale", "500", "--pack", str(pack),
        "-o", str(tmp_path / "plan.dxf"),
    )
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["error"]["code"] == "pack_hash_mismatch"
