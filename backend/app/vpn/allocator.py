"""Tunnel address allocation (ADR-004): one stable IPv4 + IPv6 per device, valid on every node.

An allocation is an integer *index*; the device's addresses are `pool.network + index` in both
families. Indices below `reserved` belong to node-side interface addresses. The `devices.
address_index` UNIQUE constraint is the final arbiter, so concurrent allocations can never
produce duplicates:

1. Normal path: `nextval('tunnel_address_seq')` — lock-free, unique by construction.
2. When the sequence passes the end of the pool, reuse the lowest index freed by purged
   devices (anti-join gap search). Racing allocators may pick the same gap; the loser hits the
   unique constraint inside a SAVEPOINT and retries.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import violated_constraint
from app.core.errors import ServiceUnavailable

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.models import Device

ADDRESS_CONSTRAINTS = frozenset({"uq_devices_address_index", "uq_devices_ipv4", "uq_devices_ipv6"})
MAX_GAP_RETRIES = 32  # each round of a race has one winner, so this bounds concurrency


class PoolExhausted(ServiceUnavailable):
    code = "address_pool_exhausted"
    message = "No tunnel addresses are available. Please try again later."


@dataclass(frozen=True)
class AddressPool:
    ipv4: ipaddress.IPv4Network
    ipv6: ipaddress.IPv6Network
    reserved: int

    @classmethod
    def from_settings(cls, settings: Settings) -> AddressPool:
        return cls(
            settings.vpn_tunnel_ipv4_pool,
            settings.vpn_tunnel_ipv6_pool,
            settings.vpn_tunnel_reserved_addresses,
        )

    @property
    def first_index(self) -> int:
        return self.reserved

    @property
    def last_index(self) -> int:
        # Exclude the IPv4 broadcast address; IPv6 pool is always far larger.
        return min(self.ipv4.num_addresses - 2, self.ipv6.num_addresses - 1)

    @property
    def capacity(self) -> int:
        return self.last_index - self.first_index + 1

    def addresses(self, index: int) -> tuple[ipaddress.IPv4Address, ipaddress.IPv6Address]:
        if not self.first_index <= index <= self.last_index:
            raise ValueError(f"index {index} outside pool")
        return self.ipv4.network_address + index, self.ipv6.network_address + index


async def _next_sequence_index(session: AsyncSession, pool: AddressPool) -> int | None:
    seq = int((await session.execute(text("SELECT nextval('tunnel_address_seq')"))).scalar_one())
    index = pool.first_index + seq - 1
    return index if index <= pool.last_index else None


async def _lowest_free_index(session: AsyncSession, pool: AddressPool) -> int | None:
    row = await session.execute(
        text(
            """
            SELECT candidate FROM (
                SELECT CAST(:first AS bigint) AS candidate
                WHERE NOT EXISTS (SELECT 1 FROM devices WHERE address_index = :first)
                UNION ALL
                SELECT d.address_index + 1
                FROM devices d
                WHERE d.address_index BETWEEN :first AND :last - 1
                  AND NOT EXISTS (
                      SELECT 1 FROM devices n WHERE n.address_index = d.address_index + 1)
            ) gaps
            ORDER BY candidate
            LIMIT 1
            """
        ),
        {"first": pool.first_index, "last": pool.last_index},
    )
    value = row.scalar_one_or_none()
    return int(value) if value is not None else None


async def insert_with_address(session: AsyncSession, device: Device, pool: AddressPool) -> None:
    """Assign tunnel addresses to a new device and INSERT it (flush) in the current transaction."""
    index = await _next_sequence_index(session, pool)
    attempts = 0
    while True:
        if index is None:
            index = await _lowest_free_index(session, pool)
            if index is None:
                raise PoolExhausted()
        v4, v6 = pool.addresses(index)
        device.address_index = index
        device.ipv4 = v4
        device.ipv6 = v6
        try:
            async with session.begin_nested():
                session.add(device)
                await session.flush()
            return
        except IntegrityError as exc:
            if violated_constraint(exc) not in ADDRESS_CONSTRAINTS:
                raise
            attempts += 1
            if attempts >= MAX_GAP_RETRIES:
                raise PoolExhausted() from exc
            index = None  # someone took it: search the gaps again
