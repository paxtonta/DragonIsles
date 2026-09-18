"""Data-driven encounter definitions."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from collections import Counter


ENCOUNTER_TYPES = ("dragon", "oni", "bakemono", "tsukumogami", "location")
METHODS = ("sneak", "steal", "strike")
DIFFICULTY_TIERS = ("very_easy", "easy", "moderate", "hard", "very_hard")
THEMATIC_BLOCKS_BY_FAMILY: dict[str, str] = {}
THEMATIC_BLOCKS_BY_ID = {
    "fushimi_inari_shrine": "steal",
    "kuraokami_of_the_snowpeak": "steal",
    "mizuchi_of_the_delta": "steal",
    "elder_mizuchi": "steal",
    "herald_of_watatsumi": "steal",
    "hannya_mask": "steal",
    "hannya_of_the_harbor_bridge": "steal",
    "hannya_of_the_black_waves": "steal",
    "young_kamaitachi": "steal",
    "kamaitachi_of_the_gale": "steal",
    "three_bladed_kamaitachi": "steal",
    "kamaitachi_of_the_sea_squall": "steal",
    "kasa_obake": "steal",
    "jatai": "steal",
    "seto_taisho": "steal",
    "shogoro": "steal",
    "hyotan_kozo": "steal",
    "chochin_obake": "steal",
    "hahakigami": "steal",
    "ungaikyo_of_the_deep": "steal",
}
THEMATIC_BLOCK_CANDIDATES_BY_ID = {
    # Tengu Peak is the explicit edge case: the resolver keeps the
    # no-possession rule as the primary block.
    "tengu_peak": ("sneak", "steal", "strike"),
}
THEMATIC_BLOCK_PRIORITY_BY_ID = {
    "tengu_peak": ("steal", "sneak", "strike"),
}
THEMATIC_HARDER_BY_FAMILY = {"Tanuki": "steal"}
THEMATIC_HARDER_BY_ID = {
    "great_tanuki": "steal",
    "chochin_obake": "sneak",
    "kumano_harbor": "sneak",
    "morinji_no_kama": "strike",
}
THEMATIC_FAVORABLE_BY_FAMILY = {
    "Kasha": "steal",
    "Kitsune": "sneak",
}
THEMATIC_FAVORABLE_BY_ID = {
    "whispering_bamboo_grove": "sneak",
}


@dataclass(frozen=True, slots=True)
class ChallengeReward:
    coins: int = 0
    treasure: bool = False


@dataclass(frozen=True, slots=True)
class Encounter:
    name: str
    victory_points: int
    strike_target: int
    sneak_target: int
    steal_target: int
    id: str = ""
    encounter_type: str = "TODO"
    rewards: dict[str, ChallengeReward] = field(default_factory=dict)
    is_sea: bool = False
    automatic_treasure: bool = False
    family: str | None = None
    difficulty_tier: str = ""
    icons: int = 1
    blocked_method: str | None = None

    def target_for(self, method: str) -> int:
        try:
            return {
                "sneak": self.sneak_target,
                "steal": self.steal_target,
                "strike": self.strike_target,
            }[method]
        except KeyError as exc:
            raise ValueError(f"unknown method: {method}") from exc


def difficulty_tier_for(encounter: Encounter) -> str:
    available_methods = [
        method for method in METHODS if method != encounter.blocked_method
    ]
    average_dice = (
        sum(encounter.target_for(method) for method in available_methods)
        / len(available_methods)
        / 2.5
    )
    if average_dice <= 2:
        return "very_easy"
    if average_dice <= 3:
        return "easy"
    if average_dice <= 4.5:
        return "moderate"
    if average_dice <= 6.5:
        return "hard"
    return "very_hard"


def display_name_for(name: str) -> str:
    words = name.lower().split()
    for index, word in enumerate(words):
        if index and word in {"and", "no", "of", "the"}:
            continue
        words[index] = "-".join(part.capitalize() for part in word.split("-"))
    return " ".join(words)


def thematic_block_for(encounter: Encounter) -> str | None:
    candidates = thematic_block_candidates_for(encounter)
    if not candidates:
        return None
    priority = THEMATIC_BLOCK_PRIORITY_BY_ID.get(encounter.id, METHODS)
    return next(method for method in priority if method in candidates)


def thematic_block_candidates_for(encounter: Encounter) -> tuple[str, ...]:
    candidates = THEMATIC_BLOCK_CANDIDATES_BY_ID.get(encounter.id)
    if candidates is not None:
        return candidates
    block = THEMATIC_BLOCKS_BY_ID.get(
        encounter.id,
        THEMATIC_BLOCKS_BY_FAMILY.get(encounter.family),
    )
    return () if block is None else (block,)


def thematic_block_priority_for(encounter: Encounter) -> tuple[str, ...]:
    return THEMATIC_BLOCK_PRIORITY_BY_ID.get(encounter.id, METHODS)


def thematic_harder_method_for(encounter: Encounter) -> str | None:
    return THEMATIC_HARDER_BY_ID.get(
        encounter.id,
        THEMATIC_HARDER_BY_FAMILY.get(encounter.family),
    )


def thematic_favorable_method_for(encounter: Encounter) -> str | None:
    return THEMATIC_FAVORABLE_BY_ID.get(
        encounter.id,
        THEMATIC_FAVORABLE_BY_FAMILY.get(encounter.family),
    )


def thematic_method_issues(encounters: list[Encounter]) -> list[str]:
    return [
        encounter.id
        for encounter in encounters
        if encounter.blocked_method != thematic_block_for(encounter)
    ]


def thematic_favorable_issues(encounters: list[Encounter]) -> list[str]:
    return [
        encounter.id
        for encounter in encounters
        if thematic_favorable_method_for(encounter) is not None
        and thematic_favorable_method_for(encounter) == encounter.blocked_method
    ]


def thematic_difficulty_issues(encounters: list[Encounter]) -> list[str]:
    """Find cards that block a method the theme only makes more difficult."""
    return [
        encounter.id
        for encounter in encounters
        if thematic_block_for(encounter) is None
        and thematic_harder_method_for(encounter) is not None
        and encounter.blocked_method == thematic_harder_method_for(encounter)
    ]


def thematic_target_issues(encounters: list[Encounter]) -> list[str]:
    """Find harder-only routes that are below both alternatives."""
    issues = []
    for encounter in encounters:
        method = thematic_harder_method_for(encounter)
        if method is None or thematic_block_for(encounter) == method:
            continue
        target = encounter.target_for(method)
        other_targets = [
            encounter.target_for(other) for other in METHODS if other != method
        ]
        if target < min(other_targets):
            issues.append(encounter.id)
    return issues


def _parse_reward(value: Mapping[str, object]) -> ChallengeReward:
    treasure = value.get("treasure", False)
    if not isinstance(treasure, bool):
        raise ValueError("reward treasure must be a boolean")
    return ChallengeReward(coins=int(value.get("coins", 0)), treasure=treasure)


def load_encounters(
    path: str | Path, *, expected_count: int | None = 50
) -> list[Encounter]:
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, Mapping):
        metadata = payload.get("_metadata", {})
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("status") != "unofficial reconstruction"
        ):
            raise ValueError(
                "encounter metadata must identify an unofficial reconstruction"
            )
        records = payload.get("encounters")
    else:
        records = payload
    if not isinstance(records, list):
        raise ValueError("encounter file must contain an encounters list")
    ids = [record.get("id") for record in records if isinstance(record, dict)]
    if len(ids) != len(set(ids)):
        duplicate = next(item for item in ids if ids.count(item) > 1)
        raise ValueError(f"duplicate encounter id: {duplicate}")
    encounters = []
    ids = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each encounter must be an object")
        record = dict(record)
        name = record.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("encounter name must be a non-empty string")
        if name.isupper():
            name = display_name_for(name)
            record["name"] = name
        encounter_id = record.get("id")
        if not isinstance(encounter_id, str) or not encounter_id:
            raise ValueError("encounter id must be a non-empty string")
        if encounter_id in ids:
            raise ValueError(f"duplicate encounter id: {encounter_id}")
        ids.add(encounter_id)
        record.pop("flavor", None)
        raw_rewards = record.pop("rewards", {})
        if not isinstance(raw_rewards, Mapping):
            raise ValueError("encounter rewards must be an object")
        automatic = record.get("automatic_treasure")
        if automatic is not None and not isinstance(automatic, bool):
            raise ValueError("automatic treasure must be a boolean")
        record["automatic_treasure"] = bool(automatic)
        blocked_method = record.get("blocked_method")
        if blocked_method is not None and blocked_method not in METHODS:
            raise ValueError("blocked method must be sneak, steal, or strike")
        rewards = {
            method: _parse_reward(value) for method, value in raw_rewards.items()
        }
        encounters.append(Encounter(**record, rewards=rewards))
    validate_encounters(encounters, expected_count=expected_count)
    return encounters


def validate_encounters(
    encounters: list[Encounter], *, expected_count: int | None = 50
) -> None:
    if expected_count is not None and len(encounters) != expected_count:
        raise ValueError(f"expected {expected_count} encounters, got {len(encounters)}")
    if not encounters:
        raise ValueError("encounter dataset cannot be empty")
    counts = Counter(encounter.encounter_type for encounter in encounters)
    if expected_count == 50 and any(counts[item] != 10 for item in ENCOUNTER_TYPES):
        raise ValueError("the standard encounter dataset requires 10 of each type")
    for encounter in encounters:
        if encounter.encounter_type not in ENCOUNTER_TYPES:
            raise ValueError(f"unknown encounter type: {encounter.encounter_type}")
        if encounter.difficulty_tier:
            if encounter.difficulty_tier not in DIFFICULTY_TIERS:
                raise ValueError("encounter has an unknown difficulty tier")
            if encounter.difficulty_tier != difficulty_tier_for(encounter):
                raise ValueError("encounter difficulty tier does not match targets")
        if not 1 <= encounter.victory_points <= 7:
            raise ValueError("encounter VP must be between 1 and 7")
        targets = (
            encounter.sneak_target,
            encounter.steal_target,
            encounter.strike_target,
        )
        if any(
            target < 0 or (target == 0 and method != encounter.blocked_method)
            for method, target in zip(METHODS, targets)
        ):
            raise ValueError("encounter targets must be positive unless blocked")
        if not isinstance(encounter.icons, int) or encounter.icons < 1:
            raise ValueError("encounter icons must be a positive integer")
        if encounter.icons > 1 and not encounter.is_sea:
            raise ValueError("only sea encounters may have more than one icon")
        if any(method not in METHODS for method in encounter.rewards):
            raise ValueError("encounter rewards contain an unknown method")
        if (
            encounter.blocked_method is not None
            and encounter.blocked_method not in METHODS
        ):
            raise ValueError("encounter has an unknown blocked method")
        if (
            encounter.blocked_method is not None
            and encounter.blocked_method in encounter.rewards
        ):
            raise ValueError("encounter rewards cannot use its blocked method")
