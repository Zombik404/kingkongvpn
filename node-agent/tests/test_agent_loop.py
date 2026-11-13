from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from agent.__main__ import Agent
from agent.client import AgentConfig, ControlPlane, ControlPlaneError, parse_desired
from tests.test_reconcile import FakeDriver, key, nets

TOKEN = "node-token-123"


class Backend:
    """Stub of the backend's /internal/v1 node API."""

    def __init__(self) -> None:
        self.state: dict[str, Any] = {"revision": 1, "peers": []}
        self.heartbeats: list[dict[str, Any]] = []
        self.requests: list[str] = []
        self.status = 200
        backend = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: Any) -> None:
                pass

            def _auth(self) -> bool:
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    self.send_response(401)
                    self.end_headers()
                    return False
                if backend.status != 200:
                    self.send_response(backend.status)
                    self.end_headers()
                    return False
                return True

            def _json(self, data: Any) -> None:
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                backend.requests.append(self.path)
                if self._auth():
                    self._json(backend.state)

            def do_POST(self) -> None:
                n = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(n))
                if self._auth():
                    backend.heartbeats.append(payload)
                    self._json({"ok": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"


@pytest.fixture
def backend() -> Any:
    b = Backend()
    yield b
    b.server.shutdown()


def cfg(url: str, token: str = TOKEN) -> AgentConfig:
    return AgentConfig(api_url=url, node_id="node-1", node_token=token, longpoll_seconds=1)


def test_env_file_parsing(tmp_path: Path) -> None:
    f = tmp_path / "agent.env"
    f.write_text('# comment\nAPI_URL="http://127.0.0.1:8000/"\nNODE_ID=abc\nNODE_TOKEN=t0k\n'
                 "TUNNEL_POOLS=10.64.0.0/10, fd00:6476:706e::/48\nHEARTBEAT_SECONDS=15\n")
    c = AgentConfig.from_env_file(str(f))
    assert c.api_url == "http://127.0.0.1:8000" and c.node_token == "t0k"
    assert c.pools == ("10.64.0.0/10", "fd00:6476:706e::/48") and c.heartbeat_seconds == 15
    f.write_text("API_URL=http://x\n")
    with pytest.raises(ValueError, match="NODE_ID"):
        AgentConfig.from_env_file(str(f))


def test_step_applies_desired_state_and_heartbeat(backend: Backend) -> None:
    drv = FakeDriver({key(9): nets("10.64.0.99/32")})  # stale peer on the node
    backend.state = {"revision": 7, "peers": [
        {"public_key": key(1), "allowed_ips": ["10.64.0.16/32", "fd00:6476:706e::10/128"]}]}
    agent = Agent(cfg(backend.url), drv)
    assert agent.step(None) == 7
    assert set(drv.peers) == {key(1)}
    assert backend.requests[-1].endswith("/nodes/node-1/desired-state")
    agent.step(7)
    assert backend.requests[-1].endswith("?since=7")
    agent.cp.heartbeat(agent.heartbeat_payload())
    hb = backend.heartbeats[-1]
    assert hb["peers_total"] == 1 and hb["applied_revision"] == 7
    assert hb["wg_public_key"] == key(255) and hb["agent_version"]


def test_backend_down_keeps_peers(backend: Backend) -> None:
    drv = FakeDriver({key(1): nets("10.64.0.16/32")})
    agent = Agent(cfg(backend.url), drv)
    agent.stop.wait = lambda *_: True  # type: ignore[method-assign]  # don't sleep in tests
    backend.status = 503
    assert agent.step(5) is None
    assert set(drv.peers) == {key(1)}  # untouched
    assert "503" in agent.last_errors[0]
    dead = Agent(cfg("http://127.0.0.1:9"), drv)
    dead.stop.wait = lambda *_: True  # type: ignore[method-assign]
    assert dead.step(None) is None and set(drv.peers) == {key(1)}


def test_bad_token_and_unsafe_state(backend: Backend) -> None:
    drv = FakeDriver()
    agent = Agent(cfg(backend.url, token="wrong"), drv)
    agent.stop.wait = lambda *_: True  # type: ignore[method-assign]
    assert agent.step(None) is None and "401" in agent.last_errors[0]
    good = Agent(cfg(backend.url), drv)
    good.stop.wait = lambda *_: True  # type: ignore[method-assign]
    backend.state = {"revision": 2, "peers": [{"public_key": key(1),
                                               "allowed_ips": ["0.0.0.0/0"]}]}
    assert good.step(None) is None  # a /0 peer would hijack traffic: refused
    assert drv.peers == {}


def test_failed_apply_requests_full_state(backend: Backend) -> None:
    drv = FakeDriver(fail_on={key(2)})
    backend.state = {"revision": 3, "peers": [
        {"public_key": key(1), "allowed_ips": ["10.64.0.16/32"]},
        {"public_key": key(2), "allowed_ips": ["10.64.0.17/32"]}]}
    agent = Agent(cfg(backend.url), drv)
    assert agent.step(None) is None  # retry with a full fetch next time
    assert key(1) in drv.peers and agent.last_errors


def test_parse_desired_rejects_garbage() -> None:
    for bad in (None, {"peers": "x"}, {"peers": [1]}, {"peers": [{"public_key": "k"}]}):
        with pytest.raises(ControlPlaneError):
            parse_desired(bad)
    s = parse_desired({"revision": "4", "peers": []})
    assert s.revision == 4 and s.peers == ()
    with pytest.raises(ControlPlaneError):
        ControlPlane(AgentConfig("file:///etc", "n", "t")).heartbeat({})


def test_threads_stop_cleanly(backend: Backend) -> None:
    agent = Agent(cfg(backend.url), FakeDriver())
    t1 = threading.Thread(target=agent.run_reconcile_loop)
    t2 = threading.Thread(target=agent.run_heartbeat_loop)
    t1.start()
    t2.start()
    agent.stop.set()
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    assert backend.heartbeats


def test_public_key_helper() -> None:
    assert base64.b64decode(key(1)) == bytes([1]) * 32
