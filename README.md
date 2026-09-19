# DragonIsles

A two-player DragonIsles game played in the browser: you against a bot.

## Play

First time only:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Every time:

```bash
.venv/bin/python -m dragonisles.web --port 8190
```

Then open http://127.0.0.1:8190 in a browser. Press Ctrl+C in the Terminal to stop.
This direct command does not check GitHub for updates. To update automatically before
starting, use the launcher described below.

## Play with a friend
```bash
.venv/bin/python -m dragonisles.web --mode versus --passphrase yourphrase --port 8190
```
Both players open the same address and enter the passphrase.
The vs-Bot instructions above are unchanged.

## Easiest way to play

Use Terminal to avoid the macOS block:

```bash
cd ~/dragonisles-bot
./"Play DragonIsles.command"
```
The launcher checks GitHub and fast-forwards a clean checkout on `main` before starting.
If you use the direct Python command instead, update manually first with:

```bash
cd ~/dragonisles-bot
git pull --ff-only origin main
```

Set `DRAGONISLES_NO_UPDATE=1` to skip the update check.
Double-click `Play with a friend.command` to start a private Cloudflare quick tunnel.
Send your friend the displayed link and passphrase.

## Keeping the Rulebook current

Any change to game rules or flow (turn order, the boat question, challenges,
rewards, scoring, seats, game end) must update the in-app Rulebook in
`frontend/components/rulebook.tsx` and `docs/rulebook.md` in the same change.
`tests/test_rulebook.py` fails when either still mentions removed mechanics.

## Troubleshooting

```text
ERROR: file:///Users/~ does not appear to be a Python project:
neither 'setup.py' nor 'pyproject.toml' found.
```

The Terminal is in your home folder instead of the game folder, so the
command looked for the game where it isn't. Move into the folder that holds
`pyproject.toml`, then run the command again:

```bash
cd ~/dragonisles-bot
ls pyproject.toml
```

If `ls` says `No such file or directory`, the game folder is somewhere else or
not downloaded yet. Find it with:

```bash
ls -d ~/*dragonisles* ~/Downloads/*dragonisles* ~/Desktop/*dragonisles* 2>/dev/null
```

Then `cd` into the path it prints. If nothing prints, download the game again:

```bash
git clone https://github.com/Muxeco/dragonisles-bot.git ~/dragonisles-bot
cd ~/dragonisles-bot
```

Using `./"Play DragonIsles.command"` avoids this error entirely, because the
launcher moves into its own folder before starting the game.
