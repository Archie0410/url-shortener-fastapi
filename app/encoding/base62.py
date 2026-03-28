"""Base62 encode/decode for compact, URL-safe short codes."""

from __future__ import annotations

ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)
_INDEX = {c: i for i, c in enumerate(ALPHABET)}


class Base62Error(ValueError):
    """Invalid Base62 input."""


def encode_base62(n: int) -> str:
    if n < 0:
        raise Base62Error("integer must be non-negative")
    if n == 0:
        return ALPHABET[0]
    chars: list[str] = []
    while n:
        n, rem = divmod(n, BASE)
        chars.append(ALPHABET[rem])
    return "".join(reversed(chars))


def decode_base62(s: str) -> int:
    if not s:
        raise Base62Error("empty string")
    n = 0
    for ch in s:
        if ch not in _INDEX:
            raise Base62Error(f"invalid character: {ch!r}")
        n = n * BASE + _INDEX[ch]
    return n
