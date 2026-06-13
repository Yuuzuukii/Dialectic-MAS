"""Run the no-schema baseline dialogue for one topic JSON file."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dialogue.common import main_topic
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import main_topic  # type: ignore


if __name__ == "__main__":
    main_topic("no_schema", "Run no-schema dialogue for one topic JSON file.")
