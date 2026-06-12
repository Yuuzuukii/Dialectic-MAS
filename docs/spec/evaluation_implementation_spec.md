# 評価スクリプト実装仕様書

## 概要

本プロジェクト（Dialect-MAS）の議論ログを対象とした LLM 評価パイプラインを構築する。
実行フローは以下の通り：

```
src/cli.py (議論実行) → logs/<timestamp>.json (ログ保存) → src/eval/run_eval.py (評価実行) → スコア表示
```

---

## 1. 背景と課題

### 既存の `evaluate_with_llm` の問題点

他プロジェクトから持ち込んだ `evaluate_with_llm` は単一エージェント想定の構造になっており、以下のフィールドを前提としている：

| フィールド | 想定内容 |
|---|---|
| `question` | 議論のテーマ |
| `initial_opinion` | 単一エージェントの初期主張 |
| `counterarguments` | 単一の反論 |
| `final_synthesis` | 最終統合結論 |

### 本プロジェクトの構造

本プロジェクトでは AG1 と AG2 の **2エージェント**が議論を行う。

| プロジェクトの概念 | 評価フィールドへのマッピング |
|---|---|
| `question` | → `question` (そのまま) |
| AG1 の main argument | → `ag1_initial_opinion` |
| AG2 の main argument | → `ag2_initial_opinion` |
| `dialogue_history` 中の defeat/counter レコード群 | → `debate_history` (議論全体の履歴) |
| `justified_argument` | → `final_synthesis` |

---

## 2. 変更対象ファイル

### 2-1. `src/cli.py` — ログ JSON 保存の追加

**変更点：** `run()` 関数の末尾で最終状態をまとめた JSON を `logs/` ディレクトリに保存する。

**保存内容 (`log_entry`)：**

```json
{
  "timestamp": "2026-05-26T12:34:56",
  "question": "...",
  "agent1_stance": "...",
  "agent2_stance": "...",
  "dialogue_history": [...],
  "justified_argument": "...",
  "justification_status": "...",
  "defeat_relations": [...],
  "ag1_thread_status": "...",
  "ag2_thread_status": "...",
  "integrated_rules": [...],
  "learned_findings": [...]
}
```

**保存パス：** `logs/YYYYMMDD_HHMMSS.json`（プロジェクトルートの `logs/` ディレクトリ）

**実装方針：**
- `graph.astream()` の最終イテレーションで `finish` ノードの出力を捕捉する
- または `graph.ainvoke()` に切り替えて最終状態を直接取得する
- 既存の `_print_node_output` によるストリーム表示は維持する
- ログ保存は `finish` または `finish_with_error` ノードの出力が得られた時点で実行する

---

### 2-2. `src/eval/evaluation.py` — 評価関数の修正・拡張

#### 2-2-1. `build_eval_input(log: dict) -> dict`（新規追加）

ログ JSON から評価用の構造化データを構築するヘルパー関数。

**処理内容：**

1. `dialogue_history` から type 別にレコードを分類する
   - `type == "main"` かつ `agent == "AG1"` → AG1 の初期主張
   - `type == "main"` かつ `agent == "AG2"` → AG2 の初期主張
   - `type in ["defeat", "counter"]` → 議論交換履歴

2. 各引数の `argument` フィールド（JSON 文字列）から `Conc`（結論）を抽出してテキスト化する

3. 議論交換履歴はエージェント名・type・結論を含むフォーマットで整形する

**返却値の構造：**

```python
{
    "question": str,
    "ag1_initial_opinion": str,   # AG1 の最初の main argument の Conc
    "ag2_initial_opinion": str,   # AG2 の最初の main argument の Conc
    "debate_history": str,        # defeat/counter の一覧（整形済みテキスト）
    "integrated_rules": str,      # 議論から抽出・統合されたルール群
    "justified_argument": str,    # 統合ルールを元に生成された最終 main arg の Conc
    "justification_status": str,
}
```

> **注意：** 本プロジェクトには "Final Synthesis" ステップは存在しない。
> 議論終了後に integrated rules が作成され、それを前提として新たな main argument が生成され、
> その argument が正当化（justify）されたものが最終出力となる。
> したがって評価対象の最終出力は `justified_argument`（新しい main arg）であり、
> `final_synthesis` という概念は使わない。

#### 2-2-2. `evaluate_with_llm(response: dict, evaluator_model) -> dict`（修正）

プロンプトテンプレートを本プロジェクトの多エージェント・ルール統合構造に対応させる。

**プロンプト全体の構成（3ブロック）：**

---

**[Block 1] Framework Context — 評価者への事前知識の提供**

evaluator LLM がこのフレームワーク固有の概念を理解できるよう、プロンプト冒頭にスキーマと攻撃種別の説明を置く。

```
You are evaluating a multi-agent dialectical argumentation system based on ASPIC+.

--- Argument Schema ---
Each argument is a sequence of rules. A rule has:
  - antecedent:
      - strong:         Established premises (must hold for the rule to fire)
      - weak_negation:  Defeasible assumptions (can be attacked by undercut)
  - consequent: The conclusion derived from the antecedent

Each argument exposes:
  - Conc: list of conclusions (consequents of the final rule)
  - Ass:  list of defeasible assumptions (weak_negation items across all rules)

--- Attack Types ---
  - rebut:    The attacker's Conc explicitly negates a Conc of the target argument.
              (direct clash of conclusions)
  - undercut: The attacker's Conc explicitly negates an Ass of the target argument.
              (attacks a defeasible assumption the target relies on)

--- Dialogue Flow ---
  1. Each agent (AG1, AG2) generates a main argument for their position.
  2. The opponent attempts to defeat it (rebut or undercut) → "defeat"
  3. The proponent counters the defeat → "counter"
  4. Defeat validity is checked; if cycles resolve, the thread closes.
  5. Warrants are extracted, generalized, and integrated into reusable rules.
  6. A new main argument is generated using the integrated rules.
  7. The argument that cannot be defeated is declared justified.
```

---

**[Block 2] Debate Content — 実際の議論データ**

```
Question:
{question}

AG1 Initial Opinion (Conc):
{ag1_initial_opinion}

AG2 Initial Opinion (Conc):
{ag2_initial_opinion}

Debate History (type / agent / attack / conclusion):
{debate_history}

Integrated Rules (derived from debate):
{integrated_rules}

Final Justified Argument (generated from integrated rules):
{justified_argument}
  Justification status: {justification_status}
```

`debate_history` の各エントリは以下のテキスト形式で整形する：

```
[{type}] {agent} (attack: {attack}, target_id: {target_id})
  Conc: {conclusions}
  Ass:  {assumptions}
```

---

**[Block 3] Scoring Instruction — 評価指示（既存を継承・修正）**

```
Rate the above dialectical reasoning on a scale from 1 to 10 for each axis:

1. Clarity        – Are arguments clearly expressed?
2. Coherence      – Does the justified argument follow logically from the debate and integrated rules?
3. Originality    – Does the final argument show novel insight beyond simply restating initial positions?
4. Dialecticality – Does the debate meaningfully integrate both perspectives through defeat/counter cycles?

Scoring rubric:
  9–10: Outstanding   7–8: Good   5–6: Adequate   1–4: Weak

IMPORTANT: Rate strictly. Perfect scores are rare.

Respond ONLY with JSON:
{
  "clarity": <int>,
  "coherence": <int>,
  "originality": <int>,
  "dialecticality": <int>,
  "evaluator_model": "..."
}
```

---

**評価軸は変更なし：** Clarity / Coherence / Originality / Dialecticality

**`evaluator_model` の型変更：**  
既存コードは `evaluator_model.model` と `evaluator_model.invoke(prompt)` を呼んでいるが、本プロジェクトの LLM は `langchain_openai.ChatOpenAI` を使用している。評価用には `src/agent/llm.py` の `call_llm` を使う同期ラッパーを作成するか、または `asyncio.run()` で非同期呼び出しを wrap する。

---

### 2-3. `src/eval/run_eval.py` — 評価エントリーポイント（新規作成）

```
python src/eval/run_eval.py [--log <path>] [--model <model_name>]
```

**引数：**

| 引数 | デフォルト | 説明 |
|---|---|---|
| `--log` | `logs/` 内の最新ファイル | 評価対象のログ JSON パス |
| `--model` | `gpt-4o-mini` | 評価に使用するモデル |

**処理フロー：**

1. ログ JSON を読み込む
2. `build_eval_input(log)` で評価入力を構築
3. `evaluate_with_llm(eval_input, evaluator_model)` でスコアを取得
4. スコアを整形して表示する

**出力例：**

```
=== Evaluation Result ===
Question   : How can we achieve both detailed shape and visibility...
Log file   : logs/20260526_123456.json
Evaluator  : gpt-4o-mini

Scores:
  Clarity       : 7 / 10
  Coherence     : 8 / 10
  Originality   : 6 / 10
  Dialecticality: 9 / 10
  ─────────────────────
  Average       : 7.5 / 10
```

---

## 3. ディレクトリ構成（変更後）

```
Dialect-MAS/
├── logs/                         # 新規作成: 議論ログ保存先
│   └── YYYYMMDD_HHMMSS.json
├── src/
│   ├── cli.py                    # 変更: ログ保存ロジックを追加
│   └── eval/
│       ├── evaluation.py         # 変更: build_eval_input 追加、プロンプト修正
│       └── run_eval.py           # 新規作成: 評価エントリーポイント
```

---

## 4. 実装順序

1. **`src/agent/llm.py`** に同期評価用の `call_llm_sync(prompt, model)` を追加する（`asyncio.run()` ラッパー）
2. **`src/cli.py`** にログ保存ロジックを追加する
3. **`src/eval/evaluation.py`** に `build_eval_input` を追加し、`evaluate_with_llm` のプロンプトを修正する
4. **`src/eval/run_eval.py`** を新規作成する
5. 既存の `result/dialogue_result.json` を使って動作確認する

---

## 5. 考慮事項・制約

### `evaluator_model` インターフェース

既存の `evaluate_with_llm` は `evaluator_model.model`（属性）と `evaluator_model.invoke(prompt)`（同期メソッド）を想定している。
`ChatOpenAI` は `.invoke()` に対応しているため、互換性は保てる。ただし本プロジェクトの LLM 呼び出しは基本的に非同期（`async def`）なので、評価用には `ChatOpenAI` インスタンスを直接渡す方式を採用し、既存の `evaluator_model.invoke()` 呼び出しをそのまま利用する。

### `dialogue_history` の `argument` フィールド

`argument` フィールドは JSON 文字列として格納されている。`parse_serialized_payload()` が既に `state.py` に存在するため、これを再利用して `Conc` を抽出する。

### ログが存在しない場合

`--log` 未指定時に `logs/` が空または存在しない場合はエラーメッセージを出して終了する。

### LLM の JSON 出力の堅牢性

既存の `evaluate_with_llm` は `json.loads(raw)` で直接パースしている。モデルが JSON 以外の文字列を返すケースに備えて、`parse_serialized_payload()` を流用した安全なパースに変更する。
