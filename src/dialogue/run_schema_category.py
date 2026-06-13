"""Run the schema-based dialogue for every topic in a category."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from src.dialogue.common import main_category
except ModuleNotFoundError:  # pragma: no cover - direct file execution.
    from common import main_category  # type: ignore


if __name__ == "__main__":
    main_category("schema", "Run schema-based dialogue for every topic in a category.")
