from dragonisles.cards import Card
from dragonisles.combos import METHOD_SHAPES, best_combo, enumerate_combos, is_legal


def test_verified_method_shapes():
    assert METHOD_SHAPES == {
        "sneak": "run",
        "steal": "same_number",
        "strike": "same_suit",
    }


def test_wild_completes_sneak_run():
    cards = [Card("red", 2), Card("blue", 4), Card.wild_card()]
    assert is_legal(cards, "sneak")
    assert any(combo.method == "sneak" for combo in enumerate_combos(cards))


def test_wild_completes_steal_and_strike():
    wild = Card.wild_card()
    assert is_legal([Card("red", 5), Card("blue", 5), wild], "steal")
    assert is_legal([Card("red", 5), Card("red", 8), wild], "strike")


def test_best_combo_prefers_probability_then_fewer_cards():
    hand = [Card("red", 1), Card("red", 2), Card("red", 3), Card("blue", 4)]
    combo, probability = best_combo(hand, method="strike", target=1)
    assert combo.card_count == 1
    assert probability == 1


def test_a_single_card_is_a_legal_one_die_play():
    card = Card("red", 5)
    assert all(is_legal([card], method) for method in METHOD_SHAPES)
    assert all(is_legal([Card.wild_card()], method) for method in METHOD_SHAPES)
    assert {combo.method for combo in enumerate_combos([card])} == set(METHOD_SHAPES)


def test_no_cards_is_never_a_legal_play():
    assert not any(is_legal([], method) for method in METHOD_SHAPES)
