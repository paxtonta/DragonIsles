# DragonIsles Bot

Data-driven two-player DragonIsles CLI implementation with a literal-strategy practice bot.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m dragonisles
```

The browser front end is available as an additional fallback/presentation
layer:

```bash
.venv/bin/python -m dragonisles.web
```

Open the printed URL (`http://127.0.0.1:8000`) in a browser, or pass
`--port 8123` if that port is taken. The web server uses the standard library
only; the existing CLI remains unchanged.

In the browser, a challenge pauses after the roll so rerolls are chosen with the dice visible, the player's
potion list and `+2` availability are shown before Challenging, and Prepare picks its
source one draw at a time so the market refill is visible between draws.
When a player receives a treasure, the browser pauses and offers two treasures;
choose which one to keep before the turn continues. The other treasure is
spent and may return when the treasure supply is reshuffled. When a Trader
receives a treasure, the browser then offers the three drawn Adventure Cards;
choose which one to keep before the turn continues.
If Prepare or a reward would exceed the hand limit, the browser likewise
pauses so you choose exactly which cards to discard.
Success odds are never displayed to the human on either front end; the bot
still computes them for its own decisions. Public player state includes each
player's current hand limit without revealing the cards in an opponent's hand.

The literal bot ramps through the encounter row by hand-independent difficulty.
Each legal method's target is adjusted by method attainability weights
(Sneak 0.90, Steal 0.67, and Strike 0.90), so Steal counts as harder than an
equal-target Sneak or Strike while Sneak and Strike remain equally easy. The encounter's
difficulty is the easiest adjusted legal method, with maximum and minimum
adjusted targets as tie-breakers. Character reward preferences only break
equal-difficulty ties.
The first seven completion counts use difficulty slots in the schedule
`1, 1, 2, 2, 3, 3, 4`; shorter rows clamp to their last available slot.
If the scheduled slot is not likely winnable, the bot falls back to the
hardest winnable slot at or before it, using the same character-specific
probability threshold. If none are winnable, it keeps the scheduled target
and the normal Prepare logic applies.
After seven completed Encounters, it switches to the easiest winnable Encounter
only when completing it would close out a win; otherwise it keeps the hardest
slot to pursue the points it needs.

## Encounter deck

`data/encounters.json` is the shipped, hand-authored 50-card encounter deck.
It is not generated at build time and is not the published Gamewright card
list. The deck has ten cards of each encounter type and currently contains
25 sea and 25 land encounters. See `encounter_deck.md` for the complete table
and reconstruction notes.

The old encounter generator was removed intentionally: it is no longer the
source of the shipped deck. Runtime loading validates only structural
requirements so hand-authored target values, tiers, families, and reward
placement can vary without being rejected.

## Confirmed rules implemented

- The Adventurer deck has 60 suited cards plus four wilds.
- Players begin with exactly five cards.
- Starting hand limits are Monk 8, Sorcerer 8, Warrior 7, Pirate 7, and
  Trader 7.
- Hand-limit skill steps are confirmed to grant +1 or +2 only. Fully levelled
  characters cap at 10 cards, except Trader at 11.
- Character skill ladders use the requested cumulative bonuses and reward
  markers: Trader has Sneak 1/2/4, Steal 1/2/3, Strike 1/2/3, and hand
  size +1/+3/+4; Monk has Sneak 1/2/3/4, Steal 1/2/3, Trophies 1/2/3,
  and hand size +1/+2; Warrior has Strike 1/2/4/5, Sneak 1/2/3,
  Trophies 1/2/3, and hand size +1/+3; Pirate has Sea 1/2/3,
  Rerolls 1/2/3/4, Trophies 1/2/3, and hand size +1/+3; Sorcerer has
  Sneak 1/2/3/4, Strike 1/2/3, Rerolls 1/2/3, and hand size +1/+2.
- Sneak uses consecutive numbers, Strike uses one color, and Steal uses one
  number across different colors. Wilds can fill missing colors.
- A challenge may be made with a single card, rolling one die. A lone card
  satisfies all three shapes, so only the encounter's blocked method is
  unavailable.
- Successful challenge cards are discarded; failed challenge cards remain in
  the player's hand.
- Potions are free actions and can be used during a turn. `+2` potions are
  restricted to Challenge rolls, and multiple `+2` potions may be used during
  one Challenge when needed.
- `Draw 2` draws two Adventurer Cards. `Purge` draws one Adventurer Card,
  discards and redeals the four-card Encounter row, and preserves the mixed
  Land/Sea row rule when possible; it does not discard the player's hand.
- Token supplies are finite: 20 potion tokens, and 30x1, 10x5 and 10x10 coin
  tokens. Larger coin tokens are exchanged into ones automatically when the
  1-coin supply runs out. If no coin token can be produced, the coin is taken
  from the other player, and if that player has none the coin cannot be
  gained. Potions come from the supply first, then from the other player, and
  only then from reshuffling the spent potion tokens.
- The treasure supply has 30 green treasures from 10 unique effects and 15
  orange treasures: 3 each for Dragon, Oni, Bakemono, Tsukumogami, and
  Location.
- One skill track level is gained after every successful encounter.
- Sorcerer and Pirate reroll tracks grant one optional die reroll per level;
  their multi-level step values are reconstructed.
- An encounter may block one challenge method. Blocked methods are unavailable
  in the CLI and are never selected by the bot; the shipped assignments are
  reconstructed.
- Skill-track slot rewards are reconstructed across the majority of all slots.
  Every Trader slot grants either a coin or treasure, per the user's explicit
  guarantee; other characters mix earlier coins/potions with rarer deeper
  treasure rewards. There are 52 slots total and 30 rewarded slots. Treasure
  rewards use the shuffled treasure supply.
- Encounter cards show their icon count. Multiple icons count multiple times
  toward the matching type trophy, but the card still counts once toward the
  eight-encounter ending and keeps its printed VP.
- Completing 8 Encounters ends the game. The player with the most VP wins;
  VP is the win condition, not merely a display score. If final VP is tied,
  the player with the highest percentage of points from Coins wins; only an
  equal percentage is a shared win.
- The 8th Encounter still counts for its printed VP, but grants no follow-on
  rewards: no skill-track advancement, printed Encounter rewards, automatic
  Treasure, trophy advance, or other success-triggered effects.
- Each type trophy has exactly one holder. It is taken by the first player to
  lead and transfers only when another player strictly exceeds that holder;
  tying does not share or transfer it. The all-five-types bonus is awarded
  independently to each player when they complete all five types, so it never
  transfers or removes the other player's bonus.
- Multiple-icon encounters are sea encounters only; land cards are limited to
  one icon.
- Humans choose their track through the CLI; bots choose automatically and
  announce their selected track.
- Market cards refill immediately whenever one is taken.
- The encounter row contains four cards. If all four are sea or all four are
  non-sea, the row is discarded and redealt. This applies during setup,
  encounter replacement, and Purge refills. Redealing is bounded; if the
  remaining deck cannot produce a mixed row, the final row is kept.
- Encounter cards removed by Purge or by a homogeneous-row redeal go to an
  encounter discard pile. When the draw pile empties, that discard pile is
  shuffled back into it using the game RNG. Encounters won by players never
  return to the deck.
- Pirate sea bonuses apply only to encounters marked `[SEA]` in the CLI.
- Orange treasures are worth 1 VP and add one encounter of their specified
  type toward trophies. Encounter rewards only say that a treasure is awarded;
  draw the top two treasures from the shuffled supply, keep one, and spend the
  other. Spent treasures are reshuffled into the supply when needed.

## Reconstructed rules and data

The following remain reconstructed stand-ins rather than confirmed published
values:

- Encounter target numbers.
- Encounter icon counts and the reconstructed distribution of two-icon cards.
- The deck uses the supplied 25 land and 25 sea cards. All Dragons are sea
  encounters with one icon, including the three Luck Dragons, three Sea
  Dragons, and two Rain Dragons.
- Unspecified skill-track step values other than the confirmed hand-limit
  steps. Every character has exactly twelve track slots; zero-bonus filler
  spaces preserve the existing reconstructed bonuses while keeping the
  ladders available through the end of the game.
- Some encounter names, family labels, rewards, and treasure effects.
- The dominance audit is advisory. An exact or near-duplicate pair may be
  intentional for deck variety; a reported pair should be reviewed rather
  than treated as an automatic reason to remove or rebalance a card.
  Its first list is technical Pareto dominance; its material-warning list
  also models the 60 colored cards, five colors, twelve numbers, and four
  wilds when comparing method difficulty. A Coin-only difference or a
  one-to-three-point target spread remains a review note rather than a defect.
  The audit also reports material shape warnings for no-reward cards with an
  extreme easy-route/hard-route spread, even when no card technically
  dominates another. In particular, a legal Steal route that is harder than
  both Sneak and Strike must have a Steal reward.
- A missing method is represented by a zero target and the card's single
  `blocked_method`; every other method remains playable. Duplicate stat groups
  share all gameplay fields, while each physical copy has its own name.
- Orange treasures are worth 1 VP while also counting toward their specified
  type trophy. The green treasures are Lucky Mallet, Daruma, Omamori,
  Dotakubell, Jewel, Katana, Mirror, Magatama Bead, Biwa, and Inuharaku.
  Every roll-1 treasure rerolls all 1s; the individual treasures then add a
  die, draw a card, or grant a coin as specified by its name.
- Equal random potion distribution.
- Reshuffling spent potion tokens once neither the supply nor the other player
  has a potion. The token counts and the "take one from another player" rule
  are confirmed; the reshuffle fallback is an assumption.

The loader accepts either a bare JSON list of encounter records or the current
metadata wrapper:

```json
{
  "_metadata": {
    "status": "unofficial reconstruction"
  },
  "encounters": []
}
```

Each encounter record requires:

- `name` (unique non-empty string)
- `victory_points` (integer from 1 through 7)
- `strike_target`, `sneak_target`, and `steal_target` (positive integers)
- `encounter_type` (`dragon`, `oni`, `bakemono`, `tsukumogami`, or `location`)

Optional fields are `family` (string or null), `difficulty_tier` (string),
`is_sea` (boolean, default false), `icons` (positive integer, default 1),
`rewards` (object), and
`automatic_treasure` (boolean, default false). Reward objects may contain
`coins` and/or `treasure: true`, indicating that one random treasure is
awarded from the reconstructed shuffled supply. `blocked_method` may be
`sneak`, `steal`, or `strike`. Green effects in the reconstructed supply are
`roll_ones`, `three_color_success`, `low_hand_success`, `sneak_success`,
`steal_success`, and `strike_success`.

## Bot strategy

The bot is a literal practice opponent. It orders the available Encounters from
easiest to hardest, using reward value as a secondary tie-breaker, and targets
the first, second, third, then hardest Encounter as it completes Encounters.
It challenges the current target only when its internally computed success
probability clears 50%; otherwise it prepares. Among methods that clear the
threshold, it prefers one with a reward unless that would prevent the normal
threshold decision. It prefers a useful face-up market card and draws facedown
when no market card improves the targeted legal challenge. These odds are never
shown to the human player. Exact probability, legal combo, risk-rescue potion,
reroll, and skill-track decisions remain engine-supported.
After a successful encounter, it prioritizes a method or Sea track that
improves the highest-VP encounter on the board. If no such track applies, it
chooses Trophy only after securing at least two type trophies; otherwise it
chooses Reroll, then Hand Limit when the current hand is likely to require a
discard.
Character-specific styles are reconstructed choices layered over this base:
Monk uses the same progression but challenges when its targeted method is less
than four points above the expected value of its dice roll. Pirate uses the same
policy with coins valued twice as highly. Trader uses the same policy while
preferring treasure rewards over other rewards when that does not undermine the
base decision. Sorcerer and Warrior use the base literal policy.
Trophy progress is history-aware: matching an opponent's icon count has no
value unless the challenge strictly passes the current holder.

The former adaptive opponent model, denial/race heuristics, potion-farming
detection, and self-play comparison harness are intentionally not shipped.
