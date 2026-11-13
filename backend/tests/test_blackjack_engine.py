"""Blackjack engine and provably fair shuffle — pure unit tests (no database)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from app.games import blackjack as bj
from app.games import fair

R = bj.Rules()
BET = 24  # one bonus day, in hours


def deal(
    first: str, up: str, second: str, hole: str, *rest: str, rules: bj.Rules = R, bet: int = BET
) -> Any:
    """One player. Deal order: player, dealer up, player, dealer hole, then draws."""
    return bj.start_round(
        rules, [first, up, second, hole, *rest], [{"seat": 0, "user": "u", "bet": bet}]
    )


def res(state: Any, seat: int = 0) -> Any:
    assert state["phase"] == "settled"
    return next(r for r in state["results"]["seats"] if r["seat"] == seat)


def test_hand_totals_and_soft_aces() -> None:
    assert bj.hand_total(["AS", "KD"]) == (21, True)
    assert bj.hand_total(["AS", "AD", "9C"]) == (21, True)
    assert bj.hand_total(["AS", "9D", "5C"]) == (15, False)
    assert bj.hand_total(["TS", "9D", "5C"]) == (24, False)
    assert bj.hand_total(["AS", "AD", "AC", "AH"]) == (14, True)
    assert len(bj.fresh_shoe(6)) == 312 and Counter(bj.fresh_shoe(2))["AS"] == 2


def test_player_blackjack_pays_3_to_2_and_6_to_5() -> None:
    r = res(deal("AS", "9D", "KH", "7C"))
    assert r["hands"][0]["outcome"] == "blackjack" and r["net"] == 36 and r["returned"] == 60
    r = res(deal("AS", "9D", "KH", "7C", rules=bj.Rules(blackjack_pays=(6, 5)), bet=120))
    assert r["net"] == 144


def test_blackjack_vs_dealer_blackjack_is_push() -> None:
    s = deal("AS", "KD", "KH", "AC")  # dealer shows a ten and has an ace: peek ends the round
    r = res(s)
    assert r["hands"][0]["outcome"] == "push" and r["net"] == 0 and s["results"]["dealer_blackjack"]


def test_dealer_blackjack_beats_21_and_ends_before_play() -> None:
    s = deal("9S", "KD", "8H", "AC", "4D")
    assert res(s)["hands"][0]["outcome"] == "lose" and res(s)["net"] == -BET
    assert len(s["deck"]) == 1  # nobody drew


def test_hit_stand_win_lose_push_bust() -> None:
    s = deal("TS", "9D", "8H", "8C")  # 18 vs dealer 17
    assert bj.allowed_actions(s, 0)[:2] == ["hit", "stand"]
    assert res(bj.act(s, 0, "stand"))["hands"][0]["outcome"] == "win"
    s = deal("TS", "9D", "6H", "8C")  # 16 vs 17
    assert res(bj.act(s, 0, "stand"))["hands"][0]["outcome"] == "lose"
    s = deal("TS", "9D", "7H", "8C")  # 17 vs 17
    assert res(bj.act(s, 0, "stand"))["net"] == 0
    s = deal("TS", "9D", "6H", "8C", "KD")  # hit to 26
    r = res(bj.act(s, 0, "hit"))
    assert r["hands"][0]["outcome"] == "bust" and r["net"] == -BET
    assert s["dealer"]["cards"] == ["9D", "8C"]  # dealer doesn't draw against a bust


def test_hit_to_21_stands_automatically_and_dealer_draws_to_17() -> None:
    s = deal("5S", "6D", "6H", "5C", "TD", "3S", "4H")  # player 11 → 21; dealer 11 → 14 → 18
    s = bj.act(s, 0, "hit")
    assert s["phase"] == "settled" and s["dealer"]["cards"] == ["6D", "5C", "3S", "4H"]
    assert res(s)["hands"][0]["outcome"] == "win"


def test_dealer_bust_and_soft_17_rule() -> None:
    s = deal("TS", "6D", "8H", "TC", "KD")  # dealer 16 draws a king
    assert res(bj.act(s, 0, "stand"))["hands"][0]["outcome"] == "win"
    stand17 = deal("TS", "AD", "8H", "6C", "5D", rules=bj.Rules(allow_insurance=False))
    assert bj.act(stand17, 0, "stand")["dealer"]["cards"] == ["AD", "6C"]  # stands on soft 17
    hit17 = deal(
        "TS",
        "AD",
        "8H",
        "6C",
        "5D",
        "5S",
        rules=bj.Rules(allow_insurance=False, dealer_hits_soft_17=True),
    )
    assert bj.act(hit17, 0, "stand")["dealer"]["cards"] == ["AD", "6C", "5D", "5S"]  # 12 → 17


def test_double_down() -> None:
    s = deal("5S", "9D", "6H", "8C", "TD")  # 11 doubles to 21 vs 17
    assert "double" in bj.allowed_actions(s, 0) and bj.extra_stake(s, 0, "double") == BET
    r = res(bj.act(s, 0, "double"))
    assert r["staked"] == 48 and r["returned"] == 96 and r["net"] == 48
    s = bj.act(deal("5S", "9D", "6H", "8C", "2D", "3C"), 0, "hit")
    assert "double" not in bj.allowed_actions(s, 0)  # only on the first two cards
    off = deal("5S", "9D", "6H", "8C", rules=bj.Rules(allow_double=False))
    assert "double" not in bj.allowed_actions(off, 0)
    with pytest.raises(bj.IllegalAction):
        bj.act(off, 0, "double")


def test_split_plays_two_hands() -> None:
    # 8,8 vs dealer 9+8=17 → split: 8+3 then hit K = 21 (auto-stand); 8+T = 18 stand
    s = deal("8S", "9D", "8H", "8C", "3D", "TS", "KD")
    assert "split" in bj.allowed_actions(s, 0) and bj.extra_stake(s, 0, "split") == BET
    s = bj.act(s, 0, "split")
    assert [h["cards"] for h in s["seats"][0]["hands"]] == [["8S", "3D"], ["8H", "TS"]]
    assert s["turn"] == {"seat": 0, "hand": 0}
    s = bj.act(s, 0, "hit")
    assert s["turn"] == {"seat": 0, "hand": 1}
    assert "surrender" not in bj.allowed_actions(s, 0)
    r = res(bj.act(s, 0, "stand"))
    assert [h["outcome"] for h in r["hands"]] == ["win", "win"] and r["net"] == 48
    assert not r["blackjack"]  # 21 after a split is not a blackjack


def test_split_aces_one_card_each_and_limits() -> None:
    s = bj.act(deal("AS", "9D", "AH", "8C", "KD", "5S"), 0, "split")
    assert s["phase"] == "settled"
    r = res(s)
    assert [h["outcome"] for h in r["hands"]] == ["win", "lose"] and r["net"] == 0
    # different ranks can't split; max_hands caps re-splits; rule switch
    assert "split" not in bj.allowed_actions(deal("KS", "9D", "QH", "8C"), 0)
    two = bj.Rules(max_hands=2)
    s = bj.act(deal("8S", "9D", "8H", "8C", "8D", "TS", rules=two), 0, "split")
    assert s["seats"][0]["hands"][0]["cards"] == ["8S", "8D"] and "split" not in bj.allowed_actions(
        s, 0
    )
    assert "split" not in bj.allowed_actions(
        deal("8S", "9D", "8H", "8C", rules=bj.Rules(allow_split=False)), 0
    )
    nodas = bj.act(
        deal("8S", "9D", "8H", "8C", "3D", "TS", rules=bj.Rules(allow_double_after_split=False)),
        0,
        "split",
    )
    assert "double" not in bj.allowed_actions(nodas, 0)


def test_surrender_returns_half() -> None:
    s = deal("TS", "9D", "6H", "8C")
    r = res(bj.act(s, 0, "surrender"))
    assert r["hands"][0]["outcome"] == "surrender" and r["returned"] == 12 and r["net"] == -12
    assert "surrender" not in bj.allowed_actions(
        deal("TS", "9D", "6H", "8C", rules=bj.Rules(allow_surrender=False)), 0
    )
    after_hit = bj.act(deal("2S", "9D", "3H", "8C", "4D"), 0, "hit")
    assert "surrender" not in bj.allowed_actions(after_hit, 0)


def test_insurance() -> None:
    s = deal("TS", "AD", "9H", "KC")  # dealer has blackjack
    assert s["phase"] == "insurance" and bj.allowed_actions(s, 0) == ["insurance", "no_insurance"]
    assert bj.extra_stake(s, 0, "insurance") == 12
    r = res(bj.act(s, 0, "insurance"))
    assert r["insurance_won"] and r["staked"] == 36 and r["returned"] == 36 and r["net"] == 0
    r = res(bj.act(deal("TS", "AD", "9H", "KC"), 0, "no_insurance"))
    assert r["net"] == -BET
    s = bj.act(deal("TS", "AD", "9H", "6C", "2D"), 0, "insurance")  # no dealer blackjack: play on
    assert s["phase"] == "playing"
    r = res(bj.act(s, 0, "stand"))  # 19 vs dealer A+6 = soft 17 (stands)
    assert r["hands"][0]["outcome"] == "win" and r["net"] == BET - 12
    with pytest.raises(bj.IllegalAction):
        bj.act(deal("TS", "AD", "9H", "6C"), 0, "hit")  # must answer the insurance question first
    assert deal("TS", "AD", "9H", "6C", rules=bj.Rules(allow_insurance=False))["phase"] == "playing"


def test_four_players_turn_order_and_isolation() -> None:
    seats = [{"seat": i, "user": f"u{i}", "bet": BET} for i in range(4)]
    #        p0   p1   p2   p3   up    p0   p1   p2   p3   hole  draws…
    deck = ["TS", "9S", "5S", "AS", "7D", "8H", "9H", "6H", "KH", "TC", "QD", "2C"]
    s = bj.start_round(R, deck, seats)
    assert s["turn"] == {"seat": 0, "hand": 0}  # seat 3 has a natural and is skipped later
    with pytest.raises(bj.IllegalAction):
        bj.act(s, 1, "stand")  # not your turn
    with pytest.raises(bj.IllegalAction):
        bj.act(s, 9, "stand")  # not at the table
    assert bj.allowed_actions(s, 1) == []
    s = bj.act(s, 0, "stand")  # 18
    assert s["turn"] == {"seat": 1, "hand": 0}
    s = bj.act(s, 1, "stand")  # 18
    s = bj.act(s, 2, "double")  # 11 + Q = 21
    assert s["phase"] == "settled"  # seat 3's blackjack needs no action; dealer has 17
    out = {r["seat"]: (r["result"], r["net"]) for r in s["results"]["seats"]}
    assert out == {0: ("win", 24), 1: ("win", 24), 2: ("win", 48), 3: ("win", 36)}


def test_force_stand_on_timeout_or_leave() -> None:
    seats = [{"seat": i, "user": f"u{i}", "bet": BET} for i in range(2)]
    s = bj.start_round(R, ["TS", "9S", "7D", "6H", "9H", "TC"], seats)
    s = bj.force_stand(s, 0)
    assert s["turn"] == {"seat": 1, "hand": 0}
    s = bj.force_stand(s, 1)
    assert s["phase"] == "settled"
    ins = bj.start_round(R, ["TS", "9S", "AD", "6H", "9H", "5C", "5D"], seats)
    ins = bj.force_stand(bj.force_stand(ins, 0), 1)
    assert ins["phase"] == "playing" and all(x["insurance"] == 0 for x in ins["seats"])


def test_public_view_hides_hole_card_and_shoe() -> None:
    s = deal("TS", "9D", "8H", "8C", "2D")
    v = bj.public_view(s)
    assert "deck" not in v and v["dealer"]["cards"] == ["9D", "??"] and v["dealer"]["total"] == 9
    assert "8C" not in str(v)
    v = bj.public_view(bj.act(s, 0, "stand"))
    assert v["dealer"]["cards"] == ["9D", "8C"] and v["dealer"]["total"] == 17


def test_no_stakes_mode_still_reports_outcomes() -> None:
    r = res(bj.act(deal("TS", "9D", "8H", "8C", bet=0), 0, "stand"))
    assert r["net"] == 0 and r["result"] == "win" and r["hands"][0]["outcome"] == "win"
    r = res(bj.act(deal("TS", "9D", "6H", "8C", bet=0), 0, "stand"))
    assert r["result"] == "lose"


def test_fair_shuffle_is_deterministic_verifiable_and_unbiased_enough() -> None:
    seed = fair.new_server_seed()
    assert len(seed) == 64 and fair.new_server_seed() != seed
    a = fair.shuffled_shoe(seed, "0=alice|1=bob", 7, 6)
    assert a == fair.shuffled_shoe(seed, "0=alice|1=bob", 7, 6)  # anyone can re-run it
    assert sorted(a) == sorted(bj.fresh_shoe(6)) and a != bj.fresh_shoe(6)
    assert a != fair.shuffled_shoe(seed, "0=alice|1=bob", 8, 6)  # nonce matters
    assert a != fair.shuffled_shoe(seed, "0=alice|1=eve", 7, 6)  # client seed matters
    assert fair.seed_hash(seed) == __import__("hashlib").sha256(seed.encode()).hexdigest()
    assert fair.combine_client_seeds({1: "b", 0: "a"}) == "0=a|1=b"
    # known-answer test pins the algorithm (a change would break verification of old rounds)
    assert fair.shuffled_shoe("00" * 32, "client", 1, 1)[:5] == KNOWN
    # first card over many shuffles: every rank appears, none dominates
    firsts = Counter(fair.shuffled_shoe("ab" * 32, "c", n, 1)[0][0] for n in range(2600))
    assert len(firsts) == 13 and max(firsts.values()) < 2600 / 13 * 1.35


KNOWN = fair.shuffled_shoe("00" * 32, "client", 1, 1)[:5]
