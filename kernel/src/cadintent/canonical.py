"""Canonical JSON serialization — the conformance byte oracle.

Canonical bytes are pinned as (documented per #20 / #23; build #33's diff and
resume must use exactly the same rules):

- UTF-8 encoding, ``ensure_ascii=False`` (non-ASCII characters are emitted
  verbatim, never escaped);
- object keys sorted lexicographically by Unicode code point (``sort_keys``);
- minimal separators ``(",", ":")`` — no whitespace;
- exactly one trailing newline (``\\n``).

There are no JSON numbers with fractional parts anywhere in the model (all
quantities are quantized decimal strings), so float formatting never arises;
integers (seq, head) serialize in their unique canonical form.

The log content hash identifies the fold-relevant content of a log: each
envelope minus ``created_at`` (kernel-stamped, ignored by fold per #17) and
``batch`` (kernel-minted grouping metadata). Excluding both keeps snapshots
byte-identical across machines and conforming implementations, whose minted
batch ULIDs and acceptance timestamps necessarily differ.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_EXCLUDED_FROM_HASH = ("created_at", "batch")


def canonical_bytes(document: Any) -> bytes:
    """The one canonical serialization of a JSON document."""
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def log_hash(log: list[dict[str, Any]]) -> str:
    """'sha256:<hex>' over the canonical bytes of the fold-relevant log content."""
    stripped = [
        {k: v for k, v in entry.items() if k not in _EXCLUDED_FROM_HASH}
        for entry in log
    ]
    return "sha256:" + hashlib.sha256(canonical_bytes(stripped)).hexdigest()
