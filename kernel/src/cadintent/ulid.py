"""Minimal ULID minting (for kernel-minted batch IDs)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def encode(value: int) -> str:
    """Encode a 128-bit integer as a canonical 26-character Crockford ULID."""
    if not 0 <= value < 1 << 128:
        raise ValueError("ULID value out of range")
    chars = []
    for _ in range(26):
        chars.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def mint() -> str:
    """A fresh ULID: 48-bit millisecond timestamp + 80 random bits."""
    ts = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = int.from_bytes(os.urandom(10), "big")
    return encode((ts << 80) | rand)
