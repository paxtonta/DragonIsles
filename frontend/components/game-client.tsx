"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Input } from "./ui/input";
import { Label } from "./ui/label";

type AdventureCard = { index: number; label: string; suit: string | null; rank: number | null; wild: boolean };
type Treasure = { label: string; color: string; description: string };
type Encounter = { id: string; name: string; type: string; vp: number; icons: number; sea: boolean; mechanics: string; targets: Record<string, number>; blocked: string | null };
type Player = { name: string; character: string; ability: string; is_bot: boolean; encounters: { name: string }[]; coins: number; hand_count: number; hand_limit: number; potions: string[] | number; treasures: Treasure[]; skills: Record<string, number>; seat: number; score: number; coin_points: number };
type Ladder = { level: number; steps: { bonus: number; reward: string | null; reached: boolean }[] };
type Challenge = { player: string; player_is_bot: boolean; cards: AdventureCard[]; encounter: string; method: string; rolls: number[]; skill_bonus: number; total: number; target: number; shortfall: number; reroll_limit: number; rerolls_used: number; phase: "reroll" | "resolve" | "skill" | "done"; plus_two: boolean; tracks: string[]; result: boolean };
type Boat = { stage: "date" | "time"; answered: boolean; mine: string | null; waiting: boolean; message?: string | null };
type State = {
  turn: number; revision: number; mode: "bot" | "versus"; seat: number; seat_name: string; opponent_name: string | null;
  human_turn: boolean; die_faces: number[]; game_over: boolean; events: string[]; prepare: { remaining: number; drawn: AdventureCard[] } | null;
  challenge: Challenge | null; discard_top: AdventureCard | null; trader: { cards: AdventureCard[] } | null;
  treasure: { treasures: Treasure[] } | null; discard: { count: number; player: string; player_is_bot: boolean } | null;
  tokens: { potions: number; coins: [number, number][] }; encounters: Encounter[]; hand: AdventureCard[]; players: Player[];
  market: AdventureCard[]; tracks: string[]; ladders: Record<string, Ladder>; trophies: Record<string, string | null | string[]>;
  boat?: Boat | null; boat_result?: string | null; first_turn?: { pending: boolean } | null; first_turn_result?: string | null;
};
type Options = Record<"sneak" | "steal" | "strike", { enabled: boolean; reason: string }>;

const methodDescriptions: Record<"sneak" | "steal" | "strike", string> = {
  sneak: "Sneak: use matching cards to quietly overcome the encounter.",
  steal: "Steal: use cards to take the encounter's treasure or reward.",
  strike: "Strike: use cards to defeat the encounter through force.",
};

const api = async (path: string, body?: Record<string, unknown>) => {
  const response = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data: unknown = await response.json();
  if (!response.ok) throw new Error(typeof data === "object" && data && "error" in data ? String(data.error) : "Request failed");
  return data;
};

function CardFace({ card }: { card: AdventureCard }) {
  return <span className={`adventure-card ${card.suit ? `suit-${card.suit}` : ""}`}>{card.label}</span>;
}

function TreasureFace({ treasure }: { treasure: Treasure }) {
  return <span className={`treasure-card treasure-${treasure.color}`} title={treasure.description}>{treasure.label}</span>;
}

function LoadingOrLogin({ onJoined }: { onJoined: () => void }) {
  const [name, setName] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api("/api/join", { name, passphrase });
      onJoined();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to join game.");
    }
  };
  return <main><Card><CardHeader><CardTitle>DragonIsles</CardTitle></CardHeader><CardContent>
    <p>This private game is for whoever has the link and passphrase.</p>
    <form onSubmit={submit}><Label>Your name<Input value={name} maxLength={20} onChange={event => setName(event.target.value)} /></Label>
      <Label>Passphrase<Input type="password" value={passphrase} onChange={event => setPassphrase(event.target.value)} /></Label>
      <Button type="submit">Join game</Button><p role="alert">{error}</p>
    </form>
  </CardContent></Card></main>;
}

export default function GameClient() {
  const [state, setState] = useState<State | null>(null);
  const [needsLogin, setNeedsLogin] = useState(false);
  const [selectedEncounter, setSelectedEncounter] = useState<string | null>(null);
  const [selectedCards, setSelectedCards] = useState<number[]>([]);
  const [discardCards, setDiscardCards] = useState<number[]>([]);
  const [rerollDice, setRerollDice] = useState<number[]>([]);
  const [method, setMethod] = useState<string | null>(null);
  const [options, setOptions] = useState<Options | null>(null);
  const [boatText, setBoatText] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const next = await api("/api/state") as State;
      setState(next); setNeedsLogin(false); setError("");
    } catch (caught) {
      if (caught instanceof Error && caught.message.includes("authentication")) setNeedsLogin(true);
      else setError(caught instanceof Error ? caught.message : "Unable to load game.");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!state) return;
    const delay = state.mode === "versus" && !state.human_turn ? 2000 : 3000;
    const timer = window.setInterval(() => { if (!state.challenge && !state.prepare && !state.discard && !state.trader && !state.treasure) void load(); }, delay);
    return () => window.clearInterval(timer);
  }, [load, state]);

  const post = async (body: Record<string, unknown>) => {
    try {
      const next = await api("/api/action", body) as State;
      setState(next); setSelectedEncounter(null); setSelectedCards([]); setDiscardCards([]); setRerollDice([]); setMethod(null); setOptions(null); setError("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Action failed."); await load(); }
  };

  useEffect(() => {
    if (!state || !selectedEncounter || !selectedCards.length || !state.human_turn) { setOptions(null); return; }
    let cancelled = false;
    void api("/api/options", { encounter: selectedEncounter, cards: selectedCards }).then(data => { if (!cancelled) setOptions(data as Options); }).catch(() => { if (!cancelled) setOptions(null); });
    return () => { cancelled = true; };
  }, [selectedCards, selectedEncounter, state]);

  if (needsLogin) return <LoadingOrLogin onJoined={() => void load()} />;
  if (!state) return <main><p>{error || "Loading…"}</p></main>;

  const busy = Boolean(state.challenge || state.prepare || state.trader || state.treasure || state.discard);
  const actionDisabled = state.game_over || Boolean(state.boat) || Boolean(state.first_turn) || (state.mode === "versus" && !state.human_turn);
  const player = state.players.find(item => item.seat === state.seat);
  const titleStatus = state.first_turn ? "" : `Turn ${state.turn} — ${state.game_over ? "Game over" : state.human_turn ? "Your turn" : state.mode === "versus" ? `Waiting for ${state.opponent_name || "opponent"}…` : "Bot turn"}`;
  const toggleCard = (index: number) => setSelectedCards(cards => cards.includes(index) ? cards.filter(item => item !== index) : [...cards, index]);
  const toggleDiscard = (index: number) => setDiscardCards(cards => cards.includes(index) ? cards.filter(item => item !== index) : [...cards, index]);
  const challenge = state.challenge;
  const completed = (item: Player) => item.encounters.map(encounter => encounter.name).join(", ") || "none";
  const trophies = Object.entries(state.trophies);

  return <main>
    <h1>DragonIsles <Button variant="secondary" onClick={() => document.documentElement.classList.toggle("dark")}>Toggle theme</Button><Button variant="secondary" onClick={() => void post({ action: "new_game" })}>New game</Button></h1>
    {error && <p role="alert">{error}</p>}
    <div className="grid"><section>
      <Card><CardContent><b>{titleStatus}</b><br /><span className="muted">Playing as {state.seat_name} · {state.mode === "versus" ? "vs Friend" : "vs Bot"}</span>
        {state.mode === "versus" && <><br /><span className="muted">This private game is for whoever has the link and passphrase.</span></>}
        {(state.boat_result || state.first_turn_result) && <><br /><span className="muted">{state.boat_result || state.first_turn_result}</span></>}
        <br />Trophies: {trophies.map(([key, value]) => <span key={key} title={`${key === "all" ? "All types" : key} trophy: ${key === "all" ? 5 : 3} Victory Points`}>{key}: {Array.isArray(value) ? value.join(", ") : value || "none"} · </span>)}<br /><span className="muted">Die faces: {state.die_faces.join(", ")}</span>
      </CardContent></Card>
      {state.mode === "bot" && state.first_turn && <Card><CardContent><b>Who goes first?</b><br /><Button onClick={() => void post({ action: "first_turn", choice: "me" })}>I go first</Button><Button onClick={() => void post({ action: "first_turn", choice: "bot" })}>Bot goes first</Button></CardContent></Card>}
      {state.boat && <Card><CardContent><b>{state.boat.stage === "time" ? "Roughly what time of day did you last travel by boat?" : "When did you last travel by boat?"}</b>
        {state.boat.waiting ? <p>Answer submitted: {state.boat.mine}. Waiting for {state.opponent_name}…</p> : <><Input value={boatText || state.boat.mine || ""} onChange={event => setBoatText(event.target.value)} /><Button onClick={() => void post({ action: state.boat?.stage === "time" ? "boat_time" : "boat_answer", text: boatText || state.boat?.mine || "" })}>Submit</Button></>}</CardContent></Card>}
      {state.mode === "versus" && !state.boat && !state.human_turn && state.opponent_name && <Card><CardContent>Waiting for {state.opponent_name}…</CardContent></Card>}
      {state.game_over && <Card><CardHeader><CardTitle>Final scores</CardTitle></CardHeader><CardContent>{state.players.map(item => <div key={item.seat}>{item.name}: <b>{item.score} VP</b></div>)}</CardContent></Card>}
      <h2>Encounters</h2><div className="encounters">{state.encounters.map((encounter, index) =>
        <Card key={encounter.id} className={`encounter ${selectedEncounter === encounter.id ? "selected" : ""}`} onClick={() => !state.game_over && !actionDisabled && setSelectedEncounter(encounter.id)}>
          <b>{index + 1}. {encounter.name}</b> <span className={encounter.sea ? "sea" : "land"}>{encounter.sea ? "SEA" : "LAND"}</span><br />{encounter.type} · {encounter.vp} VP · {encounter.icons} icon(s)<br /><span className="muted">{encounter.mechanics}</span>
        </Card>)}</div>
      {challenge && !state.game_over && <Card><CardContent><b>{challenge.player}&apos;s Challenge</b>: {challenge.cards.map(card => <span key={card.index}> <CardFace card={card} /></span>)}<br />
        <b>{challenge.encounter}</b> by {challenge.method} — target {challenge.target}<br />Dice: {challenge.rolls.map((roll, index) => <span key={index} className={`die ${rerollDice.includes(index) ? "picked" : ""}`} onClick={() => challenge.phase === "reroll" && setRerollDice(dice => dice.includes(index) ? dice.filter(item => item !== index) : [...dice, index])}>{roll}</span>)}<br />
        Skill bonus +{challenge.skill_bonus} · total <b>{challenge.total}</b>{challenge.shortfall ? ` · short by ${challenge.shortfall}` : " · meets target"}<br />
        {challenge.player_is_bot ? <span className="muted">The bot is resolving this Challenge…</span> : challenge.phase === "reroll" ? <><p>Pick up to {challenge.reroll_limit} die/dice to reroll.</p><Button onClick={() => void post({ action: "reroll", indices: rerollDice })}>Reroll selected</Button><Button onClick={() => void post({ action: "reroll", indices: [] })}>Keep this roll</Button></> : challenge.phase === "resolve" ? <><Button onClick={() => void post({ action: "resolve", plus_two: false })}>Resolve roll</Button>{challenge.plus_two && <Button onClick={() => void post({ action: "use_plus_two" })}>Use +2 potion</Button>}</> : challenge.phase === "skill" ? <>{challenge.tracks.map(track => <Button key={track} onClick={() => void post({ action: "skill", track, revision: state.revision })}>{track}</Button>)}</> : null}
      </CardContent></Card>}
      {state.prepare && <Card><CardContent><b>Prepare</b> — {state.prepare.remaining} draw(s) left {state.prepare.drawn.length > 0 && <>; drew {state.prepare.drawn.map(card => <CardFace key={card.index} card={card} />)}</>}
        <br /><Button onClick={() => void post({ action: "prepare_source", source: "deck" })}>Draw from deck</Button>{state.market.map((card, index) => <Button key={index} onClick={() => void post({ action: "prepare_source", source: `market:${index}` })}>Tavern: <CardFace card={card} /></Button>)}{state.prepare.drawn.length === 0 && <Button variant="secondary" onClick={() => void post({ action: "prepare_cancel" })}>Cancel Prepare</Button>}</CardContent></Card>}
      {state.trader && <Card><CardContent><b>Trader treasure</b> — keep one:<br />{state.trader.cards.map((card, index) => <Button key={index} onClick={() => void post({ action: "trader_keep", card: index })}>Keep <CardFace card={card} /></Button>)}</CardContent></Card>}
      {state.treasure && <Card><CardContent><b>Treasure reward</b> — keep one:<br />{state.treasure.treasures.map((treasure, index) => <Button key={index} onClick={() => void post({ action: "treasure_keep", treasure: index })}>Keep <TreasureFace treasure={treasure} /></Button>)}</CardContent></Card>}
      {state.discard && <Card><CardContent>{state.discard.player_is_bot ? <><b>{state.discard.player} is discarding</b> — {state.discard.count} remaining.</> : <><b>Choose discard</b> — {state.discard.count} remaining:<div className="hand">{state.hand.map(card => <label className="hand-label" key={card.index}><input type="checkbox" checked={discardCards.includes(card.index)} onChange={() => toggleDiscard(card.index)} /><CardFace card={card} /></label>)}</div><Button disabled={discardCards.length !== 1} onClick={() => void post({ action: "discard", cards: discardCards })}>Discard selected</Button></>}</CardContent></Card>}
      <h2>Your hand</h2><div className="hand">{state.hand.map(card => <label className="hand-label" htmlFor={`hand-${card.index}`} key={card.index}><input id={`hand-${card.index}`} type="checkbox" checked={selectedCards.includes(card.index)} disabled={actionDisabled} onChange={() => toggleCard(card.index)} /><CardFace card={card} /></label>)}</div>
      <Card><CardContent><span className="muted">Potions: {Array.isArray(player?.potions) ? player.potions.join(", ") || "none" : player?.potions}</span><br /><b>Methods:</b> <span className="muted">Sneak, Steal, and Strike are three different ways to challenge an encounter.</span><br />{(["sneak", "steal", "strike"] as const).map(candidate => <span key={candidate}><Button disabled={!selectedEncounter || !options?.[candidate].enabled || busy || actionDisabled} title={`${methodDescriptions[candidate]}${options?.[candidate].reason ? ` ${options[candidate].reason}` : ""}`} variant={method === candidate ? "secondary" : "default"} onClick={() => setMethod(candidate)}>{candidate}</Button> <span className="sr-only">{methodDescriptions[candidate]}</span></span>)}<br />
        <Button disabled={!selectedEncounter || !method || busy || actionDisabled} onClick={() => void post({ action: "attempt", encounter: selectedEncounter, method, cards: selectedCards })}>Challenge</Button><Button variant="secondary" disabled={busy || actionDisabled} onClick={() => void post({ action: "prepare_start" })}>Prepare instead</Button></CardContent></Card>
      <Card><CardHeader><CardTitle>Skill ladders</CardTitle></CardHeader><CardContent>{Object.entries(state.ladders).map(([track, ladder]) => <div key={track}><b>{track}</b> <span className="muted">level {ladder.level}/{ladder.steps.length}</span><br />{ladder.steps.map((step, index) => <span className={`step ${step.reached ? "reached" : ""}`} key={index}>{index + 1}. +{step.bonus}{step.reward ? ` → ${step.reward}` : ""}</span>)}</div>)}</CardContent></Card>
      <Card><CardHeader><CardTitle>Events</CardTitle></CardHeader><CardContent><pre className="events">{state.events.join("\n")}</pre></CardContent></Card>
    </section><aside><h2>Public state</h2>{state.players.map(item => <Card key={item.seat}><CardContent><b>{item.name} ({item.character})</b><br /><span className="muted">{item.ability}</span><br />Score: {item.score} VP<br />Hand: {item.hand_count} · Hand limit: {item.hand_limit} · Coins: {item.coins} · Potions: {Array.isArray(item.potions) ? item.potions.join(", ") || "none" : item.potions}<br />Skills: {JSON.stringify(item.skills)}<br />Completed: {completed(item)}<br />Treasures: {item.treasures.length ? item.treasures.map(treasure => <span key={treasure.label}> <TreasureFace treasure={treasure} /></span>) : "none"}</CardContent></Card>)}<Card><CardContent><b>Tavern</b>: {state.market.map(card => <span key={card.index}> <CardFace card={card} /></span>)}</CardContent></Card><Card><CardContent><b>Discard pile top</b>: {state.discard_top ? <CardFace card={state.discard_top} /> : "none"}</CardContent></Card><Card><CardContent><b>Token supply</b><br />Potions left: {state.tokens.potions} · Coins left: {state.tokens.coins.map(([value, count]) => `${count}×${value}`).join(", ")}</CardContent></Card></aside></div>
  </main>;
}
