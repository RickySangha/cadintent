"""The Implementation protocol — the seam the conformance runner drives.

The runner talks to a kernel only through this minimal protocol (#23). The
in-process adapter for our kernel lives in :mod:`.adapter`; the foreign
subprocess/JSON-over-stdio invocation contract is deliberately undecided fog
and will plug in at this same seam later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class NotSupported(Exception):
    """The implementation cannot run this operation (reported could-not-run,
    never pass)."""


@dataclass
class SubmitOutcome:
    accepted: bool
    log: list[dict[str, Any]] | None = None
    refusal: dict[str, Any] | None = None


class Implementation(Protocol):
    #: Spec versions this implementation supports (cases pin one).
    spec_versions: frozenset[str]
    #: Operations available: subset of {"submit", "fold", "fold_from", "diff"}.
    capabilities: frozenset[str]

    def submit(
        self, log: list[dict[str, Any]], submission: dict[str, Any]
    ) -> SubmitOutcome: ...

    def fold(self, log: list[dict[str, Any]]) -> bytes:
        """Canonical snapshot bytes of the folded log."""
        ...

    def fold_from(
        self, snapshot: bytes, commands: list[dict[str, Any]]
    ) -> bytes:
        """Resume from a snapshot; must byte-equal full replay (law 4)."""
        ...

    def diff(self, a: bytes, b: bytes) -> bytes:
        """Canonical diff bytes between two snapshots."""
        ...
