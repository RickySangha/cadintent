"""CLI contract tests (#34): subprocess invocation, exact exit codes, and
parseable canonical stdout for every path in the #30 exit table.

Invoked as the installed console script ``cadintent`` so the exit-code
contract is what is actually tested (never in-process function calls).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any

import pytest

from cadintent import canonical, empty_diff_bytes, snapshot_bytes
from cadintent import submit as kernel_submit

from conftest import command, create_node, submission, ulid, units_command

CADINTENT = shutil.which("cadintent")
CLI = [CADINTENT] if CADINTENT else [sys.executable, "-m", "cadintent.cli"]

PROJECT = ulid(999)


def run_cli(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*CLI, *args], input=stdin, capture_output=True)


def stdout_doc(proc: subprocess.CompletedProcess) -> Any:
    """Parse stdout and assert it is exactly the canonical serialization."""
    doc = json.loads(proc.stdout)
    assert proc.stdout == canonical.canonical_bytes(doc)
    return doc


def accepted_log() -> list[dict[str, Any]]:
    result = kernel_submit([], submission(PROJECT, 0, [units_command()]))
    result = kernel_submit(
        result.log, submission(PROJECT, 1, [create_node(ulid(1))])
    )
    return result.log


@pytest.fixture()
def log_file(tmp_path):
    path = tmp_path / "log.json"
    path.write_bytes(canonical.canonical_bytes(accepted_log()))
    return path


@pytest.fixture()
def snap_file(tmp_path, log_file):
    path = tmp_path / "snap.json"
    path.write_bytes(snapshot_bytes(json.loads(log_file.read_bytes())))
    return path


def write_submission(tmp_path, doc: Any, name: str = "sub.json"):
    path = tmp_path / name
    path.write_bytes(json.dumps(doc).encode())
    return path


# ---------------------------------------------------------------------------
# validate


def test_validate_clean_exits_0(tmp_path):
    sub = write_submission(tmp_path, submission(PROJECT, 0, [units_command()]))
    proc = run_cli("validate", str(sub))
    assert proc.returncode == 0
    assert stdout_doc(proc)["errors"] == []


def test_validate_findings_exit_1_with_stderr_lines(tmp_path):
    doc = submission(PROJECT, 0, [units_command()])
    del doc["head"]
    sub = write_submission(tmp_path, doc)
    proc = run_cli("validate", str(sub))
    assert proc.returncode == 1
    errors = stdout_doc(proc)["errors"]
    assert errors and errors[0]["code"] == "schema_violation"
    assert b"schema_violation" in proc.stderr
    assert b"validation error" in proc.stderr


def test_validate_quiet_suppresses_stderr_only(tmp_path):
    doc = submission(PROJECT, 0, [units_command()])
    del doc["head"]
    sub = write_submission(tmp_path, doc)
    proc = run_cli("validate", "--quiet", str(sub))
    assert proc.returncode == 1
    assert proc.stderr == b""
    assert stdout_doc(proc)["errors"]


def test_validate_stdin_dash():
    raw = json.dumps(submission(PROJECT, 0, [units_command()])).encode()
    proc = run_cli("validate", "-", stdin=raw)
    assert proc.returncode == 0
    assert stdout_doc(proc)["errors"] == []


def test_validate_output_file_atomic(tmp_path):
    sub = write_submission(tmp_path, submission(PROJECT, 0, [units_command()]))
    out = tmp_path / "report.json"
    proc = run_cli("validate", str(sub), "-o", str(out))
    assert proc.returncode == 0
    assert proc.stdout == b""  # -o means stdout carries nothing
    report = json.loads(out.read_bytes())
    assert out.read_bytes() == canonical.canonical_bytes(report)
    assert report["errors"] == []


# ---------------------------------------------------------------------------
# usage errors are 64, never click's default 2


def test_unknown_flag_is_64(log_file):
    proc = run_cli("fold", "--bogus", str(log_file))
    assert proc.returncode == 64
    assert proc.stdout == b""
    assert b"usage error" in proc.stderr


def test_missing_file_is_64(tmp_path):
    proc = run_cli("validate", str(tmp_path / "absent.json"))
    assert proc.returncode == 64


def test_unparseable_json_is_64(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"this is not json")
    proc = run_cli("validate", str(bad))
    assert proc.returncode == 64
    assert b"not parseable JSON" in proc.stderr


def test_no_arguments_is_64():
    proc = run_cli()
    assert proc.returncode == 64


def test_two_stdin_dashes_is_64():
    proc = run_cli("diff", "-", "-", stdin=b"{}")
    assert proc.returncode == 64
    assert b"at most one" in proc.stderr


# ---------------------------------------------------------------------------
# submit


def test_submit_accepts_and_extends_log_atomically(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    sub = write_submission(
        tmp_path, submission(PROJECT, len(entries), [create_node(ulid(2), "5.000")])
    )
    proc = run_cli("submit", str(log_file), str(sub))
    assert proc.returncode == 0
    receipt = stdout_doc(proc)
    assert receipt["accepted"] == 1
    assert receipt["head"] == len(entries) + 1
    assert receipt["project"] == PROJECT
    new_entries = json.loads(log_file.read_bytes())
    assert len(new_entries) == len(entries) + 1
    assert new_entries[-1]["seq"] == len(entries) + 1
    assert new_entries[-1]["batch"] == receipt["batch"]


def test_submit_refusal_exit_2_log_byte_identical(tmp_path, log_file):
    before = log_file.read_bytes()
    sub = write_submission(
        tmp_path, submission(PROJECT, 99, [create_node(ulid(3))])
    )
    proc = run_cli("submit", str(log_file), str(sub))
    assert proc.returncode == 2
    refusal = stdout_doc(proc)
    assert refusal["errors"][0]["code"] == "stale_head"
    assert refusal["declared_head"] == 99
    assert log_file.read_bytes() == before  # refusal atomicity: untouched bytes
    assert b"stale_head" in proc.stderr
    assert b"nothing landed" in proc.stderr


def test_submit_refusal_quiet_still_exits_2(tmp_path, log_file):
    before = log_file.read_bytes()
    sub = write_submission(tmp_path, submission(PROJECT, 99, [create_node(ulid(3))]))
    proc = run_cli("submit", "--quiet", str(log_file), str(sub))
    assert proc.returncode == 2
    assert proc.stderr == b""
    assert log_file.read_bytes() == before


def test_submit_submission_from_stdin(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    raw = json.dumps(
        submission(PROJECT, len(entries), [create_node(ulid(4), "9.000")])
    ).encode()
    proc = run_cli("submit", str(log_file), "-", stdin=raw)
    assert proc.returncode == 0
    assert stdout_doc(proc)["accepted"] == 1


def test_submit_log_never_stdin(tmp_path):
    sub = write_submission(tmp_path, submission(PROJECT, 0, [units_command()]))
    proc = run_cli("submit", "-", str(sub), stdin=b"[]")
    assert proc.returncode == 64
    assert b"real file path" in proc.stderr


# ---------------------------------------------------------------------------
# fold


def test_fold_emits_canonical_snapshot(log_file):
    entries = json.loads(log_file.read_bytes())
    proc = run_cli("fold", str(log_file))
    assert proc.returncode == 0
    assert proc.stdout == snapshot_bytes(entries)
    stdout_doc(proc)


def test_fold_log_from_stdin(log_file):
    raw = log_file.read_bytes()
    proc = run_cli("fold", "-", stdin=raw)
    assert proc.returncode == 0
    assert proc.stdout == snapshot_bytes(json.loads(raw))


def test_fold_halt_is_3(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    entries[-1]["kind"] = "bogus.kind"  # tampered log: fold halts totally
    tampered = tmp_path / "tampered.json"
    tampered.write_bytes(canonical.canonical_bytes(entries))
    proc = run_cli("fold", str(tampered))
    assert proc.returncode == 3
    error = stdout_doc(proc)["error"]
    assert error["seq"] == entries[-1]["seq"]
    assert str(entries[-1]["seq"]).encode() in proc.stderr


def test_fold_from_snapshot_byte_equals_full_replay(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    prefix_snap = tmp_path / "prefix.json"
    prefix_snap.write_bytes(snapshot_bytes(entries[:1]))
    proc = run_cli("fold", str(log_file), "--from-snapshot", str(prefix_snap))
    assert proc.returncode == 0
    assert proc.stdout == snapshot_bytes(entries)  # resume equivalence, in bytes


def test_fold_from_stale_snapshot_is_3_with_reindex_hint(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    doc = json.loads(snapshot_bytes(entries[:1]))
    doc["log_hash"] = "sha256:" + "0" * 64
    stale = tmp_path / "stale.json"
    stale.write_bytes(canonical.canonical_bytes(doc))
    proc = run_cli("fold", str(log_file), "--from-snapshot", str(stale))
    assert proc.returncode == 3
    assert stdout_doc(proc)["error"]["code"] == "stale_snapshot"
    assert b"re-index" in proc.stderr


# ---------------------------------------------------------------------------
# diff


def test_diff_two_revisions(tmp_path, log_file):
    entries = json.loads(log_file.read_bytes())
    snap_a = tmp_path / "a.json"
    snap_b = tmp_path / "b.json"
    snap_a.write_bytes(snapshot_bytes(entries[:1]))
    snap_b.write_bytes(snapshot_bytes(entries))
    proc = run_cli("diff", str(snap_a), str(snap_b))
    assert proc.returncode == 0
    doc = stdout_doc(proc)
    assert doc["created"]  # the node created after revision A shows up
    assert doc["meta"]["head"] == {"before": 1, "after": len(entries)}


def test_diff_identity_is_canonical_empty(snap_file):
    proc = run_cli("diff", str(snap_file), str(snap_file))
    assert proc.returncode == 0
    assert proc.stdout == empty_diff_bytes()


def test_diff_unsupported_spec_stamp_is_3(tmp_path, snap_file):
    doc = json.loads(snap_file.read_bytes())
    doc["spec"] = "99.0.0"
    alien = tmp_path / "alien.json"
    alien.write_bytes(canonical.canonical_bytes(doc))
    proc = run_cli("diff", str(alien), str(snap_file))
    assert proc.returncode == 3
    assert stdout_doc(proc)["error"]["code"] == "stale_snapshot"


# ---------------------------------------------------------------------------
# check


def test_check_findings_exit_1(snap_file):
    proc = run_cli("check", str(snap_file))
    assert proc.returncode == 1
    run = stdout_doc(proc)
    statuses = {r["check"]: r["status"] for r in run["results"]}
    assert statuses["civil.min_slope"] == "not_run"  # visible, never a silent 0
    assert statuses["civil.completeness"] == "findings"
    assert b"not_run" in proc.stderr
    assert b"checks not clean" in proc.stderr


def test_check_quiet(snap_file):
    proc = run_cli("check", "--quiet", str(snap_file))
    assert proc.returncode == 1
    assert proc.stderr == b""
    stdout_doc(proc)


def test_check_bad_registry_artifact_is_3(tmp_path, snap_file):
    artifact = tmp_path / "registry.json"
    artifact.write_bytes(json.dumps({"not": "a registry"}).encode())
    proc = run_cli("check", str(snap_file), "--registry", str(artifact))
    assert proc.returncode == 3
    assert stdout_doc(proc)["error"]["code"] == "schema_violation"


def test_check_snapshot_without_spec_stamp_is_3(tmp_path):
    bare = tmp_path / "bare.json"
    bare.write_bytes(b"{}")
    proc = run_cli("check", str(bare))
    assert proc.returncode == 3
    assert stdout_doc(proc)["error"]["code"] == "stale_snapshot"


# ---------------------------------------------------------------------------
# render stub


def test_render_stub_is_64_never_a_fake_pass(snap_file):
    proc = run_cli("render", str(snap_file), "--scale", "500")
    assert proc.returncode == 64
    assert proc.stdout == b""
    assert b"not yet implemented" in proc.stderr


# ---------------------------------------------------------------------------
# end-to-end: the acceptance pipeline in one shell story


def test_end_to_end_pipeline(tmp_path):
    log = tmp_path / "log.json"
    log.write_bytes(canonical.canonical_bytes([]))

    # validate
    sub1 = write_submission(
        tmp_path, submission(PROJECT, 0, [units_command()]), "sub1.json"
    )
    assert run_cli("validate", str(sub1)).returncode == 0

    # submit accepted
    assert run_cli("submit", str(log), str(sub1)).returncode == 0
    sub2 = write_submission(
        tmp_path, submission(PROJECT, 1, [create_node(ulid(10))]), "sub2.json"
    )
    assert run_cli("submit", str(log), str(sub2)).returncode == 0

    # fold revision A
    snap_a = tmp_path / "a.json"
    proc = run_cli("fold", str(log), "-o", str(snap_a))
    assert proc.returncode == 0 and proc.stdout == b""

    # submit refused: exit 2 and untouched log bytes
    before = log.read_bytes()
    stale = write_submission(
        tmp_path, submission(PROJECT, 0, [create_node(ulid(11))]), "stale.json"
    )
    proc = run_cli("submit", str(log), str(stale))
    assert proc.returncode == 2
    assert log.read_bytes() == before

    # a second accepted revision, then diff A -> B
    sub3 = write_submission(
        tmp_path, submission(PROJECT, 2, [create_node(ulid(12), "3.000")]), "sub3.json"
    )
    assert run_cli("submit", str(log), str(sub3)).returncode == 0
    snap_b = tmp_path / "b.json"
    assert run_cli("fold", str(log), "-o", str(snap_b)).returncode == 0
    proc = run_cli("diff", str(snap_a), str(snap_b))
    assert proc.returncode == 0
    assert stdout_doc(proc)["created"]

    # check: findings, visibly
    proc = run_cli("check", str(snap_b))
    assert proc.returncode == 1
    stdout_doc(proc)
