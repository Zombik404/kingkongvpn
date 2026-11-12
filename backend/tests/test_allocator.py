from __future__ import annotations

import asyncio
import base64
import ipaddress
import os
import uuid

import pytest
from sqlalchemy import select, text, update

from app.core.context import AppContext
from app.models import Device, User
from app.vpn.allocator import AddressPool, PoolExhausted, insert_with_address
from tests.conftest import make_settings


def test_pool_mapping() -> None:
    pool = AddressPool(
        ipaddress.IPv4Network("10.64.0.0/10"),
        ipaddress.IPv6Network("fd00:6476:706e::/48"),
        reserved=16,
    )
    assert pool.first_index == 16
    assert pool.last_index == 2**22 - 2  # broadcast excluded
    assert pool.capacity == 2**22 - 2 - 16 + 1
    v4, v6 = pool.addresses(16)
    assert str(v4) == "10.64.0.16"
    assert str(v6) == "fd00:6476:706e::10"
    v4, _ = pool.addresses(pool.last_index)
    assert str(v4) == "10.127.255.254"
    for bad in (15, pool.last_index + 1):
        with pytest.raises(ValueError):
            pool.addresses(bad)


def test_settings_reject_pool_without_room() -> None:
    with pytest.raises(ValueError):
        make_settings(vpn_tunnel_ipv4_pool="10.99.0.0/30", vpn_tunnel_reserved_addresses=3)


async def _user(ctx: AppContext) -> uuid.UUID:
    async with ctx.sessionmaker() as s:
        u = User(email=f"{uuid.uuid4().hex}@example.com")
        s.add(u)
        await s.commit()
        return u.id


async def _allocate(ctx: AppContext, pool: AddressPool, user_id: uuid.UUID) -> Device:
    async with ctx.sessionmaker() as s:
        d = Device(
            user_id=user_id,
            name="d",
            platform="linux",
            public_key=base64.b64encode(os.urandom(32)).decode(),
        )
        await insert_with_address(s, d, pool)
        await s.commit()
        return d


async def test_small_pool_exhaustion_and_gap_reuse(ctx: AppContext) -> None:
    # /29 = 8 addresses: index 0-1 reserved, 7 is broadcast → indices 2..6 usable
    pool = AddressPool(
        ipaddress.IPv4Network("10.99.0.0/29"), ipaddress.IPv6Network("fd00:99::/64"), reserved=2
    )
    uid = await _user(ctx)
    devices = [await _allocate(ctx, pool, uid) for _ in range(pool.capacity)]
    assert [d.address_index for d in devices] == [2, 3, 4, 5, 6]
    with pytest.raises(PoolExhausted):
        await _allocate(ctx, pool, uid)
    # purge index 4 (what the retention job does for long-revoked devices)
    async with ctx.sessionmaker() as s:
        await s.execute(
            update(Device)
            .where(Device.address_index == 4)
            .values(address_index=None, ipv4=None, ipv6=None)
        )
        await s.commit()
    reused = await _allocate(ctx, pool, uid)
    assert reused.address_index == 4
    assert str(reused.ipv4) == "10.99.0.4"
    with pytest.raises(PoolExhausted):
        await _allocate(ctx, pool, uid)


async def test_concurrent_gap_allocation_never_duplicates(ctx: AppContext) -> None:
    pool = AddressPool(
        ipaddress.IPv4Network("10.98.0.0/28"), ipaddress.IPv6Network("fd00:98::/64"), reserved=2
    )
    uid = await _user(ctx)
    async with ctx.sessionmaker() as s:  # burn the sequence so every call uses the gap path
        await s.execute(text("SELECT setval('tunnel_address_seq', 1000)"))
        await s.commit()
    results = await asyncio.gather(
        *[_allocate(ctx, pool, uid) for _ in range(pool.capacity)], return_exceptions=True
    )
    ok = [r for r in results if isinstance(r, Device)]
    assert len(ok) == pool.capacity, [r for r in results if not isinstance(r, Device)]
    async with ctx.sessionmaker() as s:
        idx = (await s.scalars(select(Device.address_index))).all()
    assert sorted(idx) == list(range(pool.first_index, pool.last_index + 1))
