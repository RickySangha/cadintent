"""Snapshot resume (#20 law 4) and staleness: refuse, never serve.

The equivalence law itself is property-tested in test_fold_laws (law 4) and
pinned by conformance case fold/002; this file covers the typed stale errors
and the chained log-hash mechanics.
"""

from __future__ import annotations

import json

import pytest

from cadintent import (
    Accepted,
    StaleSnapshot,
    canonical_bytes,
    extend_log_hash,
    fold_from,
    log_hash,
    snapshot_bytes,
    submit,
    verify_snapshot,
)
from cadintent.canonical import EMPTY_LOG_HASH
from cadintent.ulid import encode
from conftest import create_node, submission, units_command

PROJECT = encode(7)


def _log() -> list[dict]:
    result = submit([], submission(PROJECT, 0, [units_command()]))
    assert isinstance(result, Accepted)
    result = submit(result.log, submission(PROJECT, 1, [create_node(encode(101))]))
    assert isinstance(result, Accepted)
    result = submit(
        result.log, submission(PROJECT, 2, [create_node(encode(102), x="5.000")])
    )
    assert isinstance(result, Accepted)
    return result.log


def test_resume_from_prefix_byte_equals_full_replay() -> None:
    log = _log()
    for n in (1, 2, 3):
        assert fold_from(snapshot_bytes(log[:n]), log[n:]) == snapshot_bytes(log)


def test_chained_log_hash_extends_from_any_prefix() -> None:
    log = _log()
    assert log_hash([]) == EMPTY_LOG_HASH
    for n in range(len(log) + 1):
        assert extend_log_hash(log_hash(log[:n]), log[n:]) == log_hash(log)


def test_resume_with_discontinuous_commands_is_stale_with_reindex_hint() -> None:
    log = _log()
    snapshot = snapshot_bytes(log[:1])
    with pytest.raises(StaleSnapshot) as excinfo:
        fold_from(snapshot, log[2:])  # skips seq 2: the snapshot is stale
    assert excinfo.value.code == "stale_snapshot"
    assert "re-index" in excinfo.value.message


def test_resume_with_unsupported_spec_stamp_is_stale() -> None:
    log = _log()
    doc = json.loads(snapshot_bytes(log[:1]))
    doc["spec"] = "9.9.9"
    with pytest.raises(StaleSnapshot) as excinfo:
        fold_from(canonical_bytes(doc), log[1:])
    assert "9.9.9" in excinfo.value.message


def test_resume_with_unparseable_snapshot_is_stale() -> None:
    with pytest.raises(StaleSnapshot):
        fold_from(b"not json at all", [])


def test_verify_snapshot_accepts_a_true_prefix() -> None:
    log = _log()
    doc = verify_snapshot(snapshot_bytes(log[:2]), log)
    assert doc["head"] == 2


def test_verify_snapshot_rejects_a_mismatched_prefix_hash() -> None:
    log = _log()
    doc = json.loads(snapshot_bytes(log[:2]))
    doc["log_hash"] = EMPTY_LOG_HASH
    with pytest.raises(StaleSnapshot) as excinfo:
        verify_snapshot(canonical_bytes(doc), log)
    assert "does not match" in excinfo.value.message
    assert "re-index" in excinfo.value.message


def test_verify_snapshot_rejects_a_head_beyond_the_log() -> None:
    log = _log()
    snapshot = snapshot_bytes(log)
    with pytest.raises(StaleSnapshot):
        verify_snapshot(snapshot, log[:1])


def test_verify_snapshot_rejects_a_rewritten_prefix() -> None:
    # Same length, different content: the chained hash catches it.
    log = _log()
    snapshot = snapshot_bytes(log[:2])
    tampered = json.loads(json.dumps(log))
    tampered[1]["payload"]["geometry"]["point"]["x"] = "999.000"
    with pytest.raises(StaleSnapshot):
        verify_snapshot(snapshot, tampered)
