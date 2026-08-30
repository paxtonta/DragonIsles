"""Interactive terminal frontend; the engine itself performs no I/O."""

from collections.abc import Sequence

from .bot import Decision
from .cards import Card
from .characters import SKILL_TRACKS, TrackStep, track_reward
from .combos import is_legal
from .encounters import ENCOUNTER_TYPES, ChallengeReward, Encounter
from .engine import Game, GameInteraction, Player
from .potions import PLUS_TWO
from .scoring import trophy_holders, winner_key
from .treasures import Treasure


HUMAN_ACTION_PROMPT = (
    "Choose [p]repare, [u]se potion, [l]ook <number>, or encounter number: "
)


def _reward_text(reward: ChallengeReward | None) -> str:
    if reward is None:
        return "none"
    parts = []
    if reward.coins:
        parts.append(f"{reward.coins} coin")
    if reward.treasure:
        parts.append("treasure")
    return " + ".join(parts) or "none"


def _make_interaction() -> GameInteraction:
    def choose_discards(player: Player, count: int) -> Sequence[Card]:
        print(f"{player.name}, discard {count} card(s).")
        print(
            "Hand:", ", ".join(f"{i + 1}:{card}" for i, card in enumerate(player.hand))
        )
        while True:
            try:
                choices = input("Card numbers: ").split()
                if len(choices) != count or len(set(choices)) != count:
                    raise ValueError("choose distinct card numbers")
                selected = tuple(player.hand[int(choice) - 1] for choice in choices)
                return selected
            except (ValueError, IndexError) as exc:
                print(f"Invalid discard selection: {exc}")

    def choose_treasure_card(player: Player, cards: Sequence[Card]) -> Card:
        print(
            "Trader cards:",
            ", ".join(f"{i + 1}:{card}" for i, card in enumerate(cards)),
        )
        while True:
            try:
                return cards[int(input("Keep card number: ")) - 1]
            except (ValueError, IndexError):
                print("Choose one of the displayed card numbers.")

    def choose_treasure(player: Player, treasures: Sequence[Treasure]) -> Treasure:
        print(
            "Treasure choices:",
            ", ".join(
                f"{i + 1}:{treasure.display_name} — {treasure.description}"
                for i, treasure in enumerate(treasures)
            ),
        )
        while True:
            try:
                return treasures[int(input("Keep treasure number: ")) - 1]
            except (ValueError, IndexError):
                print("Choose one of the displayed treasure numbers.")

    def choose_track(player: Player, tracks: Sequence[str]) -> str:
        print(f"{player.name}, choose a skill track:")
        labels = []
        for track in tracks:
            current = player.skill_levels.get(track, 0)
            steps = SKILL_TRACKS[player.character.name][track]
            ladder = []
            cumulative = 0
            for index, step in enumerate(steps, 1):
                value = step.value if isinstance(step, TrackStep) else step
                cumulative += value
                reward = track_reward(player.character, track, index)
                marker = (
                    "✓" if index <= current else ">" if index == current + 1 else "·"
                )
                reward_text = f"/{reward}" if reward else ""
                ladder.append(f"{marker}{index}:{cumulative:+d}{reward_text}")
            labels.append(
                f"{len(labels) + 1}:{track} [{current}/{len(steps)} "
                f"{' '.join(ladder)}]"
            )
        print(", ".join(labels))
        while True:
            try:
                return tracks[int(input("Track number: ")) - 1]
            except (ValueError, IndexError):
                print("Choose one of the displayed track numbers.")

    def choose_plus_two(player: Player, rolled_total: int, target: int) -> bool:
        return (
            input(
                f"{player.name} rolled {rolled_total} against {target}. "
                "Use a +2 potion? [y/N]: "
            )
            .strip()
            .lower()
            == "y"
        )

    def choose_rerolls(
        player: Player, rolls: tuple[int, ...], limit: int
    ) -> Sequence[int]:
        while True:
            answer = input(
                f"{player.name}, reroll up to {limit} dice "
                "(numbers, or Enter for none): "
            ).strip()
            if not answer:
                return ()
            try:
                values = tuple(int(value) - 1 for value in answer.split())
                if len(values) != len(set(values)) or len(values) > limit:
                    raise ValueError(f"choose at most {limit} distinct dice")
                if any(value < 0 or value >= len(rolls) for value in values):
                    raise ValueError("choose displayed die numbers")
                return values
            except ValueError as exc:
                print(f"Invalid reroll selection: {exc}")

    def show_cards(player: Player, label: str, cards: Sequence[Card]) -> None:
        print(f"{player.name} {label}:", ", ".join(map(str, cards)))

    def show_encounters(encounters: Sequence[Encounter]) -> None:
        print("Encounter row refreshed:")
        for index, encounter in enumerate(encounters, 1):
            print(_encounter_line(index, encounter))

    def show_roll(
        player: Player, rolls: tuple[int, ...], bonus: int, total: int
    ) -> None:
        print(f"{player.name} roll: {rolls}, bonus +{bonus}, total {total}")

    def show_challenge_result(player: Player, success: bool) -> None:
        if player.is_bot:
            print("Bot succeeds." if success else "Bot fails and gains a potion.")
        else:
            print("Success!" if success else "Failed; you gained a potion.")

    return GameInteraction(
        choose_discards=choose_discards,
        choose_treasure=choose_treasure,
        choose_treasure_card=choose_treasure_card,
        choose_track=choose_track,
        choose_plus_two=choose_plus_two,
        choose_rerolls=choose_rerolls,
        show_cards=show_cards,
        show_encounters=show_encounters,
        show_roll=show_roll,
        show_challenge_result=show_challenge_result,
        announce=print,
    )


def run_cli(game: Game) -> None:
    game.interaction = _make_interaction()
    print(
        "Characters:",
        ", ".join(
            f"{player.name}={player.character.name}" for player in game.state.players
        ),
    )
    print(f"{game.state.players[game.state.current_player].name} starts.")
    while not game.state.game_over and game.state.encounters:
        current = game.state.players[game.state.current_player]
        human = game.state.players[0]
        _print_state(game, human)
        if current.is_bot:
            print("Bot's turn.")
            _run_bot_turn(game)
        else:
            try:
                action = input(HUMAN_ACTION_PROMPT).strip().lower()
                action_consumed = _human_action(game, human, action)
                if not action_consumed:
                    continue
            except (EOFError, ValueError, IndexError) as exc:
                if isinstance(exc, EOFError):
                    print("\nInput closed; exiting.")
                    return
                print(f"Invalid input: {exc}")
                continue
        if game.state.game_over:
            break
        game.state.current_player = 1 - game.state.current_player
        game.state.turn_number += 1
    print("\nGame over.")
    for player in game.state.players:
        print(f"{player.name}: {game.score(player).total} VP")
    high_key = max(winner_key(game.score(player)) for player in game.state.players)
    winners = [
        player.name
        for player in game.state.players
        if winner_key(game.score(player)) == high_key
    ]
    print(f"Winner: {', '.join(winners)} ({high_key[0]} VP)")


def _human_action(game: Game, human: Player, action: str) -> bool:
    potion_used = False
    while True:
        if _inspect_command(game, action):
            action = input(HUMAN_ACTION_PROMPT).strip().lower()
            continue
        if action != "u":
            try:
                return _human_action_once(game, human, action)
            except (ValueError, IndexError) as exc:
                if not potion_used:
                    raise
                print(f"Invalid input: {exc}")
                action = input(HUMAN_ACTION_PROMPT).strip().lower()
                continue
        if not human.potions:
            raise ValueError("you have no potions")
        potion = human.potions[int(input("Potion number: ")) - 1]
        if potion.kind == PLUS_TWO:
            raise ValueError("+2 can only be used during a challenge")
        game.use_potion(human, potion)
        potion_used = True
        print(f"You used {potion}; choose your turn action.")
        while True:
            try:
                action = input(HUMAN_ACTION_PROMPT).strip().lower()
                break
            except (ValueError, IndexError) as exc:
                print(f"Invalid input: {exc}")


def _human_action_once(game: Game, human: Player, action: str) -> bool:
    if action == "p":
        count = game.prepare_draw_count(human)
        drawn: list[Card] = []
        for draw_number in range(1, count + 1):
            while True:
                choice = input(
                    f"Choose source for draw {draw_number} of {count} "
                    "[deck or market card number]: "
                ).strip()
                try:
                    source = (
                        "deck"
                        if choice == "deck"
                        else game.state.market[int(choice) - 1]
                    )
                    card = game.prepare_one(human, source)
                except (ValueError, IndexError) as exc:
                    print(f"Invalid source: {exc}")
                    continue
                drawn.append(card)
                print(f"Drew {card}.")
                print(
                    "Market:",
                    ", ".join(
                        f"{i + 1}:{market_card}"
                        for i, market_card in enumerate(game.state.market)
                    ),
                )
                break
        game.finish_prepare(human)
        print("You prepared and drew:", ", ".join(map(str, drawn)))
        return True
    encounter = game.state.encounters[int(action) - 1]
    method = input("Challenge [sneak/steal/strike]: ").strip().lower()
    if method not in ("sneak", "steal", "strike"):
        raise ValueError("unknown challenge method")
    if method == encounter.blocked_method:
        raise ValueError(f"{method} is blocked for {encounter.name}")
    indexes = input("Hand card numbers (space-separated): ").split()
    if not indexes or len(set(indexes)) != len(indexes):
        raise ValueError("choose at least one card, without repeats")
    combo = tuple(human.hand[int(index) - 1] for index in indexes)
    if not is_legal(combo, method):
        raise ValueError("those cards do not form a legal combination")
    decision = Decision("attempt", encounter, combo, method)
    game.attempt(human, encounter, decision)
    return True


def _inspect_command(game: Game, action: str) -> bool:
    parts = action.split()
    if not parts or parts[0] not in {"look", "l"}:
        return False
    if len(parts) != 2:
        print("Usage: look <encounter number> (or l <number>).")
        return True
    try:
        index = int(parts[1])
    except ValueError:
        print("Look requires a numeric encounter number.")
        return True
    if not 1 <= index <= len(game.state.encounters):
        print(f"Choose an encounter number from 1 to {len(game.state.encounters)}.")
        return True
    encounter = game.state.encounters[index - 1]
    print(f"  {index}. {encounter.name} [{encounter.encounter_type}]")
    print(f"     {_encounter_mechanics(encounter)}")
    return True


def _run_bot_turn(game: Game) -> None:
    bot = game.state.players[1]
    while not game.state.game_over:
        context = game.decision_context(bot)
        decision = game.bot_policy.choose(context)
        if decision.action == "use_potion":
            game.use_potion(bot, decision.potion)
            print(f"Bot uses {decision.potion} (free action).")
            continue
        if decision.action == "prepare":
            drawn = game.bot_prepare(bot)
            print(f"Bot prepares, drawing {len(drawn)} cards.")
            return
        print(f"Bot challenges {decision.encounter.name} with {decision.method}.")
        game.attempt(bot, decision.encounter, decision)
        return


def _print_state(game: Game, player: Player) -> None:
    print(
        f"\nTurn {game.state.turn_number} | {player.name} "
        f"({player.character.name}) | Score {game.score(player).total} VP"
    )
    print(
        f"Coins: {player.coins} | Encounters: {len(player.encounters)}/8 "
        f"| Hand limit: {player.hand_limit}"
    )
    print(
        "Completed:",
        _completed_encounters_text(player.encounters) or "none",
    )
    print("Potions:", ", ".join(map(str, player.potions)) or "none")
    print(
        "Potion effects: +2 adds 2 during a Challenge; Draw 2 draws two cards; "
        "Purge draws 1 card and redeals the Encounter row."
    )
    print("Treasures:", _treasure_text(player) or "none")
    print("Skills:", _skill_text(player))
    print("Trophies:", _trophy_text(game))
    for opponent in game.state.players:
        if opponent is not player:
            print(_public_player_line(opponent))
    print(
        "Market:",
        ", ".join(f"{i + 1}:{card}" for i, card in enumerate(game.state.market)),
    )
    print("Hand:", ", ".join(f"{i + 1}:{card}" for i, card in enumerate(player.hand)))
    print("Encounters:")
    for index, encounter in enumerate(game.state.encounters, 1):
        print(_encounter_line(index, encounter))


def _treasure_text(player: Player) -> str:
    return ", ".join(
        f"{treasure.display_name} — {treasure.description}"
        for treasure in player.treasures
    )


def _completed_encounters_text(encounters: list[Encounter]) -> str:
    return ", ".join(encounter.name for encounter in encounters)


def _skill_text(player: Player) -> str:
    return (
        ", ".join(
            f"{track}={level}" for track, level in sorted(player.skill_levels.items())
        )
        or "none"
    )


def _public_player_line(player: Player) -> str:
    encounters = _completed_encounters_text(player.encounters) or "none"
    return (
        f"{player.name} ({player.character.name}) | "
        f"Encounters {len(player.encounters)}/8: {encounters} | "
        f"Hand limit {player.hand_limit} | "
        f"Coins {player.coins} | Potions {len(player.potions)} | "
        f"Treasures: {_treasure_text(player) or 'none'} | "
        f"Skills: {_skill_text(player)}"
    )


def _trophy_text(game: Game) -> str:
    holders, all_types_holders = trophy_holders(
        game.state.trophy_events,
        player_count=len(game.state.players),
    )
    trophy_parts = []
    for encounter_type in ENCOUNTER_TYPES:
        holder = holders[encounter_type]
        name = game.state.players[holder].name if holder is not None else "none"
        trophy_parts.append(f"{encounter_type}:{name}")
    name = (
        ", ".join(game.state.players[index].name for index in sorted(all_types_holders))
        or "none"
    )
    trophy_parts.append(f"all:{name}")
    return " | ".join(trophy_parts)


def _encounter_line(index: int, encounter: Encounter) -> str:
    return (
        f"  {index}. {encounter.name} [{encounter.encounter_type}] "
        f"{'[SEA] ' if encounter.is_sea else ''}"
        f"{_encounter_mechanics(encounter)}"
    )


def _encounter_mechanics(encounter: Encounter) -> str:
    targets = []
    for method, target in (
        ("sneak", encounter.sneak_target),
        ("steal", encounter.steal_target),
        ("strike", encounter.strike_target),
    ):
        targets.append(
            f"{method.title()} "
            + ("BLOCKED" if method == encounter.blocked_method else str(target))
        )
    rewards = ", ".join(
        f"{method}:{_reward_text(encounter.rewards.get(method))}"
        for method in ("sneak", "steal", "strike")
    )
    if encounter.automatic_treasure:
        rewards += ", auto:treasure"
    return (
        f"VP {encounter.victory_points} | Icons {encounter.icons} | "
        f"{', '.join(targets)} | "
        f"{rewards}"
    )
