"""In-process adapter driving the cadintent kernel through the protocol."""

from __future__ import annotations

from typing import Any

import cadintent

from .protocol import NotSupported, SubmitOutcome


class InProcessKernel:
    spec_versions = frozenset({cadintent.SPEC_VERSION})
    capabilities = frozenset({"submit", "fold"})

    def submit(
        self, log: list[dict[str, Any]], submission: dict[str, Any]
    ) -> SubmitOutcome:
        result = cadintent.submit(log, submission)
        if isinstance(result, cadintent.Accepted):
            return SubmitOutcome(accepted=True, log=result.log)
        return SubmitOutcome(accepted=False, refusal=result.refusal)

    def fold(self, log: list[dict[str, Any]]) -> bytes:
        return cadintent.snapshot_bytes(log)

    def fold_from(self, snapshot: bytes, commands: list[dict[str, Any]]) -> bytes:
        raise NotSupported("snapshot resume lands with build issue #33")

    def diff(self, a: bytes, b: bytes) -> bytes:
        raise NotSupported("canonical diff lands with build issue #33")
