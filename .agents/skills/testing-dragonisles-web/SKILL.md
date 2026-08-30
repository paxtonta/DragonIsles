---
name: testing-dragonisles-web
description: How to run and playtest the DragonIsles browser app locally, including contriving edge cases by mutating the in-memory WebSession from a throwaway harness.
---

# Testing the DragonIsles web app

## Running the app

- Start the shipped server: `python -m dragonisles.web --port 8125` from the repo root.
- No login/auth; open `http://127.0.0.1:<port>` in the browser.
- The UI defaults to dark mode; click `Use light mode` (theme is stored in `localStorage` under `dragonisles-theme`).
- `dragonisles.web.SESSION` is process-global and `WebSession._run_bots()` auto-plays bot turns, so a fresh game requires a fresh server process.

## Contriving edge cases (no app changes)

Run a throwaway harness OUTSIDE the repo (e.g. `/home/ubuntu/edge_case_harness.py`) so nothing is committed:

```bash
cd /path/to/dragonisles-bot && PYTHONPATH=/path/to/dragonisles-bot python3 -i /home/ubuntu/edge_case_harness.py
```

The `PYTHONPATH` export is required — importing `dragonisles.web` from a script outside the repo otherwise fails with `ModuleNotFoundError`.

In the harness: `import dragonisles.web as W`, take `S = W.SESSION`, then serve `W.Handler` with `ThreadingHTTPServer` on a free port in a daemon thread. Because the interpreter stays interactive (`python3 -i`), you can mutate state between browser clicks and just press F5 in the browser to see it.

Useful mutations:
- Force the human's turn: set `S.game.state.current_player = 0` and clear `S.pending_prepare`, `S.pending_challenge`, `S.game.pending_discard`, `S.game.pending_trader_draw`.
- Overflow/discard: replace `S.human.hand[:]` with more cards than `hand_limit`, then call `S.game.discard_down(S.human)` to stage `pending_discard`.
- Blocked method: replace `S.game.state.encounters[0]` with an `Encounter(..., blocked_method="steal")`. The encounter card then renders `Steal BLOCKED` and `/api/options` returns `{"enabled": false, "reason": "blocked method"}`, which greys out the method button.
- Potions: set `S.human.potions[:] = [PotionToken(PLUS_TWO), ...]`. `+2` buttons only appear inside a challenge with a shortfall; `Draw 2`/`Purge` appear in the `Potion effects` panel.
- Force an exact challenge shortfall: after clicking `Challenge`, set `S.pending_challenge.target = S.pending_challenge.rolled_total + N`.

## Things worth asserting

- Cards show rank only; suit is conveyed by CSS classes `suit-red|yellow|green|blue|purple` (see `SUITS` in `dragonisles/cards.py` — orange is NOT an Adventure Card suit; `.treasure-orange` is a separate Treasure-color concept and is not a leftover). Zoom into the chips to verify duplicate ranks are distinguishable — suit names are not printed. Always cross-check the rendered colors against `curl -s localhost:<port>/api/state | python3 -c "..."` so the mapping is verified against data.
- Purple has a light-mode override (`:root[data-theme="light"] .suit-purple`), so verify purple legibility in BOTH themes if the palette changes.
- The `Choose discards` panel reuses `cardHtml`, so it is the easiest place to get many suits (and duplicate ranks in different suits) on screen at once: overdraw via `Prepare instead` → repeated `Draw from deck`.
- Treasure names render with `title=` tooltips (`treasureHtml`). Native tooltips DO screenshot, but only after ~2-2.5s of hover: `mouse_move` to a nearby point first, then `mouse_move` onto the name, then `wait` 2.5s before screenshotting. If it still does not appear, fall back to asserting the `description` in `/api/state` and label the visual check inconclusive rather than claiming a visual pass.
- Green treasures each have their own text in `GREEN_TREASURE_DESCRIPTIONS`; orange treasures read `Worth 1 VP.` Hover two different treasures to prove the mapping is not swapped.
- `Use +2 potion` can be clicked repeatedly in one challenge; total should rise by 2 each click and the potion list shrink.
- Purge should draw 1 card and replace all four encounters.
- Privacy: `serialize_player(..., reveal_potions=player is self.human)` means the opponent panel must show `Potions: <count>` only. Bot decisions use `Game._decision_context_for`, which contains only that player's own hand/potions/treasures/skills plus public info (encounter row, market, trophy events) — verify with `S.game.decision_context(bot).__dataclass_fields__` if this is questioned.
- Potion use is not written to the Events log for `Draw 2`/`Purge` (only `+2` logs a line), so verify those via state changes rather than the log.

## Getting deep into a real game without mutating state

When the ask is a watchable *real* game (no harness), these levers make progress fast:
- Failing a Challenge grants a potion, so a deliberate long-shot Challenge is a reliable way to obtain potions for `+2`/`Draw 2`/`Purge` coverage.
- Choosing the `trophy` skill track on success grants treasures at levels 1 and 3 — the quickest reliable route to a green Treasure for tooltip testing. The `sneak` track level 1 grants a potion.
- A green `Mirror` (sneak_draw) trigger is easy to demonstrate: build a long run (e.g. 1-2-3-4-5, one die per card) and sneak a low-target encounter; the Events log then prints `Human's green treasure drew 1 Adventure card.`
- `Purge` redeals the whole encounter row, which is the practical way to make rare named encounters (e.g. Dragon King) appear.

## Reaching the terminal Game over in a raw game

A full game to the terminal state is achievable in ~20 turns of raw play (verified: Game over at
Turn 21, Human 33 VP vs Bot 8 VP). `engine.complete_experience` ends the game at **8 completed
Encounters** for either player, and `web.py` then renders a `Turn N — Game over` header plus a
`Final scores` panel with `— winner`. Practical guidance:

- Card count = dice count, and the challenge target is compared against the dice total, NOT the card
  ranks. So a 3-card combo against a low target (e.g. Steal 4-5 on a Shogoro / Mountain of Darkness /
  Hyotan Kozu) is nearly automatic. Prefer *more cards vs. a low target* over high-VP encounters.
- Remember the combo rules (`dragonisles/combos.py`): Sneak = run, Steal = same rank in distinct
  suits, Strike = same suit. Duplicate ranks in hand are the cheapest reliable Steal.
- Method buttons are the fastest legality oracle: `title="blocked method"` vs
  `title="no legal combination"` tells you exactly why a method is greyed out — do not go read the
  source mid-recording (that leaves dead air), just read the tooltip attribute.
- When all four Encounters have high targets, `Purge` is a legitimate raw play: it draws 1 card and
  redeals the whole row, usually surfacing a low-target card you can close the game on.
- `Prepare instead` → `Draw from deck` is the way to fish for cards; the Prepare button row shifts
  down when the panel opens, so re-screenshot before clicking `Draw from deck` or the click misses.

## Verifying duplicate-name rendering (`Completed:` / `Treasures:`)

Rendering of *repeated* names in the Public state panels (`completedText()` in `web.py`) can only be
proven by a list that actually contains the same name twice for **one** player — a list of distinct
names renders identically under both the old (`Name (vp)`) and new (bare `Name`) implementations, so
a screenshot of distinct names is not evidence. Practical notes:

- Duplicates are rare in raw play: two full games to Game over produced 8 and 4 completed Encounters
  per player with no repeat within a player's own list, even though the same Encounter name (e.g.
  `Kamaitachi`) appeared for *both* players and twice in the Encounter row at once.
- Duplicate **Treasures** are much easier to hit naturally (skill-ladder treasure rewards repeat, e.g.
  `Biwa, Biwa`), but they go through `treasureHtml()`, a different code path — do not present them as
  proof for `completedText()`.
- If the assertion must be proven, ask for permission to contrive it via the out-of-repo harness:
  append the same `Encounter` object twice to `player.encounters` on the in-memory `WebSession` and
  reload the page. Otherwise report the assertion as **untested**, not passed.

## Verifying the bot's Encounter-selection ramp from the browser alone

`BotPolicy._target_encounter` sorts the row by a **hand-independent** difficulty key and then picks the
scheduled slot. Read `bot.py` each run, because both the metric and the schedule have changed more than
once. As of the ramp-v2 work the metric is `min(printed_target / METHOD_ATTAINABILITY[method])` over
**non-blocked** methods (`{sneak: 0.90, steal: 0.67, strike: 0.90}` — a low Steal target is penalised
~1.49x), and the schedule is `slot = min(completions // 2, 3)`, i.e. **1,1,2,2,3,3,4** by completion
count. Earlier code used the plain average of legal targets and `min(completions, 3)`; computing both the
old and new expected pick per turn is what makes a turn *discriminating* evidence rather than a
coincidence.

Every input is printed on the Encounter card (`Sneak X, Steal Y, Strike Z`, with `BLOCKED` marking the
excluded method), so the expected pick is computable from a screenshot — no code instrumentation needed.

- Screenshot the row **immediately before ending your turn**, note each card's average legal target and
  the Bot's completed count from its Public state panel, then compare with what the Bot actually
  attempted (its `Completed:` line on success, or the Events-log roll on failure).
- Ties on avg/max/min are broken by reward and then alphabetically by name — expect this when the row
  holds two cards with identical targets (common for 1-VP tsukumogami cards).
- Beware silent bot turns: **a bot turn that logs nothing at all is a `Prepare`**, and a bot turn where
  its potion count drops by one with the whole row replaced is a `Purge`. Neither yields a pick to
  check, so budget extra turns — in one full game only 3 of the Bot's 10 turns were challenges.
- There is a **winnability fallback**: if the scheduled card is not likely winnable, the bot drops to the
  hardest winnable card *at or before* the scheduled slot; if nothing is winnable it keeps the scheduled
  target and Prepares. So the pass criterion is "scheduled slot, or a card at/before it" — a pick
  strictly *harder* than the scheduled slot is the failure to look for.
- Historic failure mode to regression-check: with the fallback missing/broken the bot pins itself on an
  unbeatable hardest card and **Prepares on every remaining turn**, freezing its completed count (seen at
  3 completions / 6 VP). Track each bot turn as challenge/prepare/purge; a run of 3+ consecutive Prepares
  while the row visibly holds a beatable card is a failure, not "untested".
- Prepare observability: the Events feed logs `Bot Prepared from market card <suit> <rank>.` or
  `Bot Prepared from the deck.` (deck identity hidden by design). Use these to judge whether draws
  accumulate toward the current ramp target; if every Prepare is "from the deck" the accumulation claim is
  only judgeable from the follow-up Challenge, so call it inconclusive rather than passed.
- The late-ramp and 7+ endgame branches ARE reachable in raw play once the fallback exists — a full game
  took the bot to 7 completions and it challenged there instead of deadlocking. Budget ~30 turns.
- The 7+ "close out a win" branch only fires if finishing would leave the bot ahead; when it is far
  behind on VP the branch legitimately falls through to the normal schedule, so seeing a plain ramp pick
  at 7 completions is NOT a failure — record both scores before asserting.
- Privacy re-check is a one-liner and does not need the UI:
  `python3 -c "import dataclasses,dragonisles.bot as b;print([f.name for f in dataclasses.fields(b.DecisionContext)])"` —
  there must be no `opponent_hand` / `opponent_potions`.

## Light-mode contrast on buttons (historically broken, now fixed — keep checking)

All buttons are `background:#e7b94f` (`web.py`) while card/treasure names carry suit/treasure colors. For
a while only `.suit-purple` had a light-mode override, so on any *button* embedding a card or treasure
name, yellow-suit cards and orange treasures were effectively invisible — the `Market: <card>` label in
the Prepare panel and the `Treasure reward` / `Trader treasure` keep buttons rendered with no readable
name. Darkened light-mode variants for every suit/treasure color were later added
(`:root[data-theme="light"] .suit-*` / `.treasure-*`), and a full game confirmed Market ranks and
orange/green treasure names legible again.

When re-checking: these are **pixel** assertions — zoom into the screenshot and read the text, and always
compare against the DOM text so a missing label is distinguishable from an empty one. A specific color
can only be claimed if a card of that suit actually appeared on a button during the game; otherwise mark
that color **untested** (yellow-on-button is the one that most often fails to occur naturally).

## Dice are NOT d6

`DIE_FACES = (1, 2, 2, 3, 3, 4)` in `dragonisles/dice.py`. A die averages **2.5** and caps at **4**, so
standard-d6 reasoning systematically overestimates what N cards can roll (e.g. two dice totalling >= 7 is
9/36 = 25%, not 21/36 = 58%). Never narrate or plan a challenge with d6 math; prefer quoting the app's own
displayed dice/total/verdict.

## Post-Game-over UI gating (partly fixed — always re-check every button)

Historically the `Treasure reward` keep-1-of-2 panel survived `Game over` and clicking `Keep this` raised a
JS `alert("the game is over")`. `treasureChoiceHtml` / `traderHtml` / `discardHtml` are now suppressed when
`S.game_over`, and a later raw game confirmed no pending-choice panel remains. **But other controls may
still be live**: on `7d6f580` the potion panel's `Use Purge` button and `Prepare instead` were still enabled
after Game over and both raised the same `the game is over` alert (`Challenge` was correctly disabled).
When a game ends, systematically click every still-enabled control on the final page and report any that
alert; do not assume "no pending panel" means the page is fully gated.

## Verifying the 8th (game-ending) Encounter grants no follow-on rewards

The game ends the moment a player reaches 8 completed Encounters, and that Encounter must grant **only its
printed VP** — no skill-track level-up, printed coin/treasure reward, automatic treasure, trophy advance,
Warrior draw, or green-treasure success trigger (`engine.py` `resolve_attempt` skips them when
`len(player.encounters) >= 8`).

How to assert it from the browser: screenshot the *whole* page on the turn immediately before the win and
record score, coins, skills map, visible skill-ladder levels, treasures list, the trophy header line, and
the token-supply counters; then diff against the Game over page. Useful details:

- The strongest evidence is the **missing** `<name> advanced the <track> skill track` Events line — every
  non-final win logs one, so its absence on the final win is a clean positive assertion. Capture an early
  non-final win as the baseline for that.
- **Beware roll-time coin gains inflating the score delta.** Green treasures with `roll_ones_coin`
  (`Omamori`) grant coins inside `_reroll_green_ones`, i.e. **before** resolution, and those coin gains are
  **not announced** in the Events feed (only `... rerolled dice showing 1.` is). With
  `coin_points = coins × character.coin_multiplier` (1 for most characters, 2 for Pirate) each such coin is
  +1 VP, so a 1 VP final Encounter can legitimately show a +3 VP delta. Check the token supply
  (`Coins left: N×1`) and the ordering of Events lines before calling it a reward leak.
- The game may end on the **Bot's** 8th Encounter; that is still fully assertable, because the Bot's Public
  state panel exposes score, coins, skills, completed list and treasures.
- If the game-ending card has no printed coin/treasure reward and no automatic treasure, say so and mark
  those specific branches **untested** rather than implying they were exercised.

## Winner is the highest-VP player, not whoever reaches 8

Reaching 8 Encounters only *ends* the game. `web.py`'s `gameOverHtml` marks every player whose score equals
the max with `— winner` (so ties render as shared wins). The discriminating browser evidence is a game where
the player who reaches 8 is **not** the top scorer — if the 8th-completer also has the most VP, the run is
consistent with but does not prove the rule, and should be reported that way. `state.winner` is not exposed
in the web payload, so engine/UI identity cannot be compared directly through the UI.

## Devin Secrets Needed

None.
