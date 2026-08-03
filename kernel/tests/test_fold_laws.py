"""The 12-law hypothesis invariant seed list from #20's resolution.

All twelve run: build issue #33 landed snapshot resume (law 4) and the
canonical diff document (laws 7-9 and law 10's diff leg).
"""

from __future__ import annotations

import copy
import json

import pytest
from hypothesis import given, strategies as st

import cadintent
from cadintent import (
    Accepted,
    FoldHalt,
    Refused,
    diff_bytes,
    diff_doc,
    empty_diff_bytes,
    fold,
    fold_from,
    log_hash,
    snapshot_bytes,
    submit,
)
from cadintent.canonical import canonical_bytes
from cadintent.fold import apply_command
from cadintent.snapshot import snapshot_doc
from cadintent.ulid import encode
from conftest import SPEC, command, submission, units_command

PROJECT = encode(7)


def batch_boundaries(log: list[dict]) -> list[int]:
    """Prefix lengths that end on a complete batch (snapshot-able heads)."""
    return [
        n
        for n in range(1, len(log) + 1)
        if n == len(log) or log[n]["batch"] != log[n - 1]["batch"]
    ]


# ---------------------------------------------------------------------------
# Log strategy: build an always-acceptable sequence of submissions, then land
# them through submit() so every generated log is kernel-accepted by
# construction.


@st.composite
def project_logs(draw) -> list[dict]:
    log: list[dict] = []
    result = submit(log, submission(PROJECT, 0, [units_command()]))
    assert isinstance(result, Accepted)
    log = result.log

    nodes: list[str] = []
    edges: list[str] = []
    bound: set[str] = set()  # nodes referenced by edge ends
    next_id = 100

    n_batches = draw(st.integers(min_value=1, max_value=4))
    for _ in range(n_batches):
        commands = []
        n_commands = draw(st.integers(min_value=1, max_value=4))
        minted_nodes: list[str] = []
        for _ in range(n_commands):
            choices = ["create"]
            if len(nodes) + len(minted_nodes) >= 2:
                choices.append("edge")
            if nodes:
                choices.extend(["set", "remove_free"])
            op = draw(st.sampled_from(choices))
            if op == "create":
                ulid = encode(next_id)
                next_id += 1
                x = draw(st.integers(min_value=-10_000, max_value=10_000))
                commands.append(
                    command(
                        "object.create",
                        {
                            "object": ulid,
                            "type": "civil.manhole",
                            "geometry": {
                                "kind": "point",
                                "point": {"x": f"{x / 1000:.3f}", "y": "0.000"},
                            },
                        },
                    )
                )
                minted_nodes.append(ulid)
            elif op == "edge":
                pool = nodes + minted_nodes
                a = draw(st.sampled_from(pool))
                b = draw(st.sampled_from(pool))
                ulid = encode(next_id)
                next_id += 1
                commands.append(
                    command(
                        "object.create",
                        {
                            "object": ulid,
                            "type": "civil.conduit",
                            "ends": {
                                "end_a": {"kind": "node", "node": a},
                                "end_b": {"kind": "node", "node": b},
                            },
                        },
                    )
                )
                edges.append(ulid)
                bound.update({a, b})
            elif op == "set":
                target = draw(st.sampled_from(nodes))
                value = draw(st.integers(min_value=0, max_value=99))
                commands.append(
                    command(
                        "object.set_attrs",
                        {
                            "target": target,
                            "attrs": {"count": {"kind": "integer", "value": value}},
                        },
                    )
                )
            else:  # remove a node no edge binds to
                free = [n for n in nodes if n not in bound]
                if not free:
                    continue
                target = draw(st.sampled_from(free))
                commands.append(command("object.remove", {"target": target}))
                nodes.remove(target)
        if not commands:
            continue
        result = submit(log, submission(PROJECT, log[-1]["seq"], commands))
        assert isinstance(result, Accepted), result
        log = result.log
        nodes.extend(minted_nodes)
    return log


# ---------------------------------------------------------------------------


@given(project_logs())
def test_law_1_determinism(log) -> None:
    """fold(log) twice => byte-identical snapshots."""
    assert snapshot_bytes(log) == snapshot_bytes(copy.deepcopy(log))


@given(project_logs(), st.integers(min_value=0, max_value=10))
def test_law_2_replay_totality(log, corrupt_at) -> None:
    """Every kernel-accepted log folds; a tampered log errors totally."""
    fold(log)  # accepted by construction; must not raise
    index = corrupt_at % len(log)
    tampered = copy.deepcopy(log)
    tampered[index]["kind"] = "no.such.kind"
    with pytest.raises(FoldHalt) as excinfo:
        fold(tampered)
    assert excinfo.value.seq == index + 1  # names the entry, yields no state


@given(project_logs(), st.integers(min_value=0, max_value=10))
def test_law_3_prefix_stability(log, cut) -> None:
    """Snapshot at seq n depends only on commands 1..n."""
    n = cut % len(log) + 1
    prefix = log[:n]
    # Appending never rewrites history: the prefix folds the same whether or
    # not later entries exist (only complete batches are foldable prefixes).
    if log[n - 1]["batch"] not in {e["batch"] for e in log[n:]}:
        assert snapshot_bytes(prefix) == snapshot_bytes(copy.deepcopy(prefix))


@given(project_logs(), st.integers(min_value=0, max_value=10))
def test_law_4_resume_equivalence(log, cut) -> None:
    """fold(snapshot@n, n+1..m) == full replay of 1..m, byte-identical."""
    boundaries = batch_boundaries(log)
    n = boundaries[cut % len(boundaries)]
    prefix_snapshot = snapshot_bytes(log[:n])
    assert fold_from(prefix_snapshot, log[n:]) == snapshot_bytes(log)


@given(project_logs())
def test_law_5_refusal_atomicity(log) -> None:
    """A refused submission leaves the foldable state byte-identical."""
    before = snapshot_bytes(log)
    frozen = copy.deepcopy(log)
    result = submit(
        log,
        submission(PROJECT, log[-1]["seq"] + 1000, [units_command()]),  # stale head
    )
    assert isinstance(result, Refused)
    assert log == frozen
    assert snapshot_bytes(log) == before


@given(project_logs())
def test_law_6_batch_atomicity(log) -> None:
    """A submission's commands land all-or-none; no subset is reachable."""
    before = snapshot_bytes(log)
    good = command(
        "object.create",
        {
            "object": encode(999_999),
            "type": "civil.manhole",
            "geometry": {"kind": "point", "point": {"x": "0.000", "y": "0.000"}},
        },
    )
    bad = command("object.remove", {"target": encode(888_888)})  # unknown ref
    result = submit(log, submission(PROJECT, log[-1]["seq"], [good, bad]))
    assert isinstance(result, Refused)
    after = snapshot_bytes(log)
    assert after == before  # nothing landed
    assert encode(999_999) not in json.loads(after)["objects"]


@given(project_logs())
def test_law_7_diff_identity(log) -> None:
    """diff(S, S) is the canonical empty document — one form, independent of S."""
    snapshot = snapshot_bytes(log)
    assert diff_bytes(snapshot, snapshot) == empty_diff_bytes()


@given(project_logs(), st.integers(min_value=0, max_value=10))
def test_law_8_diff_completeness(log, cut) -> None:
    """diff(fold(1..n), fold(1..m)) mentions exactly the touched objects."""
    boundaries = batch_boundaries(log)
    n = boundaries[cut % len(boundaries)]
    base, full = snapshot_bytes(log[:n]), snapshot_bytes(log)
    d = json.loads(diff_bytes(base, full))
    mentioned = set(d["created"]) | set(d["modified"]) | set(d["removed"])

    model = fold(log[:n])
    touched: dict[str, set[str]] = {}
    for entry in log[n:]:
        apply_command(model, entry["seq"], entry["kind"], entry["payload"], touched)
        model.head = entry["seq"]
    # Every mentioned object was touched; every touched object either shows in
    # the diff or ended byte-identical (e.g. created then removed in n+1..m).
    assert mentioned <= set(touched)
    base_objects = json.loads(base)["objects"]
    full_objects = json.loads(full)["objects"]
    for ulid in set(touched) - mentioned:
        assert base_objects.get(ulid) == full_objects.get(ulid)


def _apply_diff(a_doc: dict, d: dict) -> dict:
    doc = copy.deepcopy(a_doc)
    for key, change in d["meta"].items():
        doc[key] = change["after"]
    for key, change in d["declarations"].items():
        doc["declarations"][key] = change["after"]
    for ulid in d["removed"]:
        del doc["objects"][ulid]
    for ulid, entry in d["created"].items():
        doc["objects"][ulid] = entry
    for ulid, paths in d["modified"].items():
        entry = doc["objects"][ulid]
        for path, change in paths.items():
            container, key = (
                (entry, "derivation") if path == "derivation" else (entry["facts"], path)
            )
            if change["after"] is None:
                container.pop(key, None)
            else:
                container[key] = change["after"]
    return doc


@given(project_logs(), st.integers(min_value=0, max_value=10))
def test_law_9_diff_invertibility(log, cut) -> None:
    """diff(A, B) + A determines B; diff(B, A) is the mirror."""
    boundaries = batch_boundaries(log)
    n = boundaries[cut % len(boundaries)]
    a_bytes, b_bytes = snapshot_bytes(log[:n]), snapshot_bytes(log)
    a_doc, b_doc = json.loads(a_bytes), json.loads(b_bytes)
    d_ab, d_ba = diff_doc(a_doc, b_doc), diff_doc(b_doc, a_doc)

    # diff(A, B) + A determines B.
    assert canonical_bytes(_apply_diff(a_doc, d_ab)) == b_bytes

    # diff(B, A) is the mirror: created<->removed, before<->after swapped.
    assert d_ba["created"] == d_ab["removed"]
    assert d_ba["removed"] == d_ab["created"]

    def mirror(section: dict) -> dict:
        return {
            key: {**value, "before": value["after"], "after": value["before"]}
            for key, value in section.items()
        }

    assert d_ba["meta"] == mirror(d_ab["meta"])
    assert d_ba["declarations"] == mirror(d_ab["declarations"])
    assert d_ba["modified"] == {
        ulid: {
            path: {**change, "before": change["after"], "after": change["before"]}
            for path, change in paths.items()
        }
        for ulid, paths in d_ab["modified"].items()
    }


@given(project_logs(), project_logs())
def test_law_10_equality_coherence(log_a, log_b) -> None:
    """Bytes equal <=> diff empty <=> states equal."""
    bytes_a, bytes_b = snapshot_bytes(log_a), snapshot_bytes(log_b)
    states_equal = snapshot_doc(fold(log_a), log_hash(log_a)) == snapshot_doc(
        fold(log_b), log_hash(log_b)
    )
    diff_empty = diff_bytes(bytes_a, bytes_b) == empty_diff_bytes()
    assert (bytes_a == bytes_b) == states_equal == diff_empty


@given(project_logs())
def test_law_11_canonicalization_idempotence(log) -> None:
    """Parse + re-serialize any snapshot => byte-identical."""
    raw = snapshot_bytes(log)
    assert canonical_bytes(json.loads(raw)) == raw


@given(project_logs())
def test_law_12_provenance_validity(log) -> None:
    """Every fact's writing seq points at a command whose kind and author
    role could legally have written it."""
    from cadintent import spec as spec_mod

    doc = json.loads(snapshot_bytes(log))
    by_seq = {entry["seq"]: entry for entry in log}
    writers = {
        "type": {"object.create"},
        "geometry": {"object.create", "object.set_attrs"},
        "ends": {"object.create", "object.set_attrs"},
        "networks": {"object.create", "object.set_attrs"},
        "criteria": {"selection.define"},
    }
    for facts_holder in doc["objects"].values():
        for path, fact in facts_holder["facts"].items():
            entry = by_seq[fact["seq"]]
            legal = (
                {"object.create", "object.set_attrs"}
                if path.startswith("attrs.")
                else writers[path]
            )
            assert entry["kind"] in legal
            role = entry["author"].split(":", 1)[0]
            assert role in spec_mod.commands()[entry["kind"]]["roles"]
