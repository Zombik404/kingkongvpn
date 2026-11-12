"""Audit log writer. Secrets are scrubbed from details before they reach the database."""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog
from app.models.enums import ActorType, AuditResult

REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"pass|secret|token|key|otp|code|authorization|cookie|pepper|hash|signature|card|iban",
    re.IGNORECASE,
)
_MAX_STR = 256
_MAX_DEPTH = 4
_MAX_ITEMS = 50


def scrub(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact values under sensitive-looking keys and bound the size."""
    if depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_ITEMS:
                out["_truncated"] = True
                break
            key = str(k)
            out[key] = REDACTED if _SENSITIVE_KEY.search(key) else scrub(v, depth=depth + 1)
        return out
    if isinstance(value, list | tuple | set | frozenset):
        return [scrub(v, depth=depth + 1) for v in list(value)[:_MAX_ITEMS]]
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "…"
    if value is None or isinstance(value, bool | int | float):
        return value
    return scrub(str(value), depth=depth + 1)


def ip_prefix(ip: str | None) -> str | None:
    """Truncate to /24 (IPv4) or /48 (IPv6): enough for abuse triage, not a person's address."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False))


def record(
    session: AsyncSession,
    *,
    action: str,
    actor_id: uuid.UUID | None = None,
    actor_type: ActorType = ActorType.USER,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    result: AuditResult = AuditResult.SUCCESS,
    ip: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Stage an audit row in the caller's transaction (committed with the change it describes)."""
    entry = AuditLog(
        actor_id=actor_id,
        actor_type=actor_type.value,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        result=result.value,
        ip_prefix=ip_prefix(ip),
        details=scrub(details or {}),
    )
    session.add(entry)
    return entry
