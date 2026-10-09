"""real_final の集計表（SUMMARY.md）を、このフォルダの raw_dialogue と eval_result だけから作る（LLM 不使用）."""

# ruff: noqa: T201

import collections
import glob
import json
import math
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TS = (10, 15, 20, 25, 30)
ORDER = ["schema", "no_schema", "free_debate", "mad", "mad_synthesis"]
NAME = {"schema": "Schema", "no_schema": "No Schema", "free_debate": "Free Debate", "mad": "MAD", "mad_synthesis": "MAD + synthesis"}
FN = re.compile(r"^(?:\d+_)?(?P<m>.+)_\d{8}_\d{6}_\d+$")


def ci(v):
    """95% 信頼区間の半幅（正規近似）を返す."""
    return 1.96 * st.stdev(v) / math.sqrt(len(v)) if len(v) > 1 else 0.0


def load(rel):
    """全ターン設定の評価 JSON を読み、(手法, ターン設定, トピック, 詳細) の行にする."""
    rows = []
    for T in TS:
        for e in json.load(open(ROOT / f"turns{T}/eval_result/{rel}"))["detail"]:
            rows.append((e["method"], T, e["topic"], e))
    return rows


def svi_item(items):
    """SVI の項目番号 → スコア（Q3 と Q5 は 8 から引いて反転）."""
    s = {}
    for r in items:
        i, v = r.get("item"), r.get("score")
        if isinstance(i, int) and isinstance(v, (int, float)):
            s[i] = 8 - v if i in (3, 5) else v
    return s


def table(title, header, lines):
    """Markdown の表を組む."""
    return f"## {title}\n\n| 手法 | " + " | ".join(header) + " |\n|---|" + "---|" * len(header) + "\n" + "\n".join(lines) + "\n"


out = ["# real_final 集計（make_summary.py が自動生成。数値はこのフォルダのデータから計算）\n"]
# SVI
rows = load("svi/svi_comparison.json")
L = []
for m in ORDER:
    A = []
    for mm, T, t, e in rows:
        if mm != m:
            continue
        a, b = svi_item(e["agent1"]), svi_item(e["agent2"])
        if all(i in a and i in b for i in (1, 2, 3, 4)):
            A.append((sum((a[i] + b[i]) / 2 for i in (1, 2, 3, 4)) / 4, sum(abs(a[i] - b[i]) for i in (1, 2, 3, 4)) / 4, sum(min(a[i], b[i]) for i in (1, 2, 3, 4)) / 4))
    L.append(f"| {NAME[m]} | {len(A)} | {st.mean(x[0] for x in A):.3f} ± {ci([x[0] for x in A]):.3f} | {st.mean(x[1] for x in A):.3f} | {st.mean(x[2] for x in A):.3f} |")
out.append(table("SVI Instrumental Outcome（項目1-4、Q3反転。C_0=平均、C_0.5=最小）", ["n", "平均 ± 95%CI(ログ)", "差 |A-B|", "最小"], L))
# generic rate metrics
def rate(rel, key, title):
    """指標 key の手法別平均を、SUMMARY の表として追加する."""
    r = load(rel)
    L = []
    for m in ORDER:
        v = [e[key] for mm, T, t, e in r if mm == m and e.get(key) is not None and e.get("n_judged", e.get("n_turns", 1)) > 0]
        tm = [st.mean([e[key] for mm, T, tt, e in r if mm == m and tt == top and e.get(key) is not None]) for top in sorted({x[2] for x in r})]
        L.append(f"| {NAME[m]} | {len(v)} | {st.mean(v):.3f} ± {ci(v):.3f} | {st.mean(tm):.3f} ± {ci(tm):.3f} |")
    out.append(table(title, ["n", "平均 ± 95%CI(ログ)", "トピック単位 ± 95%CI"], L))
rate("turn_novelty/turn_novelty.json", "repeat_rate", "ターン新規性: 反復率（低いほど反復が少ない）")
rate("argument_update/argument_update.json", "update_rate", "論証の更新率")
rate("reframing/reframing.json", "reframe_rate", "再枠付け率")
rate("atomic_coverage/atomic_coverage_comparison.json", "atomic_ratio", "Atomic Coverage")
rate("counterargument_respect/counterargument_respect.json", "level_mean", "DQI 反論への敬意（レベル平均 0-3。Schemaは言及が少なく形式の偏りあり）")
# used turns
used = collections.defaultdict(lambda: collections.defaultdict(list))
for T in TS:
    for f in glob.glob(str(ROOT / f"turns{T}/raw_dialogue/*/*/*.json")):
        used[FN.match(Path(f).stem).group("m")][T].append(len(json.load(open(f))["dialogue_history"]))
L = [f"| {NAME[m]} | " + " | ".join(f"{st.mean(used[m][T]):.1f} ({sum(x >= T for x in used[m][T])}/{len(used[m][T])})" for T in TS) + " |" for m in ORDER]
out.append(table("使用ターン数の平均（設定ターン数に達した本数/本数）", [str(T) for T in TS], L))
(ROOT / "SUMMARY.md").write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
