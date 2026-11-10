"""Edits to a cited base: base.* commands, base selections and the log file.

The base is an immutable file the kernel never opens. These tests pin what the
kernel does know: which bases are cited and current, what edits landed on which
native reference, and who may write them.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given, strategies as st

from cadintent import (
    Accepted,
    FoldHalt,
    Refused,
    diff_bytes,
    empty_diff_bytes,
    fold,
    fold_from,
    log_hash,
    snapshot_bytes,
    submit,
)
from cadintent.canonical import log_bytes, parse_log
from cadintent.snapshot import snapshot_doc
from cadintent.ulid import encode
from conftest import command, create_node, submission, units_command

PROJECT = encode(7)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
AGENT = "agent:drafter"
EXTRACTOR = "extractor:reader"
WHY = [{"kind": "statement", "text": "the engineer asked for this"}]
CLONE = encode(900)
SELECTION = encode(901)


def cite(content_hash: str = HASH_A, name: str = "offsite") -> dict[str, Any]:
    return command(
        "base.cite", {"name": name, "content_hash": content_hash, "format": "dxf"}
    )


def entity(handle: str = "1A", content_hash: str = HASH_A) -> dict[str, Any]:
    return {"kind": "entity", "content_hash": content_hash, "entity": handle}


def clone_target(ulid: str = CLONE) -> dict[str, Any]:
    return {"kind": "clone", "object": ulid}


def selection_target(ref: str = SELECTION) -> dict[str, Any]:
    return {"kind": "selection", "selection": ref}


def edit(kind: str, payload: dict[str, Any], author: str = AGENT) -> dict[str, Any]:
    return command(kind, payload, author=author, basis=WHY)


def set_text(target: dict[str, Any], text: str = "NEW") -> dict[str, Any]:
    return edit("base.set_text", {"target": target, "text": text})


def delete(target: dict[str, Any]) -> dict[str, Any]:
    return edit("base.delete", {"target": target})


def revert(target: dict[str, Any], fields: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"target": target}
    if fields:
        payload["fields"] = fields
    return edit("base.revert", payload)


def clone(ulid: str = CLONE, **fields: Any) -> dict[str, Any]:
    return edit(
        "base.clone",
        {"object": ulid, "source": {"content_hash": HASH_A, "entity": "1A"}, **fields},
    )


def define_selection(
    entities: list[str], groups: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    criteria: dict[str, Any] = {
        "kind": "base",
        "content_hash": HASH_A,
        "where": {"layers": ["GRADE"], "types": ["INSERT"]},
        "entities": entities,
    }
    if groups is not None:
        criteria["groups"] = groups
    return command(
        "selection.define", {"object": SELECTION, "criteria": criteria}, author=AGENT
    )


def land(
    log: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    scope: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    result = submit(log, submission(PROJECT, len(log), commands, scope))
    assert isinstance(result, Accepted), getattr(result, "refusal", None)
    return result.log


def refusal(
    log: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    scope: list[dict[str, Any]] | None = None,
) -> list[tuple[str, Any, str]]:
    result = submit(log, submission(PROJECT, len(log), commands, scope))
    assert isinstance(result, Refused), "expected a refusal"
    return [(e["code"], e["command"], e["path"]) for e in result.refusal["errors"]]


@pytest.fixture
def cited() -> list[dict[str, Any]]:
    return land([], [units_command(), cite()])


def facts(log: list[dict[str, Any]], handle: str = "1A") -> dict[str, Any]:
    return snapshot_doc(fold(log), log_hash(log))["base"]["entities"][HASH_A][handle]["facts"]


# ---------------------------------------------------------------------------
# The log file


def test_log_file_is_one_entry_per_line(cited) -> None:
    raw = log_bytes(cited)
    assert raw.count(b"\n") == len(cited)
    assert parse_log(raw) == cited


def test_an_append_only_adds_lines(cited) -> None:
    longer = land(cited, [set_text(entity())])
    assert log_bytes(longer).startswith(log_bytes(cited))


def test_the_file_format_does_not_change_the_log_hash(cited) -> None:
    assert log_hash(parse_log(log_bytes(cited))) == log_hash(cited)


def test_empty_log_is_an_empty_file() -> None:
    assert log_bytes([]) == b""
    assert parse_log(b"") == []


@pytest.mark.parametrize(
    "raw, line",
    [
        (b'{"seq":1}\nnot json\n', 2),
        (b'{"seq":1}\n\n{"seq":2}\n', 2),
        (b'[{"seq":1}]\n', 1),
    ],
)
def test_a_bad_log_line_is_named(raw: bytes, line: int) -> None:
    with pytest.raises(ValueError, match=f"line {line} "):
        parse_log(raw)


# ---------------------------------------------------------------------------
# Citing a base


def test_no_base_key_until_a_base_is_cited() -> None:
    log = land([], [units_command(), create_node(encode(1))])
    assert "base" not in snapshot_doc(fold(log), log_hash(log))


def test_citation_is_recorded(cited) -> None:
    base = snapshot_doc(fold(cited), log_hash(cited))["base"]
    assert base["citations"] == [
        {"seq": 2, "name": "offsite", "content_hash": HASH_A, "format": "dxf"}
    ]
    assert base["entities"] == {}


def test_a_new_hash_supersedes_the_old_one(cited) -> None:
    log = land(cited, [cite(HASH_B)])
    assert refusal(log, [set_text(entity())]) == [
        ("unknown_reference", 0, "/payload/target/content_hash")
    ]
    land(log, [set_text(entity(content_hash=HASH_B))])


def test_an_older_base_can_be_cited_again(cited) -> None:
    log = land(cited, [cite(HASH_B)])
    log = land(log, [cite(HASH_A)])
    land(log, [set_text(entity())])


def test_cite_and_edit_in_one_submission() -> None:
    land([], [units_command(), cite(), set_text(entity())])


def test_a_hash_belongs_to_one_name(cited) -> None:
    assert refusal(cited, [cite(HASH_A, "other")]) == [
        ("id_collision", 0, "/payload/content_hash")
    ]


def test_the_current_hash_cannot_be_cited_again(cited) -> None:
    assert refusal(cited, [cite(HASH_A)]) == [
        ("id_collision", 0, "/payload/content_hash")
    ]


def test_citing_needs_the_whole_project_term(cited) -> None:
    scope = [{"kind": "base", "content_hash": HASH_A}]
    assert refusal(cited, [cite(HASH_B)], scope) == [("scope_violation", 0, "")]


@pytest.mark.parametrize(
    "author, code",
    [
        ("engineer:someone", None),
        (EXTRACTOR, None),
        (AGENT, "author_role_violation"),
        ("compiler:engine", "author_role_violation"),
    ],
)
def test_who_may_cite(cited, author: str, code: str | None) -> None:
    cmd = cite(HASH_B)
    cmd["author"] = author
    if code is None:
        land(cited, [cmd])
    else:
        assert refusal(cited, [cmd]) == [(code, 0, "/author")]


# ---------------------------------------------------------------------------
# Edits


def test_uncited_base_refuses(cited) -> None:
    assert refusal(cited, [set_text(entity(content_hash=HASH_B))]) == [
        ("unknown_reference", 0, "/payload/target/content_hash")
    ]


def test_every_bad_reference_is_reported_at_once(cited) -> None:
    bad = entity(content_hash=HASH_B)
    assert refusal(cited, [set_text(bad), delete(bad)]) == [
        ("unknown_reference", 0, "/payload/target/content_hash"),
        ("unknown_reference", 1, "/payload/target/content_hash"),
    ]


def test_edits_need_units() -> None:
    log = land([], [cite()])
    assert refusal(log, [set_text(entity())]) == [("missing_declaration", 0, "")]


def test_edits_need_a_basis(cited) -> None:
    cmd = command("base.set_text", {"target": entity(), "text": "X"}, author=AGENT)
    assert refusal(cited, [cmd]) == [("missing_basis", 0, "/basis")]


def test_an_extractor_cannot_edit_the_base(cited) -> None:
    cmd = edit("base.set_text", {"target": entity(), "text": "X"}, author=EXTRACTOR)
    assert refusal(cited, [cmd]) == [("author_role_violation", 0, "/author")]


def test_each_field_keeps_its_latest_value(cited) -> None:
    vertices = [{"point": {"x": "1.23456789", "y": "2"}}]
    transform = {"translate": {"x": "1", "y": "0"}}
    log = land(
        cited,
        [
            edit("base.set_points", {"target": entity(), "vertices": vertices}),
            edit("base.transform", {"target": entity(), "transform": transform}),
            edit("base.set_tags", {"target": entity(), "tags": {"ELEV": "1.00", "NO": "4"}}),
            set_text(entity(), "OLD"),
        ],
    )
    log = land(log, [set_text(entity(), "NEW")])
    log = land(log, [edit("base.set_tags", {"target": entity(), "tags": {"ELEV": "2.00"}})])
    assert facts(log) == {
        "points": {"seq": 3, "value": vertices},
        "transform": {"seq": 4, "value": transform},
        "tags.ELEV": {"seq": 8, "value": "2.00"},
        "tags.NO": {"seq": 5, "value": "4"},
        "text": {"seq": 7, "value": "NEW"},
    }


def test_a_later_transform_replaces_the_earlier_one(cited) -> None:
    first = {"translate": {"x": "1", "y": "0"}}
    second = {"translate": {"x": "2", "y": "0"}, "rotate": "90"}
    log = land(
        cited,
        [
            edit("base.transform", {"target": entity(), "transform": first}),
            edit("base.transform", {"target": entity(), "transform": second}),
        ],
    )
    assert facts(log)["transform"]["value"] == second


# ---------------------------------------------------------------------------
# Delete and revert


def test_a_deleted_entity_cannot_be_edited(cited) -> None:
    log = land(cited, [delete(entity())])
    assert refusal(log, [set_text(entity())]) == [("unknown_reference", 0, "/payload/target")]


def test_deleting_twice_refuses(cited) -> None:
    log = land(cited, [delete(entity())])
    assert refusal(log, [delete(entity())]) == [("unknown_reference", 0, "/payload/target")]


def test_revert_brings_a_deleted_entity_back_with_its_edits(cited) -> None:
    log = land(cited, [set_text(entity()), delete(entity())])
    log = land(log, [revert(entity(), ["deleted"])])
    assert list(facts(log)) == ["text"]
    land(log, [set_text(entity(), "AGAIN")])


def test_full_revert_leaves_no_trace_in_the_snapshot(cited) -> None:
    log = land(cited, [set_text(entity())])
    log = land(log, [revert(entity())])
    assert snapshot_doc(fold(log), log_hash(log))["base"]["entities"] == {}


def test_revert_of_all_tags(cited) -> None:
    tags = {"A": "1", "B": "2"}
    log = land(
        cited,
        [edit("base.set_tags", {"target": entity(), "tags": tags}), set_text(entity())],
    )
    log = land(log, [revert(entity(), ["tags"])])
    assert list(facts(log)) == ["text"]


def test_nothing_to_revert_refuses(cited) -> None:
    assert refusal(cited, [revert(entity())]) == [("unknown_reference", 0, "/payload/target")]


# ---------------------------------------------------------------------------
# Clones


def test_clone_is_an_object_with_its_source(cited) -> None:
    log = land(cited, [clone(text="COPY", transform={"translate": {"x": "5", "y": "0"}})])
    obj = snapshot_doc(fold(log), log_hash(log))["objects"][CLONE]["facts"]
    assert obj["type"]["value"] == "base.clone"
    assert obj["clone_of"]["value"] == {"content_hash": HASH_A, "entity": "1A"}
    assert obj["text"]["value"] == "COPY"


def test_a_clone_can_be_edited_through_its_target(cited) -> None:
    log = land(cited, [clone()])
    log = land(log, [set_text(clone_target(), "EDITED")])
    assert fold(log).objects[CLONE].facts["text"].value == "EDITED"


def test_clone_minted_and_edited_in_one_submission(cited) -> None:
    land(cited, [clone(), set_text(clone_target())])


def test_a_clone_can_outlive_its_deleted_source(cited) -> None:
    land(cited, [delete(entity()), clone()])


def test_clone_id_collision(cited) -> None:
    log = land(cited, [clone()])
    assert refusal(log, [clone()]) == [("id_collision", 0, "/payload/object")]


def test_clone_of_an_uncited_base_refuses(cited) -> None:
    cmd = edit(
        "base.clone",
        {"object": CLONE, "source": {"content_hash": HASH_B, "entity": "1A"}},
    )
    assert refusal(cited, [cmd]) == [("unknown_reference", 0, "/payload/source/content_hash")]


def test_a_clone_target_must_be_a_clone(cited) -> None:
    node = encode(5)
    log = land(cited, [create_node(node)])
    assert refusal(log, [set_text(clone_target(node))]) == [
        ("unknown_reference", 0, "/payload/target/object")
    ]


def test_object_set_attrs_refuses_a_clone(cited) -> None:
    log = land(cited, [clone()])
    cmd = command("object.set_attrs", {"target": CLONE, "attrs": {}})
    assert refusal(log, [cmd]) == [("unknown_reference", 0, "/payload/target")]


@pytest.mark.parametrize(
    "remove",
    [
        lambda: delete(clone_target()),
        lambda: command("object.remove", {"target": CLONE}),
    ],
)
def test_a_clone_can_be_removed(cited, remove) -> None:
    log = land(cited, [clone()])
    log = land(log, [remove()])
    assert CLONE not in fold(log).objects


def test_a_clone_of_a_superseded_base_cannot_be_edited(cited) -> None:
    log = land(cited, [clone()])
    log = land(log, [cite(HASH_B)])
    assert refusal(log, [set_text(clone_target())]) == [
        ("unknown_reference", 0, "/payload/target/object")
    ]
    land(log, [command("object.remove", {"target": CLONE})])


def test_a_clone_cannot_be_reverted(cited) -> None:
    log = land(cited, [clone()])
    assert refusal(log, [revert(clone_target())]) == [
        ("unknown_reference", 0, "/payload/target")
    ]


# ---------------------------------------------------------------------------
# Base selections


def test_an_edit_applies_to_each_selected_entity(cited) -> None:
    log = land(cited, [define_selection(["2B", "1A"])])
    log = land(log, [set_text(selection_target())])
    assert facts(log, "1A")["text"]["value"] == facts(log, "2B")["text"]["value"] == "NEW"


def test_a_group_narrows_the_edit(cited) -> None:
    groups = [{"name": "near", "entities": ["1A"]}]
    log = land(cited, [define_selection(["1A", "2B"], groups)])
    log = land(log, [set_text(selection_target(f"{SELECTION}#near"))])
    assert list(snapshot_doc(fold(log), log_hash(log))["base"]["entities"][HASH_A]) == ["1A"]


def test_the_recorded_list_is_the_derivation(cited) -> None:
    groups = [{"name": "near", "entities": ["1A"]}]
    log = land(cited, [define_selection(["2B", "1A"], groups)])
    entry = snapshot_doc(fold(log), log_hash(log))["objects"][SELECTION]
    assert entry["derivation"] == {
        "seq": 3,
        "entities": ["1A", "2B"],
        "groups": {"near": ["1A"]},
    }


def test_group_members_must_be_selected(cited) -> None:
    groups = [{"name": "near", "entities": ["9Z"]}]
    assert refusal(cited, [define_selection(["1A"], groups)]) == [
        ("unknown_reference", 0, "/payload/criteria/groups/0/entities/0")
    ]


def test_selection_of_an_uncited_base_refuses(cited) -> None:
    cmd = define_selection(["1A"])
    cmd["payload"]["criteria"]["content_hash"] = HASH_B
    assert refusal(cited, [cmd]) == [("unknown_reference", 0, "/payload/criteria/content_hash")]


def test_a_selection_needs_a_predicate(cited) -> None:
    cmd = define_selection(["1A"])
    cmd["payload"]["criteria"]["where"] = {}
    assert refusal(cited, [cmd])[0][0] == "schema_violation"


def test_one_vertex_list_cannot_go_to_a_whole_selection(cited) -> None:
    log = land(cited, [define_selection(["1A", "2B"])])
    payload = {"target": selection_target(), "vertices": [{"point": {"x": "1", "y": "2"}}]}
    assert refusal(log, [edit("base.set_points", payload)]) == [
        ("schema_violation", 0, "/payload/target")
    ]


def test_unknown_group_refuses(cited) -> None:
    log = land(cited, [define_selection(["1A"])])
    assert refusal(log, [set_text(selection_target(f"{SELECTION}#nope"))]) == [
        ("unknown_reference", 0, "/payload/target/selection")
    ]


def test_an_empty_selection_refuses_rather_than_doing_nothing(cited) -> None:
    log = land(cited, [define_selection([])])
    assert refusal(log, [set_text(selection_target())]) == [
        ("unknown_reference", 0, "/payload/target/selection")
    ]


def test_a_selection_on_a_superseded_base_refuses(cited) -> None:
    log = land(cited, [define_selection(["1A"])])
    log = land(log, [cite(HASH_B)])
    assert refusal(log, [set_text(selection_target())]) == [
        ("unknown_reference", 0, "/payload/target/selection")
    ]


def test_an_explicit_selection_is_not_a_base_target(cited) -> None:
    node = encode(5)
    cmd = command(
        "selection.define",
        {"object": SELECTION, "criteria": {"kind": "explicit", "objects": [node]}},
    )
    log = land(cited, [create_node(node), cmd])
    assert refusal(log, [set_text(selection_target())]) == [
        ("unknown_reference", 0, "/payload/target/selection")
    ]


@pytest.mark.parametrize("entities", [["1A"], []])
@pytest.mark.parametrize(
    "cmd",
    [
        command("object.remove", {"target": SELECTION}),
        command("object.set_attrs", {"target": SELECTION, "attrs": {}}),
    ],
)
def test_object_commands_refuse_a_base_selection(cited, entities, cmd) -> None:
    log = land(cited, [define_selection(entities)])
    assert refusal(log, [cmd]) == [("unknown_reference", 0, "/payload/target")]


# ---------------------------------------------------------------------------
# Scope


def test_entity_term_covers_only_that_entity(cited) -> None:
    scope = [{"kind": "base_entity", "content_hash": HASH_A, "entity": "1A"}]
    land(cited, [set_text(entity())], scope)
    assert refusal(cited, [set_text(entity("2B"))], scope) == [
        ("scope_violation", None, "/scope")
    ]


def test_a_scope_violation_names_the_entity(cited) -> None:
    scope = [{"kind": "base_entity", "content_hash": HASH_A, "entity": "1A"}]
    result = submit(cited, submission(PROJECT, len(cited), [set_text(entity("2B"))], scope))
    assert isinstance(result, Refused)
    error = result.refusal["errors"][0]
    assert error["entities"] == [{"content_hash": HASH_A, "entity": "2B"}]
    assert "objects" not in error


def test_base_term_covers_entities_and_clones(cited) -> None:
    scope = [{"kind": "base", "content_hash": HASH_A}]
    land(cited, [set_text(entity()), set_text(entity("2B")), clone()], scope)


def test_selection_term_covers_its_entities(cited) -> None:
    log = land(cited, [define_selection(["1A"])])
    scope = [{"kind": "selection", "selection": SELECTION}]
    land(log, [set_text(selection_target())], scope)
    assert refusal(log, [set_text(entity("2B"))], scope) == [
        ("scope_violation", None, "/scope")
    ]


def test_region_term_does_not_cover_base_entities(cited) -> None:
    corners = [("0", "0"), ("9", "0"), ("9", "9")]
    region = {
        "vertices": [{"point": {"x": x, "y": y}} for x, y in corners],
        "closed": True,
    }
    assert refusal(cited, [set_text(entity())], [{"kind": "region", "region": region}]) == [
        ("scope_violation", None, "/scope")
    ]


def test_scope_term_for_an_uncited_base_refuses(cited) -> None:
    scope = [{"kind": "base", "content_hash": HASH_B}]
    assert ("unknown_reference", None, "/scope/0/content_hash") in refusal(
        cited, [set_text(entity())], scope
    )


def test_scope_term_may_name_a_base_cited_in_the_submission() -> None:
    log = land([], [units_command()])
    scope = [{"kind": "project"}, {"kind": "base", "content_hash": HASH_A}]
    land(log, [cite(), set_text(entity())], scope)


# ---------------------------------------------------------------------------
# Diff, fold and resume


def snapshots(*logs: list[dict[str, Any]]) -> list[bytes]:
    return [snapshot_bytes(log) for log in logs]


def test_diff_reports_a_first_edit_as_created(cited) -> None:
    after = land(cited, [set_text(entity())])
    diff = json.loads(diff_bytes(*snapshots(cited, after)))
    assert list(diff["base"]["created"]) == [f"{HASH_A}#1A"]
    assert diff["base"]["citations"] is None


def test_diff_reports_a_later_edit_field_by_field(cited) -> None:
    before = land(cited, [set_text(entity(), "OLD")])
    after = land(before, [set_text(entity(), "NEW")])
    diff = json.loads(diff_bytes(*snapshots(before, after)))
    change = diff["base"]["modified"][f"{HASH_A}#1A"]["text"]
    assert (change["before"]["value"], change["after"]["value"]) == ("OLD", "NEW")
    assert change["change"] == "value"


def test_diff_reports_a_full_revert_as_removed(cited) -> None:
    before = land(cited, [set_text(entity())])
    after = land(before, [revert(entity())])
    diff = json.loads(diff_bytes(*snapshots(before, after)))
    assert list(diff["base"]["removed"]) == [f"{HASH_A}#1A"]


def test_diff_reports_a_new_citation(cited) -> None:
    after = land(cited, [cite(HASH_B)])
    diff = json.loads(diff_bytes(*snapshots(cited, after)))
    assert diff["base"]["citations"]["change"] == "value"


def test_no_base_section_when_nothing_about_the_base_changed(cited) -> None:
    after = land(cited, [create_node(encode(5))])
    assert "base" not in json.loads(diff_bytes(*snapshots(cited, after)))


def test_diff_of_a_snapshot_with_itself_is_empty(cited) -> None:
    log = land(cited, [set_text(entity())])
    snapshot = snapshot_bytes(log)
    assert diff_bytes(snapshot, snapshot) == empty_diff_bytes()


def test_a_tampered_log_halts_the_fold(cited) -> None:
    log = land(cited, [set_text(entity())])
    log[-1]["payload"]["target"]["content_hash"] = HASH_B
    with pytest.raises(FoldHalt) as halted:
        fold(log)
    assert halted.value.code == "unknown_reference"


@st.composite
def base_logs(draw) -> list[dict[str, Any]]:
    log = land([], [units_command(), cite()])
    edited: set[str] = set()
    next_clone = 1000
    for _ in range(draw(st.integers(min_value=1, max_value=6))):
        handle = draw(st.sampled_from(["1A", "2B", "3C"]))
        target = entity(handle)
        choice = draw(st.sampled_from(["text", "tags", "points", "clone", "revert"]))
        if choice == "text":
            commands = [set_text(target, draw(st.text(max_size=4)))]
        elif choice == "tags":
            commands = [edit("base.set_tags", {"target": target, "tags": {"T": "1"}})]
        elif choice == "points":
            point = {"x": str(draw(st.integers(0, 9))), "y": "0"}
            commands = [edit("base.set_points", {"target": target, "vertices": [{"point": point}]})]
        elif choice == "clone":
            commands = [clone(encode(next_clone))]
            next_clone += 1
        elif handle in edited:
            commands = [revert(target)]
            edited.discard(handle)
            log = land(log, commands)
            continue
        else:
            continue
        log = land(log, commands)
        if choice != "clone":
            edited.add(handle)
    return log


@given(base_logs())
def test_replay_is_deterministic(log: list[dict[str, Any]]) -> None:
    assert snapshot_bytes(log) == snapshot_bytes(json.loads(json.dumps(log)))


@given(base_logs(), st.integers(min_value=2, max_value=8))
def test_resume_equals_full_replay(log: list[dict[str, Any]], cut: int) -> None:
    cut = min(cut, len(log))
    assert fold_from(snapshot_bytes(log[:cut]), log[cut:]) == snapshot_bytes(log)
