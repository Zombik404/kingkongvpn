"""UUIDv7 (RFC 9562): time-ordered IDs, so B-tree inserts stay append-mostly."""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_seq = 0


def uuid7() -> uuid.UUID:
    """Return a UUIDv7. Monotonic within a process (12-bit counter in rand_a)."""
    global _last_ms, _seq
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms <= _last_ms:
            _seq += 1
            if _seq > 0xFFF:  # counter overflow: borrow the next millisecond
                _last_ms += 1
                _seq = 0
            now_ms = _last_ms
        else:
            _last_ms = now_ms
            _seq = int.from_bytes(os.urandom(2), "big") & 0x3FF  # random start, headroom
        seq = _seq
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (now_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= seq << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)
