"""Two-player game state and a small CLI loop."""

from dataclasses import dataclass, field
import random
from typing import Callable, Sequence

from .bot import Decision, DecisionContext, Policy, policy_for_character
from .cards import AdventurerDeck, Card
from .characters import (
    CHARACTERS,
    STARTING_HAND_SIZE,
    WARRIOR_DRAW_TRIGGER,
    Character,
    TrackStep,
    available_tracks,
    hand_limit_bonus,
    roll_bonus,
    reroll_count,
    track_reward,
)
from .combos import is_legal
from .dice import DIE_FACES
from .encounters import Encounter
from .potions import DRAW_TWO, PLUS_TWO, PURGE, PotionToken, random_potion
from .scoring import ScoreBreakdown, TrophyEvent, score_player, winner_key
from .treasures import (
    Treasure,
    default_treasure_supply,
    green_outcome,
    green_trigger,
)

MAX_CHALLENGE_DICE = 6


@dataclass(frozen=True, slots=True)
class RulesConfig:
    encounter_row_size: int = 4
    market_size: int = 2
    die_faces: tuple[int, ...] = DIE_FACES
    # Confirmed for successful challenges; keep configurable for testing.
    played_cards_on_success: str = "discard"
    # Confirmed: failed challenges keep their played cards in the hand.
    played_cards_on_failure: str = "keep"
    market_refill_timing: str = "end_of_prepare"
    deck_factory: Callable[[], AdventurerDeck] = AdventurerDeck
    potion_factory: Callable[[], PotionToken] = random_potion
    potion_token_count: int = 20
    coin_token_counts: tuple[tuple[int, int], ...] = ((1, 30), (5, 10), (10, 10))


@dataclass
class Player:
    name: str
    character: Character
    is_bot: bool = False
    hand: list[Card] = field(default_factory=list)
    encounters: list[Encounter] = field(default_factory=list)
    treasures: list[Treasure] = field(default_factory=list)
    coins: int = 0
    potions: list[PotionToken] = field(default_factory=list)
    skill_progress: list[int] = field(default_factory=list)
    skill_levels: dict[str, int] = field(default_factory=dict)
    attempts: int = 0
    prepares: int = 0

    @property
    def hand_limit(self) -> int:
        return self.character.starting_hand_limit + hand_limit_bonus(
            self.character, self.skill_levels
        )

    @property
    def hand_limit_upgrade(self) -> int:
        """Compatibility alias; upgrades are stored in the hand-limit track."""
        return hand_limit_bonus(self.character, self.skill_levels)

    @hand_limit_upgrade.setter
    def hand_limit_upgrade(self, value: int) -> None:
        from .characters import SKILL_TRACKS

        track = SKILL_TRACKS.get(self.character.name, {}).get("hand_limit", ())
        cumulative = 0
        for level, step in enumerate(track, 1):
            increment = step.value if isinstance(step, TrackStep) else step
            cumulative += increment
            if cumulative == value:
                self.skill_levels["hand_limit"] = level
                return
        self.skill_levels["hand_limit"] = value


@dataclass(frozen=True, slots=True)
class GameInteraction:
    choose_discards: Callable[[Player, int], Sequence[Card] | None] | None = None
    choose_treasure: Callable[[Player, Sequence[Treasure]], Treasure | None] | None = (
        None
    )
    choose_treasure_card: Callable[[Player, Sequence[Card]], Card | None] | None = None
    choose_track: Callable[[Player, Sequence[str]], str] | None = None
    choose_plus_two: Callable[[Player, int, int], bool] | None = None
    choose_rerolls: Callable[[Player, tuple[int, ...], int], Sequence[int]] | None = (
        None
    )
    show_cards: Callable[[Player, str, Sequence[Card]], None] | None = None
    show_encounters: Callable[[Sequence[Encounter]], None] | None = None
    show_roll: Callable[[Player, tuple[int, ...], int, int], None] | None = None
    show_challenge_result: Callable[[Player, bool], None] | None = None
    announce: Callable[[str], None] | None = None
    stage_bot_discards: bool = False


@dataclass
class TraderDraw:
    """Cards drawn for a Trader treasure whose keep choice is still pending."""

    player: Player
    cards: list[Card]


@dataclass
class TreasureDraw:
    """Treasures drawn for a reward whose keep choice is still pending."""

    player: Player
    treasures: list[Treasure]


@dataclass
class DiscardChoice:
    """Cards the human must choose before a hand-limit action can finish."""

    player: Player
    count: int


@dataclass
class ChallengeProgress:
    player: Player
    encounter: Encounter
    decision: Decision
    rolls: tuple[int, ...]
    skill_bonus: int
    rolled_total: int
    target: int
    reroll_limit: int
    rerolls_used: bool = False
    resolved: bool = False
    success: bool | None = None


@dataclass
class GameState:
    rules: RulesConfig
    deck: AdventurerDeck
    market: list[Card]
    encounters: list[Encounter]
    players: list[Player]
    current_player: int = 0
    turn_number: int = 1
    game_over: bool = False
    winner: Player | None = None
    trophy_events: list[TrophyEvent] = field(default_factory=list)


class Game:
    def __init__(
        self,
        encounters: list[Encounter],
        *,
        rules: RulesConfig | None = None,
        rng: random.Random | None = None,
        characters: Sequence[Character] | None = None,
        players: Sequence[Player] | None = None,
        interaction: GameInteraction | None = None,
    ) -> None:
        self.rules = rules or RulesConfig()
        self.rng = rng or random.Random()
        self.interaction = interaction or GameInteraction()
        self.last_roll: tuple[tuple[int, ...], int, int] | None = None
        self.active_challenge: ChallengeProgress | None = None
        deck = self.rules.deck_factory()
        encounter_cards = list(encounters)
        self.rng.shuffle(encounter_cards)
        if players is not None and characters is not None:
            raise ValueError("provide players or characters, not both")
        if players is None:
            chosen_characters = (
                list(characters)
                if characters is not None
                else self.rng.sample(list(CHARACTERS.values()), 2)
            )
            if len(chosen_characters) != 2:
                raise ValueError("exactly two characters are required")
            if chosen_characters[0].name == chosen_characters[1].name:
                raise ValueError("the two characters must be distinct")
            chosen_players = [
                Player("Human", chosen_characters[0], is_bot=False),
                Player("Bot", chosen_characters[1], is_bot=True),
            ]
        else:
            chosen_players = list(players)
            if len(chosen_players) != 2:
                raise ValueError("exactly two players are required")
        self.state = GameState(
            self.rules,
            deck,
            [deck.draw() for _ in range(self.rules.market_size)],
            [],
            chosen_players,
            current_player=self.rng.randrange(2),
        )
        self._encounter_deck = encounter_cards
        self._encounter_discard: list[Encounter] = []
        self.refill_encounters()
        self._treasure_supply = default_treasure_supply()
        self.rng.shuffle(self._treasure_supply)
        self._potion_supply = [
            self.rules.potion_factory() for _ in range(self.rules.potion_token_count)
        ]
        self._used_potions: list[PotionToken] = []
        self._used_treasures: list[Treasure] = []
        self.pending_trader_draw: TraderDraw | None = None
        self.pending_treasure_draw: TreasureDraw | None = None
        self.pending_discard: DiscardChoice | None = None
        self._coin_supply = dict(self.rules.coin_token_counts)
        bot_player = next((player for player in self.state.players if player.is_bot), None)
        self.bot_policy = policy_for_character(
            (bot_player or self.state.players[1]).character
        )
        for player in self.state.players:
            player.hand.extend(
                self.state.deck.draw() for _ in range(STARTING_HAND_SIZE)
            )
            self.discard_down(player)

    def discard_down(
        self, player: Player, discard_cards: Sequence[Card] | None = None
    ) -> None:
        """Discard immediately until the character's current limit is met."""
        excess = max(0, len(player.hand) - player.hand_limit)
        if not excess:
            return
        if discard_cards is None:
            context = self._decision_context(player)
            if player.is_bot and not self.interaction.stage_bot_discards:
                selected = list(self.bot_policy.choose_discards(context, excess))
            elif self.interaction.choose_discards is not None:
                selected_result = self.interaction.choose_discards(player, excess)
                if selected_result is None:
                    self.pending_discard = DiscardChoice(player, excess)
                    return
                selected = list(selected_result)
            else:
                raise ValueError("human discard selection requires an interaction")
        else:
            selected = list(discard_cards)
        if len(selected) < excess or any(card not in player.hand for card in selected):
            raise ValueError("discard selection must contain cards from the hand")
        for card in selected[:excess]:
            player.hand.remove(card)
        self.state.deck.discard(selected[:excess])

    def prepare(
        self, player: Player, choices: Sequence[Card | str] | None = None
    ) -> tuple[Card, ...]:
        """Draw and resolve the character's configured number of cards."""
        draw_count = self.prepare_draw_count(player)
        sources = list(choices or ("deck",) * draw_count)
        if len(sources) != draw_count:
            raise ValueError(f"Prepare requires exactly {draw_count} card sources")
        drawn: list[Card] = []
        for source in sources:
            drawn.append(self.prepare_one(player, source))
            if self.pending_discard is not None:
                return tuple(drawn)
        self.finish_prepare(player)
        return tuple(drawn)

    def prepare_one(self, player: Player, source: Card | str) -> Card:
        """Draw one Prepare card and immediately refill the market."""
        if source == "deck":
            card = self.state.deck.draw()
        elif isinstance(source, Card) and source in self.state.market:
            self.state.market.remove(source)
            card = source
            while len(self.state.market) < self.rules.market_size:
                self.state.market.append(self.state.deck.draw())
        else:
            raise ValueError("each Prepare source must be 'deck' or a market card")
        player.hand.append(card)
        self.discard_down(player)
        return card

    def finish_prepare(self, player: Player) -> None:
        """Apply the hand limit and record one completed Prepare action."""
        self.discard_down(player)
        player.prepares += 1

    def replace_encounter(self, encounter: Encounter) -> None:
        self.state.encounters.remove(encounter)
        card = self._draw_encounter()
        if card is not None:
            self.state.encounters.append(card)
        self._rebalance_encounter_row()

    def advance_experience(self, player: Player) -> None:
        player.skill_progress.append(1)
        tracks = available_tracks(player.character, player.skill_levels)
        if not tracks:
            return
        if player.is_bot:
            selected = self.bot_policy.choose_track(
                self._decision_context(player), tracks
            )
        elif self.interaction.choose_track is not None:
            selected = self.interaction.choose_track(player, tracks)
        else:
            selected = tracks[0]
        if selected not in tracks:
            raise ValueError("invalid skill track")
        player.skill_levels[selected] = player.skill_levels.get(selected, 0) + 1
        reward = track_reward(player.character, selected, player.skill_levels[selected])
        if reward == "coin":
            self.gain_coin(player)
        elif reward == "potion":
            self.gain_potion(player)
        elif reward == "treasure":
            self.gain_treasure(player)
        if reward is not None and self.interaction.announce is not None:
            self.interaction.announce(
                f"{player.name} received a {reward} skill reward."
            )
        if self.interaction.announce is not None:
            self.interaction.announce(
                f"{player.name} advanced the {selected} skill track "
                f"to level {player.skill_levels[selected]}."
            )

    def _draw_cards_without_discard(self, player: Player, count: int) -> list[Card]:
        drawn = [self.state.deck.draw() for _ in range(count)]
        player.hand.extend(drawn)
        return drawn

    def draw_cards(self, player: Player, count: int) -> list[Card]:
        drawn = self._draw_cards_without_discard(player, count)
        self.discard_down(player)
        return drawn

    def prepare_draw_count(self, player: Player) -> int:
        return player.character.prepare_draw_count

    def _trigger_green_effect(self, player: Player, effect: str) -> None:
        drew_cards = False
        for treasure in player.treasures:
            if (
                not treasure.is_green
                or green_trigger(treasure.passive_effect) != effect
            ):
                continue
            outcome = green_outcome(treasure.passive_effect)
            if outcome == "coin":
                self.gain_coin(player)
                message = f"{player.name}'s green treasure grants 1 coin."
            elif outcome == "draw":
                cards = self._draw_cards_without_discard(player, 1)
                drew_cards = True
                if self.interaction.show_cards is not None:
                    self.interaction.show_cards(player, "drew", cards)
                message = f"{player.name}'s green treasure drew 1 Adventure card."
            else:
                continue
            if self.interaction.announce is not None:
                self.interaction.announce(message)
        if drew_cards:
            self.discard_down(player)

    def _reroll_green_ones(
        self, player: Player, rolls: tuple[int, ...]
    ) -> tuple[int, ...]:
        holders = [
            treasure
            for treasure in player.treasures
            if treasure.is_green
            and green_trigger(treasure.passive_effect) == "roll_ones"
        ]
        if not holders or 1 not in rolls:
            return rolls
        updated = list(rolls)
        rerolled = False
        extra_dice = 0
        drew_cards = False
        for holder in holders:
            outcome = green_outcome(holder.passive_effect)
            ones = updated.count(1)
            if ones:
                updated = [
                    self.rng.choice(self.rules.die_faces) if roll == 1 else roll
                    for roll in updated
                ]
                rerolled = True
            if outcome == "reroll_extra":
                if len(updated) < MAX_CHALLENGE_DICE:
                    updated.append(self.rng.choice(self.rules.die_faces))
                    extra_dice += 1
            if outcome in {"reroll_draw", "draw"}:
                cards = self._draw_cards_without_discard(player, 1)
                drew_cards = True
                if self.interaction.show_cards is not None:
                    self.interaction.show_cards(player, "drew", cards)
                if self.interaction.announce is not None:
                    self.interaction.announce(
                        f"{player.name}'s green treasure drew 1 Adventure card."
                    )
            elif outcome == "coin":
                self.gain_coin(player)
                if self.interaction.announce is not None:
                    self.interaction.announce(
                        f"{player.name}'s green treasure grants 1 coin."
                    )
        if self.interaction.announce is not None:
            if rerolled:
                self.interaction.announce(
                    f"{player.name}'s green treasure rerolled dice showing 1."
                )
            if extra_dice:
                self.interaction.announce(
                    f"{player.name}'s green treasure added {extra_dice} die."
                )
        if drew_cards:
            self.discard_down(player)
        return tuple(updated)

    def refill_encounters(self) -> None:
        """Deal a row with mixed sea status when the deck permits it.

        A homogeneous four-card row is redealt up to the bounded retry limit.
        If the remaining cards cannot produce a mixed row, the final deal is
        kept rather than looping forever.
        """
        self._encounter_discard.extend(self.state.encounters)
        self.state.encounters.clear()
        self._deal_encounter_row()

    def _encounter_row_is_mixed(self) -> bool:
        if len(self.state.encounters) < self.rules.encounter_row_size:
            return True
        sea_count = sum(card.is_sea for card in self.state.encounters)
        return 0 < sea_count < len(self.state.encounters)

    def _deal_encounter_row(self) -> None:
        max_redeals = 20
        for attempt in range(max_redeals + 1):
            while len(self.state.encounters) < self.rules.encounter_row_size:
                card = self._draw_encounter()
                if card is None:
                    break
                self.state.encounters.append(card)
            if self._encounter_row_is_mixed() or attempt == max_redeals:
                return
            self._encounter_discard.extend(self.state.encounters)
            self.state.encounters.clear()

    def _rebalance_encounter_row(self) -> None:
        if self._encounter_row_is_mixed():
            return
        self._encounter_discard.extend(self.state.encounters)
        self.state.encounters.clear()
        self._deal_encounter_row()

    def _draw_encounter(self) -> Encounter | None:
        if not self._encounter_deck:
            if not self._encounter_discard:
                return None
            self._encounter_deck = self._encounter_discard
            self._encounter_discard = []
            self.rng.shuffle(self._encounter_deck)
        return self._encounter_deck.pop()

    def use_potion(
        self, player: Player, potion: PotionToken, *, for_challenge: bool = False
    ) -> int:
        if potion not in player.potions:
            raise ValueError("player does not have this potion")
        if potion.kind == PLUS_TWO and not for_challenge:
            raise ValueError("+2 can only be used during a challenge")
        player.potions.remove(potion)
        self._used_potions.append(potion)
        if potion.kind == PLUS_TWO:
            bonus = 2
        elif potion.kind == DRAW_TWO:
            cards = self.draw_cards(player, 2)
            if self.interaction.show_cards is not None:
                self.interaction.show_cards(player, "drew", cards)
            bonus = 0
        elif potion.kind == PURGE:
            cards = self.draw_cards(player, 1)
            self.refill_encounters()
            if self.interaction.show_cards is not None:
                self.interaction.show_cards(player, "drew", cards)
            if self.interaction.show_encounters is not None:
                self.interaction.show_encounters(self.state.encounters)
            bonus = 0
        else:
            raise ValueError(f"unknown potion type: {potion.kind}")
        if player.character.potion_draw_count:
            cards = self.draw_cards(player, player.character.potion_draw_count)
            if self.interaction.show_cards is not None:
                self.interaction.show_cards(player, "drew", cards)
        return bonus

    @property
    def potion_supply_count(self) -> int:
        """Potion tokens still available in the shared supply."""
        return len(self._potion_supply)

    @property
    def coin_supply_counts(self) -> dict[int, int]:
        """Remaining coin tokens by denomination."""
        return dict(self._coin_supply)

    @property
    def used_potions(self) -> list[PotionToken]:
        """Spent potion tokens waiting to be reshuffled into the supply."""
        return list(self._used_potions)

    @property
    def used_treasures(self) -> list[Treasure]:
        """Treasures discarded from a reward choice awaiting reshuffle."""
        return list(self._used_treasures)

    def gain_coin(self, player: Player) -> bool:
        """Give one coin token, taking it from the opponent if supplies are empty."""
        if self._coin_supply[1] == 0:
            if self._coin_supply[5]:
                self._coin_supply[5] -= 1
                self._coin_supply[1] += 5
            elif self._coin_supply[10]:
                self._coin_supply[10] -= 1
                self._coin_supply[1] += 10
        if self._coin_supply[1]:
            self._coin_supply[1] -= 1
            player.coins += 1
            return True
        opponent = next(other for other in self.state.players if other is not player)
        if opponent.coins:
            opponent.coins -= 1
            player.coins += 1
            return True
        return False

    def gain_potion(self, player: Player) -> bool:
        """Give a potion, recycling spent tokens when the supply is empty."""
        if self._potion_supply:
            player.potions.append(self._potion_supply.pop())
            return True
        opponent = next(other for other in self.state.players if other is not player)
        if opponent.potions:
            player.potions.append(opponent.potions.pop())
            return True
        if self._used_potions:
            self._potion_supply = self._used_potions
            self._used_potions = []
            self.rng.shuffle(self._potion_supply)
        if not self._potion_supply:
            return False
        player.potions.append(self._potion_supply.pop())
        return True

    def gain_treasure(
        self,
        player: Player,
        treasure: Treasure | None = None,
        keep_card: Card | None = None,
        keep_treasure: Treasure | None = None,
    ) -> None:
        if treasure is None:
            choices = self._draw_treasures(2)
            if not choices:
                return
            if len(choices) == 1:
                treasure = choices[0]
            elif keep_treasure is not None:
                if keep_treasure not in choices:
                    raise ValueError("kept treasure must be one of the drawn treasures")
                treasure = keep_treasure
            elif player.is_bot:
                treasure = self.bot_policy.choose_best_treasure(
                    self._decision_context(player), choices
                )
            elif self.interaction.choose_treasure is not None:
                treasure = self.interaction.choose_treasure(player, choices)
            elif self.interaction.choose_treasure_card is not None:
                treasure = self.interaction.choose_treasure_card(player, choices)
            else:
                self.pending_treasure_draw = TreasureDraw(player, choices)
                return
            if treasure is None:
                self.pending_treasure_draw = TreasureDraw(player, choices)
                return
            self._used_treasures.extend(
                choice for choice in choices if choice is not treasure
            )
        self._finish_treasure_gain(player, treasure, keep_card)

    def _draw_treasures(self, count: int) -> list[Treasure]:
        choices: list[Treasure] = []
        while len(choices) < count:
            if not self._treasure_supply:
                if not self._used_treasures:
                    break
                self._treasure_supply = self._used_treasures
                self._used_treasures = []
                self.rng.shuffle(self._treasure_supply)
            choices.append(self._treasure_supply.pop())
        return choices

    def _finish_treasure_gain(
        self, player: Player, treasure: Treasure, keep_card: Card | None
    ) -> None:
        player.treasures.append(treasure)
        if treasure.is_orange and treasure.encounter_type:
            self._record_trophy_event(player, treasure.encounter_type, 1)
        if self.interaction.announce is not None:
            self.interaction.announce(
                f"{player.name} received {treasure.display_name}."
            )
        if player.character.trader_draw_count <= 0:
            return
        cards = self.draw_cards_without_limit(player.character.trader_draw_count)
        if self.interaction.show_cards is not None:
            self.interaction.show_cards(player, "drew for Trader", cards)
        if keep_card is None:
            if player.is_bot:
                keep_card = self.bot_policy.choose_best_card(
                    self._decision_context(player),
                    cards,
                )
            elif self.interaction.choose_treasure_card is not None:
                keep_card = self.interaction.choose_treasure_card(player, cards)
            else:
                raise ValueError("human treasure selection requires an interaction")
        if keep_card is None:
            self.pending_trader_draw = TraderDraw(player, list(cards))
            return
        self._keep_trader_card(player, cards, keep_card)

    def resolve_treasure_draw(self, keep_treasure: Treasure) -> None:
        """Finish a staged two-treasure reward choice."""
        pending = self.pending_treasure_draw
        if pending is None:
            raise ValueError("no treasure choice is waiting")
        if keep_treasure not in pending.treasures:
            raise ValueError("kept treasure must be one of the drawn treasures")
        self.pending_treasure_draw = None
        self._used_treasures.extend(
            treasure for treasure in pending.treasures if treasure is not keep_treasure
        )
        self._finish_treasure_gain(pending.player, keep_treasure, None)

    def _keep_trader_card(
        self, player: Player, cards: Sequence[Card], keep_card: Card
    ) -> None:
        if keep_card not in cards:
            raise ValueError("Trader keep card must be one of the drawn cards")
        player.hand.append(keep_card)
        self.state.deck.discard(card for card in cards if card != keep_card)
        self.discard_down(player)

    def resolve_trader_draw(self, keep_card: Card) -> None:
        """Finish a Trader treasure draw whose choice was deferred."""
        pending = self.pending_trader_draw
        if pending is None:
            raise ValueError("no Trader draw is waiting for a card")
        self.pending_trader_draw = None
        self._keep_trader_card(pending.player, pending.cards, keep_card)

    def resolve_discard(self, cards: Sequence[Card]) -> None:
        """Finish a staged hand-limit discard choice."""
        pending = self.pending_discard
        if pending is None:
            raise ValueError("no discard choice is waiting")
        if len(cards) != 1:
            raise ValueError("choose exactly one card")
        if any(card not in pending.player.hand for card in cards):
            raise ValueError("discard selection must contain cards from the hand")
        pending.player.hand.remove(cards[0])
        self.state.deck.discard(cards)
        pending.count -= 1
        if pending.count == 0:
            self.pending_discard = None

    def _record_trophy_event(
        self, player: Player, encounter_type: str, amount: int
    ) -> None:
        player_index = self.state.players.index(player)
        self.state.trophy_events.append((player_index, encounter_type, amount))

    def draw_cards_without_limit(self, count: int) -> list[Card]:
        return [self.state.deck.draw() for _ in range(count)]

    def _decision_context(self, player: Player) -> DecisionContext:
        return self._decision_context_for(player)

    def decision_context(self, player: Player) -> DecisionContext:
        """Return the current policy context for a player."""
        return self._decision_context_for(player)

    def _decision_context_for(self, player: Player) -> DecisionContext:
        opponent = next(item for item in self.state.players if item is not player)
        opponent_challenge_cards = (
            self.active_challenge.decision.combo
            if self.active_challenge is not None
            and self.active_challenge.player is opponent
            else ()
        )
        possible_adventure_cards = list(self.state.deck.cards)
        known_cards = [
            *player.hand,
            *self.state.market,
            *opponent_challenge_cards,
        ]
        if self.state.deck.discard_pile:
            known_cards.append(self.state.deck.discard_pile[-1])
        for card in known_cards:
            if card in possible_adventure_cards:
                possible_adventure_cards.remove(card)
        return DecisionContext(
            hand=player.hand,
            encounters=self.state.encounters,
            market=self.state.market,
            character=player.character,
            potions=player.potions,
            treasures=player.treasures,
            die_faces=self.rules.die_faces,
            skill_levels=player.skill_levels,
            trophy_events=self.state.trophy_events,
            player_index=self.state.players.index(player),
            completed_encounters=player.encounters,
            coins=player.coins,
            opponent_encounters=opponent.encounters,
            opponent_treasures=opponent.treasures,
            opponent_coins=opponent.coins,
            opponent_character=opponent.character,
            opponent_challenge_cards=opponent_challenge_cards,
            adventure_cards=tuple(possible_adventure_cards),
        )

    def bot_prepare_one(
        self, player: Player, policy: Policy | None = None
    ) -> Card:
        """Resolve one bot Prepare draw against the current market."""
        selected_policy = policy or self.bot_policy
        context = self._decision_context_for(player)
        source = selected_policy.choose_prepare_source(context)
        if self.interaction.announce is not None:
            if isinstance(source, Card):
                self.interaction.announce(
                    f"{player.name} Prepared from market card {source}."
                )
            else:
                self.interaction.announce(f"{player.name} Prepared from the deck.")
        return self.prepare_one(player, source)

    def bot_prepare(
        self,
        player: Player,
        policy: Policy | None = None,
    ) -> tuple[Card, ...]:
        """Resolve a bot's Prepare draws against the current market each time."""
        drawn: list[Card] = []
        for _ in range(self.prepare_draw_count(player)):
            drawn.append(self.bot_prepare_one(player, policy))
            if self.pending_discard is not None:
                return tuple(drawn)
        self.finish_prepare(player)
        return tuple(drawn)

    def attempt(self, player: Player, encounter: Encounter, decision: Decision) -> bool:
        progress = self.begin_attempt(player, encounter, decision)
        if progress.reroll_limit:
            if player.is_bot:
                reroll_indices = self.bot_policy.choose_reroll_indices(
                    self._decision_context(player),
                    encounter,
                    decision.method,
                    progress.rolls,
                )
            elif self.interaction.choose_rerolls is not None:
                reroll_indices = self.interaction.choose_rerolls(
                    player, progress.rolls, progress.reroll_limit
                )
            else:
                reroll_indices = ()
            self.reroll_attempt(progress, reroll_indices)
        use_plus_two = False
        while progress.target > progress.rolled_total and any(
            potion.kind == PLUS_TWO for potion in player.potions
        ):
            if player.is_bot:
                use_plus_two = self.bot_policy.choose_plus_two_after_roll(
                    self._decision_context(player),
                    encounter,
                    decision.method,
                    progress.rolled_total,
                )
            elif self.interaction.choose_plus_two is not None:
                use_plus_two = self.interaction.choose_plus_two(
                    player, progress.rolled_total, progress.target
                )
            if not use_plus_two:
                break
            self.apply_plus_two(progress)
        return self.resolve_attempt(progress)

    def begin_attempt(
        self, player: Player, encounter: Encounter, decision: Decision
    ) -> ChallengeProgress:
        if self.state.game_over or encounter not in self.state.encounters:
            raise ValueError("invalid encounter attempt")
        if decision.method == encounter.blocked_method:
            raise ValueError(f"{decision.method} is blocked for {encounter.name}")
        if decision.method is None or not is_legal(decision.combo, decision.method):
            raise ValueError("invalid card combination")
        if decision.potion is not None:
            raise ValueError("+2 potion is selected after the challenge roll")
        if any(card not in player.hand for card in decision.combo):
            raise ValueError("attempt contains cards not in player's hand")
        for card in decision.combo:
            player.hand.remove(card)
        rolls = tuple(self.rng.choice(self.rules.die_faces) for _ in decision.combo)
        rolls = self._reroll_green_ones(player, rolls)
        skill_bonus = roll_bonus(
            player.character,
            player.skill_levels,
            method=decision.method,
            is_sea=encounter.is_sea,
        )
        rolled_total = sum(rolls) + skill_bonus
        self.last_roll = (rolls, skill_bonus, rolled_total)
        player.attempts += 1
        if self.interaction.show_roll is not None:
            self.interaction.show_roll(player, rolls, skill_bonus, rolled_total)
        progress = ChallengeProgress(
            player,
            encounter,
            decision,
            rolls,
            skill_bonus,
            rolled_total,
            encounter.target_for(decision.method),
            reroll_count(player.character, player.skill_levels),
        )
        self.active_challenge = progress
        return progress

    def reroll_attempt(
        self, progress: ChallengeProgress, indices: Sequence[int]
    ) -> tuple[int, ...]:
        if progress.rerolls_used:
            raise ValueError("rerolls have already been used")
        if (
            len(indices) > progress.reroll_limit
            or len(set(indices)) != len(indices)
            or any(index < 0 or index >= len(progress.rolls) for index in indices)
        ):
            raise ValueError("invalid reroll selection")
        if indices:
            progress.rolls = tuple(
                (self.rng.choice(self.rules.die_faces) if index in indices else roll)
                for index, roll in enumerate(progress.rolls)
            )
            progress.rolled_total = sum(progress.rolls) + progress.skill_bonus
            self.last_roll = (
                progress.rolls,
                progress.skill_bonus,
                progress.rolled_total,
            )
            if self.interaction.show_roll is not None:
                self.interaction.show_roll(
                    progress.player,
                    progress.rolls,
                    progress.skill_bonus,
                    progress.rolled_total,
                )
        progress.rerolls_used = True
        return progress.rolls

    def resolve_attempt(
        self,
        progress: ChallengeProgress,
        *,
        use_plus_two: bool = False,
        advance_experience: bool = True,
    ) -> bool:
        player = progress.player
        if use_plus_two:
            self.apply_plus_two(progress)
        success = progress.rolled_total >= progress.target
        progress.resolved = True
        progress.success = success
        decision = progress.decision
        encounter = progress.encounter
        if success:
            player.encounters.append(encounter)
            ending = len(player.encounters) >= 8
            if not ending:
                self._record_trophy_event(
                    player, encounter.encounter_type, encounter.icons
                )
                reward = encounter.rewards.get(decision.method)
                if reward is not None:
                    for _ in range(reward.coins):
                        self.gain_coin(player)
                    if reward.treasure:
                        self.gain_treasure(player)
                if encounter.automatic_treasure:
                    self.gain_treasure(player)
                if player.character.warrior_draw_trigger == WARRIOR_DRAW_TRIGGER:
                    self.draw_cards(player, 1)
                real_colors = {card.suit for card in decision.combo if not card.wild}
                wild_count = sum(card.wild for card in decision.combo)
                if min(5, len(real_colors) + wild_count) >= 3:
                    self._trigger_green_effect(player, "three_color_success")
                if len(player.hand) < 3:
                    self._trigger_green_effect(player, "low_hand_success")
                self._trigger_green_effect(player, f"{decision.method}_success")
            self.replace_encounter(encounter)
            if self.interaction.show_challenge_result is not None:
                self.interaction.show_challenge_result(player, True)
            if advance_experience:
                self.complete_experience(player)
        else:
            self.gain_potion(player)
            if self.interaction.show_challenge_result is not None:
                self.interaction.show_challenge_result(player, False)
        if self.rules.played_cards_on_success == "discard" and success:
            self.state.deck.discard(decision.combo)
        if self.rules.played_cards_on_failure == "discard" and not success:
            self.state.deck.discard(decision.combo)
        elif not success:
            player.hand.extend(decision.combo)
        if self.active_challenge is progress:
            self.active_challenge = None
        return success

    def apply_plus_two(self, progress: ChallengeProgress) -> None:
        """Spend one +2 potion on an unresolved Challenge roll."""
        plus_two = next(
            (potion for potion in progress.player.potions if potion.kind == PLUS_TWO),
            None,
        )
        shortfall = progress.target - progress.rolled_total
        if plus_two is None or shortfall <= 0:
            raise ValueError("a +2 potion is not available for this roll")
        bonus = self.use_potion(progress.player, plus_two, for_challenge=True)
        progress.rolled_total += bonus
        self.last_roll = (
            progress.rolls,
            progress.skill_bonus + bonus,
            progress.rolled_total,
        )
        if self.interaction.announce is not None:
            self.interaction.announce(
                f"{progress.player.name} used a +2 potion after the roll."
            )

    def complete_experience(self, player: Player) -> None:
        if len(player.encounters) >= 8:
            self.state.game_over = True
            self.state.winner = max(
                self.state.players,
                key=lambda candidate: winner_key(self.score(candidate)),
            )
            self.pending_treasure_draw = None
            self.pending_trader_draw = None
            self.pending_discard = None
            return
        self.advance_experience(player)

    def score(self, player: Player) -> ScoreBreakdown:
        player_index = self.state.players.index(player)
        return score_player(
            player.encounters,
            player.treasures,
            player.coins,
            player.character,
            player_index=player_index,
            trophy_event_log=self.state.trophy_events,
            skill_levels=player.skill_levels,
        )
