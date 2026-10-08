"""反論の取り入れ(accepts)と SVI 合意スコア(mini, k=0.5)の関係を 1 枚にする.

入力: logs/fin_test2/turns*/eval_result/rebuttal_defeat/（accepts は 1 ログ内の反論の平均）、
      logs/fin/turns*/eval_result/svi_mini/（C_k）。出力: logs/fin/analysis/accepts_vs_svi.png
Usage: .venv/bin/python logs/fin/analysis/make_figure.py
"""

# ruff: noqa: T201, E402

from __future__ import annotations

import json
import math
import statistics as st
import sys
from typing import Any

sys.path.insert(0, ".")

import matplotlib.pyplot as plt

from experiments.eval.plots.plot_svi_evaluators import INSTRUMENTAL_ITEMS, _item_scores

plt.rcParams["font.family"] = ["Hiragino Sans", "sans-serif"]
M = ("schema", "no_schema", "free_debate", "mad")
NAME = {"schema": "Schema", "no_schema": "No Schema", "free_debate": "Free Debate", "mad": "MAD"}
COL = {"schema": "#1f77b4", "no_schema": "#ff7f0e", "free_debate": "#7f7f7f", "mad": "#9467bd"}


def ci(values: list[float]) -> float:
    """Return the half width of the 95% confidence interval."""
    return 1.96 * st.stdev(values) / math.sqrt(len(values))


def load_rows() -> list[dict[str, Any]]:
    """Join accepts (rebuttal_defeat) and C_k (svi_mini) per log."""
    rows: dict[tuple[int, str], dict[str, Any]] = {}
    for t in (10, 15, 20, 25, 30):
        with open(f"logs/fin_test2/turns{t}/eval_result/rebuttal_defeat/rebuttal_defeat_comparison.json") as f:
            detail = json.load(f)["detail"]
        for r in detail:
            a = [j["scores"]["accepts"] for j in r["rebuttals"] if j["scores"] and None not in j["scores"].values()]
            if a:
                rows[(t, r["file"])] = {"m": r["method"], "acc": st.mean(a)}
        with open(f"logs/fin/turns{t}/eval_result/svi_mini/questionnaire_result/svi_comparison.json") as f:
            svi = json.load(f)["detail"]
        for r in svi:
            x, y = _item_scores(r["agent1"]), _item_scores(r["agent2"])
            if all(i in x and i in y for i in INSTRUMENTAL_ITEMS) and (t, r["file"]) in rows:
                rows[(t, r["file"])]["ck"] = st.mean((x[i] + y[i]) / 2 for i in INSTRUMENTAL_ITEMS) - 0.5 * st.mean(
                    abs(x[i] - y[i]) for i in INSTRUMENTAL_ITEMS
                )
    return [r for r in rows.values() if "ck" in r]


def main() -> None:
    """Draw the figure and save it."""
    data = load_rows()
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6), gridspec_kw={"width_ratios": [1, 1, 1.4]})
    for a, key, title in (
        (ax[0], "acc", "反論を取り入れた度合い accepts"),
        (ax[1], "ck", "SVI 合意スコア C_k（mini, k=0.5）"),
    ):
        for i, m in enumerate(M):
            v = [r[key] for r in data if r["m"] == m]
            a.bar(i, st.mean(v), color=COL[m], yerr=ci(v), capsize=4)
            a.text(i, st.mean(v) + ci(v) + 0.01 * (1 if key == "acc" else 5), f"{st.mean(v):.2f}", ha="center", fontsize=9)
        a.set_xticks(range(4))
        a.set_xticklabels([NAME[m] for m in M], fontsize=9)
        a.set_title(title, fontsize=11)
        a.spines[["top", "right"]].set_visible(False)
    ax[0].set_ylim(0, 1)
    ax[1].set_ylim(0, 4.5)
    for m in M:
        ax[2].scatter(
            [r["acc"] for r in data if r["m"] == m],
            [r["ck"] for r in data if r["m"] == m],
            s=14,
            alpha=0.55,
            color=COL[m],
            label=NAME[m],
        )
    ax[2].set_xlabel("accepts（1 ログ内の反論の平均）")
    ax[2].set_ylabel("C_k")
    ax[2].set_title("ログごとの関係（偏相関 +0.22、手法の違いを除く、n=300）", fontsize=11)
    ax[2].legend(frameon=False, fontsize=9)
    ax[2].spines[["top", "right"]].set_visible(False)
    fig.text(
        0.01,
        0.01,
        "各手法 75 本、95% 信頼区間。accepts: 最終回答が反論を取り入れて結論を変えた/限定した度合い（Jev）。",
        fontsize=8,
        color="#555",
    )
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig("logs/fin/analysis/accepts_vs_svi.png", dpi=180)
    print(len(data))


if __name__ == "__main__":
    main()
