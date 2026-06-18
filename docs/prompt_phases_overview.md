# プロンプト一覧（SystemMessage / AIMessage / HumanMessage 構成）と no_schema を基準にした再構成案

## 0. 背景

`no_schema` 実装の過程で、schema 版 / no_schema 版のプロンプトはほぼ同じ骨格
（task / protocol_flow / history_format / grounding / argument_format / output）を持ちながら、
各ブロックを丸ごと複製している（`*_SYSTEM` と `*_SYSTEM_NO_SCHEMA` のペア）。

今回の振り返り：

> 提案手法（schema あり）は、「出力形式・その指示がない素の状態（= no_schema）」に
> schema 由来の指示を **上乗せ（overlay）** する形であるべき。

この文書は、各フェーズで実際に LLM に送られるメッセージ列
（`SystemMessage` / 履歴の `AIMessage` / `HumanMessage`）を **そのまま** 書き出し、
schema/no_schema の差分を可視化するための資料。**まだ実装はしていない** —
この文書をもとに、どこを base（no_schema）にしてどこを overlay（schema 追加分）にするかを決める。

すべてのフェーズで、メッセージ列の形は共通：

```python
[
    SystemMessage(content=...),   # 役割 + stance + タスク定義
    *render_history(state.history),  # AIMessage の列（過去ターン、0件以上）
    HumanMessage(content=...),    # この手番固有の指示
]
```

（`generalize` / `integrate` / `final_answer` は履歴 `AIMessage` を持たず、
`[SystemMessage, HumanMessage]` の2件のみ。）

---

## 1. 共有ブロック（参照用）

以下は複数フェーズで再利用される断片。各フェーズの SystemMessage はこれらを
`\n\n` 区切りで連結したもの（+ フェーズ固有のブロック）。

### `_GROUNDING`（schema / no_schema 共通）
```
<grounding>
- Your values and priorities come from your stance. You may use general knowledge to identify real-world options that satisfy them.
</grounding>
```

### `_PROTOCOL_FLOW`（schema / no_schema 共通）
```
<protocol_flow>
You and the other agent (AG1 and AG2) debate one Issue, each from a fixed stance, over one or more rounds.
A round proceeds as a dialectical thread:
- A proponent states a main argument (phase "main").
- The opponent attacks it with a defeating argument (phase "defeat", via rebut or undercut).
- The proponent defends with a counterargument (phase "counter"). A rebut can be blocked by an undercut.
- The thread closes with one outcome, recorded on the main argument's "status":
    - justified  – the main survives every attack → the debate ends with this answer.
    - overruled  – the main is defeated and cannot be defended.
    - defensible – the two sides defeat each other; the conflict stays unresolved.
When neither side's main is justified, the shared warrants are generalized and merged into reusable
"integrated rules" that BOTH sides accept. In the NEXT round the proponent must build a NEW main argument
grounded in those integrated rules, different from every earlier main and not vulnerable to the same attacks.
The debate ends when a main is justified, or when the round limit is reached (then a provisional, no-consensus
answer is produced from the integrated rules).
</protocol_flow>
```

### `_ATTACK_TYPES`（schema / no_schema 共通 — ただし Conc/Ass という schema 語彙のまま）
```
<attack_types>
- rebut: a conclusion of the attacker explicitly negates a conclusion (Conc) of the target.
- undercut: a conclusion of the attacker explicitly negates an assumption (Ass) of the target.
</attack_types>
```

### `_ARGUMENT_FORMAT`（schema 専用）
```
<argument_format>
- An argument is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent (strong premises + weak_negation assumptions) and a consequent it derives.
- Every rule must have at least one explicit strong or weak_negation antecedent; never derive a consequent from an empty antecedent.
- Each consequent must follow directly from its antecedents, with no implicit logical leap.
- Strong antecedents of r_i (i > 1) must be consequents of earlier rules; every non-final consequent must reappear as a strong antecedent of a later rule.
- Use as few rules as possible; a single rule suffices when your stance directly supports the conclusion.
</argument_format>
```

### `_FREE_ARGUMENT_FORMAT`（no_schema 専用）
```
<argument_format>
- Express Argument as a short, coherent passage of natural-language reasoning: state the premises (including any assumptions you rely on) and the conclusion they support.
- Each conclusion must follow directly from the stated premises, with no implicit logical leap.
- Be concise; do not pad the reasoning with repetition.
</argument_format>
```

### `_HISTORY_FORMAT`（schema 専用）
```
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": {"rules","Conc","Ass"}}
- "phase" is one of main / defeat / counter; "status" (on a main, when known) is its thread outcome above.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to avoid repeating defeated moves and to stay consistent with the current round and integrated rules.
</history_format>
```

### `_HISTORY_FORMAT_FREE`（no_schema 専用）
```
<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": "<free-text argument>"}
- "phase" is one of main / defeat / counter; "status" (on a main, when known) is its thread outcome above.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to avoid repeating defeated moves and to stay consistent with the current round and integrated rules.
</history_format>
```

### `<identity>`（main / defeat / counter / undercut のみ。`agent_system()` が付与）
```
<identity>
You are {agent} in this debate. In the message history, turns whose agent/name is "{agent}" are your own past turns; the other agent is your opponent.
</identity>
```
`{agent}` は `"AG1"` または `"AG2"`。

---

## 2. フェーズ別メッセージ構成

各フェーズの実際のメッセージ列を、schema / no_schema それぞれについて示す。
`{stance}` は `state.agent1_stance` または `state.agent2_stance`（手番のエージェントの stance）。

### 2-1. main argument

`build_main_argument_messages(state, agent)` → `generate_main`

#### SystemMessage（schema）
```
<identity>
You are {agent} in this debate. In the message history, turns whose agent/name is "{agent}" are your own past turns; the other agent is your opponent.
</identity>

{stance}

<task>
Construct an argument for your position on the Issue.
</task>

[_PROTOCOL_FLOW]

[_HISTORY_FORMAT]

[_GROUNDING]

[_ARGUMENT_FORMAT]

<conclusion>
- The final conclusion must clearly express your opinion on the Issue, stated in a concise and specific way.
</conclusion>

<output>
- If you can construct such an argument: set can_generate=YES and include Argument.
- Otherwise: set can_generate=NO and omit Argument.
</output>
```

#### SystemMessage（no_schema）
同一だが `[_HISTORY_FORMAT]` → `[_HISTORY_FORMAT_FREE]`、`[_ARGUMENT_FORMAT]` → `[_FREE_ARGUMENT_FORMAT]`。
`<task>` / `<conclusion>` / `<output>` の文面は schema と同一。

#### AIMessage（履歴、0件以上）
`state.history` の各 `ArgumentRecord` を `AIMessage(content=record.message_content(), name=record.agent)` に変換。

schema の場合の `content`（main の例）:
```json
{"id": "arg-xxxxxxxxxx", "round": 1, "phase": "main", "agent": "AG1", "status": "overruled", "Argument": {"rules": [...], "Conc": ["..."], "Ass": ["..."]}}
```

no_schema の場合の `content`:
```json
{"id": "arg-xxxxxxxxxx", "round": 1, "phase": "main", "agent": "AG1", "status": "overruled", "Argument": "<free-text argument>"}
```

defeat/counter の場合は `"attack"`, `"target_id"`, `"target_statement"` も追加される（後述）。

#### HumanMessage
`main_instruction(state)`:
```
Round {debate_round}. Construct your main argument for the Issue.
Issue: {issue}
```
`state.integrated_rules` が非空（改訂ラウンド）の場合、さらに追記:
```

This is a revision round: your earlier main arguments (shown in the history) were defeated.
Ground your NEW main argument in the integrated rules below, make it different from every earlier
main argument, and ensure it is not vulnerable to the same attacks that defeated them:
- {integrated_rule_1}
- {integrated_rule_2}
...
```

---

### 2-2. defeating argument（defeat フェーズ）

`build_attack_messages(state, attacker, target, purpose="defeat")` → `generate_attack`

#### SystemMessage（schema）
```
<identity>
You are {attacker} in this debate. In the message history, turns whose agent/name is "{attacker}" are your own past turns; the other agent is your opponent.
</identity>

{stance}

<task>
Construct a defeating argument against the target argument.
</task>

[_PROTOCOL_FLOW]

[_HISTORY_FORMAT]

[_GROUNDING]

[_ATTACK_TYPES]

[_ARGUMENT_FORMAT]

<defeat_conditions>
- rebut may target only an exact statement in Conc(target); undercut may target only an exact statement in Ass(target), never a strong premise.
- For a rebut, your rules must directly derive the negation of the targeted conclusion. Supporting a different option does not by itself negate the target.
- Do not declare an attack whose targeted statement does not appear in the required field.
- If the negation cannot be directly derived, set can_defeat=NO.
</defeat_conditions>

<output>
- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + exact targeted statement).
- Otherwise: set can_defeat=NO and omit Argument and Attack.
</output>
```

#### SystemMessage（no_schema）
`[_HISTORY_FORMAT]` → `[_HISTORY_FORMAT_FREE]`、`[_ARGUMENT_FORMAT]` → `[_FREE_ARGUMENT_FORMAT]`、`[_ATTACK_TYPES]` は同一（Conc/Ass語彙のまま）。
`<defeat_conditions>` / `<output>` は文面が異なる:
```
<defeat_conditions>
- rebut may target only the target's stated conclusion; undercut may target only an assumption the target's argument relies on, never its core premise.
- For a rebut, your argument must directly derive the negation of the targeted conclusion. Supporting a different option does not by itself negate the target.
- Do not declare an attack on a claim or assumption that is not actually present in the target's argument.
- If the negation cannot be directly derived, set can_defeat=NO.
</defeat_conditions>

<output>
- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + a quote or close paraphrase of the targeted claim/assumption).
- Otherwise: set can_defeat=NO and omit Argument and Attack.
</output>
```

#### AIMessage（履歴）
main と同様。defeat/counter ターン自身が履歴に乗る場合は次の形（schema 例）:
```json
{"id": "arg-yyyyyyyyyy", "round": 1, "phase": "defeat", "agent": "AG2", "attack": "rebut", "target_id": "arg-xxxxxxxxxx", "target_statement": "...", "Argument": {"rules": [...], "Conc": [...], "Ass": [...]}}
```
no_schema では `"Argument"` が文字列になる点のみ異なる。

#### HumanMessage
`attack_instruction("defeat", target.id)`:
```
Construct a defeating argument against your opponent's latest argument (id={target_id}) shown in the history.
```

---

### 2-3. counter argument（counter フェーズ）

`build_attack_messages(state, attacker, target, purpose="counter")` → `generate_attack`

#### SystemMessage（schema）
```
<identity>
You are {attacker} in this debate. ...
</identity>

{stance}

<task>
Construct a counterargument against the target argument that defends your position.
</task>

[_PROTOCOL_FLOW]

[_HISTORY_FORMAT]

[_GROUNDING]

[_ATTACK_TYPES]

[_ARGUMENT_FORMAT]

<non_repetition>
- Do not derive the same conclusion from substantially the same rules or warrant as any of your previous arguments.
- A counterargument that merely restates your original main argument is not allowed.
- If the only available counterargument would repeat a previous argument, set can_defeat=NO.
</non_repetition>

<output>
- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + exact targeted statement).
- Otherwise: set can_defeat=NO and omit Argument and Attack.
</output>
```

#### SystemMessage（no_schema）
`[_HISTORY_FORMAT_FREE]` / `[_FREE_ARGUMENT_FORMAT]` に置換。`<non_repetition>` / `<output>` は文面が異なる:
```
<non_repetition>
- Do not derive the same conclusion from substantially the same reasoning as any of your previous arguments.
- A counterargument that merely restates your original main argument is not allowed.
- If the only available counterargument would repeat a previous argument, set can_defeat=NO.
</non_repetition>

<output>
- If a valid attack exists: set can_defeat=YES, and include Argument and Attack (method + a quote or close paraphrase of the targeted claim/assumption).
- Otherwise: set can_defeat=NO and omit Argument and Attack.
</output>
```

#### AIMessage（履歴）
defeat と同形式（`"phase": "counter"`）。

#### HumanMessage
`attack_instruction("counter", target.id)`:
```
Construct a counterargument that defends your main argument against the latest attack (id={target_id}) shown in the history.
```

---

### 2-4. undercut

`build_undercut_messages(state, attacker, target)` → `generate_undercut`

#### SystemMessage（schema）
```
<identity>
You are {attacker} in this debate. ...
</identity>

{stance}

<task>
Construct an undercutting argument against the target argument.
</task>

[_PROTOCOL_FLOW]

[_HISTORY_FORMAT]

[_GROUNDING]

[_ATTACK_TYPES]

[_ARGUMENT_FORMAT]

<output>
- If a conclusion of your argument can explicitly negate an assumption (Ass) of the target: set can_undercut=YES and include Argument.
- Otherwise: set can_undercut=NO and omit Argument.
</output>
```

#### SystemMessage（no_schema）
`[_HISTORY_FORMAT_FREE]` / `[_FREE_ARGUMENT_FORMAT]` に置換。`<output>`:
```
<output>
- If your argument's conclusion can explicitly negate an assumption the target's argument relies on: set can_undercut=YES and include Argument.
- Otherwise: set can_undercut=NO and omit Argument.
</output>
```

#### AIMessage（履歴）
main/defeat/counter と同形式。

#### HumanMessage
`undercut_instruction(target.id)`:
```
Construct an undercutting argument against the argument (id={target_id}) shown in the history, by negating one of its assumptions (Ass).
```

---

### 2-5. generalization

`generate_generalization(state)` — 履歴 `AIMessage` なし、`[SystemMessage, HumanMessage]` の2件。
system は `compose_system(state.agent1_stance, template)`（**常に `agent1_stance`**、identity ブロックなし）。

#### SystemMessage（schema）
```
{agent1_stance}

<task>
Generalize each warrant into a reusable abstract criterion.
</task>

<rules>
- Abstract away from issue-specific entities.
- For each warrant, identify the underlying value or principle that makes it rationally compelling.
- Express that principle as the criterion's conditions (strong) and conclusion (consequent).
- Record the principle name explicitly.
</rules>
```

#### SystemMessage（no_schema）
```
{agent1_stance}

<task>
Generalize each warrant into a reusable abstract criterion.
</task>

<rules>
- Abstract away from issue-specific entities.
- For each warrant, identify the underlying value or principle that makes it rationally compelling.
- Express each criterion as a short natural-language statement: the general condition(s) under which it applies, and the conclusion it supports.
- Name the underlying principle explicitly within that statement.
</rules>
```

#### HumanMessage
```
## Warrants
{state.warrant_result}

## Dialogue History
{json.dumps(state.dialogue_history, ensure_ascii=False, indent=2)}
```

---

### 2-6. integration

`generate_integration(state)` — `[SystemMessage, HumanMessage]` の2件。system は `compose_system(state.agent1_stance, template)`。

#### SystemMessage（schema）
```
{agent1_stance}

<task>
Integrate the generalized criteria into one reusable rule.
</task>

<rules>
- Identify the shared higher-level principle that unifies the underlying values of all criteria.
- Express that principle as a single abstract rule whose antecedent covers each criterion as an alternative sufficient condition (OR).
- The rule should be more abstract than any individual criterion, not merely a list of them.
- Output one rule applicable to future arguments.
</rules>
```

#### SystemMessage（no_schema）
```
{agent1_stance}

<task>
Integrate the generalized criteria into one reusable rule.
</task>

<rules>
- Identify the shared higher-level principle that unifies the underlying values of all criteria.
- Express that principle as a single natural-language rule of the form 'If <condition from any criterion, combined with OR>, then <integrated conclusion>.'
- The rule should be more abstract than any individual criterion, not merely a list of them.
- Output one rule applicable to future arguments.
</rules>
```

#### HumanMessage
```
{state.warrant_result}

{state.generalization_result}
```

---

### 2-7. final answer（schema / no_schema 共通・分岐なし）

`generate_final_answer(state)` — `chat_text`（構造化出力なし）。`[SystemMessage, HumanMessage]` の2件。
system は `compose_system(stance, template)`（`stance` は justified した側の agent の stance）。

#### SystemMessage（合意あり: `FINAL_ANSWER_SYSTEM`）
```
{stance}

<task>
You participated in a dialectical debate on a question, and your argument was justified. Write the final answer.
</task>

<style>
- Write a concise answer to the question in natural language from your perspective.
- State your position clearly and briefly explain the key reasoning that was upheld through the debate.
</style>
```

#### HumanMessage（`FINAL_ANSWER_USER`）
```
Question: {question}

Dialogue history:
{dialogue_history}

Your justified argument:
{justified_argument}
```

#### SystemMessage（合意なし: `FINAL_ANSWER_NO_CONSENSUS_SYSTEM`、`state.consensus_reached is False` のとき）
```
{stance}

<context>
The dialectical debate reached its round limit WITHOUT either side's argument being justified, so no consensus was reached.
</context>

<task>
Produce a provisional, best-effort answer grounded in the integrated rules that neither side could deny.
</task>

<style>
- Make it explicit that this is a provisional answer and that no agreement was reached in the debate.
- Base your reasoning on the integrated rules and the provisional main argument built on them.
- Be concise: state the provisional position and the shared rules it rests on.
</style>
```

#### HumanMessage（`FINAL_ANSWER_NO_CONSENSUS_USER`）
```
Question: {question}

No consensus was reached within the debate limit. The following integrated rules were agreed as undeniable by both sides:
{integrated_rules}

Dialogue history:
{dialogue_history}

Provisional main argument built on the integrated rules:
{justified_argument}
```

`justified_argument` は no_schema では自由記述テキスト、schema では `ArgumentRecord.body`（rules/Conc/Ass の dict）。

---

## 3. 差分の分類

各フェーズの schema/no_schema 差分は、大きく2種類に分けられる。

### (a) 出力構造そのものの差（本質的）
- `_ARGUMENT_FORMAT` vs `_FREE_ARGUMENT_FORMAT`（main/defeat/counter/undercut）
- `_HISTORY_FORMAT` vs `_HISTORY_FORMAT_FREE`（main/defeat/counter/undercut）
- generalization の `<rules>` 最後の2項目（criterion を condition/consequent として構造化するか、自然文にするか）
- integration の `<rules>` 2番目の項目（antecedent の OR 構造 vs natural-language if-then）

これらは `Argument`（および generalization/integration の出力）が構造化スキーマか自由記述かという、
まさに ablation の対象そのものなので、schema/no_schema で **必ず異なる**。

### (b) 語彙の言い換えだけの差（非本質的）
- defeat/counter の `<defeat_conditions>` / `<non_repetition>` / `<output>`：
  「Conc(target)/Ass(target)/rules」⇄「the target's stated conclusion / an assumption the target's
  argument relies on / argument」
- undercut の `<output>`：「a conclusion of your argument ... Ass of the target」⇄
  「your argument's conclusion ... an assumption the target's argument relies on」

これらはロジックは同一で、Argument が構造化か自由文かに応じて参照表現を変えているだけ。

### (c) 共有ブロックなのに schema 語彙が残っているもの
- `_ATTACK_TYPES` は no_schema 側でも「conclusion (Conc)」「assumption (Ass)」という表記のまま使われている。
  no_schema の `<defeat_conditions>` 等は claim/assumption ベースの言い回しに書き換えたのに、
  `_ATTACK_TYPES` だけ取り残されている。

---

## 4. 再構成方針（案）

### 方針
- **no_schema 版を「base」テンプレート**として正本にする（schema 由来の語彙・構造を含まない）。
- schema 版は `base + schema overlay` の合成にする。overlay は次の2種類：
  1. **語彙オーバーレイ**：(b) の差分のように、claim/assumption ベースの文を rules/Conc/Ass ベースの文に
     "置き換える" もの。
  2. **出力構造オーバーレイ**：(a) の差分のように、Argument（や generalization/integration の出力）が
     `ArgumentBody`（rules/Conc/Ass）でなければならない、という追加の `<output_schema>` ブロックを
     base の末尾に追加するもの。

### 検討すべき選択肢

1. **(a) は型/スキーマ側で表現し、プロンプト文面は base に統一する**
   - `_ARGUMENT_FORMAT` の内容（rules/antecedent/consequent の文法）を、base の `_FREE_ARGUMENT_FORMAT`
     とは別の追加ブロック `<output_schema>` として schema 版にのみ付加する。
   - `_HISTORY_FORMAT` も同様：base は `_HISTORY_FORMAT_FREE` を使い、schema 版は
     「ただし過去ターンの `"Argument"` は `{"rules","Conc","Ass"}` 構造である」という追記ブロックを足す。
   - generalization/integration も同様に、base（自然文の criterion/rule）+ 追記ブロック（構造化要件）。

2. **(b) は base 側を中立的な語彙に統一し、schema 側は overlay で rules/Conc/Ass の用語対応を明示する**
   - 例：base の `<defeat_conditions>` は「the target's stated conclusion / an assumption the target's
     argument relies on」のような中立表現のまま。
   - schema overlay は「Argument は rules の列であり、conclusion は Conc、assumption は Ass に対応する」
     という対応関係だけを追記し、defeat_conditions 自体は書き換えない。
   - `<output>` の「exact targeted statement」vs「a quote or close paraphrase」も同様に、
     base は paraphrase 可（自由記述なので当然）、schema overlay で「Argument が構造化されているため
     `Conc`/`Ass` の **exact** な要素を指定すること」という制約を追記する形にできる。

3. **`_ATTACK_TYPES` を中立語彙に書き換える**
   - 「rebut: a conclusion of the attacker negates a conclusion of the target」のように Conc/Ass を
     外し、(2) の overlay で「conclusion ≒ Conc, assumption ≒ Ass」という対応を明示する。

### 実装イメージ（例：main argument）

```python
MAIN_ARGUMENT_SYSTEM_BASE = _system(   # 現行の *_NO_SCHEMA とほぼ同じ
    "<task>...",
    _PROTOCOL_FLOW,
    _HISTORY_FORMAT_FREE,
    _GROUNDING,
    _FREE_ARGUMENT_FORMAT,
    "<conclusion>...",
    "<output>...",
)

_ARGUMENT_SCHEMA_OVERLAY = """\
<output_schema>
- Argument is not free text: it is a sequence of rules r_1..r_n, each with antecedent
  (strong premises + weak_negation assumptions) and a consequent.
  ... (現行 _ARGUMENT_FORMAT の内容)
- In the history above, "Argument" objects use {"rules","Conc","Ass"} instead of free text;
  Conc = conclusions of the final rule, Ass = weak_negation assumptions across all rules.
</output_schema>"""

MAIN_ARGUMENT_SYSTEM = _system(MAIN_ARGUMENT_SYSTEM_BASE, _ARGUMENT_SCHEMA_OVERLAY)
```

defeat/counter/undercut も同様に、base は現行 `_NO_SCHEMA` 版の `<defeat_conditions>` /
`<non_repetition>` / `<output>` をそのまま使い、schema 版は同じ base に
`_ARGUMENT_SCHEMA_OVERLAY`（+ Conc/Ass 対応の追記）を足すだけにする。

---

## 5. 決めるべきこと

- 上記「方針2」のように、defeat/counter/undercut の `<defeat_conditions>` / `<non_repetition>` /
  `<output>` の **文面そのもの**を no_schema 側（中立語彙）に統一し、schema 側は overlay で
  Conc/Ass との対応関係だけ追記する、で良いか。
  - あるいは、(b) の差分は「overlay が文面ごと置き換える」方式（テンプレート文字列の一部を
    `.format()` 等でパラメータ化）にするか。
- generalization/integration の overlay をどう書くか（"criterion を `{condition, conclusion}` の
  構造で出力せよ" / "rule を antecedent(OR)/consequent の構造で出力せよ" を追記ブロックにする）。
- `_ATTACK_TYPES` を中立語彙に書き換え、Conc/Ass 対応を schema overlay 側に移すか。
- overlay ブロックの粒度：フェーズ単位（`MAIN_ARGUMENT_SCHEMA_OVERLAY` 等）で個別に持つか、
  共通の `_ARGUMENT_SCHEMA_OVERLAY` + `_HISTORY_SCHEMA_OVERLAY` のような少数の共有ブロックに
  まとめるか。
</content>
