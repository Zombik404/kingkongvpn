"""Subscription lifecycle as a pure state machine (no I/O, fully unit-testable).

    (none) ──start_trial──► trialing ──period_end──► expired
       │                       │
       └──activate─────────────┴─────► active ◄──renew── past_due / grace
                                         │  ▲
                         payment_failed  │  │ renew
                                         ▼  │
                                      past_due
    active/past_due ──period_end──► grace (no cancel flag, grace_days > 0)
                                 ├► expired (no cancel flag, grace_days == 0)
                                 └► canceled (cancel_at_period_end)
    grace ──grace_end──► expired
    any entitled/ended ──refund──► refunded   (access ends immediately)
    any live ──revoke──► expired              (admin / account deletion)

`cancel` / `resume` only toggle `cancel_at_period_end`; access continues to period end.
Terminal states (expired, canceled, refunded) are never reactivated: a new purchase creates a
new subscription row, which keeps history auditable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace
from enum import StrEnum

from app.models.enums import SubscriptionStatus as S


class Event(StrEnum):
    START_TRIAL = "start_trial"
    ACTIVATE = "activate"
    RENEW = "renew"
    PAYMENT_FAILED = "payment_failed"
    CANCEL = "cancel"
    RESUME = "resume"
    PERIOD_END = "period_end"
    GRACE_END = "grace_end"
    REFUND = "refund"
    REVOKE = "revoke"
    EXTEND = "extend"  # add days to the current period (promo / support goodwill)


ENTITLED = frozenset({S.TRIALING, S.ACTIVE, S.PAST_DUE, S.GRACE})
TERMINAL = frozenset({S.EXPIRED, S.CANCELED, S.REFUNDED})


class InvalidTransition(ValueError):
    def __init__(self, status: S | None, event: Event) -> None:
        super().__init__(f"cannot apply {event.value} to {status.value if status else 'none'}")
        self.status = status
        self.event = event


@dataclass(frozen=True)
class SubState:
    status: S
    period_start: dt.datetime
    period_end: dt.datetime
    cancel_at_period_end: bool = False
    grace_until: dt.datetime | None = None
    canceled_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None

    @property
    def entitled(self) -> bool:
        return self.status in ENTITLED


def start(event: Event, *, now: dt.datetime, period_end: dt.datetime) -> SubState:
    """Create the initial state for a new subscription row."""
    if period_end <= now:
        raise ValueError("period_end must be in the future")
    if event is Event.START_TRIAL:
        return SubState(S.TRIALING, now, period_end)
    if event is Event.ACTIVATE:
        return SubState(S.ACTIVE, now, period_end)
    raise InvalidTransition(None, event)


def apply(
    state: SubState,
    event: Event,
    *,
    now: dt.datetime,
    period_end: dt.datetime | None = None,
    grace_days: int = 0,
    days: int = 0,
) -> SubState:
    s = state.status
    if event is Event.RENEW:
        if s not in (S.ACTIVE, S.PAST_DUE, S.GRACE, S.TRIALING):
            raise InvalidTransition(s, event)
        if period_end is None or period_end <= now:
            raise ValueError("renew needs a future period_end")
        start_at = (
            state.period_end if s in (S.ACTIVE, S.TRIALING) and state.period_end > now else now
        )
        return replace(
            state,
            status=S.ACTIVE,
            period_start=start_at,
            period_end=period_end,
            grace_until=None,
            cancel_at_period_end=False,
            canceled_at=None,
        )
    if event is Event.EXTEND:
        if s not in ENTITLED or days <= 0:
            raise InvalidTransition(s, event)
        base = max(state.period_end, now)
        new_status = S.ACTIVE if s in (S.GRACE, S.PAST_DUE, S.TRIALING) else s
        return replace(
            state, status=new_status, period_end=base + dt.timedelta(days=days), grace_until=None
        )
    if event is Event.PAYMENT_FAILED:
        if s is not S.ACTIVE:
            raise InvalidTransition(s, event)
        return replace(state, status=S.PAST_DUE)
    if event is Event.CANCEL:
        if s not in (S.TRIALING, S.ACTIVE, S.PAST_DUE) or state.cancel_at_period_end:
            raise InvalidTransition(s, event)
        return replace(state, cancel_at_period_end=True, canceled_at=now)
    if event is Event.RESUME:
        if s not in (S.TRIALING, S.ACTIVE, S.PAST_DUE) or not state.cancel_at_period_end:
            raise InvalidTransition(s, event)
        return replace(state, cancel_at_period_end=False, canceled_at=None)
    if event is Event.PERIOD_END:
        if state.period_end > now:
            raise InvalidTransition(s, event)
        if s is S.TRIALING:
            return replace(state, status=S.EXPIRED, ended_at=now)
        if s in (S.ACTIVE, S.PAST_DUE):
            if state.cancel_at_period_end:
                return replace(state, status=S.CANCELED, ended_at=now)
            if grace_days > 0:
                return replace(
                    state,
                    status=S.GRACE,
                    grace_until=state.period_end + dt.timedelta(days=grace_days),
                )
            return replace(state, status=S.EXPIRED, ended_at=now)
        raise InvalidTransition(s, event)
    if event is Event.GRACE_END:
        if s is not S.GRACE or state.grace_until is None or state.grace_until > now:
            raise InvalidTransition(s, event)
        return replace(state, status=S.EXPIRED, ended_at=now)
    if event is Event.REFUND:
        if s is S.REFUNDED:
            raise InvalidTransition(s, event)
        return replace(state, status=S.REFUNDED, ended_at=state.ended_at or now)
    if event is Event.REVOKE:
        if s not in ENTITLED:
            raise InvalidTransition(s, event)
        return replace(state, status=S.EXPIRED, ended_at=now)
    raise InvalidTransition(s, event)
