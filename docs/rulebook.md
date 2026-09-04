# DragonIsles Rulebook

DragonIsles is a two-player card-and-dice adventure game. Players use
Adventure Cards to challenge encounters, collect treasures, advance skills,
and score the most Victory Points (VP).

## Objective

Complete encounters and collect valuable treasures. The player with the higher
final score wins. If final VP totals are equal, the player who earned the
larger share of their score from coins wins the tie.

The app automatically prepares the encounter row, Tavern, starting hands,
characters, and shared supplies. In multiplayer, both players use the same
private link and passphrase. Each seat sees its own hand and potions; the public
board shows shared encounters, Tavern cards, discard top card, challenge
activity, and public player totals.

## Starting player

Each player answers the boat question. A more recent date goes first. If the
dates match, the game asks for a clock time; the later specific time goes
first. Continue with more specific answers until the order is determined.

## Turn sequence

On your turn, choose one:

- **Challenge:** select an encounter, select cards, choose Sneak, Steal, or
  Strike, then roll.
- **Prepare:** draw your character's configured number of cards, one source at
  a time, from the Adventure Deck or Tavern.

After an action resolves, refill the encounter row or Tavern as required,
apply rewards and triggered abilities, enforce the hand limit, and pass the
turn.

## Adventure Cards and combinations

Cards have a number, color/suit, and sometimes a Wild value. A challenge uses
one or more cards and rolls one die per selected card, up to the method limit.
Wild cards can fill a missing number or suit where the combination rules allow.

### Sneak

Play a **run**: distinct consecutive numbers. Wild cards may fill gaps.
Sneak is limited to six cards.

### Steal

Play a **set**: cards with the same number and different suits. Wild cards may
complete the set. Steal is limited to five cards.

### Strike

Play cards sharing a **suit/color**. Wild cards can join a suited group.
Strike is limited to six cards.

An encounter can block a method. A selected hand must also form a legal
combination; otherwise that method is unavailable and Prepare may be used.

## Challenge resolution

1. Select an encounter and a legal card combination.
2. Choose a legal method and compare the roll target shown on the encounter.
3. Roll one DragonIsles die per card. Die faces are 1, 2, 2, 3, 3, and 4.
4. Add skill bonuses and any eligible modifiers.
5. If available, use a reroll ability or reroll potion according to its
   prompt.
6. If a **+2** potion is available, decide whether to use it during the
   challenge.
7. Resolve the total against the target.

Meeting or exceeding the target succeeds. A shortfall fails. On success, the
encounter is completed, the played cards are discarded, rewards are applied,
and the encounter is replaced. On failure, the played cards remain in hand
and the encounter is not completed.

## Prepare

Prepare draws two cards by default. Sorcerers draw three. For each draw,
choose the Adventure Deck or a Tavern card. Tavern cards are immediately
refilled from the deck. After each draw, discard down if the hand exceeds its
limit. Prepare ends after all draws and required discards are complete.

## Rewards

An encounter may award coins, a treasure, or both. Treasure rewards present
two treasures; keep one and return the other to the Treasure supply. Orange
treasures are worth 1 VP and contribute an encounter-type icon. Green
treasures provide passive effects.

A Trader who gains a treasure draws three Adventure Cards and keeps one.

## Skills

Every successful Challenge advances the player's experience and offers an
available skill track. Choose one track to advance. Each track step can grant
an ability bonus or a reward such as a coin, potion, or treasure.

Common track effects include:

- **Method tracks:** add dice-result bonuses for Sneak, Steal, or Strike.
- **Sea:** adds a bonus for a Pirate challenging a Sea encounter.
- **Reroll:** increases available rerolls.
- **Trophy:** increases the player's trophy bonus.
- **Hand limit:** increases the maximum hand size.

## Potions

Potions are shared-supply tokens:

- **+2:** add two to a challenge total; usable only during a challenge.
- **Draw 2:** draw two Adventure Cards and resolve the hand limit.
- **Purge:** draw one Adventure Card and redeal the encounter row.

Potions are spent when used. Character and treasure effects can grant
additional cards, coins, or potion-related effects.

## Characters

- **Monk:** draws one extra card after using a potion.
- **Pirate:** coins are worth double when scoring; Sea skill also helps on Sea
  encounters.
- **Warrior:** draws one Adventure Card after completing an encounter.
- **Sorcerer:** draws three cards during Prepare.
- **Trader:** draws three cards after gaining a treasure and keeps one.

## Green treasures

Green treasures trigger when their condition occurs. The supply includes
effects such as rerolling 1s, adding a die, drawing a card, gaining a coin,
and gaining a reward after a Sneak, Steal, Strike, three-color, or low-hand
success. The exact trigger and effect are shown when the treasure is displayed.

## Scoring

Final score is the sum of:

- encounter VP;
- VP printed on orange treasures;
- 3 VP for each encounter-type trophy held;
- 5 VP for the all-types trophy;
- coin value, multiplied by the character ability when applicable.

Trophy ownership is based on the player's accumulated icons for each
encounter type, including matching orange treasure icons. Trophy bonuses from
the character's Trophy skill are added when trophies are scored.

## Multiplayer and privacy

The versus game has two seats. A seat name is shown in the header as
`Playing as [name] · vs [opponent]`. A player who closes their browser can
reclaim their seat after the inactive session expires. While waiting, the UI
identifies the opponent by name or says that no other player has joined yet.

Private hands and potion inventories are filtered by seat. Challenge cards,
dice, totals, rewards, and shared-board information become visible only at the
appropriate public stage.

## End of game

When the game ends, compare final scores and apply the coin-share tie-break.
The final-score panel shows each player's VP total.
