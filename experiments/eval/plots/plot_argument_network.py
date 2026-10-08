"""議論ログ（topic × method × run）を 1 枚の HTML で切り替えながら見られるネットワークビューアにする.

- タブ: topic → method、ボタン: run（複数回実行）
- schema / no_schema: target_id（どの論証を攻撃したか）で親子をつないだ木構造
  （根 = main、子 = それを攻撃/反論した論証。実線 rebut / 破線 undercut、枠色は status）
- free_debate / mad / mad_synthesis: 明示的な辺が無いため、発話順の応答関係（直前の相手発話への返答）を
  グレーの点線で描く。※順序からの推定であり、ログ上の関係ではない。

Usage:
    python -m experiments.eval.plots.plot_argument_network [LOG_ROOT] [-o OUT.html]

LOG_ROOT が実験フォルダ（logs/experiment_<日時>、turns<N>/raw_dialogue を持つ）なら、
設定ターン数のタブを足して 1 枚にまとめ、実験フォルダ直下に argument_network.html を出す。
LOG_ROOT が単一の raw_dialogue なら、従来どおりその 1 設定だけを出す。
"""

# ruff: noqa: T201
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("logs/experiment_20260916_020350/raw_dialogue")
DEFAULT_OUT = Path("logs/experiment_20260916_020350/eval_result/dialogue_tree/argument_network.html")
METHODS = ["schema", "no_schema", "free_debate", "mad", "mad_synthesis"]
EDGE_METHODS = {"schema", "no_schema"}
TREE_DX, TREE_DY = 170, 140
AGENT_COLORS = {"AG1": "#1f77b4", "AG2": "#d62728"}
STATUS_BORDER = {
    "justified": "#2ca02c",
    "defensible": "#e6b800",
    "overruled": "#888888",
}
FILE_RE = re.compile(
    r"^(?:(\d+)_)?(schema|no_schema|free_debate|mad_synthesis|mad)_\d{8}_\d{6}_\d+\.json$"
)

ATTEMPT_LABELS = {
    "no_attack": "攻撃なし",
    "no_counter": "反論なし",
}

METRIC_KEYS = [
    "total_dialogue_turns",
    "attack_turn_count",
    "main_argument_count",
    "justified_proven_count",
    "justified_by_budget_count",
    "overruled_count",
    "defensible_count",
    "total_cost_usd",
]

HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Argument Network Viewer</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js"></script>
<style>
:root{--bd:#d0d0d0;--bg:#fff;--fg:#222;--acc:#2563eb;--mut:#f3f4f6}
@media (prefers-color-scheme:dark){:root{--bd:#444;--bg:#16181d;--fg:#e6e6e6;--acc:#60a5fa;--mut:#23262d}}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;flex-direction:column;font:14px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}
.tabs{display:flex;flex-wrap:wrap;gap:4px;padding:6px 10px;border-bottom:1px solid var(--bd);align-items:center}
.tabs b{font-size:12px;color:#888;margin-right:4px;min-width:52px}
button{font:inherit;color:inherit;background:var(--mut);border:1px solid var(--bd);border-radius:6px;padding:3px 10px;cursor:pointer}
button.on{background:var(--acc);border-color:var(--acc);color:#fff}
main{flex:1;display:flex;min-height:0}
#cy{flex:1;min-width:0}
#side{width:400px;border-left:1px solid var(--bd);padding:12px;overflow:auto;font-size:13px}
#side h3{margin:0 0 6px;font-size:15px}
pre{white-space:pre-wrap;word-break:break-word;background:var(--mut);padding:8px;border-radius:6px;margin:6px 0}
.lg span{margin-right:12px;white-space:nowrap}
details{margin:6px 0}
</style></head><body>
<div class="tabs" id="turns"><b>Turns</b></div>
<div class="tabs" id="topics"><b>Topic</b></div>
<div class="tabs" id="methods"><b>Method</b></div>
<div class="tabs" id="runs"><b>Run</b></div>
<main><div id="cy"></div><div id="side">
<h3 id="q"></h3>
<div class="lg"><span style="color:#1f77b4">■ AG1</span><span style="color:#d62728">■ AG2</span>
<span>□ main　○ その他</span></div>
<div id="legend2" class="lg"></div>
<div id="meta"></div>
<h4>選択中のノード</h4><pre id="detail">ノードをクリック</pre>
</div></main>
<script>
const DATA = __DATA__;
const METHODS = __METHODS__;
const st = {turns:null, topic:null, method:null, run:0};
const D = ()=>DATA[st.turns];
const cy = cytoscape({container:document.getElementById('cy'), wheelSensitivity:0.3,
 style:[
  {selector:'node',style:{label:'data(label)','text-wrap':'wrap','text-max-width':150,'font-size':10,
    'color':getComputedStyle(document.body).color,'background-color':'data(color)',shape:'data(shape)',
    width:34,height:34,'text-valign':'bottom','text-margin-y':4,'border-width':'data(bw)','border-color':'data(bc)'}},
  {selector:'edge',style:{'curve-style':'bezier','target-arrow-shape':'triangle',width:2,'line-color':'#666',
    'target-arrow-color':'#666','line-style':'data(ls)',label:'data(label)','font-size':9,'text-wrap':'wrap',
    'text-max-width':140,'text-rotation':'autorotate','color':getComputedStyle(document.body).color,
    'text-background-color':getComputedStyle(document.body).backgroundColor,'text-background-opacity':0.85,
    'text-background-padding':2}},
  {selector:'edge[inferred]',style:{'line-color':'#aaa','target-arrow-color':'#aaa',width:1.5}},
  {selector:'node.note',style:{shape:'round-rectangle','background-color':'#fff7d6','background-opacity':1,width:'label',
    height:'label',padding:6,'border-width':1,'border-color':'#e6b800','color':'#333','font-size':11,
    'text-valign':'center','text-margin-y':0,'text-wrap':'wrap','text-max-width':320}},
  {selector:':selected',style:{'overlay-color':'#2563eb','overlay-opacity':0.25}},
 ]});
cy.on('tap','node,edge',e=>{document.getElementById('detail').textContent=e.target.data('detail')||'';});

function btn(parent,label,on,fn){const b=document.createElement('button');b.textContent=label;
  if(on)b.className='on';b.onclick=fn;parent.appendChild(b);}
function fit(){ // 切り替え後も、できるだけ同じ topic / method を保つ
  const d=D();
  if(!d[st.topic])st.topic=Object.keys(d)[0];
  if(!d[st.topic][st.method])st.method=METHODS.find(m=>d[st.topic][m]);
  if(st.run>=d[st.topic][st.method].length)st.run=0;
}
function renderTabs(){
  const U=document.getElementById('turns'),T=document.getElementById('topics'),
        M=document.getElementById('methods'),R=document.getElementById('runs');
  for(const el of [U,T,M,R]){while(el.children.length>1)el.removeChild(el.lastChild);}
  const keys=Object.keys(DATA);
  U.style.display=(keys.length===1&&keys[0]==='')?'none':'';
  keys.forEach(k=>btn(U,k,k===st.turns,()=>{st.turns=k;fit();show();}));
  const d=D();
  Object.keys(d).forEach(t=>btn(T,t,t===st.topic,()=>{st.topic=t;st.run=0;
    if(!d[t][st.method])st.method=METHODS.find(m=>d[t][m]);show();}));
  METHODS.filter(m=>d[st.topic][m]).forEach(m=>btn(M,m,m===st.method,()=>{st.method=m;st.run=0;show();}));
  d[st.topic][st.method].forEach((r,i)=>btn(R,'#'+r.run,i===st.run,()=>{st.run=i;show();}));
}
function show(){
  renderTabs();
  const r=D()[st.topic][st.method][st.run];
  document.getElementById('q').textContent=r.question;
  document.getElementById('legend2').textContent=r.lane
    ?'点線: 発話順からの推定（直前の相手発話への応答）'
    :'木構造: 上 = 攻撃された論証、下 = それを攻撃/反論した論証（矢印は攻撃の向き）。実線 rebut / 破線 undercut ／ 枠 緑=justified 黄=defensible 灰=overruled';
  document.getElementById('meta').innerHTML=r.meta;
  document.getElementById('detail').textContent='ノードをクリック';
  cy.elements().remove(); cy.add(r.elements);
  cy.layout({name:'preset',fit:true,padding:40}).run();
}
st.turns=Object.keys(DATA)[0];st.topic=Object.keys(D())[0];st.method=METHODS.find(m=>D()[st.topic][m]);show();
</script></body></html>
"""


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _text(argument: object) -> str:
    """ノードに表示する本文（schema は最終規則の結論、その他は本文）."""
    if isinstance(argument, dict):
        try:
            return str(argument["Argument"]["rules"][-1]["consequent"])
        except (KeyError, IndexError, TypeError):
            return json.dumps(argument, ensure_ascii=False)
    return str(argument)


def _detail(rec: dict[str, Any]) -> str:
    out = {k: v for k, v in rec.items() if k != "argument"}
    arg = rec.get("argument")
    body = (
        json.dumps(arg, ensure_ascii=False, indent=2)
        if isinstance(arg, dict)
        else str(arg)
    )
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n\n" + body


def _edge_label(rec: dict[str, Any]) -> str:
    """辺の上に出す攻撃名（rebut / undercut）."""
    return str(rec.get("attack") or "?")


def _edge_detail(rec: dict[str, Any]) -> str:
    return (
        f"{rec['id']} ({rec['agent']} {rec.get('type')}) → {rec.get('target_id')}\n"
        f"attack: {rec.get('attack')}\n"
        f"target_field: {rec.get('target_field')}\n"
        f"target_statement: {rec.get('target_statement')}"
    )


def _end_reason(main: dict[str, Any]) -> str:
    """木が終わった理由（status / closed_by_budget から決める日本語の文言）."""
    status = main.get("status") or ""
    if status.startswith("justified"):
        return "終了: justified（全ての攻撃を撃退）"
    if status.startswith("overruled"):
        return "終了: overruled（反論できず敗北）"
    if main.get("closed_by_budget"):
        return "終了: ターン上限到達 → defensible"
    return f"終了: {status or '不明'}"


def _node(
    rec: dict[str, Any], node_id: str, label: str, pos: dict[str, float] | None = None
) -> dict[str, Any]:
    status = rec.get("status") or ""
    border = next(
        (c for k, c in STATUS_BORDER.items() if status.startswith(k)), "#ffffff"
    )
    data = {
        "id": node_id,
        "kind": rec.get("type", "turn"),
        "label": label,
        "color": AGENT_COLORS.get(rec["agent"], "#999"),
        "shape": "round-rectangle" if rec.get("type") == "main" else "ellipse",
        "bw": 4 if status else 0,
        "bc": border,
        "detail": _detail(rec),
    }
    node = {"data": data}
    if pos:
        node["position"] = pos
    return node


def build_run(method: str, log: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """dialogue_history を Cytoscape の elements にする。戻り値は (elements, lane レイアウトか)."""
    hist = log.get("dialogue_history", [])
    elements: list[dict[str, Any]] = []
    if method in EDGE_METHODS:
        ids = {r["id"] for r in hist}
        children: dict[str, list[str]] = {}
        roots: list[str] = []
        for rec in hist:
            tid = rec.get("target_id")
            if tid in ids:
                children.setdefault(tid, []).append(rec["id"])
            else:
                roots.append(rec["id"])
        pos: dict[str, dict[str, float]] = {}
        slot = [0]

        def place(nid: str, depth: int) -> float:
            kids = children.get(nid, [])
            if kids:
                xs = [place(k, depth + 1) for k in kids]
                x = (xs[0] + xs[-1]) / 2
            else:
                x = slot[0] * TREE_DX
                slot[0] += 1
            pos[nid] = {"x": x, "y": depth * TREE_DY}
            return x

        for r in roots:
            place(r, 0)
        root_of: dict[str, str] = {}
        by_id = {r["id"]: r for r in hist}
        for rec in hist:
            cur = rec
            while cur.get("target_id") in ids:
                cur = by_id[cur["target_id"]]
            root_of[rec["id"]] = cur["id"]
        last_leaf = {root_of[r["id"]]: r["id"] for r in hist}
        for rec in hist:
            label = f"{rec['agent']} {rec['type']}\n{_text(rec.get('argument'))[:40]}"
            elements.append(_node(rec, rec["id"], label, pos[rec["id"]]))
            if rec.get("target_id") in ids:
                elements.append(
                    {
                        "data": {
                            "id": f"e-{rec['id']}",
                            "source": rec["id"],
                            "target": rec["target_id"],
                            "ls": "dashed"
                            if rec.get("attack") == "undercut"
                            else "solid",
                            "label": _edge_label(rec),
                            "detail": _edge_detail(rec),
                        }
                    }
                )
        # 各木の終了理由メモ（＋反論／攻撃を出せなかった理由）。他の要素と重ならないよう、
        # 全体の下に木ごとに縦へ積み、最後の葉へ点線でつなぐ。
        stop_events: dict[str, dict[str, Any]] = {}
        for ev in log.get("attempt_log") or []:
            if ev.get("kind") in {"no_attack", "no_counter"} and ev.get("target_id") in root_of:
                stop_events[root_of[ev["target_id"]]] = ev
        bottom = max((p["y"] for p in pos.values()), default=0) + TREE_DY * 0.9
        k = 0
        for root_id, leaf_id in last_leaf.items():
            root = by_id[root_id]
            if root.get("type") != "main":
                continue
            label = _end_reason(root)
            detail = label
            ev = stop_events.get(root_id)
            if ev:
                reason = str(ev.get("reason") or "")
                who = f"{ev['agent']} {ATTEMPT_LABELS.get(ev['kind'], ev['kind'])}"
                short = reason if len(reason) <= 200 else reason[:200] + "…"
                label += f"\n{who}: {short}"
                detail += f"\n{who}: {reason}"
            elements.append(
                {
                    "data": {"id": f"end-{root_id}", "label": label, "detail": detail},
                    "position": {"x": pos[leaf_id]["x"], "y": bottom + k * 150},
                    "classes": "note",
                    "grabbable": False,
                }
            )
            elements.append(
                {
                    "data": {
                        "id": f"end-e-{root_id}",
                        "source": f"end-{root_id}",
                        "target": leaf_id,
                        "ls": "dotted",
                        "inferred": 1,
                    }
                }
            )
            k += 1
        reasons = log.get("main_unavailable_reasons") or {}
        right = max((p["x"] for p in pos.values()), default=0) + TREE_DX
        for i, (agent, reason) in enumerate(reasons.items()):
            elements.append(
                {
                    "data": {
                        "id": f"nomain-{agent}",
                        "label": f"{agent}: 新しい main を出せず\n{reason[:120]}",
                    },
                    "position": {"x": right, "y": i * TREE_DY * 0.6},
                    "classes": "note",
                    "selectable": False,
                    "grabbable": False,
                }
            )
        return elements, False
    # free_debate / mad: 2 レーンに並べ、直前の相手発話への応答を推定の辺にする
    last_by_agent: dict[str, str] = {}
    for i, rec in enumerate(hist):
        nid = f"t{i}"
        label = f"{rec['agent']} R{rec.get('round', i // 2 + 1)}\n{_text(rec.get('argument'))[:40]}"
        y = 0 if rec["agent"] == "AG1" else 220
        elements.append(_node(rec, nid, label, {"x": i * 130, "y": y}))
        other = next((v for k, v in last_by_agent.items() if k != rec["agent"]), None)
        if other:
            elements.append(
                {
                    "data": {
                        "id": f"e-{nid}",
                        "source": nid,
                        "target": other,
                        "ls": "dotted",
                        "inferred": 1,
                    }
                }
            )
        last_by_agent[rec["agent"]] = nid
    return elements, True


def build_meta(log: dict[str, Any]) -> str:
    """右パネルに出す指標・stance・最終回答の HTML 断片を作る."""
    m = log.get("metrics", {})
    rows = "".join(
        f"<tr><td>{k}</td><td>{_esc(m[k])}</td></tr>" for k in METRIC_KEYS if k in m
    )
    parts = [f"<table>{rows}</table>"] if rows else []
    for key in ("agent1_stance", "agent2_stance", "final_answer"):
        if log.get(key):
            parts.append(
                f"<details><summary>{key}</summary><pre>{_esc(log[key])}</pre></details>"
            )
    for key in ("justification_status", "consensus_reached"):
        if key in log:
            parts.append(f"<div>{key}: <b>{_esc(log[key])}</b></div>")
    return "".join(parts)


def collect(root: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """LOG_ROOT 配下の全ログを {topic: {method: [run, ...]}} に集める."""
    data: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for path in sorted(root.glob("*/*/*.json")):
        mt = FILE_RE.match(path.name)
        if not mt:
            continue
        run, method = int(mt.group(1) or 1), mt.group(2)
        log = json.loads(path.read_text(encoding="utf-8"))
        if not log.get("dialogue_history"):
            continue
        elements, lane = build_run(method, log)
        data.setdefault(path.parent.name, {}).setdefault(method, []).append(
            {
                "run": run,
                "question": log.get("question", ""),
                "elements": elements,
                "lane": lane,
                "meta": build_meta(log),
            }
        )
    for methods in data.values():
        for runs in methods.values():
            runs.sort(key=lambda r: r["run"])
    return data


def collect_all(root: Path) -> tuple[dict[str, dict[str, dict[str, list[dict[str, Any]]]]], bool]:
    """実験フォルダ（turns<N>/raw_dialogue を持つ）か、単一の raw_dialogue かを判別して集める.

    戻り値は ({ターン数: {topic: {method: [run, ...]}}}, 実験フォルダか)。単一の raw_dialogue
    のときはターン数のキーを "" にして、ビューア側でターン数のタブを隠す。
    """
    turns_dirs = sorted(
        (d for d in root.glob("turns*") if (d / "raw_dialogue").is_dir()),
        key=lambda d: int(re.sub(r"\D", "", d.name) or 0),
    )
    if not turns_dirs:
        return {"": collect(root)}, False
    return {re.sub(r"\D", "", d.name): collect(d / "raw_dialogue") for d in turns_dirs}, True


def main() -> None:
    """CLI エントリポイント."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("root", type=Path, nargs="?", default=DEFAULT_ROOT)
    ap.add_argument("-o", "--out", type=Path, default=None)
    args = ap.parse_args()

    data, is_experiment = collect_all(args.root)
    out = args.out or (args.root / "argument_network.html" if is_experiment else DEFAULT_OUT)
    page = HTML.replace(
        "__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    )
    page = page.replace("__METHODS__", json.dumps(METHODS))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    n = sum(len(r) for per in data.values() for m in per.values() for r in m.values())
    print(f"{out} ({len(data)} turn settings, {n} runs)")


if __name__ == "__main__":
    main()
