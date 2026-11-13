"""Provably fair shuffle.

Before a round the server commits to a random `server_seed` by publishing SHA-256(server_seed).
Players then contribute a `client_seed`; `nonce` is the round number at the table. The shoe is a
Fisher-Yates shuffle of the canonical shoe driven by the byte stream

    HMAC-SHA256(key = server_seed, msg = f"{client_seed}:{nonce}:{counter}")   counter = 0, 1, …

read as 32-bit big-endian integers with rejection sampling (no modulo bias). After the round the
server reveals `server_seed`: anyone can check it against the published hash and re-run the
shuffle to see that the cards could not have been changed after the bets.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Iterator

from app.games.blackjack import fresh_shoe


def new_server_seed() -> str:
    return secrets.token_hex(32)  # CSPRNG, 256 bits


def seed_hash(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


def combine_client_seeds(seeds: dict[int, str]) -> str:
    """One client seed for a table: every seat's seed, in seat order."""
    return "|".join(f"{seat}={seeds[seat]}" for seat in sorted(seeds))


def _stream(server_seed: str, client_seed: str, nonce: int) -> Iterator[int]:
    counter = 0
    while True:
        block = hmac.new(
            server_seed.encode(), f"{client_seed}:{nonce}:{counter}".encode(), hashlib.sha256
        ).digest()
        for i in range(0, 32, 4):
            yield int.from_bytes(block[i : i + 4], "big")
        counter += 1


def shuffled_shoe(server_seed: str, client_seed: str, nonce: int, decks: int) -> list[str]:
    shoe = fresh_shoe(decks)
    rnd = _stream(server_seed, client_seed, nonce)
    for i in range(len(shoe) - 1, 0, -1):
        span = i + 1
        limit = (1 << 32) - ((1 << 32) % span)  # reject values that would bias the modulo
        while True:
            x = next(rnd)
            if x < limit:
                break
        j = x % span
        shoe[i], shoe[j] = shoe[j], shoe[i]
    return shoe
