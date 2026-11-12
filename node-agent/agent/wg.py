"""WireGuard interface access for the node agent.

Reads state with `wg show <iface> dump` and changes peers with `wg set`, one peer
at a time, so live tunnels are never interrupted by an interface restart.

Privacy (ADR-010): the peer endpoint (client's real IP:port) is present in the
dump output but is deliberately discarded during parsing and never stored,
returned or logged.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class WgError(RuntimeError):
    """Raised when wg output can't be parsed or a wg command fails."""


def is_valid_public_key(key: str) -> bool:
    """A WireGuard public key is 32 bytes, standard base64 (44 chars, '=' padded)."""
    if len(key) != 44 or not key.endswith("="):
        return False
    try:
        return len(base64.b64decode(key, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


@dataclass(frozen=True)
class PeerState:
    public_key: str
    allowed_ips: frozenset[IPNetwork]
    latest_handshake: int  # unix seconds, 0 = never
    rx_bytes: int
    tx_bytes: int


@dataclass(frozen=True)
class InterfaceState:
    public_key: str
    listen_port: int
    peers: dict[str, PeerState] = field(default_factory=dict)


def _parse_allowed_ips(raw: str) -> frozenset[IPNetwork]:
    if raw in ("(none)", ""):
        return frozenset()
    try:
        return frozenset(ipaddress.ip_network(p, strict=True) for p in raw.split(","))
    except ValueError as exc:
        raise WgError(f"bad allowed-ips field: {raw!r}") from exc


def parse_dump(text: str) -> InterfaceState:
    """Parse `wg show <iface> dump` (tab-separated).

    Line 1 (interface): private-key public-key listen-port fwmark
    Peers: public-key preshared-key endpoint allowed-ips latest-handshake rx tx keepalive
    The interface private key and peer endpoints are not retained.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise WgError("empty wg dump")
    head = lines[0].split("\t")
    if len(head) != 4:
        raise WgError("unexpected interface line in wg dump")
    _private_key, public_key, listen_port, _fwmark = head
    peers: dict[str, PeerState] = {}
    for ln in lines[1:]:
        cols = ln.split("\t")
        if len(cols) != 8:
            raise WgError("unexpected peer line in wg dump")
        pub, _psk, _endpoint, allowed, handshake, rx, tx, _keepalive = cols
        try:
            peers[pub] = PeerState(
                public_key=pub,
                allowed_ips=_parse_allowed_ips(allowed),
                latest_handshake=int(handshake),
                rx_bytes=int(rx),
                tx_bytes=int(tx),
            )
        except ValueError as exc:
            raise WgError("non-numeric counter in wg dump") from exc
    try:
        port = int(listen_port)
    except ValueError as exc:
        raise WgError("bad listen port in wg dump") from exc
    return InterfaceState(public_key=public_key, listen_port=port, peers=peers)


class WgDriver(Protocol):
    def show(self, iface: str) -> InterfaceState: ...
    def set_peer(self, iface: str, public_key: str, allowed_ips: frozenset[IPNetwork]) -> None: ...
    def remove_peer(self, iface: str, public_key: str) -> None: ...


class CliWgDriver:
    """Driver backed by the `wg` binary. Arguments are passed as a list — never a shell."""

    def __init__(self, wg_binary: str = "wg", timeout: float = 10.0) -> None:
        self._wg = wg_binary
        self._timeout = timeout

    def _run(self, *args: str) -> str:
        try:
            res = subprocess.run(  # noqa: S603 - fixed binary, validated args, no shell
                [self._wg, *args],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise WgError(f"wg {args[0]} failed to run: {exc}") from exc
        if res.returncode != 0:
            # stderr may contain the interface name but never key material we passed
            raise WgError(f"wg {args[0]} exited {res.returncode}: {res.stderr.strip()[:200]}")
        return res.stdout

    def show(self, iface: str) -> InterfaceState:
        return parse_dump(self._run("show", iface, "dump"))

    def set_peer(self, iface: str, public_key: str, allowed_ips: frozenset[IPNetwork]) -> None:
        if not is_valid_public_key(public_key):
            raise WgError("refusing to set peer with invalid public key")
        ips = ",".join(sorted(str(n) for n in allowed_ips))
        self._run("set", iface, "peer", public_key, "allowed-ips", ips)

    def remove_peer(self, iface: str, public_key: str) -> None:
        if not is_valid_public_key(public_key):
            raise WgError("refusing to remove peer with invalid public key")
        self._run("set", iface, "peer", public_key, "remove")
