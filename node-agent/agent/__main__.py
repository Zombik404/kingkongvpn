"""Node agent main loop: `python3 -m agent --env /etc/globalvpn/agent.env`.

* Long-polls the desired peer set and reconciles WireGuard to it (full reconcile at least every
  long-poll timeout, so drift is corrected within ~25 s even without changes).
* Sends a heartbeat every HEARTBEAT_SECONDS from a separate thread.
* If the backend is unreachable, live tunnels are left untouched (control/data plane split).
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
import time
from typing import Any

from . import __version__
from .client import AgentConfig, ControlPlane, ControlPlaneError
from .reconcile import DesiredStateError, MassRemovalRefused, parse_pools, reconcile
from .wg import CliWgDriver, WgDriver, WgError

log = logging.getLogger("globalvpn.agent")
ACTIVE_HANDSHAKE_SECONDS = 180


class Agent:
    def __init__(self, cfg: AgentConfig, driver: WgDriver, cp: ControlPlane | None = None):
        self.cfg = cfg
        self.driver = driver
        self.cp = cp or ControlPlane(cfg)
        self.pools = parse_pools(cfg.pools)
        self.stop = threading.Event()
        self.applied_revision: int | None = None
        self.last_errors: list[str] = []

    # --- reconcile ----------------------------------------------------------------------
    def step(self, since: int | None) -> int | None:
        """One poll + reconcile. Returns the revision to wait on next (None = full fetch)."""
        try:
            desired = self.cp.desired_state(since)
            plan, result = reconcile(self.driver, self.cfg.iface, desired, self.pools)
        except MassRemovalRefused as exc:
            log.error("refusing mass removal: %s", exc)
            self.last_errors = [str(exc)[:200]]
            self.stop.wait(30)
            return None
        except DesiredStateError as exc:
            log.error("unsafe desired state rejected: %s", exc)
            self.last_errors = [str(exc)[:200]]
            self.stop.wait(15)
            return None
        except (ControlPlaneError, WgError) as exc:
            log.warning("%s; keeping current peers", exc)
            self.last_errors = [str(exc)[:200]]
            self.stop.wait(5)
            return None
        if not plan.is_empty:
            log.info("revision %s: +%d ~%d -%d peers", desired.revision, len(plan.add),
                     len(plan.update), len(plan.remove))
        for err in result.errors:
            log.error("apply: %s", err)
        self.last_errors = result.errors[:20]
        self.applied_revision = desired.revision
        # If anything failed, ask for a full state next time instead of waiting for a change.
        return None if result.errors else desired.revision

    def run_reconcile_loop(self) -> None:
        since: int | None = None
        while not self.stop.is_set():
            since = self.step(since)

    # --- heartbeat ----------------------------------------------------------------------
    def heartbeat_payload(self) -> dict[str, Any]:
        state = self.driver.show(self.cfg.iface)
        now = int(time.time())
        return {
            "wg_public_key": state.public_key,
            "applied_revision": self.applied_revision,
            "peers_total": len(state.peers),
            "peers_active": sum(1 for p in state.peers.values()
                                if p.latest_handshake and now - p.latest_handshake
                                < ACTIVE_HANDSHAKE_SECONDS),
            "rx_bytes": sum(p.rx_bytes for p in state.peers.values()),
            "tx_bytes": sum(p.tx_bytes for p in state.peers.values()),
            "handshakes": {k: p.latest_handshake for k, p in state.peers.items()
                           if p.latest_handshake},
            "errors": self.last_errors,
            "agent_version": __version__,
        }

    def run_heartbeat_loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.cp.heartbeat(self.heartbeat_payload())
            except (ControlPlaneError, WgError) as exc:
                log.warning("heartbeat failed: %s", exc)
            self.stop.wait(self.cfg.heartbeat_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="globalvpn-agent")
    parser.add_argument("--env", default="/etc/globalvpn/agent.env")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    agent = Agent(AgentConfig.from_env_file(args.env), CliWgDriver())
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: agent.stop.set())
    hb = threading.Thread(target=agent.run_heartbeat_loop, name="heartbeat", daemon=True)
    hb.start()
    log.info("agent %s started for node %s on %s", __version__, agent.cfg.node_id,
             agent.cfg.iface)
    agent.run_reconcile_loop()
    log.info("agent stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
