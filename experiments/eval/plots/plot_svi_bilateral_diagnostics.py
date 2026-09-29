r"""Diagnose bilateral SVI outcomes against formal consensus/fallback status.

This script is intended for the current final experiment logs. It keeps the raw
SVI output untouched and applies reverse scoring only during analysis:
- Q3 is reversed for Instrumental Outcome.
- Q5 is reversed for Self.

For every debate log, it computes AG1/AG2 scores plus bilateral summaries:
mean, minimum (worst-off participant), and absolute gap. It also joins the raw
log's consensus_reached and justification_status fields so we can distinguish
formal protocol resolution from subjective acceptability.

Usage:
    python -m experiments.eval.plots.plot_svi_bilateral_diagnostics

Outputs are written under:
    logs/final_gpt54nano_turns10/svi_analysis/bilateral/
"""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]

DEFAULT_ROOT = Path("logs/final_gpt54nano_turns10")
METHOD_ORDER = ("free_debate", "mad", "no_schema", "schema")
DISPLAY_NAMES = {
    "free_debate": "Free Debate",
    "mad": "MAD",
    "no_schema": "No Schema",
    "schema": "Schema",
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--svi", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    return parser.parse_args()


def _item_score(items: list[dict[str, Any]], item_no: int) -> float:
    for item in items:
        if int(item["item"]) == item_no:
            return float(item["score"])
    raise KeyError(f"SVI item {item_no} not found")


def _scores(items: list[dict[str, Any]]) -> dict[str, float]:
    q = {i: _item_score(items, i) for i in range(1, 17)}
    q3 = 8.0 - q[3]
    q5 = 8.0 - q[5]
    instrumental = statistics.fmean([q[1], q[2], q3, q[4]])
    self_score = statistics.fmean([q5, q[6], q[7], q[8]])
    process = statistics.fmean([q[9], q[10], q[11], q[12]])
    relationship = statistics.fmean([q[13], q[14], q[15], q[16]])
    global_score = statistics.fmean(
        [q[1], q[2], q3, q[4], q5, q[6], q[7], q[8], q[9], q[10], q[11], q[12], q[13], q[14], q[15], q[16]]
    )
    return {
        "instrumental": instrumental,
        "self": self_score,
        "process": process,
        "relationship": relationship,
        "global": global_score,
    }


def _mean_sd_ci(vals: list[float]) -> tuple[float, float, float]:
    mean = statistics.fmean(vals)
    if len(vals) <= 1:
        return mean, 0.0, 0.0
    sd = statistics.stdev(vals)
    ci = 1.96 * sd / math.sqrt(len(vals))
    return mean, sd, ci


def _find_log(root: Path, rec: dict[str, Any]) -> Path:
    path = root / str(rec["category"]) / str(rec["topic"]) / str(rec["file"])
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def _build_rows(root: Path, svi_path: Path) -> list[dict[str, Any]]:
    data = json.loads(svi_path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for rec in data["detail"]:
        log_path = _find_log(root, rec)
        log = json.loads(log_path.read_text(encoding="utf-8"))
        a1 = _scores(rec["agent1"])
        a2 = _scores(rec["agent2"])
        row: dict[str, Any] = {
            "topic": rec["topic"],
            "category": rec["category"],
            "method": rec["method"],
            "file": rec["file"],
            "consensus_reached": bool(log.get("consensus_reached")) if log.get("consensus_reached") is not None else None,
            "justification_status": log.get("justification_status"),
        }
        for metric in ("instrumental", "self", "process", "relationship", "global"):
            x = a1[metric]
            y = a2[metric]
            row[f"ag1_{metric}"] = x
            row[f"ag2_{metric}"] = y
            row[f"bilateral_mean_{metric}"] = (x + y) / 2.0
            row[f"bilateral_min_{metric}"] = min(x, y)
            row[f"bilateral_gap_{metric}"] = abs(x - y)
        rows.append(row)
    return rows


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["method"])].append(row)

    out: list[dict[str, Any]] = []
    for method in METHOD_ORDER:
        rs = groups.get(method, [])
        if not rs:
            continue
        result: dict[str, Any] = {
            "method": method,
            "n_logs": len(rs),
            "formal_consensus_n": sum(r["consensus_reached"] is True for r in rs),
            "formal_consensus_rate": sum(r["consensus_reached"] is True for r in rs) / len(rs),
            "fallback_n": sum(r["justification_status"] == "fallback_no_consensus" for r in rs),
        }
        for key in (
            "bilateral_mean_instrumental",
            "bilateral_min_instrumental",
            "bilateral_gap_instrumental",
            "bilateral_mean_process",
            "bilateral_min_process",
            "bilateral_gap_process",
        ):
            vals = [float(r[key]) for r in rs]
            mean, sd, ci = _mean_sd_ci(vals)
            result[f"{key}_mean"] = mean
            result[f"{key}_sd"] = sd
            result[f"{key}_ci95"] = ci
        out.append(result)
    return out


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _plot_method_metric(summary: list[dict[str, Any]], out_dir: Path, suffix: str, title: str, ylabel: str) -> None:
    methods = [str(r["method"]) for r in summary]
    vals = [float(r[f"{suffix}_mean"]) for r in summary]
    cis = [float(r[f"{suffix}_ci95"]) for r in summary]
    labels = [DISPLAY_NAMES.get(m, m) for m in methods]

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    xs = list(range(len(labels)))
    ax.bar(xs, vals, yerr=cis, capsize=5)
    ax.set_xticks(xs, labels)
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    if "gap" not in suffix:
        ax.set_ylim(1, 7)
    else:
        ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / f"{suffix}.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _plot_schema_by_status(rows: list[dict[str, Any]], out_dir: Path) -> None:
    schema = [r for r in rows if r["method"] == "schema"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in schema:
        status = "formal_consensus" if row["consensus_reached"] is True else str(row["justification_status"] or "no_consensus")
        groups[status].append(row)
    if len(groups) < 2:
        return

    labels: list[str] = []
    means: list[float] = []
    cis: list[float] = []
    for status, rs in sorted(groups.items()):
        vals = [float(r["bilateral_min_instrumental"]) for r in rs]
        mean, _, ci = _mean_sd_ci(vals)
        labels.append(f"{status}\n(n={len(rs)})")
        means.append(mean)
        cis.append(ci)

    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    xs = list(range(len(labels)))
    ax.bar(xs, means, yerr=cis, capsize=5)
    ax.set_xticks(xs, labels)
    ax.set_ylim(1, 7)
    ax.set_ylabel("Worst-off participant: corrected Instrumental")
    ax.set_title("Schema: subjective acceptability by formal resolution status")
    ax.grid(axis="y", alpha=0.2)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "schema_by_formal_status.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """Run bilateral SVI diagnostics."""
    args = _parse_args()
    root: Path = args.root
    svi_path: Path = args.svi or root / "svi_comparison.json"
    out_dir: Path = args.out_dir or root / "svi_analysis" / "bilateral"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = _build_rows(root, svi_path)
    summary = _summary(rows)
    _write_rows(out_dir / "svi_bilateral_trials.csv", rows)
    _write_summary(out_dir / "svi_bilateral_summary_by_method.csv", summary)

    _plot_method_metric(
        summary,
        out_dir,
        "bilateral_mean_instrumental",
        "Corrected SVI Instrumental: mean of both participants",
        "Score (1–7)",
    )
    _plot_method_metric(
        summary,
        out_dir,
        "bilateral_min_instrumental",
        "Corrected SVI Instrumental: worst-off participant",
        "Score (1–7)",
    )
    _plot_method_metric(
        summary,
        out_dir,
        "bilateral_gap_instrumental",
        "Corrected SVI Instrumental: participant asymmetry",
        "Absolute AG1–AG2 gap",
    )
    _plot_schema_by_status(rows, out_dir)

    print(f"Wrote {len(rows)} trial rows to {out_dir}")
    for row in summary:
        print(
            row["method"],
            f"n={row['n_logs']}",
            f"formal_consensus_rate={row['formal_consensus_rate']:.3f}",
            f"bilateral_min={row['bilateral_min_instrumental_mean']:.3f}",
            f"gap={row['bilateral_gap_instrumental_mean']:.3f}",
        )


if __name__ == "__main__":
    main()
