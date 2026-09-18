from pathlib import Path

from .cli import run_cli
from .encounters import load_encounters
from .engine import Game


def main() -> None:
    data_path = Path(__file__).parent.parent / "data" / "encounters.json"
    run_cli(Game(load_encounters(data_path)))


if __name__ == "__main__":
    main()
