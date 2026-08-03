"""Conformance runner (#23): case discovery, evaluation, report, exit codes.

Case = a directory holding ``case.json`` (metadata + inputs: a setup log and
ordered submissions, each declaring expect accept/refuse) plus expected files:

- ``expected.snapshot.json`` — canonical snapshot bytes, compared byte-for-byte
  against the implementation's fold of the final log;
- ``expected.refusal.json`` — ``{"submission": i, "errors": [{code, command,
  path[, objects]}]}``; compared as the canonically sorted set of (code,
  command, path) triples, plus the referring-object ULID set for
  dangling_reference errors. Messages are outside the contract;
- ``expected.diff.json`` — canonical diff bytes (cases carrying a ``diff``
  input; needs the "diff" capability).

Terminal states per case: pass / fail / could-not-run / not-selected.
Exit codes: 0 all-pass, 1 any failure (an empty suite is a failure),
2 any could-not-run. A could-not-run is never a pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .protocol import Implementation, NotSupported

PASS = "pass"
FAIL = "fail"
COULD_NOT_RUN = "could-not-run"
NOT_SELECTED = "not-selected"

DEFAULT_CASES_DIR = Path(__file__).resolve().parents[2] / "cases"


@dataclass
class CaseResult:
    case_id: str
    status: str
    detail: str = ""


@dataclass
class Report:
    results: list[CaseResult] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {PASS: 0, FAIL: 0, COULD_NOT_RUN: 0, NOT_SELECTED: 0}
        for result in self.results:
            counts[result.status] += 1
        return counts

    @property
    def exit_code(self) -> int:
        counts = self.counts()
        ran = counts[PASS] + counts[FAIL] + counts[COULD_NOT_RUN]
        if counts[FAIL] or ran == 0:
            return 1  # an empty suite must never report green
        if counts[COULD_NOT_RUN]:
            return 2
        return 0


def discover(cases_dir: Path = DEFAULT_CASES_DIR) -> list[Path]:
    return sorted(
        (p.parent for p in cases_dir.glob("*/*/case.json")),
        key=lambda p: (p.parent.name, p.name),
    )


def case_id(case_dir: Path) -> str:
    return f"{case_dir.parent.name}/{case_dir.name}"


# ---------------------------------------------------------------------------
# Refusal comparison


def _triples(errors: list[dict[str, Any]]) -> set[tuple[str, Any, str]]:
    return {(e["code"], e["command"], e["path"]) for e in errors}


def _dangling_objects(
    errors: list[dict[str, Any]],
) -> dict[tuple[str, Any, str], frozenset[str]]:
    return {
        (e["code"], e["command"], e["path"]): frozenset(e.get("objects", []))
        for e in errors
        if e["code"] == "dangling_reference"
    }


def compare_refusal(
    expected_errors: list[dict[str, Any]], actual: dict[str, Any]
) -> str | None:
    """None when conformant, else a failure detail."""
    expected_set = _triples(expected_errors)
    actual_set = _triples(actual["errors"])
    if expected_set != actual_set:
        return (
            "refusal triples differ; "
            f"missing={sorted(expected_set - actual_set)} "
            f"unexpected={sorted(actual_set - expected_set)}"
        )
    expected_dangling = _dangling_objects(expected_errors)
    actual_dangling = _dangling_objects(actual["errors"])
    if expected_dangling != actual_dangling:
        return (
            "dangling_reference referring-object sets differ; "
            f"expected={expected_dangling} actual={actual_dangling}"
        )
    return None


# ---------------------------------------------------------------------------
# Case evaluation


def _prefix(log: list[dict[str, Any]], head: int) -> list[dict[str, Any]]:
    return [entry for entry in log if entry["seq"] <= head]


def run_case(case_dir: Path, impl: Implementation) -> CaseResult:
    cid = case_id(case_dir)
    try:
        case = json.loads((case_dir / "case.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return CaseResult(cid, FAIL, f"unreadable case.json: {exc}")

    if case["spec"] not in impl.spec_versions:
        return CaseResult(
            cid, COULD_NOT_RUN, f"implementation does not support spec {case['spec']}"
        )
    for required in case.get("requires", []):
        if required not in impl.capabilities:
            return CaseResult(
                cid, COULD_NOT_RUN, f"implementation lacks capability {required!r}"
            )

    try:
        return _evaluate(case_dir, cid, case, impl)
    except NotSupported as exc:
        return CaseResult(cid, COULD_NOT_RUN, str(exc))


def _evaluate(
    case_dir: Path, cid: str, case: dict[str, Any], impl: Implementation
) -> CaseResult:
    expected_refusal = None
    refusal_path = case_dir / "expected.refusal.json"
    if refusal_path.exists():
        expected_refusal = json.loads(refusal_path.read_text())

    log: list[dict[str, Any]] = case.get("setup", [])
    for index, entry in enumerate(case.get("submissions", [])):
        expect_accept = entry["expect"] == "accept"
        pre = impl.fold(log)
        outcome = impl.submit(log, entry["submission"])
        if outcome.accepted != expect_accept:
            got = "accepted" if outcome.accepted else f"refused: {outcome.refusal}"
            return CaseResult(
                cid, FAIL, f"submission {index}: expected {entry['expect']}, got {got}"
            )
        if outcome.accepted:
            log = outcome.log
        else:
            post = impl.fold(log)
            if post != pre:
                return CaseResult(
                    cid,
                    FAIL,
                    f"submission {index}: refusal was not atomic — the foldable "
                    "state changed",
                )
            if expected_refusal is not None and expected_refusal["submission"] == index:
                detail = compare_refusal(expected_refusal["errors"], outcome.refusal)
                if detail is not None:
                    return CaseResult(cid, FAIL, f"submission {index}: {detail}")

    snapshot_path = case_dir / "expected.snapshot.json"
    if case.get("expects_snapshot") and not snapshot_path.exists():
        return CaseResult(
            cid,
            FAIL,
            "case expects a snapshot but expected.snapshot.json is missing "
            "(regenerate via --rebaseline and review the bytes)",
        )
    if snapshot_path.exists():
        first = impl.fold(log)
        second = impl.fold(log)
        if first != second:
            return CaseResult(cid, FAIL, "fold is not deterministic across runs")
        expected = snapshot_path.read_bytes()
        if first != expected:
            return CaseResult(
                cid,
                FAIL,
                "snapshot bytes differ from expected.snapshot.json\n"
                f"expected: {expected!r}\nactual:   {first!r}",
            )

    resume = case.get("resume")
    if resume is not None:
        prefix_head = resume["prefix_head"]
        prefix_log = _prefix(log, prefix_head)
        rest = [entry for entry in log if entry["seq"] > prefix_head]
        resumed = impl.fold_from(impl.fold(prefix_log), rest)
        full = impl.fold(log)
        if resumed != full:
            return CaseResult(
                cid, FAIL, "fold_from(snapshot, rest) differs from full replay"
            )

    diff_spec = case.get("diff")
    if diff_spec is not None:
        base = impl.fold(_prefix(log, diff_spec["base_head"]))
        full = impl.fold(log)
        actual_diff = impl.diff(base, full)
        diff_path = case_dir / "expected.diff.json"
        if not diff_path.exists():
            return CaseResult(cid, FAIL, "case exercises diff but has no expected.diff.json")
        if actual_diff != diff_path.read_bytes():
            return CaseResult(cid, FAIL, "diff bytes differ from expected.diff.json")
        identity_path = case_dir / "expected.diff.identity.json"
        if identity_path.exists():
            if impl.diff(full, full) != identity_path.read_bytes():
                return CaseResult(
                    cid, FAIL, "diff(S, S) differs from the canonical empty document"
                )

    return CaseResult(cid, PASS)


# ---------------------------------------------------------------------------
# Suite


def run_suite(
    impl: Implementation,
    cases_dir: Path = DEFAULT_CASES_DIR,
    select: str | None = None,
) -> Report:
    report = Report()
    for case_dir in discover(cases_dir):
        cid = case_id(case_dir)
        if select is not None and select not in cid:
            report.results.append(CaseResult(cid, NOT_SELECTED))
            continue
        report.results.append(run_case(case_dir, impl))
    return report


# ---------------------------------------------------------------------------
# Rebaseline (explicit only; prints the full byte diff — no auto-update path)


def rebaseline_case(case_dir: Path, impl: Implementation) -> list[str]:
    """Regenerate this case's expected files from the implementation.

    Returns human-readable change notes (empty = no change)."""
    notes: list[str] = []
    case = json.loads((case_dir / "case.json").read_text())
    for required in case.get("requires", []):
        if required not in impl.capabilities:
            return [f"skipped: implementation lacks capability {required!r}"]

    log: list[dict[str, Any]] = case.get("setup", [])
    for index, entry in enumerate(case.get("submissions", [])):
        outcome = impl.submit(log, entry["submission"])
        if outcome.accepted != (entry["expect"] == "accept"):
            return [
                f"cannot rebaseline: submission {index} expected "
                f"{entry['expect']}, implementation disagrees "
                f"({outcome.refusal if not outcome.accepted else 'accepted'})"
            ]
        if outcome.accepted:
            log = outcome.log
        else:
            refusal_path = case_dir / "expected.refusal.json"
            if refusal_path.exists():
                current = json.loads(refusal_path.read_text())
                if current["submission"] == index:
                    regenerated = {
                        "submission": index,
                        "errors": [
                            {
                                "code": e["code"],
                                "command": e["command"],
                                "path": e["path"],
                                **(
                                    {"objects": e["objects"]}
                                    if e["code"] == "dangling_reference"
                                    else {}
                                ),
                            }
                            for e in outcome.refusal["errors"]
                        ],
                    }
                    new_bytes = (
                        json.dumps(regenerated, indent=2, sort_keys=False) + "\n"
                    ).encode()
                    if new_bytes != refusal_path.read_bytes():
                        notes.append(
                            f"expected.refusal.json changed:\n"
                            f"  old: {refusal_path.read_bytes()!r}\n"
                            f"  new: {new_bytes!r}"
                        )
                        refusal_path.write_bytes(new_bytes)

    snapshot_path = case_dir / "expected.snapshot.json"
    if snapshot_path.exists() or case.get("expects_snapshot"):
        new_bytes = impl.fold(log)
        old_bytes = snapshot_path.read_bytes() if snapshot_path.exists() else b""
        if new_bytes != old_bytes:
            notes.append(
                f"expected.snapshot.json changed:\n"
                f"  old: {old_bytes!r}\n  new: {new_bytes!r}"
            )
            snapshot_path.write_bytes(new_bytes)
    return notes
