"""Reconcile the live WireGuard peer set with the backend's desired state (ADR-002).

Safety rules enforced here, independent of the backend:
  * A peer's allowed-ips must be single host routes (/32, /128) inside the
    node's configured tunnel pools. A peer with e.g. 0.0.0.0/0 would receive
    every other client's return traffic, so such entries are rejected.
  * No two desired peers may claim the same address.
  * A plan that would remove an unusually large share of peers is refused
    unless the desired state explicitly allows it (guards against a backend
    bug or an empty response wiping a live server).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass, field

from .wg import InterfaceState, IPNetwork, WgDriver, is_valid_public_key


class DesiredStateError(ValueError):
    """The desired state from the backend is unsafe or malformed."""


class MassRemovalRefused(RuntimeError):
    """The plan would remove more peers than the safety guard allows."""


@dataclass(frozen=True)
class DesiredPeer:
    public_key: str
    allowed_ips: frozenset[IPNetwork]


@dataclass(frozen=True)
class DesiredState:
    revision: int
    peers: tuple[DesiredPeer, ...]
    allow_mass_removal: bool = False


@dataclass(frozen=True)
class Plan:
    add: tuple[DesiredPeer, ...] = ()
    update: tuple[DesiredPeer, ...] = ()
    remove: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.add or self.update or self.remove)


@dataclass
class ApplyResult:
    applied: int = 0
    errors: list[str] = field(default_factory=list)


def validate(desired: DesiredState, pools: Iterable[IPNetwork]) -> None:
    pool_list = list(pools)
    seen_keys: set[str] = set()
    seen_ips: set[IPNetwork] = set()
    for peer in desired.peers:
        if not is_valid_public_key(peer.public_key):
            raise DesiredStateError("invalid public key in desired state")
        if peer.public_key in seen_keys:
            raise DesiredStateError("duplicate public key in desired state")
        seen_keys.add(peer.public_key)
        if not peer.allowed_ips:
            raise DesiredStateError("peer without allowed-ips")
        for net in peer.allowed_ips:
            host_len = 32 if net.version == 4 else 128
            if net.prefixlen != host_len:
                raise DesiredStateError(f"non-host route {net} for a peer")
            if not any(net.version == p.version and net.subnet_of(p) for p in pool_list):  # type: ignore[arg-type]
                raise DesiredStateError(f"address {net} outside tunnel pools")
            if net in seen_ips:
                raise DesiredStateError(f"address {net} assigned to two peers")
            seen_ips.add(net)


def make_plan(
    current: InterfaceState,
    desired: DesiredState,
    *,
    max_removal_fraction: float = 0.5,
    min_peers_for_guard: int = 20,
) -> Plan:
    want = {p.public_key: p for p in desired.peers}
    add = tuple(p for k, p in sorted(want.items()) if k not in current.peers)
    update = tuple(
        p
        for k, p in sorted(want.items())
        if k in current.peers and current.peers[k].allowed_ips != p.allowed_ips
    )
    remove = tuple(sorted(k for k in current.peers if k not in want))

    n_current = len(current.peers)
    if (
        not desired.allow_mass_removal
        and n_current >= min_peers_for_guard
        and len(remove) > n_current * max_removal_fraction
    ):
        raise MassRemovalRefused(
            f"plan removes {len(remove)} of {n_current} peers (revision {desired.revision})"
        )
    return Plan(add=add, update=update, remove=remove)


def apply(plan: Plan, driver: WgDriver, iface: str) -> ApplyResult:
    """Apply removals first so an address freed by a revoked peer is never briefly
    shared, then updates and additions. Continues past individual failures; the
    next reconcile retries anything that failed."""
    result = ApplyResult()
    for key in plan.remove:
        try:
            driver.remove_peer(iface, key)
            result.applied += 1
        except Exception as exc:  # noqa: BLE001 - recorded, retried next cycle
            result.errors.append(f"remove {key[:8]}…: {exc}")
    for peer in (*plan.update, *plan.add):
        try:
            driver.set_peer(iface, peer.public_key, peer.allowed_ips)
            result.applied += 1
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"set {peer.public_key[:8]}…: {exc}")
    return result


def reconcile(
    driver: WgDriver,
    iface: str,
    desired: DesiredState,
    pools: Iterable[IPNetwork],
    **guard: float | int,
) -> tuple[Plan, ApplyResult]:
    validate(desired, pools)
    plan = make_plan(driver.show(iface), desired, **guard)  # type: ignore[arg-type]
    return plan, apply(plan, driver, iface)


def parse_pools(raw: Iterable[str]) -> list[IPNetwork]:
    return [ipaddress.ip_network(r, strict=True) for r in raw]
