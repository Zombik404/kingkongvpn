"""Control-plane client for the node agent (stdlib only: no extra packages on nodes).

Test phase: the agent talks to the backend over the host's loopback with a per-node bearer
token (ADR-017). Multi-node production switches this to mTLS over the public endpoint.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .reconcile import DesiredPeer, DesiredState, parse_pools


class ControlPlaneError(RuntimeError):
    """Backend unreachable or answered with an error. Existing peers stay as they are."""


@dataclass(frozen=True)
class AgentConfig:
    api_url: str
    node_id: str
    node_token: str
    iface: str = "wg0"
    pools: tuple[str, ...] = ("10.64.0.0/10", "fd00:6476:706e::/48")
    heartbeat_seconds: float = 30.0
    longpoll_seconds: float = 25.0

    @classmethod
    def from_env_file(cls, path: str) -> AgentConfig:
        values: dict[str, str] = {}
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
        try:
            return cls(
                api_url=values["API_URL"].rstrip("/"),
                node_id=values["NODE_ID"],
                node_token=values["NODE_TOKEN"],
                iface=values.get("WG_IFACE", "wg0"),
                pools=tuple(p.strip() for p in values.get(
                    "TUNNEL_POOLS", "10.64.0.0/10,fd00:6476:706e::/48").split(",") if p.strip()),
                heartbeat_seconds=float(values.get("HEARTBEAT_SECONDS", "30")),
                longpoll_seconds=float(values.get("LONGPOLL_SECONDS", "25")),
            )
        except KeyError as exc:
            raise ValueError(f"missing {exc.args[0]} in {path}") from exc


def parse_desired(data: Any) -> DesiredState:
    if not isinstance(data, dict) or not isinstance(data.get("peers"), list):
        raise ControlPlaneError("malformed desired state")
    peers = []
    for p in data["peers"]:
        if not isinstance(p, dict) or not isinstance(p.get("allowed_ips"), list):
            raise ControlPlaneError("malformed peer")
        peers.append(DesiredPeer(str(p.get("public_key", "")),
                                 frozenset(parse_pools(str(c) for c in p["allowed_ips"]))))
    return DesiredState(revision=int(data.get("revision", 0)), peers=tuple(peers))


class ControlPlane:
    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg

    def _request(self, method: str, path: str, body: dict[str, Any] | None,
                 timeout: float) -> Any:
        url = f"{self.cfg.api_url}/internal/v1/nodes/{self.cfg.node_id}{path}"
        if not url.startswith(("http://", "https://")):
            raise ControlPlaneError("API_URL must be http(s)")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(  # noqa: S310 - scheme checked above
            url, data=data, method=method,
            headers={"Authorization": f"Bearer {self.cfg.node_token}",
                     "Content-Type": "application/json", "User-Agent": "globalvpn-agent"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            raise ControlPlaneError(f"{method} {path}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ControlPlaneError(f"{method} {path}: {exc}") from exc

    def desired_state(self, since: int | None) -> DesiredState:
        path = "/desired-state" + (f"?since={since}" if since is not None else "")
        return parse_desired(self._request("GET", path, None, self.cfg.longpoll_seconds + 10))

    def heartbeat(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/heartbeat", payload, 10)
