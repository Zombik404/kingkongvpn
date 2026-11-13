"""Blackjack 21 engine — pure functions over a JSON-serialisable round state.

No database, no I/O, no randomness: the caller supplies the shuffled shoe (see fair.py), so the
same engine serves solo and multiplayer tables, tests and any client platform.

Cards are two characters: rank (A23456789TJQK) + suit (SHDC). Bets are integers in the caller's
unit (bonus hours; 0 in the no-stakes mode) — the engine never rounds anything except the
blackjack premium and surrender/insurance halves, which the caller keeps exact by using even units.

Round phases:  insurance → playing → settled   (insurance only when the dealer shows an ace)
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass
from typing import Any

RANKS = "A23456789TJQK"
SUITS = "SHDC"

State = dict[str, Any]


class IllegalAction(Exception):
    """The action isn't allowed in the current state (wrong turn, wrong phase, rule off…)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Rules:
    decks: int = 6
    dealer_hits_soft_17: bool = False
    blackjack_pays: tuple[int, int] = (3, 2)  # 3:2 (or 6:5)
    allow_double: bool = True
    allow_double_after_split: bool = True
    allow_split: bool = True
    max_hands: int = 4  # per seat, after splits
    allow_surrender: bool = True  # late surrender: first decision on the original hand
    allow_insurance: bool = True

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["blackjack_pays"] = list(self.blackjack_pays)
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Rules:
        d = dict(d)
        d["blackjack_pays"] = tuple(d.get("blackjack_pays", (3, 2)))
        return cls(**d)


def fresh_shoe(decks: int) -> list[str]:
    """Unshuffled shoe in canonical order (the input to the provably fair shuffle)."""
    return [r + s for _ in range(decks) for s in SUITS for r in RANKS]


def card_value(card: str) -> int:
    r = card[0]
    if r == "A":
        return 11
    return 10 if r in "TJQK" else int(r)


def hand_total(cards: list[str]) -> tuple[int, bool]:
    """Best total ≤ 21 if possible, and whether an ace still counts as 11 (a "soft" hand)."""
    total = sum(card_value(c) for c in cards)
    aces = sum(1 for c in cards if c[0] == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


def is_natural(hand: dict[str, Any]) -> bool:
    """Blackjack: an ace and a ten-value card as the first two cards of an unsplit hand."""
    return len(hand["cards"]) == 2 and not hand["from_split"] and hand_total(hand["cards"])[0] == 21


def _new_hand(cards: list[str], bet: int, *, from_split: bool = False) -> dict[str, Any]:
    return {
        "cards": cards,
        "bet": bet,
        "doubled": False,
        "from_split": from_split,
        "surrendered": False,
        "done": False,
    }


def _draw(state: State) -> str:
    if not state["deck"]:
        raise IllegalAction("shoe_empty")  # cannot happen with ≥1 deck and ≤4 seats
    return str(state["deck"].pop(0))


def start_round(rules: Rules, deck: list[str], seats: list[dict[str, Any]]) -> State:
    """Deal: one card to each seat in order, one to the dealer, a second to each seat, then the
    dealer's hole card. `seats` = [{"seat": int, "user": str, "bet": int}, …] in seat order."""
    if not seats:
        raise IllegalAction("no_players")
    state: State = {
        "rules": rules.to_json(),
        "deck": list(deck),
        "dealer": {"cards": []},
        "seats": [
            {
                "seat": s["seat"],
                "user": s["user"],
                "bet": int(s["bet"]),
                "insurance": None,
                "hands": [],
            }
            for s in seats
        ],
        "phase": "playing",
        "turn": None,
        "results": None,
    }
    firsts = [_draw(state) for _ in state["seats"]]
    up = _draw(state)
    seconds = [_draw(state) for _ in state["seats"]]
    hole = _draw(state)
    state["dealer"]["cards"] = [up, hole]
    for seat, a, b in zip(state["seats"], firsts, seconds, strict=True):
        hand = _new_hand([a, b], seat["bet"])
        hand["done"] = is_natural(hand)  # a natural stands by itself
        seat["hands"].append(hand)
    if up[0] == "A" and rules.allow_insurance:
        state["phase"] = "insurance"
        return state
    return _after_peek(state)


def _dealer_natural(state: State) -> bool:
    cards = state["dealer"]["cards"]
    return hand_total(cards[:2])[0] == 21


def _after_peek(state: State) -> State:
    """The dealer peeks with an ace or ten showing; a dealer blackjack ends the round at once."""
    up = state["dealer"]["cards"][0]
    if card_value(up) >= 10 and _dealer_natural(state):
        return _settle(state)
    state["phase"] = "playing"
    return _advance(state)


def decide_insurance(state: State, seat_no: int, take: bool) -> State:
    if state["phase"] != "insurance":
        raise IllegalAction("wrong_phase")
    seat = _seat(state, seat_no)
    if seat["insurance"] is not None:
        raise IllegalAction("already_decided")
    seat["insurance"] = seat["bet"] // 2 if take else 0
    if all(s["insurance"] is not None for s in state["seats"]):
        return _after_peek(state)
    return state


def insurance_pending(state: State) -> list[int]:
    if state["phase"] != "insurance":
        return []
    return [s["seat"] for s in state["seats"] if s["insurance"] is None]


def _seat(state: State, seat_no: int) -> dict[str, Any]:
    for s in state["seats"]:
        if s["seat"] == seat_no:
            return s  # type: ignore[no-any-return]
    raise IllegalAction("not_in_round")


def _advance(state: State) -> State:
    """Point `turn` at the next unfinished hand, or let the dealer play when none is left."""
    for seat in state["seats"]:
        for i, hand in enumerate(seat["hands"]):
            if not hand["done"]:
                state["turn"] = {"seat": seat["seat"], "hand": i}
                return state
    state["turn"] = None
    return _dealer_play(state)


def allowed_actions(state: State, seat_no: int) -> list[str]:
    """What the player in `seat_no` may do right now (empty when it isn't their turn)."""
    if state["phase"] == "insurance":
        seat = _seat(state, seat_no)
        return ["insurance", "no_insurance"] if seat["insurance"] is None else []
    turn = state.get("turn")
    if state["phase"] != "playing" or not turn or turn["seat"] != seat_no:
        return []
    rules = Rules.from_json(state["rules"])
    seat = _seat(state, seat_no)
    hand = seat["hands"][turn["hand"]]
    acts = ["hit", "stand"]
    two = len(hand["cards"]) == 2
    if two and rules.allow_double and (not hand["from_split"] or rules.allow_double_after_split):
        acts.append("double")
    if (
        two
        and rules.allow_split
        and hand["cards"][0][0] == hand["cards"][1][0]
        and len(seat["hands"]) < rules.max_hands
    ):
        acts.append("split")
    if two and rules.allow_surrender and not hand["from_split"] and len(seat["hands"]) == 1:
        acts.append("surrender")
    return acts


def extra_stake(state: State, seat_no: int, action: str) -> int:
    """How much more the player must put up for this action (double/split/insurance)."""
    seat = _seat(state, seat_no)
    if action == "insurance":
        return int(seat["bet"]) // 2
    if action in ("double", "split"):
        return int(seat["hands"][state["turn"]["hand"]]["bet"])
    return 0


def act(state: State, seat_no: int, action: str) -> State:
    """Apply one player action. Raises IllegalAction; returns the same (mutated) state."""
    if action in ("insurance", "no_insurance"):
        return decide_insurance(state, seat_no, action == "insurance")
    if action not in allowed_actions(state, seat_no):
        raise IllegalAction("not_allowed")
    seat = _seat(state, seat_no)
    idx = state["turn"]["hand"]
    hand = seat["hands"][idx]
    if action == "stand":
        hand["done"] = True
    elif action == "hit":
        hand["cards"].append(_draw(state))
        if hand_total(hand["cards"])[0] >= 21:  # bust, or 21 stands by itself
            hand["done"] = True
    elif action == "double":
        hand["bet"] *= 2
        hand["doubled"] = True
        hand["cards"].append(_draw(state))
        hand["done"] = True
    elif action == "surrender":
        hand["surrendered"] = True
        hand["done"] = True
    elif action == "split":
        a, b = hand["cards"]
        aces = a[0] == "A"
        first = _new_hand([a, _draw(state)], hand["bet"], from_split=True)
        second = _new_hand([b, _draw(state)], hand["bet"], from_split=True)
        for h in (first, second):  # split aces get one card each; 21 stands by itself
            h["done"] = aces or hand_total(h["cards"])[0] == 21
        seat["hands"][idx : idx + 1] = [first, second]
    return _advance(state)


def force_stand(state: State, seat_no: int) -> State:
    """Timeout / player left: decline insurance, stand on every unfinished hand of the seat."""
    if state["phase"] == "insurance":
        seat = _seat(state, seat_no)
        if seat["insurance"] is None:
            return decide_insurance(state, seat_no, False)
        return state
    if state["phase"] != "playing":
        return state
    seat = _seat(state, seat_no)
    for hand in seat["hands"]:
        hand["done"] = True
    return _advance(state)


def _dealer_play(state: State) -> State:
    rules = Rules.from_json(state["rules"])
    live = any(
        not h["surrendered"] and hand_total(h["cards"])[0] <= 21 and not is_natural(h)
        for s in state["seats"]
        for h in s["hands"]
    )
    cards = state["dealer"]["cards"]
    while live:  # the dealer only draws when somebody can still win or lose against the total
        total, soft = hand_total(cards)
        if total < 17 or (total == 17 and soft and rules.dealer_hits_soft_17):
            cards.append(_draw(state))
        else:
            break
    return _settle(state)


def _settle(state: State) -> State:
    rules = Rules.from_json(state["rules"])
    num, den = rules.blackjack_pays
    dealer_cards = state["dealer"]["cards"]
    dealer_total = hand_total(dealer_cards)[0]
    dealer_bj = len(dealer_cards) == 2 and dealer_total == 21
    results = []
    for seat in state["seats"]:
        staked = returned = 0
        hands = []
        for hand in seat["hands"]:
            hand["done"] = True
            bet = hand["bet"]
            total = hand_total(hand["cards"])[0]
            staked += bet
            if hand["surrendered"]:
                outcome, back = "surrender", bet - bet // 2
            elif total > 21:
                outcome, back = "bust", 0
            elif is_natural(hand):
                outcome, back = (
                    ("push", bet) if dealer_bj else ("blackjack", bet + bet * num // den)
                )
            elif dealer_bj:
                outcome, back = "lose", 0
            elif dealer_total > 21 or total > dealer_total:
                outcome, back = "win", 2 * bet
            elif total == dealer_total:
                outcome, back = "push", bet
            else:
                outcome, back = "lose", 0
            returned += back
            hands.append({"outcome": outcome, "total": total, "bet": bet, "returned": back})
        ins = seat["insurance"] or 0
        staked += ins
        if ins and dealer_bj:
            returned += 3 * ins  # insurance pays 2:1
        net = returned - staked
        results.append(
            {
                "seat": seat["seat"],
                "user": seat["user"],
                "staked": staked,
                "returned": returned,
                "net": net,
                "insurance": ins,
                "insurance_won": bool(ins and dealer_bj),
                "result": "win" if net > 0 else "lose" if net < 0 else _zero_result(hands),
                "blackjack": any(h["outcome"] == "blackjack" for h in hands),
                "hands": hands,
            }
        )
    state["phase"] = "settled"
    state["turn"] = None
    state["results"] = {
        "dealer_total": dealer_total,
        "dealer_blackjack": dealer_bj,
        "seats": results,
    }
    return state


def _zero_result(hands: list[dict[str, Any]]) -> str:
    """With no stakes every net is 0, so the round result comes from the hand outcomes."""
    score = sum(
        1
        if h["outcome"] in ("win", "blackjack")
        else -1
        if h["outcome"] in ("lose", "bust", "surrender")
        else 0
        for h in hands
    )
    return "win" if score > 0 else "lose" if score < 0 else "push"


def public_view(state: State) -> State:
    """The state without secrets: no shoe, and the hole card hidden until the round is settled."""
    settled = state["phase"] == "settled"
    cards = state["dealer"]["cards"]
    shown = cards if settled else [cards[0], "??"]
    return {
        "phase": state["phase"],
        "turn": state["turn"],
        "dealer": {
            "cards": shown,
            "total": hand_total(cards)[0] if settled else card_value(cards[0]),
        },
        "seats": [
            {
                "seat": s["seat"],
                "user": s["user"],
                "bet": s["bet"],
                "insurance": s["insurance"],
                "hands": [
                    {
                        "cards": h["cards"],
                        "total": hand_total(h["cards"])[0],
                        "soft": hand_total(h["cards"])[1],
                        "bet": h["bet"],
                        "doubled": h["doubled"],
                        "surrendered": h["surrendered"],
                        "done": h["done"],
                        "blackjack": is_natural(h),
                    }
                    for h in s["hands"]
                ],
            }
            for s in state["seats"]
        ],
        "results": copy.deepcopy(state["results"]),  # a copy: callers may trim the view
    }
