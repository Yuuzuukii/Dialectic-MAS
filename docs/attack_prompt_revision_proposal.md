# attack / counter プロンプト再構成案（shared base + HumanMessage task）

## 0. 背景

[main_argument_prompt_revision_proposal.md](main_argument_prompt_revision_proposal.md) では、argument 生成全体に
共通する方針として、次を採用した。

- `SystemMessage` は identity / stance / grounding / 論証品質 / schema overlay に絞る。
- main / defeat / counter の具体的な手番差分は `HumanMessage` に置く。
- 履歴は `HumanMessage(question/instruction)` と `AIMessage(Argument, name=agent)` のペアとして保存する。
- `AIMessage` にはエージェントの実発話だけを入れ、id / phase / status / attack などのメタデータを混ぜない。
- `ArgumentRecord` は LLM 履歴ではなく、target 解決・status 更新・defeat relation 記録のための簿記用 state として別に持つ。

この文書では、そのうち **defeating argument** と **counterargument** の修正案を書く。
主張生成と同様に、プロトコル説明や履歴形式説明は `SystemMessage` から外し、
反論時に必要な target / attack 条件 / non-repetition / 出力契約を `HumanMessage` に寄せる。

---

## 1. 設計方針

反論生成の切り分けは次の通り。

- Shared `SystemMessage`: main と共通。identity、stance、grounding、論証品質、schema overlay のみ。
- `HumanMessage`: defeat / counter の具体タスク、Issue、target argument、attack conditions、non-repetition、response contract。
- LLM 履歴: 過去に実際に送った `HumanMessage` と、返ってきた `AIMessage(name=agent)` のペア。
- 簿記用 state: `ArgumentRecord` / `DefeatRelation` に、target id、attack method、target statement、validity などを保存する。

重要なのは、**反論の対象情報は過去の `AIMessage` にメタデータとして混ぜない**こと。
反論時に必要な target は、その反論を依頼する今回の `HumanMessage` に明示する。

---

## 2. メッセージ構成

`build_attack_messages(state, attacker, target, purpose)` → `generate_attack`

概念的には次の形にする。

```python
[
    SystemMessage(content=argument_system(...)),
    *state.history,
    HumanMessage(content=attack_instruction(...)),
]
```

### Shared SystemMessage

main argument と同じ shared SystemMessage を使う。
defeat / counter 専用の `<task>`、`<attack_types>`、`<defeat_conditions>`、`<non_repetition>`、`<output>` は置かない。

no_schema:

```xml
<identity>
You are {agent} in this debate.
In the message history, turns whose agent/name is "{agent}" are your own past turns; the other agent is your opponent.
You speak from the following stance:
{stance}
</identity>

<grounding>
- Your values and priorities come from your stance.
- Your argument must be grounded in that stance.
- You may use general knowledge only when it helps identify real-world options or reasons that satisfy your stance.
</grounding>

<argumentation_rules>
- State the premises and assumptions you rely on.
- The conclusion must follow directly from the stated reasoning, with no implicit logical leap.
- The final conclusion must clearly express your opinion on the Issue in a concise and specific way.
- Be concise; do not pad the reasoning with repetition.
</argumentation_rules>
```

schema 版は末尾に `<schema_overlay>` を追加する。

```xml
<schema_overlay>
Represent Argument as a structured object consisting of rules, Conc, and Ass.
- rules is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent and a consequent.
- Antecedents may contain strong premises and weak_negation assumptions.
- Every rule must have at least one explicit strong or weak_negation antecedent; never derive a consequent from an empty antecedent.
- Strong antecedents of r_i (i > 1) must be consequents of earlier rules.
- Every non-final consequent must reappear as a strong antecedent of a later rule.
- Conc contains the conclusions derived by the rules.
- Ass contains the weak_negation assumptions used by the rules.
- Use as few rules as possible; a single rule suffices when your stance directly supports the conclusion.
</schema_overlay>
```

---

## 3. Defeating Argument の HumanMessage

Opponent が Proponent の main argument を攻撃する手番。

```xml
<task>
Round {debate_round}. Construct a defeating argument against the target argument.
</task>

<issue>
{issue}
</issue>

<target>
id: {target_id}
agent: {target_agent}
argument:
{target_argument}
</target>

<attack_conditions>
- You may use rebut or undercut.
- rebut: your argument must directly negate the target's stated conclusion.
- undercut: your argument must directly negate an assumption the target relies on.
- Do not attack a claim or assumption that is not present in the target argument.
- Supporting a different option does not by itself count as negating the target.
</attack_conditions>

<response_contract>
If a valid attack exists, set can_defeat=YES and include Argument and Attack.
Otherwise, set can_defeat=NO and omit Argument and Attack.
</response_contract>
```

schema 条件では、`Attack.target.field` は `Conc` または `Ass` の exact item を指す。
no_schema 条件では、target の結論または仮定を quote / close paraphrase で指定する。
この差分は、Pydantic schema の field description と `attack_conditions` の文言で吸収する。

---

## 4. Counterargument の HumanMessage

Proponent が Opponent の defeating argument に応答する手番。

```xml
<task>
Round {debate_round}. Construct a counterargument that defends your prior main argument against the target attack.
</task>

<issue>
{issue}
</issue>

<your_prior_main_argument>
id: {main_argument_id}
{main_argument}
</your_prior_main_argument>

<target>
id: {target_id}
agent: {target_agent}
attack: {attack_method}
target_statement: {target_statement}
argument:
{target_argument}
</target>

<attack_conditions>
- Your counterargument must defeat the target attack.
- You may use rebut or undercut.
- rebut: your argument must directly negate the target's stated conclusion.
- undercut: your argument must directly negate an assumption the target relies on.
- Do not attack a claim or assumption that is not present in the target argument.
</attack_conditions>

<non_repetition>
Do not merely restate your original main argument.
Do not derive the same conclusion from substantially the same reasoning as any of your previous arguments.
If the only available counterargument would repeat a previous argument, set can_defeat=NO.
</non_repetition>

<response_contract>
If a valid counterargument exists, set can_defeat=YES and include Argument and Attack.
Otherwise, set can_defeat=NO and omit Argument and Attack.
</response_contract>
```

counter の non-repetition は main の revision non-repetition とは別物である。
ここでは「main argument をそのまま言い直すだけの counter」を防ぐため、counter の
`HumanMessage` にだけ入れる。

---

## 5. 履歴保存

反論手番でも、履歴は実際に送った質問文と実発話をそのまま保存する。

```python
history = [
    *state.history,
    HumanMessage(content=attack_instruction(...)),
    AIMessage(content=argument_only, name=attacker),
]
```

`AIMessage.content` には `Argument` だけを入れる。
`attack`, `target_id`, `target_statement`, `valid` などは `AIMessage` に混ぜない。

反論生成後の簿記は別 state に保持する。

```python
argument_records = [
    *state.argument_records,
    ArgumentRecord(
        type="defeat" or "counter",
        argument=argument_only,
        agent=attacker,
        target_id=target.id,
        attack=output.Attack.method,
        target_field=output.Attack.target.field,
        target_statement=output.Attack.target.statement,
        round=state.debate_round,
    ),
]
```

defeat relation の検証結果は `DefeatRelation` に保存する。

---

## 6. 現状からの変更点

### (a) defeat / counter 専用 SystemMessage を廃止する

現状は `DEFEATING_ARGUMENT_SYSTEM` と `COUNTER_ARGUMENT_SYSTEM` が別々にあり、
それぞれに `_PROTOCOL_FLOW`、`_HISTORY_FORMAT`、`_ATTACK_TYPES`、`_ARGUMENT_FORMAT`、
`<defeat_conditions>` / `<non_repetition>` / `<output>` が入っている。

提案では、defeat / counter の SystemMessage は shared argument SystemMessage に統一する。
差分は HumanMessage に寄せる。

### (b) プロトコル説明を削除する

`_PROTOCOL_FLOW` は LLM に毎回説明しない。
反論手番か counter 手番かは LangGraph の node / edge が決め、LLM には今回の局所タスクだけを渡す。

### (c) attack 条件を HumanMessage に移す

`_ATTACK_TYPES` と `<defeat_conditions>` は、今回の target を見ながら判断する局所条件なので、
反論時の HumanMessage に入れる。

### (d) counter の non-repetition を HumanMessage に移す

counter の non-repetition は counter 手番だけの制約であり、SystemMessage に常時置かない。

### (e) 出力契約を HumanMessage に移す

`can_defeat` / `Argument` / `Attack` の契約は反論手番固有なので、HumanMessage に置く。
`with_structured_output` の Pydantic schema は引き続き出力形式を強制する。

---

## 7. 実装時の注意

- `build_attack_messages(...)` は shared `ARGUMENT_SYSTEM` / `ARGUMENT_SYSTEM_NO_SCHEMA` を使う。
- `attack_instruction(purpose, target, state)` は target 本文を含める。
  現状の `target.id` だけでは、履歴形式を自然な Human/AI ペアに変えた後に target 解決が弱くなる。
- `purpose == "counter"` のときだけ `<non_repetition>` を追加する。
- `ArgumentRecord` は LLM 履歴とは分ける。既存の `state.history` を `BaseMessage` に変える場合、
  現在の `history: list[ArgumentRecord]` 利用箇所は `argument_records` へ移す。
- undercut 生成も同じ shared SystemMessage に含めるかは別途判断する。
  undercut は `can_undercut` を使うため、HumanMessage の response contract は別になる。

