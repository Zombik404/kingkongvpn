from __future__ import annotations

import dataclasses
import datetime as dt
import itertools

import pytest

from app.models.enums import SubscriptionStatus as S
from app.subscriptions import state_machine as sm
from app.subscriptions.state_machine import Event as E

NOW = dt.datetime(2026, 11, 1, 12, 0, tzinfo=dt.UTC)
DAY = dt.timedelta(days=1)


def state(
    status: S,
    *,
    end: dt.datetime = NOW + 10 * DAY,
    cancel: bool = False,
    grace_until: dt.datetime | None = None,
) -> sm.SubState:
    return sm.SubState(
        status, NOW - 20 * DAY, end, cancel_at_period_end=cancel, grace_until=grace_until
    )


def test_start() -> None:
    t = sm.start(E.START_TRIAL, now=NOW, period_end=NOW + 3 * DAY)
    assert t.status is S.TRIALING and t.entitled
    a = sm.start(E.ACTIVATE, now=NOW, period_end=NOW + 30 * DAY)
    assert a.status is S.ACTIVE
    with pytest.raises(ValueError):
        sm.start(E.ACTIVATE, now=NOW, period_end=NOW)
    with pytest.raises(sm.InvalidTransition):
        sm.start(E.RENEW, now=NOW, period_end=NOW + DAY)


def test_trial_ends_expired_without_grace() -> None:
    s = sm.apply(state(S.TRIALING, end=NOW - DAY), E.PERIOD_END, now=NOW, grace_days=3)
    assert s.status is S.EXPIRED and s.ended_at == NOW and not s.entitled


@pytest.mark.parametrize("status", [S.ACTIVE, S.PAST_DUE])
def test_period_end_goes_to_grace_then_expired(status: S) -> None:
    s = sm.apply(state(status, end=NOW), E.PERIOD_END, now=NOW, grace_days=3)
    assert s.status is S.GRACE and s.entitled
    assert s.grace_until == NOW + 3 * DAY
    with pytest.raises(sm.InvalidTransition):
        sm.apply(s, E.GRACE_END, now=NOW + DAY)  # too early
    e = sm.apply(s, E.GRACE_END, now=NOW + 3 * DAY)
    assert e.status is S.EXPIRED and e.ended_at == NOW + 3 * DAY


def test_period_end_without_grace_days_expires() -> None:
    s = sm.apply(state(S.ACTIVE, end=NOW), E.PERIOD_END, now=NOW, grace_days=0)
    assert s.status is S.EXPIRED


def test_period_end_before_end_is_invalid() -> None:
    with pytest.raises(sm.InvalidTransition):
        sm.apply(state(S.ACTIVE, end=NOW + DAY), E.PERIOD_END, now=NOW)


def test_cancel_at_period_end_then_canceled() -> None:
    s = sm.apply(state(S.ACTIVE), E.CANCEL, now=NOW)
    assert s.status is S.ACTIVE and s.cancel_at_period_end and s.canceled_at == NOW
    with pytest.raises(sm.InvalidTransition):
        sm.apply(s, E.CANCEL, now=NOW)
    r = sm.apply(s, E.RESUME, now=NOW)
    assert not r.cancel_at_period_end and r.canceled_at is None
    with pytest.raises(sm.InvalidTransition):
        sm.apply(r, E.RESUME, now=NOW)
    ended = sm.apply(dataclasses.replace(s, period_end=NOW), E.PERIOD_END, now=NOW, grace_days=3)
    assert ended.status is S.CANCELED  # no grace after an explicit cancel


def test_payment_failed_and_renew_recovers() -> None:
    pd = sm.apply(state(S.ACTIVE), E.PAYMENT_FAILED, now=NOW)
    assert pd.status is S.PAST_DUE and pd.entitled
    with pytest.raises(sm.InvalidTransition):
        sm.apply(pd, E.PAYMENT_FAILED, now=NOW)
    a = sm.apply(pd, E.RENEW, now=NOW, period_end=NOW + 30 * DAY)
    assert a.status is S.ACTIVE and a.period_start == NOW


def test_renew_active_chains_periods_and_clears_cancel() -> None:
    s = sm.apply(
        state(S.ACTIVE, end=NOW + 2 * DAY, cancel=True), E.RENEW, now=NOW, period_end=NOW + 32 * DAY
    )
    assert s.period_start == NOW + 2 * DAY  # new period starts when the old one ends
    assert s.period_end == NOW + 32 * DAY
    assert not s.cancel_at_period_end
    g = sm.apply(
        state(S.GRACE, end=NOW - DAY, grace_until=NOW + DAY),
        E.RENEW,
        now=NOW,
        period_end=NOW + 30 * DAY,
    )
    assert g.status is S.ACTIVE and g.grace_until is None and g.period_start == NOW
    with pytest.raises(ValueError):
        sm.apply(state(S.ACTIVE), E.RENEW, now=NOW, period_end=NOW - DAY)


def test_extend() -> None:
    s = sm.apply(state(S.ACTIVE, end=NOW + DAY), E.EXTEND, now=NOW, days=7)
    assert s.period_end == NOW + 8 * DAY and s.status is S.ACTIVE
    t = sm.apply(state(S.TRIALING, end=NOW + DAY), E.EXTEND, now=NOW, days=7)
    assert t.status is S.ACTIVE  # promo/support on a trial converts it
    g = sm.apply(state(S.GRACE, end=NOW - DAY, grace_until=NOW + DAY), E.EXTEND, now=NOW, days=7)
    assert g.status is S.ACTIVE and g.period_end == NOW + 7 * DAY and g.grace_until is None
    with pytest.raises(sm.InvalidTransition):
        sm.apply(state(S.ACTIVE), E.EXTEND, now=NOW, days=0)


def test_refund_and_revoke() -> None:
    for status in (S.ACTIVE, S.TRIALING, S.GRACE, S.PAST_DUE, S.EXPIRED, S.CANCELED):
        r = sm.apply(state(status), E.REFUND, now=NOW)
        assert r.status is S.REFUNDED and not r.entitled
    with pytest.raises(sm.InvalidTransition):
        sm.apply(state(S.REFUNDED), E.REFUND, now=NOW)
    v = sm.apply(state(S.ACTIVE), E.REVOKE, now=NOW)
    assert v.status is S.EXPIRED and v.ended_at == NOW


@pytest.mark.parametrize("status,event", list(itertools.product(sm.TERMINAL, list(E))))
def test_terminal_states_never_reactivate(status: S, event: E) -> None:
    try:
        s = sm.apply(
            state(status, end=NOW - DAY),
            event,
            now=NOW,
            period_end=NOW + 30 * DAY,
            grace_days=3,
            days=5,
        )
    except (sm.InvalidTransition, ValueError):
        return
    assert not s.entitled, f"{event} reactivated {status}"


def test_entitled_set() -> None:
    assert {S.TRIALING, S.ACTIVE, S.PAST_DUE, S.GRACE} == sm.ENTITLED
    assert sm.ENTITLED.isdisjoint(sm.TERMINAL)
