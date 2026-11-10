"""Canonical JSON serialization — the conformance byte oracle.

Canonical bytes are pinned as (documented per #20 / #23; snapshots, diffs, and
check runs all use exactly the same rules):

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

The hash is a per-entry chain (spec'd for #33's snapshot resume): starting
from a 32-zero-byte seed, each entry folds in as
``digest = sha256(digest || canonical_bytes(stripped_entry))``. Chaining makes
the hash extensible from a snapshot's recorded prefix hash alone — resume
never needs the prefix entries to stamp the resulting snapshot — while any
change to any prefix entry still changes every subsequent hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_EXCLUDED_FROM_HASH = ("created_at", "batch")

#: The chain seed: the hash of the empty log.
EMPTY_LOG_HASH = "sha256:" + bytes(32).hex()


def canonical_bytes(document: Any) -> bytes:
    """The one canonical serialization of a JSON document."""
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def log_bytes(log: list[dict[str, Any]]) -> bytes:
    """The log file format: one canonical entry per line, append-only.

    An empty log is an empty file. One entry per line lets line-oriented tools
    such as git show what an append added. It does not make two appends
    mergeable: ``seq``, the declared head and the hash chain each allow one
    writer at a time.
    """
    return b"".join(canonical_bytes(entry) for entry in log)


def parse_log(raw: bytes) -> list[dict[str, Any]]:
    """Parse the log file format. Raises ValueError naming the bad line."""
    entries: list[dict[str, Any]] = []
    lines = raw.split(b"\n")
    if lines[-1] == b"":
        lines.pop()
    for number, line in enumerate(lines, start=1):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"line {number} is not parseable JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"line {number} is not one envelope-complete command")
        entries.append(entry)
    return entries


def _entry_bytes(entry: dict[str, Any]) -> bytes:
    return canonical_bytes(
        {k: v for k, v in entry.items() if k not in _EXCLUDED_FROM_HASH}
    )


def extend_log_hash(prefix_hash: str, entries: list[dict[str, Any]]) -> str:
    """Fold ``entries`` into the chain continuing from ``prefix_hash``."""
    digest = bytes.fromhex(prefix_hash.removeprefix("sha256:"))
    for entry in entries:
        digest = hashlib.sha256(digest + _entry_bytes(entry)).digest()
    return "sha256:" + digest.hex()


def log_hash(log: list[dict[str, Any]]) -> str:
    """'sha256:<hex>': the chained content hash of the fold-relevant log."""
    return extend_log_hash(EMPTY_LOG_HASH, log)
