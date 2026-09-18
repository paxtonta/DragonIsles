"""End-game scoring and trophy calculation."""

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from .characters import Character, trophy_bonus
from .encounters import ENCOUNTER_TYPES, Encounter
from .treasures import Treasure


@dataclass(frozen=True, slots=True)
class ScoreBreakdown:
    encounter_points: int
    orange_treasure_points: int
    trophy_points: int
    coin_points: int
    total: int

    @property
    def coin_tiebreak(self) -> int:
        return self.coin_points

    @property
    def coin_percentage(self) -> float:
        return self.coin_points / self.total if self.total else 0.0


def winner_key(score: ScoreBreakdown) -> tuple[int, float]:
    """Rank final scores by VP, then by the share earned from coins."""
    return score.total, score.coin_percentage


TrophyEvent = tuple[int, str, int]


def trophy_holders(
    events: Sequence[TrophyEvent],
    *,
    player_count: int,
    encounter_types: tuple[str, ...] = ENCOUNTER_TYPES,
) -> tuple[dict[str, int | None], frozenset[int]]:
    """Resolve type trophies and every player's all-types trophy."""
    counts = [Counter() for _ in range(player_count)]
    holders: dict[str, int | None] = {
        encounter_type: None for encounter_type in encounter_types
    }
    all_types_holders: set[int] = set()
    for player_index, encounter_type, amount in events:
        counts[player_index][encounter_type] += amount
        holder = holders.get(encounter_type)
        if holder is None:
            if counts[player_index][encounter_type] > 0:
                holders[encounter_type] = player_index
        elif (
            player_index != holder
            and counts[player_index][encounter_type] > counts[holder][encounter_type]
        ):
            holders[encounter_type] = player_index
        if all(counts[player_index][item] > 0 for item in encounter_types):
            all_types_holders.add(player_index)
    return holders, frozenset(all_types_holders)


def score_player(
    encounters: Iterable[Encounter],
    treasures: Iterable[Treasure],
    coins: int,
    character: Character,
    *,
    other_players: Iterable[object] = (),
    encounter_types: tuple[str, ...] = ENCOUNTER_TYPES,
    player_index: int = 0,
    trophy_event_log: Sequence[TrophyEvent] | None = None,
    skill_levels: dict[str, int] | None = None,
) -> ScoreBreakdown:
    encounter_list = list(encounters)
    treasure_list = list(treasures)
    encounter_points = sum(card.victory_points for card in encounter_list)
    orange_points = sum(
        treasure.victory_points for treasure in treasure_list if treasure.is_orange
    )
    type_counts = Counter()
    for card in encounter_list:
        type_counts[card.encounter_type] += card.icons
    type_counts.update(
        treasure.encounter_type
        for treasure in treasure_list
        if treasure.is_orange and treasure.encounter_type
    )
    all_counts = []
    for other in other_players:
        if isinstance(other, tuple) and len(other) == 2:
            other_encounters, other_treasures = other
        else:
            other_encounters, other_treasures = other, ()
        counts = Counter()
        for card in other_encounters:
            counts[card.encounter_type] += card.icons
        counts.update(
            treasure.encounter_type
            for treasure in other_treasures
            if treasure.is_orange and treasure.encounter_type
        )
        all_counts.append(counts)
    if trophy_event_log is None:
        trophy_event_log = []
        for encounter_type, count in type_counts.items():
            if count:
                trophy_event_log.append((player_index, encounter_type, count))
        for other_index, counts in enumerate(all_counts, 1):
            for encounter_type, count in counts.items():
                if count:
                    trophy_event_log.append((other_index, encounter_type, count))
    event_player_count = max((event[0] for event in trophy_event_log), default=-1) + 1
    holders, all_types_holders = trophy_holders(
        trophy_event_log,
        player_count=max(player_index + 1, len(all_counts) + 1, event_player_count),
        encounter_types=encounter_types,
    )
    regular_trophy_count = sum(
        holders[encounter_type] == player_index for encounter_type in encounter_types
    )
    all_trophy_count = player_index in all_types_holders
    trophy_points = sum(
        3
        for encounter_type in encounter_types
        if holders[encounter_type] == player_index
    )
    if all_trophy_count:
        trophy_points += 5
    trophy_count = regular_trophy_count + all_trophy_count
    trophy_points += trophy_count * trophy_bonus(character, skill_levels or {})
    coin_points = coins * character.coin_multiplier
    return ScoreBreakdown(
        encounter_points,
        orange_points,
        trophy_points,
        coin_points,
        encounter_points + orange_points + trophy_points + coin_points,
    )
