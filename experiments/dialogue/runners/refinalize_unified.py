"""既存の議論ログから、最終回答だけを共通の経路で作り直し、新しい実験フォルダに保存する.

議論の過程（dialogue_history・立場文・metrics など）はそのままコピーし、最終回答だけを
two_path_finalization の共通の経路で作り直す。元のログは書き換えない。

- schema / no_schema: 決着した主張があるログ（経路 A）は、最終回答を変えずにコピーする。
  それ以外（経路 B）は、議論全体の統合 → 回答で作り直す。
- free_debate / mad_synthesis: 決着の概念が無いので、すべて経路 B で作り直す。
- ``--copy-methods`` に挙げた手法（例: mad）は、作り直さずにそのままコピーする。

出力は ``<出力先>/turns<N>/raw_dialogue/<カテゴリ>/<トピック>/<元のファイル名>``。出力先を省略すると
``logs/experiment_<日時>/`` になる。

Usage:
    python -m experiments.dialogue.runners.refinalize_unified \
      --source logs/experiment_20261004_035427:schema,no_schema \
      --source logs/experiment_20261002_052448:free_debate \
      --copy-source logs/experiment_20261002_052448:mad \
      [--dry-run] [--limit 3]
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.agent.two_path_finalization import SUPPORTED_METHODS, refinalize_unresolved_log  # noqa: E402

LOGS_DIR = ROOT / "logs"


@dataclass(frozen=True)
class Source:
    """実験フォルダと、そこから取り込む手法."""

    root: Path
    methods: frozenset[str]


def parse_source(value: str) -> Source:
    """``<実験フォルダ>:<手法,手法>`` を解釈する."""
    path, _, methods = value.rpartition(":")
    if not path or not methods:
        raise argparse.ArgumentTypeError(f"形式は <実験フォルダ>:<手法,手法> です: {value!r}")
    return Source(Path(path), frozenset(m.strip() for m in methods.split(",") if m.strip()))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source", action="append", type=parse_source, default=[], help="最終回答を作り直す対象（複数可）。"
    )
    parser.add_argument(
        "--copy-source", action="append", type=parse_source, default=[], help="そのままコピーする対象（複数可）。"
    )
    parser.add_argument("--output-root", type=Path, default=None, help="既定は logs/experiment_<日時>/。")
    parser.add_argument("--model", default=None, help="モデルの上書き（既定は環境変数 MODEL）。")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None, help="試運転用: 処理するログの総数の上限。")
    parser.add_argument("--dry-run", action="store_true", help="LLM を呼ばず、対象の件数だけ表示する。")
    return parser.parse_args()


def collect(source: Source) -> list[tuple[Path, Path]]:
    """``(元のログ, 実験フォルダからの相対パス)`` を返す。手法はファイル名ではなくログの method で判定する."""
    found: list[tuple[Path, Path]] = []
    for path in sorted(source.root.glob("turns*/raw_dialogue/*/*/*.json")):
        method = json.loads(path.read_text(encoding="utf-8")).get("method")
        if method in source.methods:
            found.append((path, path.relative_to(source.root)))
    return found


async def process_one(
    path: Path,
    relative: Path,
    *,
    output_root: Path,
    rebuild: bool,
    model: str | None,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str]:
    """1 つのログをコピー（必要なら最終回答を作り直し）して保存し、(手法, 経路) を返す."""
    async with semaphore:
        log = json.loads(path.read_text(encoding="utf-8"))
        if rebuild:
            log = await refinalize_unresolved_log(log, model=model)
            log["finalization_path"] = log.get("finalization_path") or "fallback_full_dialogue_synthesis"
        else:
            log["finalization_path"] = log.get("finalization_path") or "original_unchanged"
        log["refinalized_from"] = str(path.resolve())
        out = output_root / relative
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return str(log.get("method")), str(log["finalization_path"])


async def main() -> None:
    args = parse_args()
    unsupported = {m for source in args.source for m in source.methods} - SUPPORTED_METHODS
    if unsupported:
        raise SystemExit(f"作り直しに対応していない手法: {sorted(unsupported)}（コピーは --copy-source へ）")
    jobs = [(p, r, True) for source in args.source for p, r in collect(source)]
    jobs += [(p, r, False) for source in args.copy_source for p, r in collect(source)]
    if args.limit is not None:
        jobs = jobs[: args.limit]
    if not jobs:
        raise SystemExit("対象のログが見つかりません。")

    output_root = args.output_root or LOGS_DIR / f"experiment_{datetime.now():%Y%m%d_%H%M%S}"
    rebuilt = sum(1 for _, _, rebuild in jobs if rebuild)
    print(f"output: {output_root}")
    print(f"logs: {len(jobs)}（最終回答を作り直す {rebuilt} / そのままコピー {len(jobs) - rebuilt}）", flush=True)
    if args.dry_run:
        return

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    results = await asyncio.gather(
        *[
            process_one(
                path, relative, output_root=output_root, rebuild=rebuild, model=args.model, semaphore=semaphore
            )
            for path, relative, rebuild in jobs
        ]
    )
    counts: dict[tuple[str, str], int] = {}
    for key in results:
        counts[key] = counts.get(key, 0) + 1
    for (method, finalization_path), value in sorted(counts.items()):
        print(f"  {method} / {finalization_path}: {value}")
    print(f"saved -> {output_root}")


if __name__ == "__main__":
    asyncio.run(main())
