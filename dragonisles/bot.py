"""Literal DragonIsles bot policy."""

from dataclasses import dataclass
from collections import Counter
from itertools import combinations, product
from functools import lru_cache
from typing import Mapping, Protocol, Sequence

from .cards import Card
from .characters import (
    Character,
    hand_limit_bonus,
    roll_bonus,
    reroll_count,
    track_reward,
)
from .combos import Combo, best_combo, enumerate_combos
from .dice import DIE_FACES, probability_at_least
from .encounters import ENCOUNTER_TYPES, Encounter
from .potions import DRAW_TWO, PLUS_TWO, PURGE, PotionToken
from .scoring import TrophyEvent, score_player, trophy_holders, winner_key
from .treasures import Treasure, expected_treasure_value, green_trigger

METHOD_ATTAINABILITY = {
    "sneak": 0.90,
    "steal": 0.67,
    "strike": 0.90,
}


@dataclass(frozen=True, slots=True)
class DecisionContext:
    hand: Sequence[Card]
    encounters: Sequence[Encounter]
    market: Sequence[Card] = ()
    character: Character | None = None
    potions: Sequence[PotionToken] = ()
    treasures: Sequence[Treasure] = ()
    die_faces: tuple[int, ...] = DIE_FACES
    skill_levels: Mapping[str, int] = ()
    trophy_events: Sequence[TrophyEvent] = ()
    player_index: int = 0
    completed_encounters: Sequence[Encounter] = ()
    coins: int = 0
    opponent_encounters: Sequence[Encounter] = ()
    opponent_treasures: Sequence[Treasure] = ()
    opponent_coins: int = 0
    opponent_character: Character | None = None
    opponent_challenge_cards: Sequence[Card] = ()
    adventure_cards: Sequence[Card] = ()


@dataclass(frozen=True, slots=True)
class Decision:
    action: str
    encounter: Encounter | None = None
    combo: tuple[Card, ...] = ()
    method: str | None = None
    probability: float = 0.0
    potion: PotionToken | None = None


class Policy(Protocol):
    def choose(self, context: DecisionContext) -> Decision: ...

    def choose_discards(
        self, context: DecisionContext, count: int
    ) -> tuple[Card, ...]: ...

    def choose_track(self, context: DecisionContext, tracks: Sequence[str]) -> str: ...

    def choose_prepare_source(self, context: DecisionContext) -> Card | str: ...

    def choose_reroll_indices(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        rolls: tuple[int, ...],
    ) -> tuple[int, ...]: ...


def _targets(encounter: Encounter) -> tuple[int, int, int]:
    return tuple(
        encounter.target_for(method) for method in ("sneak", "steal", "strike")
    )


def _method_bonus(context: DecisionContext, encounter: Encounter, method: str) -> int:
    if context.character is None:
        return 0
    return roll_bonus(
        context.character,
        dict(context.skill_levels),
        method=method,
        is_sea=encounter.is_sea,
    )


def _rerolls(context: DecisionContext) -> int:
    if context.character is None:
        return 0
    return reroll_count(context.character, dict(context.skill_levels))


def _reroll_ones(context: DecisionContext) -> bool:
    return any(
        treasure.is_green and green_trigger(treasure.passive_effect) == "roll_ones"
        for treasure in context.treasures
    )


def challenge_probability(
    context: DecisionContext,
    encounter: Encounter,
    method: str,
    dice_count: int,
) -> float:
    """Return the exact success probability for a selected challenge."""
    return probability_at_least(
        dice_count,
        encounter.target_for(method),
        bonus=_method_bonus(context, encounter, method),
        faces=context.die_faces,
        rerolls=_rerolls(context),
        reroll_ones=_reroll_ones(context),
    )


@lru_cache(maxsize=4096)
def _best_probability(
    hand: tuple[Card, ...],
    targets: tuple[int, int, int],
    bonuses: tuple[int, int, int],
    die_faces: tuple[int, ...],
    rerolls: int,
    reroll_ones: bool,
) -> float:
    return max(
        (
            result[1]
            for method, target, bonus in zip(
                ("sneak", "steal", "strike"), targets, bonuses
            )
            if (
                result := best_combo(
                    hand,
                    method=method,
                    target=target,
                    bonus=bonus,
                    faces=die_faces,
                    rerolls=rerolls,
                    reroll_ones=reroll_ones,
                )
            )
            is not None
        ),
        default=0.0,
    )


def _encounter_probability(
    context: DecisionContext, hand: tuple[Card, ...], encounter: Encounter
) -> float:
    return _best_probability(
        hand,
        _targets(encounter),
        tuple(
            _method_bonus(context, encounter, method)
            for method in ("sneak", "steal", "strike")
        ),
        context.die_faces,
        _rerolls(context),
        _reroll_ones(context),
    )


def _useful_face_up_card(
    context: DecisionContext,
    cards: Sequence[Card],
    target: Encounter | None,
) -> Card | None:
    if not cards:
        return None
    current = tuple(context.hand)
    encounters = tuple(context.encounters)
    baseline_target = (
        _encounter_probability(context, current, target) if target is not None else 0.0
    )
    baseline_row = max(
        (
            _encounter_probability(context, current, encounter)
            for encounter in encounters
        ),
        default=0.0,
    )
    scored: list[tuple[float, float, Card]] = []
    for card in cards:
        candidate = (*current, card)
        target_gain = (
            _encounter_probability(context, candidate, target) - baseline_target
            if target is not None
            else 0.0
        )
        row_gain = max(
            (
                _encounter_probability(context, candidate, encounter) - baseline_row
                for encounter in encounters
            ),
            default=0.0,
        )
        scored.append((target_gain, row_gain, card))
    target_gain, row_gain, best_card = max(scored, key=lambda item: (item[0], item[1]))
    return (
        best_card
        if target_gain > 1e-12 or (target is None and row_gain > 1e-12)
        else None
    )


def _adventure_draw_value(context: DecisionContext, draw_count: int) -> float:
    """Estimate the value of keeping the best card from a random draw."""
    if not context.adventure_cards or not context.encounters:
        return 0.0
    current = tuple(context.hand)
    baseline = [
        _encounter_probability(context, current, encounter)
        for encounter in context.encounters
    ]
    card_values = [
        _adventure_card_value(context, card, baseline)
        for card in context.adventure_cards
    ]
    draw_count = min(draw_count, len(card_values))
    draws = list(combinations(range(len(card_values)), draw_count))
    if not draws:
        return 0.0
    return sum(max(card_values[index] for index in drawn) for drawn in draws) / len(
        draws
    )


def _adventure_card_value(
    context: DecisionContext, card: Card, baseline: Sequence[float]
) -> float:
    """Return one card's best VP-weighted encounter probability gain."""
    current = tuple(context.hand)
    return max(
        (
            (
                _encounter_probability(context, (*current, card), encounter)
                - baseline[encounter_index]
            )
            * encounter.victory_points
            for encounter_index, encounter in enumerate(context.encounters)
        ),
        default=0.0,
    )


def _public_plan_value(
    context: DecisionContext,
    hand: tuple[Card, ...],
    encounters: tuple[Encounter, ...],
) -> float:
    if not encounters:
        return 0.0
    best = 0.0
    for encounter in encounters:
        for method in ("sneak", "steal", "strike"):
            if method == encounter.blocked_method:
                continue
            result = best_combo(
                hand,
                method=method,
                target=encounter.target_for(method),
                bonus=_method_bonus(context, encounter, method),
                faces=context.die_faces,
                rerolls=_rerolls(context),
                reroll_ones=_reroll_ones(context),
            )
            if result is None:
                continue
            combo, probability = result
            reward = encounter.rewards.get(method)
            reward_value = (
                0.0
                if reward is None
                else reward.coins
                + (expected_treasure_value() if reward.treasure else 0.0)
            )
            remaining = list(hand)
            for card in combo.cards:
                remaining.remove(card)
            next_encounters = tuple(
                candidate for candidate in encounters if candidate != encounter
            )
            value = probability * (
                encounter.victory_points
                + reward_value
                + _public_plan_value(
                    context, tuple(remaining), next_encounters
                )
            )
            best = max(best, value)
    return best


class LiteralPolicy:
    """Reconstructed progression and threshold policy."""

    def __init__(self, threshold: float = 0.50, monk_threshold: float = 0.10):
        self.threshold = threshold
        self.monk_threshold = monk_threshold

    def choose(self, context: DecisionContext) -> Decision:
        encounter = self._target_encounter(context)
        endgame = len(context.completed_encounters) == 7
        rejected_endgame_target = (
            endgame
            and encounter is not None
            and not self._would_close_out_a_win(context, encounter)
        )
        if rejected_endgame_target:
            decision = self._non_attempt_decision(
                context, ignore_plannable_target=True
            )
        else:
            decision = self._choose_core(
                context,
                encounter,
                maximize_probability=self._must_get_encounter(context, encounter),
            )
        if decision.action != "prepare" or encounter is None:
            return decision
        ordered = sorted(
            context.encounters,
            key=lambda candidate: self._encounter_order_key(context, candidate),
        )
        for fallback in ordered:
            if fallback == encounter:
                continue
            if endgame and not self._would_close_out_a_win(context, fallback):
                continue
            decision = self._choose_core(context, fallback)
            if decision.action != "prepare":
                return decision
        return self._non_attempt_decision(
            context, ignore_plannable_target=rejected_endgame_target
        )

    def _must_get_encounter(
        self, context: DecisionContext, encounter: Encounter | None
    ) -> bool:
        return (
            encounter is not None
            and len(context.completed_encounters) == 7
            and context.character is not None
            and context.opponent_character is not None
            and self._would_close_out_a_win(context, encounter)
        )

    def _target_encounter(self, context: DecisionContext) -> Encounter | None:
        if not context.encounters:
            return None
        ordered = tuple(
            sorted(
                context.encounters,
                key=lambda encounter: self._encounter_order_key(context, encounter),
            )
        )
        if len(context.completed_encounters) == 7:
            for encounter in ordered:
                if self._encounter_is_winnable(
                    context, encounter
                ) and self._would_close_out_a_win(context, encounter):
                    return encounter
        slot = min(len(context.completed_encounters) // 2, 3)
        scheduled = ordered[min(slot, len(ordered) - 1)]
        if self._encounter_is_winnable(context, scheduled):
            return scheduled
        scheduled_index = ordered.index(scheduled)
        winnable = [
            encounter
            for encounter in ordered[: scheduled_index + 1]
            if self._encounter_is_winnable(context, encounter)
        ]
        return winnable[-1] if winnable else scheduled

    def _would_close_out_a_win(
        self, context: DecisionContext, encounter: Encounter
    ) -> bool:
        if context.character is None or context.opponent_character is None:
            return True
        projected_events = list(context.trophy_events)
        if len(context.completed_encounters) != 7:
            projected_events.append(
                (context.player_index, encounter.encounter_type, encounter.icons)
            )
        projected = score_player(
            [*context.completed_encounters, encounter],
            context.treasures,
            context.coins,
            context.character,
            player_index=context.player_index,
            trophy_event_log=projected_events,
            skill_levels=dict(context.skill_levels),
        )
        opponent = score_player(
            context.opponent_encounters,
            context.opponent_treasures,
            context.opponent_coins,
            context.opponent_character,
            player_index=1 - context.player_index,
            trophy_event_log=projected_events,
            skill_levels={},
        )
        return winner_key(projected) >= winner_key(opponent)

    def _encounter_order_key(
        self, context: DecisionContext, encounter: Encounter
    ) -> tuple[float, float, float, float, str]:
        adjusted_targets = tuple(
            encounter.target_for(method) / METHOD_ATTAINABILITY[method]
            for method in ("sneak", "steal", "strike")
            if method != encounter.blocked_method
        )
        reward = max(
            (
                self._method_reward_score(context, encounter, method)
                for method in ("sneak", "steal", "strike")
                if method != encounter.blocked_method
            ),
            default=0.0,
        )
        return (
            min(adjusted_targets, default=0.0),
            max(adjusted_targets, default=0.0),
            min(adjusted_targets, default=0.0),
            -reward,
            encounter.name,
        )

    def _encounter_is_winnable(
        self, context: DecisionContext, encounter: Encounter
    ) -> bool:
        return any(
            result[1] > self._threshold(context)
            for method in ("sneak", "steal", "strike")
            if method != encounter.blocked_method
            and (
                result := best_combo(
                    context.hand,
                    method=method,
                    target=encounter.target_for(method),
                    bonus=_method_bonus(context, encounter, method),
                    faces=context.die_faces,
                    rerolls=_rerolls(context),
                    reroll_ones=_reroll_ones(context),
                )
            )
            is not None
        )

    def _method_reward_score(
        self, context: DecisionContext, encounter: Encounter, method: str
    ) -> float:
        reward = encounter.rewards.get(method)
        score = (
            0.0
            if reward is None
            else reward.coins + (expected_treasure_value() if reward.treasure else 0.0)
        )
        if context.character is not None and context.character.name == "Warrior":
            combo = best_combo(
                context.hand,
                method=method,
                target=encounter.target_for(method),
                bonus=_method_bonus(context, encounter, method),
                faces=context.die_faces,
                rerolls=_rerolls(context),
                reroll_ones=_reroll_ones(context),
            )
            if combo is not None:
                score += _adventure_draw_value(context, 1)
        return score

    def _method_reward_priority(
        self, context: DecisionContext, encounter: Encounter, method: str
    ) -> int:
        return int(self._method_reward_score(context, encounter, method) > 0)

    def _should_challenge(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        result: tuple[Combo, float],
    ) -> bool:
        return result[1] > self._threshold(context)

    def _method_choice(
        self,
        context: DecisionContext,
        encounter: Encounter,
        options: Sequence[tuple[str, tuple[Combo, float]]],
        *,
        maximize_probability: bool = False,
    ) -> tuple[str, tuple[Combo, float]]:
        qualifying = [
            item
            for item in options
            if self._should_challenge(context, encounter, item[0], item[1])
        ]
        pool = qualifying or list(options)
        if maximize_probability:
            return max(
                pool,
                key=lambda item: (
                    item[1][1],
                    self._challenge_option_value(
                        context, encounter, item[0], item[1], maximize_probability
                    ),
                ),
            )
        return max(
            pool,
            key=lambda item: self._challenge_option_value(
                context, encounter, item[0], item[1], maximize_probability
            ),
        )

    def _challenge_option_value(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        result: tuple[Combo, float],
        maximize_probability: bool = False,
    ) -> float:
        combo, probability = result
        reward_value = (
            encounter.victory_points
            + _trophy_gain(context, encounter)
            + self._method_reward_score(context, encounter, method)
        )
        future_hand_value = self._remaining_hand_value(context, encounter, combo)
        card_efficiency = 1.0 / combo.card_count
        probability_weight = 2.0 if maximize_probability else 1.0
        return (
            probability_weight * probability * reward_value
            + 0.25 * future_hand_value
            + 3.0 * card_efficiency
        )

    def _smallest_qualifying_combo(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        fallback: tuple[Combo, float],
        *,
        maximize_probability: bool = False,
    ) -> tuple[Combo, float]:
        if maximize_probability:
            return fallback
        minimum_cards = (
            1
            if _method_bonus(context, encounter, method) or encounter.target_for(method) != 3
            else 2
        )
        if (
            context.character is not None
            and context.character.warrior_draw_trigger
        ):
            minimum_cards = max(
                minimum_cards,
                len(context.hand)
                + 1
                - self._hand_limit(context),
            )
        candidates = []
        for combo in enumerate_combos(context.hand):
            if combo.method != method or combo.card_count < minimum_cards:
                continue
            probability = challenge_probability(
                context, encounter, method, combo.card_count
            )
            result = (combo, probability)
            if self._should_challenge(context, encounter, method, result):
                candidates.append(result)
        return (
            max(
                candidates,
                key=lambda item: self._challenge_option_value(
                    context,
                    encounter,
                    method,
                    item,
                    maximize_probability,
                ),
            )
            if candidates
            else fallback
        )

    @staticmethod
    def _remaining_hand_value(
        context: DecisionContext, encounter: Encounter, combo: Combo
    ) -> float:
        remaining = list(context.hand)
        for card in combo.cards:
            remaining.remove(card)
        return _public_plan_value(
            context,
            tuple(remaining),
            tuple(
                candidate
                for candidate in context.encounters
                if candidate != encounter
            ),
        )

    def choose_track(self, context: DecisionContext, tracks: Sequence[str]) -> str:
        method_choice = self._useful_method_track(context, tracks)
        if method_choice is not None:
            return method_choice
        if "trophy" in tracks and self._secured_trophy_count(context) >= 2:
            return "trophy"
        if "reroll" in tracks:
            return "reroll"
        if "hand_limit" in tracks and self._likely_to_discard(context):
            return "hand_limit"
        return max(
            tracks,
            key=lambda track: (
                self._reward_score(context, track),
                track,
            ),
        )

    def _useful_method_track(
        self, context: DecisionContext, tracks: Sequence[str]
    ) -> str | None:
        if context.character is None or not context.encounters:
            return None
        highest = max(
            context.encounters,
            key=lambda encounter: encounter.victory_points,
        )
        candidates: list[tuple[tuple[int, int, int, float, str], str]] = []
        for track in tracks:
            if track not in ("sneak", "steal", "strike", "sea"):
                continue
            if track == "sea" and not highest.is_sea:
                continue
            method = track if track != "sea" else "strike"
            if method == highest.blocked_method:
                continue
            before = _method_bonus(context, highest, method)
            levels = dict(context.skill_levels)
            levels[track] = levels.get(track, 0) + 1
            after = roll_bonus(
                context.character,
                levels,
                method=method,
                is_sea=highest.is_sea,
            )
            if after <= before:
                continue
            before_combo = best_combo(
                context.hand,
                method=method,
                target=highest.target_for(method),
                bonus=before,
                faces=context.die_faces,
                rerolls=_rerolls(context),
                reroll_ones=_reroll_ones(context),
            )
            after_combo = best_combo(
                context.hand,
                method=method,
                target=highest.target_for(method),
                bonus=after,
                faces=context.die_faces,
                rerolls=_rerolls(context),
                reroll_ones=_reroll_ones(context),
            )
            if after_combo is None:
                continue
            card_count = after_combo[0].card_count
            reward = track_reward(
                context.character,
                track,
                dict(context.skill_levels).get(track, 0) + 1,
            )
            reward_priority = (
                2
                if card_count in (5, 6) and reward in ("treasure", "potion")
                else (
                    2
                    if card_count not in (5, 6) and reward == "coin"
                    else 1 if reward is not None else 0
                )
            )
            probability_gain = after_combo[1] - (
                before_combo[1] if before_combo is not None else 0.0
            )
            candidates.append(
                (
                    (
                        highest.victory_points,
                        reward_priority,
                        -card_count,
                        probability_gain,
                        track,
                    ),
                    track,
                )
            )
        return max(candidates)[1] if candidates else None

    def _secured_trophy_count(self, context: DecisionContext) -> int:
        player_counts = Counter()
        opponent_counts = Counter()
        for player_index, encounter_type, amount in context.trophy_events:
            target = (
                player_counts
                if player_index == context.player_index
                else opponent_counts
            )
            target[encounter_type] += amount
        holders, _ = trophy_holders(
            context.trophy_events,
            player_count=max(context.player_index + 1, 2),
        )
        return sum(
            holder == context.player_index
            and player_counts[encounter_type] - opponent_counts[encounter_type] >= 1
            for encounter_type, holder in holders.items()
        )

    def _likely_to_discard(self, context: DecisionContext) -> bool:
        if context.character is None:
            return False
        limit = context.character.starting_hand_limit + hand_limit_bonus(
            context.character,
            dict(context.skill_levels),
        )
        return len(context.hand) >= limit - 1

    @staticmethod
    def _reward_score(context: DecisionContext, track: str) -> int:
        if context.character is None:
            return 0
        reward = track_reward(
            context.character,
            track,
            dict(context.skill_levels).get(track, 0) + 1,
        )
        if reward == "coin":
            return context.character.coin_multiplier
        return {"treasure": 3, "potion": 2}.get(reward, 0)

    def _threshold(self, context: DecisionContext) -> float:
        return self.threshold

    def _undesirable_card_count(self, context: DecisionContext) -> int:
        target = self._target_encounter(context)
        if target is None and not context.encounters:
            return 0
        current = tuple(context.hand)
        if target is not None:
            baseline = _encounter_probability(context, current, target)
        else:
            baseline = max(
                (
                    _encounter_probability(context, current, encounter)
                    for encounter in context.encounters
                ),
                default=0.0,
            )
        undesirable = 0
        for index in range(len(current)):
            candidate = current[:index] + current[index + 1 :]
            if target is not None:
                after = _encounter_probability(context, candidate, target)
            else:
                after = max(
                    (
                        _encounter_probability(context, candidate, encounter)
                        for encounter in context.encounters
                    ),
                    default=0.0,
                )
            if baseline - after <= 0:
                undesirable += 1
        return undesirable

    def _non_attempt_decision(
        self, context: DecisionContext, *, ignore_plannable_target: bool = False
    ) -> Decision:
        hand_limit = self._hand_limit(context)
        potion_draw_count = (
            context.character.potion_draw_count if context.character is not None else 0
        )
        if ignore_plannable_target or not any(
            self._encounter_is_winnable(context, encounter)
            for encounter in context.encounters
        ):
            purge = next((p for p in context.potions if p.kind == PURGE), None)
            if purge is not None:
                return Decision("use_potion", potion=purge)
        draw_two_draws = 2 + potion_draw_count
        draw_two = next((p for p in context.potions if p.kind == DRAW_TWO), None)
        if draw_two is not None and (
            len(context.hand) + draw_two_draws <= hand_limit
            or (
                self._undesirable_card_count(context) >= draw_two_draws
                and _adventure_draw_value(context, draw_two_draws) > 0
            )
        ):
            return Decision("use_potion", potion=draw_two)
        return Decision("prepare")

    def _choose_core(
        self,
        context: DecisionContext,
        encounter: Encounter | None,
        *,
        maximize_probability: bool = False,
    ) -> Decision:
        if encounter is None:
            return Decision("prepare")
        base_options: list[tuple[Encounter, str, tuple[Combo, float]]] = []
        options: list[tuple[str, tuple[Combo, float]]] = [
            (method, result)
            for method in ("sneak", "steal", "strike")
            if method != encounter.blocked_method
            and (
                result := best_combo(
                    context.hand,
                    method=method,
                    target=encounter.target_for(method),
                    bonus=_method_bonus(context, encounter, method),
                    faces=context.die_faces,
                    rerolls=_rerolls(context),
                    reroll_ones=_reroll_ones(context),
                )
            )
            is not None
        ]
        if options:
            options = [
                (
                    method,
                    self._smallest_qualifying_combo(
                        context,
                        encounter,
                        method,
                        result,
                        maximize_probability=maximize_probability,
                    ),
                )
                for method, result in options
            ]
            method, (combo, probability) = self._method_choice(
                context,
                encounter,
                options,
                maximize_probability=maximize_probability,
            )
            if self._should_challenge(context, encounter, method, (combo, probability)):
                return Decision(
                    "attempt",
                    encounter,
                    combo.cards,
                    method,
                    probability=probability,
                )
            base_options.extend(
                (encounter, candidate_method, candidate_result)
                for candidate_method, candidate_result in options
            )
        if any(potion.kind == PLUS_TWO for potion in context.potions):
            potion_options: list[tuple[float, Encounter, str, tuple[Combo, float]]] = []
            for encounter, method, (_, base_probability) in base_options:
                boosted = best_combo(
                    context.hand,
                    method=method,
                    target=encounter.target_for(method),
                    bonus=2 + _method_bonus(context, encounter, method),
                    faces=context.die_faces,
                    rerolls=_rerolls(context),
                    reroll_ones=_reroll_ones(context),
                )
                if boosted is not None and self._should_challenge(
                    context, encounter, method, boosted
                ):
                    potion_options.append(
                        (boosted[1] - base_probability, encounter, method, boosted)
                    )
            if potion_options:
                _, encounter, method, (combo, probability) = max(
                    potion_options, key=lambda item: item[0]
                )
                base_result = best_combo(
                    context.hand,
                    method=method,
                    target=encounter.target_for(method),
                    bonus=_method_bonus(context, encounter, method),
                    faces=context.die_faces,
                    rerolls=_rerolls(context),
                    reroll_ones=_reroll_ones(context),
                )
                return Decision(
                    "attempt",
                    encounter,
                    combo.cards,
                    method,
                    probability=(
                        base_result[1] if base_result is not None else probability
                    ),
                )
        return self._non_attempt_decision(context)

    def choose_plus_two_after_roll(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        rolled_total: int,
    ) -> bool:
        """Spend a potion only when success beats taking the failure potion."""
        plus_twos = sum(potion.kind == PLUS_TWO for potion in context.potions)
        if plus_twos == 0 or rolled_total >= encounter.target_for(method):
            return False
        if encounter.target_for(method) - rolled_total > 2:
            return False
        potion_value = 1.0 / plus_twos
        success_value = _encounter_value(context, encounter, method)
        return success_value - potion_value > potion_value

    def choose_reroll_indices(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        rolls: tuple[int, ...],
    ) -> tuple[int, ...]:
        limit = _rerolls(context)
        if not limit:
            return ()
        target = encounter.target_for(method)
        bonus = _method_bonus(context, encounter, method)
        base_probability = float(sum(rolls) + bonus >= target)
        best_probability = base_probability
        best_indices: tuple[int, ...] = ()
        for count in range(1, min(limit, len(rolls)) + 1):
            for indices in combinations(range(len(rolls)), count):
                probability = sum(
                    sum(
                        (
                            replacement[indices.index(index_position)]
                            if index_position in indices
                            else rolls[index_position]
                        )
                        for index_position in range(len(rolls))
                    )
                    + bonus
                    >= target
                    for replacement in product(context.die_faces, repeat=count)
                ) / (len(context.die_faces) ** count)
                if probability > best_probability:
                    best_probability = probability
                    best_indices = indices
        return best_indices

    @staticmethod
    def _hand_limit(context: DecisionContext) -> int:
        return (
            context.character.starting_hand_limit
            + hand_limit_bonus(context.character, dict(context.skill_levels))
            if context.character
            else 8
        )

    def choose_best_card(self, context: DecisionContext, cards: Sequence[Card]) -> Card:
        target = self._target_encounter(context)
        useful = _useful_face_up_card(context, cards, target)
        return useful if useful is not None else cards[0]

    def choose_best_treasure(
        self, context: DecisionContext, treasures: Sequence[Treasure]
    ) -> Treasure:
        return max(
            treasures, key=lambda treasure: self._treasure_value(context, treasure)
        )

    def _treasure_value(self, context: DecisionContext, treasure: Treasure) -> float:
        if treasure.is_orange:
            return float(treasure.victory_points)
        return expected_treasure_value()

    def choose_discards(self, context: DecisionContext, count: int) -> tuple[Card, ...]:
        remaining = list(context.hand)
        selected: list[Card] = []
        target = self._target_encounter(context)
        for _ in range(min(count, len(remaining))):
            if target is not None:
                baseline = _encounter_probability(context, tuple(remaining), target)
            else:
                baseline = max(
                    (
                        _encounter_probability(context, tuple(remaining), encounter)
                        for encounter in context.encounters
                    ),
                    default=0.0,
                )
            scored: list[tuple[float, Card]] = []
            for card in remaining:
                candidate = remaining.copy()
                candidate.remove(card)
                if target is not None:
                    after = _encounter_probability(context, tuple(candidate), target)
                else:
                    after = max(
                        (
                            _encounter_probability(context, tuple(candidate), encounter)
                            for encounter in context.encounters
                        ),
                        default=0.0,
                    )
                scored.append((baseline - after, card))
            _, discard = min(scored, key=lambda item: item[0])
            selected.append(discard)
            remaining.remove(discard)
        return tuple(selected)

    def choose_prepare_source(self, context: DecisionContext) -> Card | str:
        """Choose one source using the market currently visible to the bot."""
        if not context.market or not context.encounters:
            return "deck"
        current = tuple(context.hand)
        baseline = [
            _encounter_probability(context, current, encounter)
            for encounter in context.encounters
        ]
        market_gain, useful = max(
            (
                (_adventure_card_value(context, card, baseline), card)
                for card in context.market
            ),
            key=lambda item: item[0],
        )
        if market_gain <= 1e-12:
            return "deck"
        return (
            useful
            if market_gain > _adventure_draw_value(context, 1)
            else "deck"
        )


def _trophy_gain(context: DecisionContext, encounter: Encounter) -> int:
    if encounter.encounter_type not in ENCOUNTER_TYPES:
        return 0
    before, _ = trophy_holders(
        context.trophy_events,
        player_count=max(context.player_index + 1, 2),
    )
    after_events = (
        *context.trophy_events,
        (context.player_index, encounter.encounter_type, encounter.icons),
    )
    after, _ = trophy_holders(
        after_events,
        player_count=max(context.player_index + 1, 2),
    )
    return (
        3
        if after[encounter.encounter_type] == context.player_index
        and before[encounter.encounter_type] != context.player_index
        else 0
    )


def _encounter_value(
    context: DecisionContext, encounter: Encounter, method: str
) -> float:
    reward = encounter.rewards.get(method)
    if reward is None:
        return float(encounter.victory_points)
    return (
        encounter.victory_points
        + _trophy_gain(context, encounter)
        + reward.coins
        + (expected_treasure_value() if reward.treasure else 0.0)
    )


class MonkPolicy(LiteralPolicy):
    """Literal progression with Monk's expected-roll challenge condition."""

    def _should_challenge(
        self,
        context: DecisionContext,
        encounter: Encounter,
        method: str,
        result: tuple[Combo, float],
    ) -> bool:
        expected_roll = result[0].card_count * (
            sum(context.die_faces) / len(context.die_faces)
        ) + _method_bonus(context, encounter, method)
        return encounter.target_for(method) < expected_roll + 2


class PiratePolicy(LiteralPolicy):
    """Literal progression with Pirate's doubled coin value."""

    def _method_reward_score(
        self, context: DecisionContext, encounter: Encounter, method: str
    ) -> float:
        reward = encounter.rewards.get(method)
        if reward is None:
            return 0.0
        return 2 * reward.coins + (
            expected_treasure_value() if reward.treasure else 0.0
        )


class TraderPolicy(LiteralPolicy):
    """Literal progression that values the possibilities from Trader draws."""

    def _method_reward_score(
        self, context: DecisionContext, encounter: Encounter, method: str
    ) -> float:
        reward = encounter.rewards.get(method)
        if reward is None:
            return 0.0
        return (
            float(reward.coins)
            + (expected_treasure_value() if reward.treasure else 0.0)
            + (_adventure_draw_value(context, 3) if reward.treasure else 0.0)
        )

    def _method_reward_priority(
        self, context: DecisionContext, encounter: Encounter, method: str
    ) -> int:
        reward = encounter.rewards.get(method)
        if reward is None:
            return 0
        return int(round(self._method_reward_score(context, encounter, method) * 100))


def policy_for_character(character: Character) -> LiteralPolicy:
    if character.name == "Monk":
        return MonkPolicy()
    if character.name == "Pirate":
        return PiratePolicy()
    if character.name == "Trader":
        return TraderPolicy()
    return LiteralPolicy()
