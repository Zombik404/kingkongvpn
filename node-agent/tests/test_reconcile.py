from __future__ import annotations

import base64
import ipaddress

import pytest

from agent.reconcile import (
    DesiredPeer,
    DesiredState,
    DesiredStateError,
    MassRemovalRefused,
    apply,
    make_plan,
    parse_pools,
    reconcile,
    validate,
)
from agent.wg import InterfaceState, PeerState, WgError, is_valid_public_key, parse_dump

POOLS = parse_pools(["10.64.0.0/10", "fd00:6476:706e::/48"])


def key(i: int) -> str:
    return base64.b64encode(bytes([i]) * 32).decode()


def nets(*cidrs: str) -> frozenset:
    return frozenset(ipaddress.ip_network(c) for c in cidrs)


def peer(i: int, *cidrs: str) -> DesiredPeer:
    return DesiredPeer(key(i), nets(*cidrs))


class FakeDriver:
    def __init__(self, peers: dict[str, frozenset] | None = None, fail_on: set[str] | None = None):
        self.peers = dict(peers or {})
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on or set()

    def show(self, iface: str) -> InterfaceState:
        return InterfaceState(
            public_key=key(255),
            listen_port=51820,
            peers={k: PeerState(k, v, 0, 0, 0) for k, v in self.peers.items()},
        )

    def set_peer(self, iface, public_key, allowed_ips):
        if public_key in self.fail_on:
            raise WgError("boom")
        self.calls.append(("set", public_key))
        self.peers[public_key] = allowed_ips

    def remove_peer(self, iface, public_key):
        self.calls.append(("remove", public_key))
        self.peers.pop(public_key, None)


# --- wg dump parsing ---------------------------------------------------------

DUMP = (
    "PRIVATEKEYNOTKEPT=\t" + key(255) + "\t51820\toff\n"
    + key(1) + "\t(none)\t203.0.113.7:40000\t10.64.0.2/32,fd00:6476:706e::2/128\t1700000000\t100\t200\t0\n"
    + key(2) + "\t(none)\t(none)\t(none)\t0\t0\t0\toff\n"
)


def test_parse_dump_reads_peers_and_drops_endpoint_and_private_key():
    state = parse_dump(DUMP)
    assert state.listen_port == 51820
    assert state.peers[key(1)].allowed_ips == nets("10.64.0.2/32", "fd00:6476:706e::2/128")
    assert state.peers[key(1)].rx_bytes == 100
    assert state.peers[key(2)].allowed_ips == frozenset()
    # privacy: neither the client endpoint nor the server private key survives parsing
    assert "203.0.113.7" not in repr(state)
    assert "PRIVATEKEYNOTKEPT" not in repr(state)


@pytest.mark.parametrize("bad", ["", "a\tb\n", "x\ty\t51820\toff\nbad\tline\n"])
def test_parse_dump_rejects_malformed(bad):
    with pytest.raises(WgError):
        parse_dump(bad)


def test_public_key_validation():
    assert is_valid_public_key(key(1))
    assert not is_valid_public_key("not-a-key")
    assert not is_valid_public_key(base64.b64encode(b"x" * 31).decode())
    assert not is_valid_public_key(key(1)[:-2] + "!=")


# --- validation of desired state --------------------------------------------

def test_validate_accepts_host_routes_in_pools():
    validate(DesiredState(1, (peer(1, "10.64.0.2/32", "fd00:6476:706e::2/128"),)), POOLS)


@pytest.mark.parametrize(
    "bad_peer",
    [
        peer(1, "0.0.0.0/0"),            # would hijack all return traffic
        peer(1, "10.64.0.0/24"),          # not a host route
        peer(1, "192.168.1.5/32"),        # outside pools
        peer(1, "2001:db8::1/128"),       # outside pools (v6)
        DesiredPeer("bogus", nets("10.64.0.2/32")),
        DesiredPeer(key(1), frozenset()),
    ],
)
def test_validate_rejects_unsafe_peers(bad_peer):
    with pytest.raises(DesiredStateError):
        validate(DesiredState(1, (bad_peer,)), POOLS)


def test_validate_rejects_duplicate_address_and_key():
    with pytest.raises(DesiredStateError):
        validate(DesiredState(1, (peer(1, "10.64.0.2/32"), peer(2, "10.64.0.2/32"))), POOLS)
    with pytest.raises(DesiredStateError):
        validate(DesiredState(1, (peer(1, "10.64.0.2/32"), peer(1, "10.64.0.3/32"))), POOLS)


# --- planning ----------------------------------------------------------------

def test_plan_add_update_remove():
    drv = FakeDriver({key(1): nets("10.64.0.2/32"), key(2): nets("10.64.0.3/32")})
    desired = DesiredState(5, (peer(1, "10.64.0.2/32"), peer(2, "10.64.0.9/32"), peer(3, "10.64.0.4/32")))
    plan = make_plan(drv.show("wg0"), desired)
    assert [p.public_key for p in plan.add] == [key(3)]
    assert [p.public_key for p in plan.update] == [key(2)]
    assert plan.remove == ()


def test_plan_is_empty_when_in_sync():
    drv = FakeDriver({key(1): nets("10.64.0.2/32")})
    assert make_plan(drv.show("wg0"), DesiredState(1, (peer(1, "10.64.0.2/32"),))).is_empty


def test_mass_removal_guard():
    current = {key(i): nets(f"10.64.0.{i}/32") for i in range(1, 31)}
    drv = FakeDriver(current)
    with pytest.raises(MassRemovalRefused):
        make_plan(drv.show("wg0"), DesiredState(9, ()))
    plan = make_plan(drv.show("wg0"), DesiredState(9, (), allow_mass_removal=True))
    assert len(plan.remove) == 30


def test_small_node_can_drop_to_zero_without_flag():
    drv = FakeDriver({key(1): nets("10.64.0.2/32")})
    assert make_plan(drv.show("wg0"), DesiredState(2, ())).remove == (key(1),)


# --- applying ----------------------------------------------------------------

def test_apply_removes_before_adding():
    drv = FakeDriver({key(1): nets("10.64.0.2/32")})
    desired = DesiredState(2, (peer(2, "10.64.0.2/32"),))  # address moves to a new device
    plan, result = reconcile(drv, "wg0", desired, POOLS)
    assert drv.calls == [("remove", key(1)), ("set", key(2))]
    assert result.applied == 2 and not result.errors
    assert drv.peers == {key(2): nets("10.64.0.2/32")}


def test_apply_continues_after_failure_and_reports_it():
    drv = FakeDriver(fail_on={key(1)})
    desired = DesiredState(1, (peer(1, "10.64.0.2/32"), peer(2, "10.64.0.3/32")))
    _, result = reconcile(drv, "wg0", desired, POOLS)
    assert result.applied == 1
    assert len(result.errors) == 1 and key(1)[:8] in result.errors[0]
    assert key(2) in drv.peers


def test_reconcile_is_idempotent():
    drv = FakeDriver()
    desired = DesiredState(1, (peer(1, "10.64.0.2/32"), peer(2, "fd00:6476:706e::5/128")))
    reconcile(drv, "wg0", desired, POOLS)
    drv.calls.clear()
    plan, result = reconcile(drv, "wg0", desired, POOLS)
    assert plan.is_empty and result.applied == 0 and drv.calls == []


def test_unsafe_state_never_reaches_driver():
    drv = FakeDriver({key(1): nets("10.64.0.2/32")})
    with pytest.raises(DesiredStateError):
        reconcile(drv, "wg0", DesiredState(1, (peer(1, "0.0.0.0/0"),)), POOLS)
    assert drv.calls == []
    assert apply  # imported for API surface
