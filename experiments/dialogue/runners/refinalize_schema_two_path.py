"""Re-finalize existing schema logs with the two-path finalization policy.

This keeps every dialogue turn fixed and changes only unresolved finalization:

A) justified path: keep the original result unchanged.
B) unresolved path: full dialogue -> fresh neutral synthesis -> final answer.

The source logs are never overwritten by default. The relative directory structure is copied
under the output root so downstream evaluators can be rerun against the new final answers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agent.two_path_finalization import refinalize_unresolved_log

DEFAULT_INPUT = ROOT / "logs" / "final_gpt54nano_turns10"
DEFAULT_OUTPUT = ROOT / "logs" / "final_gpt54nano_turns10_two_path"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-finalize schema fallback logs using full-dialogue synthesis."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional model override. By default src.agent.llm resolves MODEL from the environment.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Maximum concurrent fallback re-finalizations.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional number of schema logs to process, useful for a small pilot.",
    )
    return parser.parse_args()


def _schema_logs(input_root: Path) -> list[Path]:
    return sorted(input_root.rglob("*_schema_*.json"))


async def _process_one(
    path: Path,
    *,
    input_root: Path,
    output_root: Path,
    model: str | None,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str]:
    async with semaphore:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = await refinalize_unresolved_log(data, model=model)
        out_path = output_root / path.relative_to(input_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path.name, str(result.get("finalization_path", "unknown"))


async def main() -> None:
    args = parse_args()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    paths = _schema_logs(input_root)
    if args.limit is not None:
        paths = paths[: args.limit]

    if not paths:
        raise SystemExit(f"No schema logs found under {input_root}")

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[
            _process_one(
                path,
                input_root=input_root,
                output_root=output_root,
                model=args.model,
                semaphore=semaphore,
            )
            for path in paths
        ]
    )

    counts: dict[str, int] = {}
    for _, finalization_path in results:
        counts[finalization_path] = counts.get(finalization_path, 0) + 1

    print(f"input:  {input_root}")
    print(f"output: {output_root}")
    print(f"processed schema logs: {len(results)}")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
