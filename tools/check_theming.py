"""Audit thematic method changes across the reconstructed Encounter deck."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonisles.encounters import (
    load_encounters,
)


def profile_for(encounter):
    return (
        f"blocked:{encounter.blocked_method}" if encounter.blocked_method else "neutral"
    )


def context_for(encounter):
    return (
        f"type={encounter.encounter_type}, family={encounter.family or '-'}, "
        f"vp={encounter.victory_points}, targets="
        f"{encounter.sneak_target}/{encounter.steal_target}/"
        f"{encounter.strike_target}, rewards={sorted(encounter.rewards)}, "
        f"icons={encounter.icons}, sea={encounter.is_sea}, "
        f"automatic_treasure={encounter.automatic_treasure}"
    )


if __name__ == "__main__":
    encounters = load_encounters(Path("data/encounters.json"))
    for encounter in encounters:
        print(f"{encounter.id}: {profile_for(encounter)}; " f"{context_for(encounter)}")
    print(
        "blocked methods: "
        f"{sum(encounter.blocked_method is not None for encounter in encounters)}"
    )
