"""Kernel unit tests: validate, submit pipeline refusals, fold halting."""

from __future__ import annotations

import copy
import json

import pytest

from cadintent import (
    Accepted,
    FoldHalt,
    Refused,
    fold,
    snapshot_bytes,
    submit,
    validate_submission,
)
from conftest import SPEC, command, create_node, submission, ulid, units_command

PROJECT = ulid(1)
N1, N2, N3, E1, SEL = ulid(10), ulid(11), ulid(12), ulid(20), ulid(30)


def accept(log, doc):
    result = submit(log, doc)
    assert isinstance(result, Accepted), getattr(result, "refusal", None)
    return result.log


def refuse(log, doc):
    result = submit(log, doc)
    assert isinstance(result, Refused), "expected a refusal"
    return result.refusal


def base_log():
    return accept(
        [],
        submission(
            PROJECT,
            0,
            [units_command(), create_node(N1), create_node(N2, x="10.000")],
        ),
    )


def edge_log():
    log = base_log()
    return accept(
        log,
        submission(
            PROJECT,
            3,
            [
                command(
                    "object.create",
                    {
                        "object": E1,
                        "type": "civil.conduit",
                        "ends": {
                            "end_a": {"kind": "node", "node": N1},
                            "end_b": {"kind": "node", "node": N2},
                        },
                    },
                )
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Validate


def test_validate_reports_command_position_and_field_path() -> None:
    doc = submission(PROJECT, 0, [units_command()])
    doc["commands"][0]["author"] = "plumber:joe"
    errors = validate_submission(doc)
    assert errors[0]["command"] == 0
    assert errors[0]["path"] == "/author"
    assert errors[0]["code"] == "schema_violation"


def test_validate_reports_submission_level_errors_with_null_command() -> None:
    errors = validate_submission({"project": PROJECT, "head": 0, "commands": []})
    positions = {(e["command"], e["path"]) for e in errors}
    assert (None, "") in positions or (None, "/commands") in positions


def test_validate_accepts_a_clean_submission() -> None:
    assert validate_submission(submission(PROJECT, 0, [units_command()])) == []


# ---------------------------------------------------------------------------
# Submit pipeline refusal codes


def test_missing_declaration_before_units() -> None:
    refusal = refuse([], submission(PROJECT, 0, [create_node(N1)]))
    assert [(e["code"], e["command"]) for e in refusal["errors"]] == [
        ("missing_declaration", 0)
    ]


def test_immutable_declaration_on_redeclared_units() -> None:
    refusal = refuse(base_log(), submission(PROJECT, 3, [units_command()]))
    assert [(e["code"], e["command"], e["path"]) for e in refusal["errors"]] == [
        ("immutable_declaration", 0, "/payload")
    ]


def test_unknown_kind() -> None:
    refusal = refuse(
        base_log(), submission(PROJECT, 3, [command("object.explode", {"target": N1})])
    )
    assert refusal["errors"][0]["code"] == "unknown_kind"
    assert refusal["errors"][0]["path"] == "/kind"


def test_spec_unsupported() -> None:
    bad = create_node(N3)
    bad["spec"] = "9.9.9"
    refusal = refuse(base_log(), submission(PROJECT, 3, [bad]))
    assert ("spec_unsupported", 0, "/spec") in {
        (e["code"], e["command"], e["path"]) for e in refusal["errors"]
    }


def test_id_collision_within_submission_and_against_prestate() -> None:
    refusal = refuse(
        base_log(),
        submission(PROJECT, 3, [create_node(N3), create_node(N3), create_node(N1)]),
    )
    assert [(e["code"], e["command"]) for e in refusal["errors"]] == [
        ("id_collision", 1),
        ("id_collision", 2),
    ]


def test_name_collision_per_type() -> None:
    def named(obj, name):
        c = create_node(obj)
        c["payload"]["attrs"] = {"name": {"kind": "string", "value": name}}
        return c

    log = accept(base_log(), submission(PROJECT, 3, [named(N3, "SMH-4")]))
    refusal = refuse(log, submission(PROJECT, 4, [named(ulid(13), "SMH-4")]))
    assert refusal["errors"][0]["code"] == "name_collision"
    assert set(refusal["errors"][0]["objects"]) == {N3, ulid(13)}


def test_rule_citation_requires_prior_import() -> None:
    cited = command(
        "object.set_attrs",
        {"target": N1, "attrs": {"crown": {"kind": "quantity", "value": "101.250"}}},
        basis=[
            {
                "kind": "rule",
                "registry": "crown-rules",
                "version": "1.0.0",
                "name": "crown_from_pl",
                "params": {},
            }
        ],
    )
    refusal = refuse(base_log(), submission(PROJECT, 3, [cited]))
    assert refusal["errors"][0]["code"] == "unknown_reference"
    assert refusal["errors"][0]["path"] == "/basis/0"


def test_command_citation_must_point_at_an_earlier_entry() -> None:
    cited = command(
        "object.set_attrs",
        {"target": N1, "attrs": {"a": {"kind": "integer", "value": 1}}},
        basis=[{"kind": "command", "seq": 99}],
    )
    refusal = refuse(base_log(), submission(PROJECT, 3, [cited]))
    assert refusal["errors"][0]["code"] == "unknown_reference"
    assert refusal["errors"][0]["path"] == "/basis/0/seq"


def test_scope_violation_names_the_stray_object_and_its_fields() -> None:
    doc = submission(
        PROJECT,
        3,
        [
            command(
                "object.set_attrs",
                {"target": N2, "attrs": {"status": {"kind": "string", "value": "x"}}},
            )
        ],
        scope=[{"kind": "object", "object": N1}],
    )
    refusal = refuse(base_log(), doc)
    error = refusal["errors"][0]
    assert error["code"] == "scope_violation"
    assert error["command"] is None
    assert error["path"] == "/scope"
    assert error["objects"] == [N2]


def test_declarations_require_the_explicit_project_scope_term() -> None:
    doc = submission(
        PROJECT,
        3,
        [command("project.crs", {"crs": {"id": "EPSG:26910"}})],
        scope=[{"kind": "object", "object": N1}],
    )
    refusal = refuse(base_log(), doc)
    assert refusal["errors"][0]["code"] == "scope_violation"


def test_selection_scope_term_resolves_against_pre_state() -> None:
    log = accept(
        base_log(),
        submission(
            PROJECT,
            3,
            [
                command(
                    "selection.define",
                    {
                        "object": SEL,
                        "criteria": {"kind": "explicit", "objects": [N1]},
                    },
                )
            ],
        ),
    )
    # N2 is not a member at the declared head: touching it via the selection
    # scope term is a scope violation (no self-widening).
    doc = submission(
        PROJECT,
        4,
        [
            command(
                "object.set_attrs",
                {"target": N2, "attrs": {"s": {"kind": "string", "value": "x"}}},
            )
        ],
        scope=[{"kind": "selection", "selection": SEL}],
    )
    refusal = refuse(log, doc)
    assert refusal["errors"][0]["code"] == "scope_violation"
    # ... while a pre-state member is in scope.
    ok = submission(
        PROJECT,
        4,
        [
            command(
                "object.set_attrs",
                {"target": N1, "attrs": {"s": {"kind": "string", "value": "x"}}},
            )
        ],
        scope=[{"kind": "selection", "selection": SEL}],
    )
    accept(log, ok)


def test_region_scope_term_covers_contained_geometry() -> None:
    region = {
        "vertices": [
            {"point": {"x": "-1.000", "y": "-1.000"}},
            {"point": {"x": "1.000", "y": "-1.000"}},
            {"point": {"x": "1.000", "y": "1.000"}},
            {"point": {"x": "-1.000", "y": "1.000"}},
        ],
        "closed": True,
    }
    scope = [{"kind": "region", "region": region}]
    # N1 sits at the origin -> in region; accepted.
    accept(
        base_log(),
        submission(
            PROJECT,
            3,
            [
                command(
                    "object.set_attrs",
                    {"target": N1, "attrs": {"s": {"kind": "string", "value": "x"}}},
                )
            ],
            scope=scope,
        ),
    )
    # N2 sits at x=10 -> outside; refused.
    refusal = refuse(
        base_log(),
        submission(
            PROJECT,
            3,
            [
                command(
                    "object.set_attrs",
                    {"target": N2, "attrs": {"s": {"kind": "string", "value": "x"}}},
                )
            ],
            scope=scope,
        ),
    )
    assert refusal["errors"][0]["code"] == "scope_violation"


def test_network_scope_term_covers_members_made_in_the_submission() -> None:
    net = ulid(40)
    log = accept(
        base_log(),
        submission(
            PROJECT, 3, [command("object.create", {"object": net, "type": "civil.network"})]
        ),
    )
    accept(
        log,
        submission(
            PROJECT,
            4,
            [command("object.set_attrs", {"target": N1, "networks": [net]})],
            scope=[{"kind": "network", "network": net}],
        ),
    )


def test_dangling_reference_names_dependents() -> None:
    refusal = refuse(
        edge_log(),
        submission(
            PROJECT,
            4,
            [command("object.remove", {"target": N1})],
            scope=[{"kind": "object", "object": N1}],
        ),
    )
    error = refusal["errors"][0]
    assert error["code"] == "dangling_reference"
    assert error["command"] == 0
    assert error["objects"] == [E1]


def test_refused_submission_leaves_the_log_byte_identical() -> None:
    log = edge_log()
    before = snapshot_bytes(log)
    frozen = copy.deepcopy(log)
    refuse(
        log,
        submission(
            PROJECT,
            4,
            [command("object.remove", {"target": N1})],
            scope=[{"kind": "object", "object": N1}],
        ),
    )
    assert log == frozen
    assert snapshot_bytes(log) == before


def test_selection_group_reference_expands_to_group_members() -> None:
    log = accept(
        base_log(),
        submission(
            PROJECT,
            3,
            [
                command(
                    "selection.define",
                    {
                        "object": SEL,
                        "criteria": {
                            "kind": "explicit",
                            "objects": [N1, N2],
                            "groups": [{"name": "mains", "objects": [N2]}],
                        },
                    },
                )
            ],
        ),
    )
    log = accept(
        log,
        submission(
            PROJECT,
            4,
            [
                command(
                    "object.set_attrs",
                    {
                        "target": f"{SEL}#mains",
                        "attrs": {"s": {"kind": "string", "value": "x"}},
                    },
                )
            ],
        ),
    )
    doc = json.loads(snapshot_bytes(log))
    assert "attrs.s" in doc["objects"][N2]["facts"]
    assert "attrs.s" not in doc["objects"][N1]["facts"]


def test_stamping_completes_the_nine_field_envelope() -> None:
    log = base_log()
    entry = log[0]
    assert set(entry) == {
        "project",
        "seq",
        "batch",
        "author",
        "kind",
        "payload",
        "basis",
        "created_at",
        "spec",
    }
    assert [e["seq"] for e in log] == [1, 2, 3]
    assert len({e["batch"] for e in log}) == 1  # one submission, one batch ULID


# ---------------------------------------------------------------------------
# Fold halting


def test_corrupted_mid_log_command_halts_with_typed_error_not_skip() -> None:
    log = edge_log()
    log[2]["payload"] = {"object": "not-a-ulid", "type": "civil.manhole"}
    with pytest.raises(FoldHalt) as excinfo:
        fold(log)
    assert excinfo.value.seq == 3
    assert excinfo.value.code == "schema_violation"


def test_tampered_author_role_halts() -> None:
    log = base_log()
    log[0]["author"] = "agent:claude"  # project.units is engineer-only
    with pytest.raises(FoldHalt) as excinfo:
        fold(log)
    assert (excinfo.value.seq, excinfo.value.code) == (1, "author_role_violation")


def test_created_at_and_batch_are_ignored_by_fold_and_hash() -> None:
    log = edge_log()
    mutated = copy.deepcopy(log)
    for entry in mutated:
        entry["created_at"] = "1999-01-01T00:00:00Z"
        entry["batch"] = ulid(999)
    assert snapshot_bytes(mutated) == snapshot_bytes(log)
