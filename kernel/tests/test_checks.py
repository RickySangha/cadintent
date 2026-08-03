"""The civil pack's five v0 checks, the rule registry, and rule commands.

Covers #21 (as amended: five checks, no invert_continuity), #28 (registry
resolution, verification semantics, rule.define / rule.verify), and the
finding-document contract: visible not_run, visible vacuity, and
unverified-consistency never reading as compliance.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from cadintent import (
    Accepted,
    RegistryError,
    RegistryStore,
    Refused,
    artifact_hash,
    fold,
    run_checks,
    submit,
)
from cadintent.checks import derived_length
from cadintent.spec import schema_errors
from cadintent.ulid import encode
from conftest import command, submission, units_command

PROJECT = encode(7)
MH1, MH2, PIPE, NET = encode(101), encode(102), encode(103), encode(104)


def _elev(value: str) -> dict[str, Any]:
    return {
        "kind": "elevation",
        "value": {
            "value": value,
            "kind": "surveyed",
            "sources": [{"kind": "statement", "text": "survey"}],
        },
    }


def _network_log(
    *,
    invert_a: str = "100.00",
    invert_b: str = "99.90",
    flow: str = "a_to_b",
    material: str = "pvc",
    rim1: str | None = "102.00",
    sump1: str | None = "99.50",
    extra_commands: list[dict[str, Any]] | None = None,
    setup_commands: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """A small sanitary run: MH1 --PIPE(10 m)--> MH2."""
    mh1_attrs: dict[str, Any] = {}
    if rim1 is not None:
        mh1_attrs["rim_elevation"] = _elev(rim1)
    if sump1 is not None:
        mh1_attrs["sump_elevation"] = _elev(sump1)
    commands = list(setup_commands or [])
    commands += [
        command(
            "object.create",
            {
                "object": NET,
                "type": "civil.network",
                "attrs": {"system": {"kind": "string", "value": "sanitary"}},
            },
        ),
        command(
            "object.create",
            {
                "object": MH1,
                "type": "civil.manhole",
                "geometry": {"kind": "point", "point": {"x": "0.000", "y": "0.000"}},
                **({"attrs": mh1_attrs} if mh1_attrs else {}),
            },
        ),
        command(
            "object.create",
            {
                "object": MH2,
                "type": "civil.manhole",
                "geometry": {"kind": "point", "point": {"x": "10.000", "y": "0.000"}},
                "attrs": {
                    "rim_elevation": _elev("101.80"),
                    "sump_elevation": _elev("99.30"),
                },
            },
        ),
        command(
            "object.create",
            {
                "object": PIPE,
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
                    "invert_a": _elev(invert_a),
                    "invert_b": _elev(invert_b),
                    "shape": {"kind": "string", "value": "circular"},
                    "diameter": {"kind": "quantity", "value": "0.250"},
                    "material": {"kind": "string", "value": material},
                    "flow_direction": {"kind": "string", "value": flow},
                },
            },
        ),
    ]
    commands += extra_commands or []
    result = submit([], submission(PROJECT, 0, [units_command()]))
    assert isinstance(result, Accepted)
    result = submit(result.log, submission(PROJECT, 1, commands))
    assert isinstance(result, Accepted), result
    return result.log


def _results(log: list[dict[str, Any]], store: RegistryStore | None = None):
    run = run_checks(fold(log), store)
    assert not schema_errors("finding.json#/$defs/CheckRun", run), run
    return {r["check"]: r for r in run["results"]}


def _min_slope_registry(
    minimum: str | None = "0.004", verification: str = "verified"
) -> tuple[dict[str, Any], RegistryStore]:
    entry: dict[str, Any] = {
        "name": "civil.min_slope",
        "params": {"type": "object"},
        "result": {"quantity": "ratio", "quantum": "0.000000001"},
        "semantics": "Minimum design slope for gravity mains.",
        "verification": verification,
        "provenance": {"author": "engineer:ricky"},
    }
    if minimum is not None:
        entry["value"] = minimum
    artifact = {"id": "metro-rules", "version": "1.0.0", "entries": [entry]}
    store = RegistryStore()
    store.add(artifact)
    return artifact, store


def _import_registry_command(artifact: dict[str, Any]) -> dict[str, Any]:
    return command(
        "registry.import",
        {
            "registry": {
                "id": artifact["id"],
                "version": artifact["version"],
                "content_hash": artifact_hash(artifact),
            }
        },
    )


# ---------------------------------------------------------------------------
# The check list itself


def test_the_five_checks_and_only_the_five() -> None:
    # invert_continuity is removed per the #21 amendment (drop standards are
    # municipal rule data, not spec comparisons).
    results = _results(_network_log())
    assert set(results) == {
        "civil.flow_vs_invert",
        "civil.min_slope",
        "civil.rim_sump_envelope",
        "civil.vocabulary",
        "civil.completeness",
    }


# ---------------------------------------------------------------------------
# flow_vs_invert


def test_flow_vs_invert_agreement_is_a_real_pass() -> None:
    result = _results(_network_log())["civil.flow_vs_invert"]
    assert result["status"] == "pass"
    assert result["evaluated"] == 1
    assert result["vacuous"] is False


def test_flow_vs_invert_disagreement_carries_both_values() -> None:
    result = _results(_network_log(flow="b_to_a"))["civil.flow_vs_invert"]
    assert result["status"] == "findings"
    (finding,) = result["findings"]
    assert finding["subjects"] == [PIPE]
    assert finding["values"]["declared"] == "b_to_a"
    assert finding["values"]["derived"] == "a_to_b"
    assert finding["values"]["invert_a"] == "100.00"
    assert finding["values"]["invert_b"] == "99.90"
    assert finding["judged_against"]["kind"] == "schema"


def test_flow_vs_invert_flat_grade_is_flagged_never_silently_picked() -> None:
    result = _results(_network_log(invert_b="100.00"))["civil.flow_vs_invert"]
    assert result["status"] == "findings"
    (finding,) = result["findings"]
    assert finding["values"]["derived"] == "flat"
    assert finding["values"]["declared"] == "a_to_b"


def test_flow_vs_invert_vacuous_pass_is_visible() -> None:
    # A model with no conduits judges nothing — and says so.
    result = _results(_empty_project())["civil.flow_vs_invert"]
    assert result["status"] == "pass"
    assert result["evaluated"] == 0
    assert result["vacuous"] is True


def _empty_project() -> list[dict[str, Any]]:
    result = submit([], submission(PROJECT, 0, [units_command()]))
    assert isinstance(result, Accepted)
    return result.log


# ---------------------------------------------------------------------------
# min_slope


def test_min_slope_without_declared_minima_is_visibly_not_run() -> None:
    # Acceptance criterion: an empty rule registry demonstrates visible
    # not_run — never a vacuous pass, never a default minimum.
    result = _results(_network_log(), RegistryStore())["civil.min_slope"]
    assert result["status"] == "not_run"
    assert result["evaluated"] == 0
    assert result["vacuous"] is True
    assert "no default minima" in result["reason"]
    assert result["findings"] == []


def test_min_slope_without_any_store_is_visibly_not_run() -> None:
    result = _results(_network_log())["civil.min_slope"]
    assert result["status"] == "not_run"


def test_min_slope_below_declared_minimum_is_a_finding_with_rule_citation() -> None:
    # 0.10 m over 10 m = 0.01 slope; minimum 0.02 -> finding.
    artifact, store = _min_slope_registry("0.020000000")
    log = _network_log(setup_commands=[_import_registry_command(artifact)])
    result = _results(log, store)["civil.min_slope"]
    assert result["status"] == "findings"
    (finding,) = result["findings"]
    assert finding["subjects"] == [PIPE]
    assert finding["values"]["slope"] == "0.010000000"
    assert finding["values"]["minimum"] == "0.020000000"
    judged = finding["judged_against"]
    assert judged == {
        "kind": "rule",
        "registry": "metro-rules",
        "version": "1.0.0",
        "name": "civil.min_slope",
        "params": {"material": "pvc", "diameter": "0.250"},
        "verification": "verified",
    }


def test_min_slope_meeting_a_verified_minimum_is_a_pass() -> None:
    artifact, store = _min_slope_registry("0.004")
    log = _network_log(setup_commands=[_import_registry_command(artifact)])
    result = _results(log, store)["civil.min_slope"]
    assert result["status"] == "pass"
    assert result["evaluated"] == 1
    assert result["consulted"][0]["verification"] == "verified"


def test_min_slope_against_unverified_entry_never_reads_as_compliance() -> None:
    artifact, store = _min_slope_registry("0.004", verification="unverified")
    log = _network_log(setup_commands=[_import_registry_command(artifact)])
    result = _results(log, store)["civil.min_slope"]
    assert result["status"] == "unverified_consistent"
    assert result["status"] != "pass"


def test_min_slope_entry_without_value_is_a_finding_never_a_default() -> None:
    artifact, store = _min_slope_registry(minimum=None)
    log = _network_log(setup_commands=[_import_registry_command(artifact)])
    result = _results(log, store)["civil.min_slope"]
    assert result["status"] == "findings"
    (finding,) = result["findings"]
    assert finding["values"]["minimum"] is None


def test_min_slope_registry_hash_mismatch_is_a_typed_error() -> None:
    artifact, _ = _min_slope_registry()
    log = _network_log(setup_commands=[_import_registry_command(artifact)])
    tampered = dict(artifact, entries=[])
    store = RegistryStore()
    store.add(dict(tampered, id="metro-rules", version="1.0.0"))
    with pytest.raises(RegistryError) as excinfo:
        store.entries_named(fold(log), "civil.min_slope")
    assert excinfo.value.code == "registry_hash_mismatch"


# ---------------------------------------------------------------------------
# rim_sump_envelope


def test_rim_sump_envelope_within_envelope_passes() -> None:
    result = _results(_network_log())["civil.rim_sump_envelope"]
    assert result["status"] == "pass"
    assert result["evaluated"] == 2  # both ends judged


def test_rim_sump_envelope_invert_below_sump_is_a_finding() -> None:
    result = _results(_network_log(invert_a="99.00"))["civil.rim_sump_envelope"]
    findings = [f for f in result["findings"] if f["values"]["end"] == "a"]
    (finding,) = findings
    assert finding["subjects"] == [PIPE, MH1]
    assert finding["values"]["invert"] == "99.00"
    assert finding["values"]["sump_elevation"] == "99.50"


def test_rim_sump_envelope_invert_above_rim_is_a_finding() -> None:
    result = _results(_network_log(invert_a="102.50"))["civil.rim_sump_envelope"]
    findings = [f for f in result["findings"] if f["values"]["end"] == "a"]
    (finding,) = findings
    assert finding["values"]["rim_elevation"] == "102.00"


# ---------------------------------------------------------------------------
# vocabulary


def test_vocabulary_off_list_material_is_a_finding_never_a_refusal() -> None:
    # The submission with the unknown material was *accepted* by the kernel
    # (_network_log asserts acceptance); the check reports a finding.
    log = _network_log(material="unobtainium")
    result = _results(log)["civil.vocabulary"]
    assert result["status"] == "findings"
    (finding,) = result["findings"]
    assert finding["subjects"] == [PIPE]
    assert finding["values"]["material"] == "unobtainium"
    assert finding["judged_against"] == {
        "kind": "vocabulary",
        "vocabulary": "civil.material",
        "version": "0.1.0",
    }


def test_vocabulary_on_list_material_passes() -> None:
    result = _results(_network_log(material="concrete"))["civil.vocabulary"]
    assert result["status"] == "pass"


# ---------------------------------------------------------------------------
# completeness


def test_completeness_missing_rim_is_a_finding() -> None:
    result = _results(_network_log(rim1=None, sump1=None))["civil.completeness"]
    assert result["status"] == "findings"
    by_subject = {f["subjects"][0]: f for f in result["findings"]}
    assert MH1 in by_subject
    missing = by_subject[MH1]["values"]["missing"]
    assert "attrs.rim_elevation" in missing
    assert "attrs.sump_elevation" in missing


def test_completeness_shape_drives_expected_size_facts() -> None:
    # A box conduit without span/rise is incomplete; diameter is not expected.
    extra = [
        command(
            "object.set_attrs",
            {"target": PIPE, "attrs": {"shape": {"kind": "string", "value": "box"}}},
        )
    ]
    result = _results(_network_log(extra_commands=extra))["civil.completeness"]
    by_subject = {f["subjects"][0]: f for f in result["findings"]}
    assert set(by_subject[PIPE]["values"]["missing"]) == {"attrs.span", "attrs.rise"}


def test_completeness_full_network_passes_non_vacuously() -> None:
    result = _results(_network_log())["civil.completeness"]
    assert result["status"] == "pass"
    assert result["evaluated"] == 4  # network, two manholes, conduit
    assert result["vacuous"] is False


# ---------------------------------------------------------------------------
# rule.define / rule.verify (#28 statement -> registry entry path)


def _define_rule_command(author: str = "agent:claude") -> dict[str, Any]:
    return command(
        "rule.define",
        {
            "name": "civil.min_slope",
            "params": {"type": "object"},
            "result": {"quantity": "ratio", "quantum": "0.000000001"},
            "semantics": "PVC mains at 0.40% minimum, per Ricky.",
            "value": "0.004",
        },
        author=author,
        basis=[{"kind": "statement", "text": "lay PVC mains at 0.40% minimum"}],
    )


def test_rule_define_lands_unverified_and_backs_min_slope_visibly() -> None:
    log = _network_log(setup_commands=[_define_rule_command()])
    model = fold(log)
    (rule,) = model.rules
    assert rule["verification"] == "unverified"
    assert rule["seq"] == 2  # first command after project.units
    result = _results(log, RegistryStore())["civil.min_slope"]
    assert result["status"] == "unverified_consistent"  # taught but unconfirmed
    assert result["consulted"] == [
        {
            "kind": "rule",
            "registry": "project",
            "version": "2",
            "name": "civil.min_slope",
            "verification": "unverified",
        }
    ]


def test_engineer_rule_verify_flips_to_verified_and_backs_a_pass() -> None:
    verify = command("rule.verify", {"name": "civil.min_slope"})
    log = _network_log(setup_commands=[_define_rule_command(), verify])
    model = fold(log)
    (rule,) = model.rules
    assert rule["verification"] == "verified"
    assert rule["verified_by"] == 3
    result = _results(log, RegistryStore())["civil.min_slope"]
    assert result["status"] == "pass"


def test_rule_verify_is_engineer_only() -> None:
    log = _empty_project()
    verify = command("rule.verify", {"name": "civil.min_slope"}, author="agent:claude")
    result = submit(
        log, submission(PROJECT, 1, [_define_rule_command(), verify])
    )
    assert isinstance(result, Refused)
    assert {(e["code"], e["command"]) for e in result.refusal["errors"]} == {
        ("author_role_violation", 1)
    }


def test_rule_verify_of_unknown_name_refuses() -> None:
    log = _empty_project()
    verify = command("rule.verify", {"name": "civil.min_slope"})
    result = submit(log, submission(PROJECT, 1, [verify]))
    assert isinstance(result, Refused)
    assert result.refusal["errors"][0]["code"] == "unknown_reference"


def test_rule_define_requires_basis() -> None:
    log = _empty_project()
    bare = command(
        "rule.define",
        {
            "name": "civil.min_slope",
            "params": {"type": "object"},
            "result": {"quantity": "ratio", "quantum": "0.000000001"},
            "semantics": "unfounded",
        },
    )
    result = submit(log, submission(PROJECT, 1, [bare]))
    assert isinstance(result, Refused)
    assert result.refusal["errors"][0]["code"] == "missing_basis"


def test_project_local_rule_citation_resolves_by_defining_seq() -> None:
    cite = command(
        "object.create",
        {
            "object": MH1,
            "type": "civil.manhole",
            "geometry": {"kind": "point", "point": {"x": "0.000", "y": "0.000"}},
        },
        basis=[
            {
                "kind": "rule",
                "registry": "project",
                "version": "2",
                "name": "civil.min_slope",
                "params": {},
            }
        ],
    )
    result = submit(
        _empty_project(), submission(PROJECT, 1, [_define_rule_command(), cite])
    )
    assert isinstance(result, Accepted)

    wrong_seq = json.loads(json.dumps(cite))
    wrong_seq["basis"][0]["version"] = "9"
    result = submit(
        _empty_project(), submission(PROJECT, 1, [_define_rule_command(), wrong_seq])
    )
    assert isinstance(result, Refused)
    assert result.refusal["errors"][0]["code"] == "unknown_reference"


def test_registry_store_resolves_project_rules() -> None:
    log = _network_log(setup_commands=[_define_rule_command()])
    store = RegistryStore()
    resolved = store.resolve(fold(log), "project", "2", "civil.min_slope")
    assert resolved.entry["value"] == "0.004"
    with pytest.raises(RegistryError):
        store.resolve(fold(log), "project", "3", "civil.min_slope")


# ---------------------------------------------------------------------------
# derived length (never stored)


def test_derived_length_straight_and_arc() -> None:
    straight = {
        "kind": "polyline",
        "vertices": [
            {"point": {"x": "0.000", "y": "0.000"}},
            {"point": {"x": "3.000", "y": "4.000"}},
        ],
        "closed": False,
    }
    assert derived_length(straight) == pytest.approx(5.0)
    # bulge 1 = semicircle: arc length = pi * chord / 2
    semicircle = {
        "kind": "arc",
        "start": {"x": "0.000", "y": "0.000"},
        "end": {"x": "10.000", "y": "0.000"},
        "bulge": "1",
    }
    assert derived_length(semicircle) == pytest.approx(10.0 * 3.141592653589793 / 2)
    assert derived_length({"kind": "point", "point": {"x": "0", "y": "0"}}) is None
