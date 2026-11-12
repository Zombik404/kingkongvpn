"""Role → permission map for staff roles (ADR-007). Regular users have no staff roles."""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import Role


class Perm(StrEnum):
    USERS_READ = "users:read"
    USERS_WRITE = "users:write"  # suspend / reactivate
    ROLES_WRITE = "roles:write"
    SUBSCRIPTIONS_GRANT = "subscriptions:grant"
    PLANS_READ = "plans:read"
    PLANS_WRITE = "plans:write"
    PROMO_WRITE = "promo:write"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"
    AUDIT_READ = "audit:read"


ROLE_PERMISSIONS: dict[str, frozenset[Perm]] = {
    Role.SUPPORT: frozenset(
        {
            Perm.USERS_READ,
            Perm.USERS_WRITE,
            Perm.SUBSCRIPTIONS_GRANT,
            Perm.PLANS_READ,
            Perm.SETTINGS_READ,
        }
    ),
    Role.OPS: frozenset(
        {Perm.USERS_READ, Perm.PLANS_READ, Perm.SETTINGS_READ, Perm.SETTINGS_WRITE, Perm.AUDIT_READ}
    ),
    Role.FINANCE: frozenset(
        {Perm.USERS_READ, Perm.PLANS_READ, Perm.PLANS_WRITE, Perm.PROMO_WRITE, Perm.SETTINGS_READ}
    ),
    Role.SUPERADMIN: frozenset(Perm),
}

STAFF_ROLES = frozenset(r.value for r in Role)


def permissions_for(roles: list[str] | tuple[str, ...]) -> frozenset[Perm]:
    perms: set[Perm] = set()
    for role in roles:
        perms |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(perms)


def is_staff(roles: list[str] | tuple[str, ...]) -> bool:
    return any(r in STAFF_ROLES for r in roles)
