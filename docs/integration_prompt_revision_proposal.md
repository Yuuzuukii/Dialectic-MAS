# 統合フェーズ プロンプト再構成案（generalize / integrate）

## 0. 背景

main / defeat / counter の argument 生成では、`SystemMessage` を shared base に寄せ、
具体タスクを `HumanMessage` に置く方針にした。

一方で、統合フェーズは argument 生成とは役割が違う。
ここでは **AG1 が synthesis 担当として**、対立した warrant から次ラウンドで使う
共有ルールを作る。したがって、統合フェーズだけは専用の `SystemMessage` を持つ方が自然である。

現状の統合系は次の3段階である。

1. `extract_warrants`: AG1 / AG2 の main argument から統合材料となる warrant を取り出す。
2. `generalize`: AG1 / AG2 の warrant を抽象的な criterion にする。
3. `integrate`: generalized criteria を1つの reusable integrated rule にまとめる。

この文書では、この3段階の修正案を書く。

---

## 1. 現状の課題

### (a) AG1 identity / stance の扱いが曖昧

現状の `generate_generalization` / `generate_integration` は、`compose_system(state.agent1_stance, template)` を使っている。

```python
system = compose_system(state.agent1_stance, template)
```

統合フェーズは AG1 が担当する、という前提であれば、AG1 の identity / stance は
SystemMessage に入れる必要がある。

ただし、ここでの AG1 は通常の main argument 生成者ではなく、synthesis 担当である。
AG1 の stance は「どの視点から統合を担当するか」を与えるが、AG2 の warrant を無視したり、
AG1 の主張をそのまま勝たせたりしてはいけない。

### (b) generalize と integrate の入出力契約が弱い

現状は `warrant_result` と `dialogue_history` をそのまま `HumanMessage` に渡している。
ただし、何を材料として、何を抽象化し、何を保持し、何を捨てるべきかがやや曖昧である。

特に重要なのは次の区別である。

- issue-specific detail: 製品名、固有名、今回だけの事実
- warrant value: その主張を合理的にしている価値・判断基準
- reusable criterion: 将来の main argument で再利用できる抽象条件
- integrated rule: 複数 criterion を包摂する1つの共有ルール

### (c) extract_warrants の位置づけを明確にする必要がある

`extract_warrants` は LLM プロンプトではなく、state から統合材料を取り出すコード上の前処理である。
そのため、`generalize` / `integrate` とは違い、SystemMessage は不要である。

ただし、履歴設計を `state.history: list[BaseMessage]` と
`state.argument_records: list[ArgumentRecord]` に分けるなら、`extract_warrants` が参照するべきなのは
LLM 履歴ではなく簿記用の `ArgumentRecord` である。

### (d) schema / no_schema の差分を切り出したい

argument 生成と同様に、base は自然言語でも構造化でも共通する役割説明にし、
schema 固有の出力形式は overlay として切り出した方がよい。

---

## 2. 設計方針

統合フェーズでは、argument 生成用 shared SystemMessage は使わない。
代わりに、次の2つの専用 SystemMessage を持つ。

- `GENERALIZATION_SYSTEM_BASE`
- `INTEGRATION_SYSTEM_BASE`

どちらも AG1 identity / stance を含む。
役割は「AG1 としての synthesis operator」である。

共通方針:

- You are AG1, and you perform the synthesis step.
- AG1 の stance を保持するが、両者の warrant を公平に扱う。
- どちらか一方の結論をそのまま勝たせない。
- issue-specific な具体物を抽象化する。
- 次ラウンドの main argument に使える、再利用可能な判断基準を作る。
- 統合結果は「妥協案の文章」ではなく「新しい main argument を作るための rule」である。

---

## 3. Extract Warrants

`extract_warrants` は、LLM を呼ばずに統合材料を作る工程である。
役割は、直近ラウンドで互いに justified にならなかった AG1 / AG2 の main argument から、
次の `generalize` に渡す warrant を取り出すこと。

### 入力

- `ag1_main_argument`
- `ag2_main_argument`
- `output_mode`
- 必要なら `argument_records`

### schema モード

schema モードでは、`Argument` は `rules / Conc / Ass` を持つ。
現状と同様に、各 main argument の最後の rule を warrant として取り出す。

```python
ag1_last_rule = state.ag1_main_argument.body.get("rules", [])[-1]
ag2_last_rule = state.ag2_main_argument.body.get("rules", [])[-1]
```

出力イメージ:

```json
{
  "Argument1": {
    "agent": "AG1",
    "warrant": {
      "antecedent": {...},
      "consequent": "..."
    }
  },
  "Argument2": {
    "agent": "AG2",
    "warrant": {
      "antecedent": {...},
      "consequent": "..."
    }
  }
}
```

### no_schema モード

no_schema では、`Argument` 本体が自然文であり、明示的な最後の rule が存在しない。
初期案としては、現状と同様に main argument 全体を warrant として渡す。

```json
{
  "Argument1": {
    "agent": "AG1",
    "warrant": "<AG1 free-text main argument>"
  },
  "Argument2": {
    "agent": "AG2",
    "warrant": "<AG2 free-text main argument>"
  }
}
```

ただし、より厳密に比較するなら、no_schema でも別途 warrant extraction 用 LLM を置く案がある。
その場合は `extract_warrants` もプロンプト化されるが、まずは実装差分を小さくするため、
main argument 全体を warrant として扱う。

### 出力

`extract_warrants` は `state.warrant_result` を更新する。
これは `generalize` の `HumanMessage` の `<warrants>` に入る。

```xml
<warrants>
{warrant_result}
</warrants>
```

### 注意

- `state.history` が `BaseMessage` になっても、`extract_warrants` はそこを読まない。
- `state.ag1_main_argument` / `state.ag2_main_argument` または `state.argument_records` を読む。
- `warrant_result` には `AIMessage` 由来の発話メタデータを混ぜず、統合に必要な warrant 情報だけを入れる。

---

## 4. Generalization Prompt

### SystemMessage base

```xml
<role>
You are AG1 in this debate.
You now act as the synthesis operator for the debate.
Your task is to generalize each side's warrant into a reusable criterion for future arguments.
</role>

<stance>
{agent1_stance}
</stance>

<generalization_principles>
- Treat both sides' warrants as inputs to be preserved at the level of value or principle.
- Do not discard AG2's warrant merely because it conflicts with AG1's stance.
- Do not simply restate AG1's own warrant as the synthesis result.
- Abstract away from issue-specific entities, examples, and one-off facts.
- Preserve the condition under which each warrant is rationally compelling.
- Preserve the conclusion type supported by each warrant.
- Do not choose a winner between the two sides during generalization.
- Do not produce a final answer to the original Issue.
</generalization_principles>
```

### schema overlay

schema 版では、generalized criterion を構造化して出す。

```xml
<schema_overlay>
Represent each generalized criterion as a structured object.
- strong: generalized condition(s) under which the criterion applies.
- consequent: the generalized conclusion supported by those conditions.
- principle: a short name or phrase for the underlying value or principle.
</schema_overlay>
```

実際の Pydantic schema は既存の `GeneralizedCriterion` に合わせる。

### HumanMessage

```xml
<task>
Generalize the warrants into reusable criteria.
</task>

<warrants>
{warrant_result}
</warrants>

<dialogue_context>
{dialogue_history_summary}
</dialogue_context>

<response_contract>
Return generalized criteria only.
If using no_schema output, each criterion should be one short natural-language statement.
Do not return an integrated rule yet.
Do not answer the original Issue.
</response_contract>
```

`dialogue_context` は全文履歴ではなく、必要なら compact summary にする。
generalization の直接材料は `warrants` であり、履歴全文は補助情報である。

---

## 5. Integration Prompt

### SystemMessage base

```xml
<role>
You are AG1 in this debate.
You now act as the synthesis operator for the debate.
Your task is to integrate generalized criteria into one reusable rule for the next debate round.
</role>

<stance>
{agent1_stance}
</stance>

<integration_principles>
- The integrated rule must preserve every generalized criterion as an alternative sufficient condition.
- The integrated rule must be more abstract than any individual criterion.
- The integrated rule must not merely list the criteria without unifying them.
- The integrated rule must be usable by either side in the next round.
- Do not discard AG2's generalized criterion merely because it conflicts with AG1's stance.
- Do not simply restate AG1's own criterion as the integrated rule.
- Do not produce a final answer to the original Issue.
</integration_principles>
```

### schema overlay

schema 版では、既存の `IntegrationBody` に合わせて、1つの integrated rule を構造化する。

```xml
<schema_overlay>
Represent the integrated rule as one structured reusable rule.
- The antecedent should cover each generalized criterion as an alternative sufficient condition.
- Use OR to combine alternative sufficient conditions.
- The consequent should state the shared generalized conclusion.
- The result must be one rule, not multiple unrelated rules.
</schema_overlay>
```

### HumanMessage

```xml
<task>
Integrate the generalized criteria into one reusable rule.
</task>

<warrants>
{warrant_result}
</warrants>

<generalized_criteria>
{generalization_result}
</generalized_criteria>

<response_contract>
Return exactly one integrated rule.
If using no_schema output, return it as one concise natural-language rule.
The rule must be applicable to future main arguments.
Do not answer the original Issue.
</response_contract>
```

---

## 6. 履歴の扱い

統合フェーズでは、main / defeat / counter のような agent 発話履歴をそのまま再送する必要は薄い。
直接の入力は `warrant_result` と `generalization_result` である。

必要なら `dialogue_history` は全文ではなく、次のような要約にする。

```xml
<dialogue_context>
- AG1 main was not justified because ...
- AG2 main was not justified because ...
- The shared synthesis target is to produce a reusable rule for the next round.
</dialogue_context>
```

ただし、最初の修正では `dialogue_history` を完全に削ってもよい。
統合フェーズの入力を warrant / generalized criteria に限定すると、プロンプトの焦点が絞られる。

---

## 7. 現状からの変更点

### (a) AG1 identity / stance を明示する

統合フェーズは AG1 が担当するため、SystemMessage には AG1 identity / stance を入れる。
ただし、役割は通常の main argument 生成ではなく synthesis である。
そのため、AG1 の stance を保持しつつ、AG2 の warrant / criterion も統合対象として公平に扱う制約を入れる。

### (b) extract_warrants はコード上の前処理として明示する

`extract_warrants` は LLM プロンプトではなく、`ArgumentRecord` から `warrant_result` を作る工程である。
履歴が `BaseMessage` 化しても、統合材料の抽出は簿記用 state から行う。

### (c) generalize / integrate 専用 SystemMessage を残す

argument 生成の shared SystemMessage は使わない。
統合は論証発話ではなく、warrant から次ラウンド用 rule を作る変換工程だからである。

### (d) 出力契約を HumanMessage に置く

generalize では「criteria のみ、integrated rule は返さない」。
integrate では「exactly one integrated rule、original Issue には答えない」。
この違いは HumanMessage に置く。

### (e) schema / no_schema 差分を overlay にする

base は統合工程の目的と原則だけを持つ。
構造化出力の説明は schema overlay に寄せる。
no_schema の自然文粒度は HumanMessage の response contract で軽く指定する。

---

## 8. 実装時の注意

- `extract_warrants` は `state.history` ではなく、`state.ag1_main_argument` / `state.ag2_main_argument`
  または `state.argument_records` を参照する。
- schema モードでは最後の rule を warrant として抽出する。
- no_schema モードではまず main argument 全体を warrant として渡す。必要なら後で LLM extraction を追加する。
- `generate_generalization` / `generate_integration` では AG1 identity / stance を SystemMessage に含める。
- ただし既存の `compose_system(state.agent1_stance, template)` をそのまま使うだけでは、
  AG1 が通常発話するように見えやすい。専用の synthesis 用 composer を作る方がよい。
  例: `compose_synthesis_system(agent="AG1", stance=state.agent1_stance, template=...)`
- `HumanMessage` は XML 風タグに揃える。
- `dialogue_history` を渡す場合は、全文 JSON ではなく summary にするか、少なくとも補助情報として扱う。
- `extract_warrants` は schema/no_schema で入力形が大きく異なるため、`warrants` の表現を安定化させる必要がある。
- `integrated_rule` は次ラウンドの main argument `HumanMessage` に `integrated_rules` として渡されるため、最終回答文ではなく reusable rule として保存する。
