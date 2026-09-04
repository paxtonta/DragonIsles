import { useState } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";

const commonSections = [
  ["Objective", "Complete encounters and collect treasures. The highest final score wins; equal VP totals are decided by the larger share earned from coins."],
  ["Cards and board", "The app automatically prepares five-card starting hands, four encounters, two public Tavern cards, and the shared Adventure Card, Treasure, Potion, and Coin supplies. Encounters show their type, VP, icons, Sea/Land status, method targets, blocked method, and any reward."],
  ["Starting player", "The later boat date goes first. If dates match, submit increasingly specific clock times until a later time determines the order."],
  ["Turn sequence", "On your turn, Challenge an encounter or Prepare. Resolve the action, apply rewards and abilities, enforce your hand limit, refill the board, and pass the turn."],
  ["Sneak, Steal, and Strike", "Sneak uses a run of consecutive numbers and allows up to six cards. Steal uses a same-number set with distinct suits and allows up to five cards. Strike uses cards sharing a suit/color and allows up to six cards. Wild cards can fill a missing number or suit where legal. An encounter may block a method."],
  ["Challenge resolution", "Play one legal combination, roll one die per card, and compare the result with the selected encounter target. Dice have faces 1, 2, 2, 3, 3, and 4. Add skill bonuses and eligible modifiers, then resolve any reroll or +2 decisions. Meeting or exceeding the target succeeds: played cards are discarded, the encounter is completed, rewards are applied, and the row is refilled. A shortfall fails: played cards stay in hand and the encounter remains."],
  ["Prepare", "Prepare draws two cards by default, or three for a Sorcerer, from the Adventure Deck or Tavern. Refill Tavern cards immediately and discard down whenever the hand exceeds its limit."],
  ["Hand limits and discards", "The starting limits are Monk 8, Pirate 7, Warrior 7, Sorcerer 8, and Trader 7. When a draw exceeds the limit, choose cards to discard until the limit is restored. Failed challenge cards are not discarded."],
  ["Rewards", "Encounter rewards can include coins and treasure. Draw two treasures and keep one. Orange treasures are worth 1 VP and contribute their encounter-type icon; green treasures provide passive effects. A Trader draws three cards after gaining treasure and keeps one."],
  ["Skills", "Each successful Challenge advances experience and offers an available skill track. Tracks can improve Sneak, Steal, Strike, Sea, rerolls, trophies, or hand limit, and can award coins, potions, or treasures. Pirate's Sea skill adds to Sea encounters."],
  ["Potions", "+2 adds two to a challenge total and is usable only during a challenge. Draw 2 draws two cards. Purge draws one card and redeals the encounter row."],
  ["Characters", "Monk draws one extra card after using a potion. Pirate's coins are worth double when scoring, and Pirate Sea skill helps on Sea encounters. Warrior draws one card after completing an encounter. Sorcerer draws three during Prepare. Trader draws three after gaining treasure and keeps one."],
  ["Green treasures", "Green treasures trigger on their displayed condition. Their passive effects include rerolling all 1s, adding a die, drawing a card, gaining a coin, and gaining a reward after a low-hand, method, or three-color success. The treasure text identifies its exact trigger and effect."],
  ["Scoring", "Final VP combines completed encounters, orange treasure VP, 3 VP per regular encounter-type trophy, 5 VP for the all-types trophy, and coin value after character modifiers. Trophy skill rewards add their configured bonus."],
  ["End of game", "Compare final scores. If tied, the player with the larger coin-derived share wins."],
] as const;

type RulebookProps = { mode: "bot" | "versus" };

export function Rulebook({ mode }: RulebookProps) {
  const [open, setOpen] = useState(false);
  const sections = mode === "versus"
    ? [...commonSections.slice(0, -1), ["Multiplayer privacy", "Each seat sees its own hand and potions. Shared encounters, Tavern cards, discard top card, challenge activity, dice, rewards, and public totals are shown according to the current game stage. Stale seats become reclaimable after inactivity."], commonSections.at(-1)!]
    : [...commonSections.slice(0, -1), ["Bot mode", "In bot mode, the second seat is controlled by the DragonIsles bot. The bot follows the same encounter, card, dice, reward, skill, potion, and scoring rules as a human player."], commonSections.at(-1)!];

  return <>
    <Button variant="secondary" onClick={() => setOpen(true)}>Rulebook</Button>
    {open && <div className="rulebook-backdrop" role="presentation" onClick={() => setOpen(false)}>
      <Card className="rulebook-dialog" role="dialog" aria-modal="true" aria-labelledby="rulebook-title" onClick={event => event.stopPropagation()}>
        <CardHeader><CardTitle id="rulebook-title">DragonIsles Rulebook</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">The complete rules for cards, challenges, progression, scoring, and multiplayer play.</p>
          {sections.map(([title, text]) => <section className="rulebook-section" key={title}><h3>{title}</h3><p>{text}</p></section>)}
          <Button onClick={() => setOpen(false)}>Close rulebook</Button>
        </CardContent>
      </Card>
    </div>}
  </>;
}
