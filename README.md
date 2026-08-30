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

## Play with a friend
```bash
.venv/bin/python -m dragonisles.web --mode versus --passphrase yourphrase --port 8190
```
Both players open the same address and enter the passphrase.
The vs-Bot instructions above are unchanged.

## Easiest way to play

Double-click `Play DragonIsles.command`. If macOS blocks it as unidentified, right-click it and choose **Open**.
