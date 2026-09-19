"""Guard the in-app Rulebook and docs against wording for removed mechanics."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_SOURCES = (
    ROOT / "frontend" / "components" / "rulebook.tsx",
    ROOT / "docs" / "rulebook.md",
)

STALE_PHRASES = (
    "clock time",
    "boat date",
    "later boat",
    "reclaimable after inactivity",
    "after the inactive session expires",
)

CURRENT_PHRASES = (
    "Who traveled by boat most recently?",
    "eighth Encounter",
    "Reset game",
)


def test_rulebook_has_no_stale_mechanics() -> None:
    for path in RULEBOOK_SOURCES:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in STALE_PHRASES:
            assert phrase not in text, f"{path.name} still mentions {phrase!r}"


def test_rulebook_describes_current_mechanics() -> None:
    for path in RULEBOOK_SOURCES:
        text = path.read_text(encoding="utf-8")
        for phrase in CURRENT_PHRASES:
            assert phrase in text, f"{path.name} is missing {phrase!r}"
