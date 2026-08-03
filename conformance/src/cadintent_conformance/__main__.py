"""CLI: run the conformance suite against the in-process kernel.

Exit codes (part of the contract): 0 all-pass, 1 any failure or empty suite,
2 any could-not-run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .adapter import InProcessKernel
from .runner import DEFAULT_CASES_DIR, discover, rebaseline_case, run_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cadintent-conformance")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--select", default=None, help="substring case filter")
    parser.add_argument(
        "--rebaseline",
        action="store_true",
        help="regenerate expected files, printing the full byte diff for review",
    )
    args = parser.parse_args(argv)
    impl = InProcessKernel()

    if args.rebaseline:
        for case_dir in discover(args.cases):
            for note in rebaseline_case(case_dir, impl):
                print(f"[{case_dir.parent.name}/{case_dir.name}] {note}")
        return 0

    report = run_suite(impl, cases_dir=args.cases, select=args.select)
    for result in report.results:
        line = f"{result.status:>14}  {result.case_id}"
        if result.detail:
            line += f"  ({result.detail})"
        print(line)
    counts = report.counts()
    print(
        f"\n{counts['pass']} pass, {counts['fail']} fail, "
        f"{counts['could-not-run']} could-not-run, "
        f"{counts['not-selected']} not-selected"
    )
    if not report.results:
        print("no cases discovered: an empty suite must never report green")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
