"""eval_sweep.py の結果(eval_results.json)をCSV化し、棒グラフを出力する.

ルーブリック軸ごとに schema / no_schema / free_debate / mad を横並びにする.

Usage:
    python src/eval/plot_sweep.py --eval-results logs/sweep/artificial_intelligence/eval_results.json
"""

# print による進捗出力と、sys.path 追加後の import はこのスクリプトでは意図的。
# ruff: noqa: T201, E402, I001

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt
import pandas as pd

METRICS = [
    "coherence",
    "originality",
    "dialecticality",
    "validity",
    "elapsed_seconds",
    "total_tokens",
]


def load_dataframe(eval_results_path: Path) -> pd.DataFrame:
    """eval_results.json を読み込み、turns/attempts でソートした DataFrame を返す."""
    data = json.loads(eval_results_path.read_text(encoding="utf-8"))
    df = pd.DataFrame(data["per_run"])
    df = df.sort_values(["turns", "attempts"])
    df["combo"] = df.apply(lambda r: f"turns{int(r['turns']):02d}_attempts{int(r['attempts']):02d}", axis=1)
    return df


def plot_metric(df: pd.DataFrame, metric: str, out_dir: Path) -> Path:
    """指定したメトリクスについて method 別の棒グラフを生成し、画像として保存する."""
    pivot = df.pivot_table(index="combo", columns="method", values=metric, aggfunc="first")
    combo_order = (
        df[["combo", "turns", "attempts"]]
        .drop_duplicates()
        .sort_values(["turns", "attempts"])["combo"]
        .tolist()
    )
    pivot = pivot.reindex(combo_order)
    for col in ("schema", "no_schema", "free_debate", "mad"):
        if col not in pivot.columns:
            pivot[col] = None
    pivot = pivot[["schema", "no_schema", "free_debate", "mad"]]

    fig, ax = plt.subplots(figsize=(16, 6))
    pivot.plot.bar(ax=ax, width=0.8)
    ax.set_title(metric)
    ax.set_xlabel("turns_attempts")
    ax.set_ylabel(metric)
    ax.legend(title="method")
    plt.xticks(rotation=90)
    plt.tight_layout()

    out_path = out_dir / f"{metric}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def main() -> None:
    """CLI エントリポイント: eval_results.json から CSV と棒グラフ群を出力する."""
    parser = argparse.ArgumentParser(description="Plot sweep eval results as bar charts.")
    parser.add_argument("--eval-results", required=True, help="Path to eval_results.json")
    parser.add_argument("--out-dir", default=None, help="Output directory for csv/png (default: alongside eval_results.json)")
    args = parser.parse_args()

    eval_results_path = Path(args.eval_results)
    if not eval_results_path.is_absolute():
        eval_results_path = ROOT / eval_results_path
    if not eval_results_path.exists():
        print(f"eval_results.json not found: {eval_results_path}", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(args.out_dir) if args.out_dir else eval_results_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    df = load_dataframe(eval_results_path)

    csv_path = out_dir / "eval_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"CSV saved to {csv_path}")

    for metric in METRICS:
        png_path = plot_metric(df, metric, out_dir)
        print(f"Plot saved to {png_path}")


if __name__ == "__main__":
    main()
