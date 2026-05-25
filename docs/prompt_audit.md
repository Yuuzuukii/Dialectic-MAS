# Prompt Audit

この文書は、各ノードで LLM に渡している prompt を確認するためのメモである。

## 共通

LLM 呼び出しは `invoke_agent_structured(system_prompt, human_prompt, schema)` を通る。

```python
[SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
```

`system_prompt` は原則として対象 agent の stance である。

```python
agent_stance(state, "AG1") == state.agent1_stance
agent_stance(state, "AG2") == state.agent2_stance
```

例外として、`generalize` と `integrate` は現在 `state.agent1_stance` を system prompt に使っている。

## Dynamic Blocks

### `main_argument_context_text(state)`

`state.integrated_rules` が空なら空文字を返す。空でない場合、次を main argument prompt に追加する。

```text
SPECIAL RULE FOR THE NEXT MAIN ARGUMENT:
- Your previous main argument was rejected, so do not repeat the same logic.
- You may reach the same conclusion only if you use different logic.
Previous main argument:
{prev_arg}
- Use the new IntegratedRules to construct a compromise alternative argument.
- IntegratedRules are compromise criteria, not strict requirements.
- If no argument satisfies all criteria, choose an alternative that satisfies the criteria better.
IntegratedRules:
- {integrated rule 1}
- {integrated rule 2}
...
```

### `proponent_previous_moves_text(state, agent)`

`agent != state.current_proponent` なら空文字を返す。

`agent == state.current_proponent` の場合だけ、Proponent の過去 argument を渡す。

```text
ProponentPreviousMoves in this dialogue branch:
Non-repetition rule: if you are the Proponent, do not repeat the same conclusion from the same or substantially same rules, premises, or warrant as any item below.
{"id": "...", "type": "...", "attack": ..., "target_id": ..., "rules": [...], "Conc": [...], "Ass": [...]}
...
```

これは Proponent 側にのみ non-repetition rule を適用するためのブロックである。

## `can_generate_main`

場所: `src/agent/graphs/nodes.py::can_generate_main`

Schema: `MainArgumentAvailabilityOutput`

System prompt:

```text
{current_proponent stance}
```

Human prompt:

```text
Issue: {state.question}

Task:
Decide whether a new main argument can be presented for the Issue.

Rules:
- The Argument needs to go straight to the point.
- Its conclusion must directly answer the Issue.
- Include only rules needed to derive that answer.
- You may use rules and facts already present in your stance.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- If can_generate is YES, include Argument.
- If can_generate is NO, omit Argument and give the reason.

{proponent_previous_moves_text(state, current_proponent)}

{main_argument_context_text(state)}
```

Notes:

- `can_generate` と `Argument` は同じ LLM 出力で返す。
- `YES` の場合、その `Argument` がそのまま `current_argument` になる。
- `proponent_previous_moves_text` により、switch 後の AG2 main でも AG2 の過去 argument がある場合は渡される。
- `Conc` と `Ass` は保存時に system 側で再計算される。
  - `Conc = rules[*].consequent`
  - `Ass = rules[*].antecedent.weak_negation`

## `o_defeat_a`

場所: `src/agent/graphs/nodes.py::o_defeat_a`

実際の prompt は `generate_attack(..., purpose="defeat_main")` で作られる。

Schema: `DefeatingArgumentOutput`

System prompt:

```text
{current_opponent stance}
```

Human prompt:

```text
Purpose: defeat_main
Target argument id: {A.id}
Target argument:
{A.argument}

{proponent_previous_moves_text(state, current_opponent)}

Task:
Construct a defeating argument against the target argument, if possible.

Terms:
- rebut: Conc(attacker) contradicts Conc(target).
- undercut: Conc(attacker) contradicts Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- If can_defeat is YES, include Argument and Attack.
- If can_defeat is NO, omit Argument and Attack.
- Attack contains attack and target.
```

Notes:

- 通常 `current_opponent != current_proponent` なので、`proponent_previous_moves_text` は空になる。
- したがって non-repetition rule は Opponent の defeating argument には通常入らない。

## `p_counter_b`

場所: `src/agent/graphs/nodes.py::p_counter_b`

実際の prompt は `generate_attack(..., purpose="defend_main", prompt_template=COUNTER_ARGUMENT)` で作られる。

Schema: `DefeatingArgumentOutput`

System prompt:

```text
{current_proponent stance}
```

Human prompt:

```text
Purpose: defend_main
Target argument id: {B.id}
Target argument:
{B.argument}

{proponent_previous_moves_text(state, current_proponent)}

Task:
Construct a counterargument against the target argument, if possible.

Terms:
- rebut: Conc(attacker) contradicts Conc(target).
- undercut: Conc(attacker) contradicts Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- Proponent non-repetition rule: do not repeat a previous Proponent argument.
- Repetition means deriving the same conclusion from the same or substantially
  same rules, premises, or warrant.
- A counterargument that only restates the original main argument is not allowed.
- If the only possible counterargument repeats a previous Proponent argument,
  set can_defeat to NO.
- If can_defeat is YES, include Argument and Attack.
- If can_defeat is NO, omit Argument and Attack.
- Attack contains attack and target.
```

Notes:

- ここでは `current_proponent` が attacker なので、`proponent_previous_moves_text` が入る。
- Proponent の non-repetition rule はここに適用される。
- system 側では non-repetition の機械的 reject はしていない。

## `generate_undercut`

場所: `src/agent/graphs/nodes.py::generate_undercut`

呼び出し元:

- `validate_b_defeats_a`
- `validate_c_defeats_b`
- `validate_b_defeats_c` の defeat subgraph

Schema: `UndercutOutput`

System prompt:

```text
{attacker stance}
```

Human prompt:

```text
Target argument id: {target.id}
Target argument:
{target.argument}

{proponent_previous_moves_text(state, attacker)}

Task:
Construct an undercutting argument against the target argument, if possible.

Term:
- undercut: Conc(attacker) contradicts Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- If can_undercut is YES, include Argument and Attack.
- If can_undercut is NO, omit Argument and Attack.
- Attack contains attack and target.
```

Notes:

- `target` に Ass がない場合、LLM を呼ばずに `None` を返す。
- `attacker == current_proponent` の場合だけ `proponent_previous_moves_text` が入る。

## `validate_b_defeats_a`

場所: `src/agent/graphs/nodes.py::validate_b_defeats_a`

このノード自体は LLM prompt を直接作らない。

内部で `run_defeat_subgraph` を実行する。`B` が `rebut` の場合、`generate_undercut(state, current_proponent, B)` が呼ばれる可能性がある。

## `validate_c_defeats_b`

場所: `src/agent/graphs/nodes.py::validate_c_defeats_b`

このノード自体は LLM prompt を直接作らない。

内部で `run_defeat_subgraph` を実行する。`C` が `rebut` の場合、`generate_undercut(state, current_opponent, C)` が呼ばれる可能性がある。

## `validate_b_defeats_c`

場所: `src/agent/graphs/nodes.py::validate_b_defeats_c`

このノード自体は LLM prompt を直接作らない。

内部で `run_strict_defeat_subgraph` を実行する。現状では reverse check の `allow_generated_blocker=False` により、reverse side の追加 undercut 生成は行わない。

## `extract_warrants`

場所: `src/agent/graphs/nodes.py::extract_warrants`

LLM は呼ばない。

`ag1_main_argument` と `ag2_main_argument` の最後の rule から warrant を抽出し、`warrant_result` を作る。

## `generalize`

場所: `src/agent/graphs/nodes.py::generalize`

Schema: `GeneralizationOutput`

System prompt:

```text
{state.agent1_stance}
```

Human prompt:

```text
{state.warrant_result}

Task:
Generalize the given warrants.

Rules:
- Output reusable criteria.
- Do not mention issue-specific entities.
```

## `integrate`

場所: `src/agent/graphs/nodes.py::integrate`

Schema: `IntegrationOutput`

System prompt:

```text
{state.agent1_stance}
```

Human prompt:

```text
{state.warrant_result}

{state.generalization_result}
Task:
Integrate the generalized criteria.

Rules:
- Output one reusable rule.
- The rule may be used in a later main argument.
- Do not combine alternative criteria with OR.
- Prefer a balanced criterion that can compare how well later arguments satisfy the criteria.
```

## `add_integrated_rule`

場所: `src/agent/graphs/nodes.py::add_integrated_rule`

LLM は呼ばない。

`state.integrated_rule` を `state.integrated_rules` に追加し、次 round の `can_generate_main` に渡す。
