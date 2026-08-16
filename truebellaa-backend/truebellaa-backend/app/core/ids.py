"""
A tiny ULID generator (26-char Crockford base32).

A ULID is a sortable, random, URL-safe id. We store one in the `public_id`
column of important tables so the outside world never sees the internal
auto-increment number. No external library needed.
"""
import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # excludes I, L, O, U


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a fresh 26-character ULID (10 chars time + 16 chars randomness)."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ms, 10) + _encode(rand, 16)
