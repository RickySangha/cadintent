"""Run the conformance seed cases against the in-process kernel.

Under plain pytest a could-not-run case is a visible skip (never a silent
pass); the exit-code contract (0/1/2, empty-suite-fails) is exercised through
the programmatic runner below.
"""

from __future__ import annotations

import pytest

from cadintent_conformance.adapter import InProcessKernel
from cadintent_conformance.runner import (
    COULD_NOT_RUN,
    DEFAULT_CASES_DIR,
    PASS,
    Report,
    CaseResult,
    case_id,
    compare_refusal,
    discover,
    run_case,
    run_suite,
)

IMPL = InProcessKernel()
CASE_DIRS = discover()


def test_suite_is_not_empty() -> None:
    # Visible vacuity: an empty suite must never report green.
    assert CASE_DIRS, f"no conformance cases discovered under {DEFAULT_CASES_DIR}"


def test_the_ten_seed_cases_exist() -> None:
    assert {case_id(d) for d in CASE_DIRS} == {
        "envelope/001_minimal_accept",
        "envelope/002_stale_head",
        "envelope/003_author_role_violation",
        "envelope/004_all_errors_at_once",
        "envelope/005_batch_atomicity",
        "topology/001_dangling_reference",
        "topology/002_rewire_atomically",
        "fold/001_determinism",
        "fold/002_resume_equivalence",
        "diff/001_canonical_shape",
    }


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=case_id)
def test_case(case_dir) -> None:
    result = run_case(case_dir, IMPL)
    assert result.status == PASS, f"{result.status}: {result.detail}"


def test_full_seed_suite_is_green() -> None:
    # Build #33 landed fold_from + diff: every seed case runs and passes.
    report = run_suite(IMPL)
    statuses = {r.case_id: r.status for r in report.results}
    assert all(status == PASS for status in statuses.values()), statuses
    assert report.counts()[COULD_NOT_RUN] == 0
    assert report.exit_code == 0


def test_exit_code_contract_empty_suite_fails(tmp_path) -> None:
    report = run_suite(IMPL, cases_dir=tmp_path)
    assert report.results == []
    assert report.exit_code == 1


def test_exit_code_contract_failure_dominates() -> None:
    report = Report(
        results=[
            CaseResult("a/1", PASS),
            CaseResult("a/2", "fail", "boom"),
            CaseResult("a/3", COULD_NOT_RUN, "no capability"),
        ]
    )
    assert report.exit_code == 1


def test_exit_code_contract_all_pass_is_zero() -> None:
    assert Report(results=[CaseResult("a/1", PASS)]).exit_code == 0


def test_not_selected_cases_are_reported_not_run() -> None:
    report = run_suite(IMPL, select="envelope/001")
    by_status = {r.case_id: r.status for r in report.results}
    assert by_status["envelope/001_minimal_accept"] == PASS
    assert by_status["fold/001_determinism"] == "not-selected"


def test_refusal_comparison_is_triples_not_messages() -> None:
    actual = {
        "errors": [
            {
                "code": "stale_head",
                "command": None,
                "path": "/head",
                "message": "any wording at all",
            }
        ]
    }
    assert compare_refusal(
        [{"code": "stale_head", "command": None, "path": "/head"}], actual
    ) is None
    assert compare_refusal(
        [{"code": "stale_head", "command": 0, "path": "/head"}], actual
    ) is not None


def test_refusal_comparison_enforces_dangling_object_sets() -> None:
    triple = {"code": "dangling_reference", "command": 0, "path": "/payload/target"}
    actual = {"errors": [{**triple, "message": "m", "objects": ["0" + "A" * 25]}]}
    assert compare_refusal([{**triple, "objects": ["0" + "A" * 25]}], actual) is None
    assert compare_refusal([{**triple, "objects": ["0" + "B" * 25]}], actual) is not None
