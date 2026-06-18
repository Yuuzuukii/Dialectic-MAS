# argument プロンプト再構成案（shared base + removable schema overlay）

## 0. 背景

[prompt_phases_overview.md](prompt_phases_overview.md) では、現状の各フェーズで LLM に送られる
`SystemMessage` / 履歴 `AIMessage` / `HumanMessage` をそのまま整理した。

この文書は、そのうち **argument 生成（main / defeat / counter）** について、次の設計方針に従って
再構成したプロンプト案を書き出すための資料である。**まだ実装はしていない**。

> no_schema を「出力スキーマを乗せる前の base」とし、提案手法である schema 版は
> base に schema 固有の指示ブロックを追加する。

今回のポイントは、schema 固有の指示を **タグブロック単位で丸ごと取り除ける**ようにすること。
つまり、schema 版の SystemMessage から `<schema_overlay>` を削除すれば no_schema 版になる。

加えて、履歴の持たせ方も見直す。現状は1ターンを1つの `AIMessage` にまとめ、その `content` に
`id`/`round`/`phase`/`status`/`attack` などのメタデータと実際の論証（`Argument`）を同じ JSON に
混在させている。これだと LLM からは「メタデータも含めてそのエージェントが発話した内容」に見えてしまう。

そこで、LLM に再送する履歴は LangChain のメッセージモデルに合わせて、各ターンを
**HumanMessage（その時に投げた質問・指示）** と
**AIMessage（name 付きのエージェント発話）** のペアとして `state.history` に保持・再送する。
一方、defeat 判定や `target_id` 解決に必要な構造化レコードは、`ArgumentRecord` として別フィールド
（例: `state.argument_records`）に保持する：

```python
[
    SystemMessage(content=...),       # identity + stance + argument rules
    *state.history,                   # [HumanMessage(question/instruction), AIMessage(Argument, name=agent)] のペア列
    HumanMessage(content=...),        # この手番固有の Issue / round / revision constraints
]
```

---

## 1. 設計方針

この文書では、プロンプトを部品名ではなく **LLM に送る全文**として書く。
実装時には重複を避けるために定数化してよいが、設計レビューでは実際のメッセージ内容が
そのまま読めることを優先する。

argument 生成の切り分けは次の通り。

- SystemMessage base: identity、stance、grounding、論証品質。
- schema overlay: `Argument` を `rules / Conc / Ass` の構造化形式として表すための追加制約。
- no_schema: SystemMessage base のみ。`<schema_overlay>` を含めない。
- schema: SystemMessage base + `<schema_overlay>`。
- LLM 履歴: 1ターン = `[HumanMessage(question/instruction), AIMessage(Argument, name=agent)]` のペア。
  `HumanMessage` には、そのターンで実際にエージェントへ投げた質問・指示を入れる。
  `AIMessage` には Argument 以外の情報を含めない（= そのエージェントの発話そのもの）。
  `id`/`round`/`phase`/`target_id`/`target_statement` など、その手番の質問に必要な情報は
  `HumanMessage` 側に含める。後から確定する `status` は過去メッセージへ追記せず、
  2周目以降の main argument 生成時に `revision_context` として新しい `HumanMessage` に含める。
- 内部レコード: 攻撃検証・status 更新・最終ログ生成に必要な構造化情報は、
  `ArgumentRecord` のリストとして LLM 履歴とは別に保持する。
- HumanMessage（今回の手番）: main / defeat / counter の具体タスク、round、Issue、target、
  revision round の integrated rules、non-repetition constraints、出力契約。

base には `rules / Conc / Ass` などの schema 固有語彙を入れない。
base は「論証として何を満たすべきか」を指示し、schema overlay は「その論証をどの構造で出すか」を指示する。

---

## 2. argument メッセージ構成（提案）

`build_*_messages(state, agent, ...)` → `generate_main` / `generate_attack`

### Shared SystemMessage base（no_schema）

main / defeat / counter の no_schema は、この SystemMessage を共通で使う。
具体的に「主張する」「反論する」「どの target を攻撃する」は HumanMessage に置く。

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

### Shared SystemMessage（schema）

schema 版は、上の SystemMessage base の末尾に `<schema_overlay>` を追加する。
no_schema に戻すときは、このブロックを丸ごと取り除く。

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

### no_schema で取り除くブロック

schema 版から no_schema 版へ戻すときは、次のタグブロックだけを取り除く。

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

### 履歴メッセージ（0ターン以上、ターンごとに2件のペア）

`state.history` は、LLM に再送する履歴として `BaseMessage` のリストを直接持つ。
各ターンは、**その時に投げた質問・指示**と **エージェントの発話**の2メッセージで保存する。

1. `HumanMessage(content=<question/instruction>)` — そのターンで実際にエージェントへ投げた質問・指示。
   Argument 本体は含めない。

   1周目 main の例:
   ```xml
   <task>
   Round 1. Construct your main argument for the Issue.
   </task>

   <issue>
   ...
   </issue>

   <response_contract>
   If you can construct a main argument, set can_generate=YES and include Argument.
   Otherwise, set can_generate=NO and omit Argument.
   </response_contract>
   ```

   defeat/counter の例:
   ```xml
   <task>
   Round 1. Construct a defeating argument against the target argument.
   </task>

   <issue>
   ...
   </issue>

   <target>
   id: arg-xxxxxxxxxx
   ...
   </target>

   <response_contract>
   If you can defeat the target, set can_defeat=YES and include Argument and Attack.
   Otherwise, set can_defeat=NO and omit Argument and Attack.
   </response_contract>
   ```

2. `AIMessage(content=<Argument>, name=agent)` — そのエージェントの発話そのもの。
   id/round/phase/status/attack 等は一切含めない。

   schema の場合:
   ```json
   {"rules": [...], "Conc": ["..."], "Ass": ["..."]}
   ```

   no_schema の場合:
   ```text
   <free-text argument>
   ```

新しいターンを保存するときは、LLM に送った `HumanMessage` と、LLM から返った `AIMessage` を
そのまま `state.history` に追加する。

```python
history = [
    *state.history,
    HumanMessage(content=main_instruction(state)),
    AIMessage(content=argument_only, name=agent),
]
```

SystemMessage では、この履歴形式を改めて説明しない。
`HumanMessage` / `AIMessage(name=...)` という標準的な会話履歴として渡すことで、
LLM には通常のメッセージ列として読ませる。
schema/no_schema の差は `AIMessage` の `content` の形（dict か free text か）だけである。

`ArgumentRecord` は LLM 履歴ではなく、プログラム側の簿記用レコードとして別に持つ。
例えば `state.argument_records` に `ArgumentRecord` を保存し、`target_id` の解決、
`status` の更新、`defeat_relations` の記録、最終出力用の `dialogue_history` 生成に使う。
`status` は過去の `HumanMessage` に後から書き込まない。必要になるのは主に2周目以降の
main argument 生成時なので、その時点の `HumanMessage` に `revision_context` として含める。

### HumanMessage

各 `*_instruction(...)` は、今回の手番だけで変わる情報を持つ。
main / defeat / counter の違いは、SystemMessage ではなく HumanMessage で表す。

main の例:

```xml
<task>
Round {debate_round}. Construct your main argument for the Issue.
</task>

<issue>
{issue}
</issue>

<response_contract>
If you can construct a main argument, set can_generate=YES and include Argument.
Otherwise, set can_generate=NO and omit Argument.
</response_contract>
```

`state.integrated_rules` が非空（改訂ラウンド）の場合、さらに追記する。
`integrated_rules` は共有ルールなので AG1 / AG2 の両方の main argument 生成時に渡す。
一方、`revision_context` は現在の proponent ごとに作る。
AG1 の main 生成時には AG1 の前回 main とそれを破った理由を渡し、
AG2 の main 生成時には AG2 の前回 main とそれを破った理由を渡す。
この `revision_context` は、その時点で実際に LLM へ送る質問文の一部なので、
生成後はそのまま `state.history` に保存してよい。

```xml
<revision_context>
Your previous main argument was overruled:
"{current_proponent_previous_main_argument}"

It was defeated by the opponent's rebuttal:
"..."

Do not repeat the same main argument unless the defeating reason is resolved.
Ground your NEW main argument in the integrated rules below.
</revision_context>

<integrated_rules>
- {integrated_rule_1}
- {integrated_rule_2}
...
</integrated_rules>
```

defeat の例:

```xml
<task>
Round {debate_round}. Construct a defeating argument against the target argument.
</task>

<issue>
{issue}
</issue>

<target>
id: {target_id}
{target_argument}
</target>

<response_contract>
If you can defeat the target, set can_defeat=YES and include Argument and Attack.
Otherwise, set can_defeat=NO and omit Argument and Attack.
</response_contract>
```

counter の例:

```xml
<task>
Round {debate_round}. Construct a counterargument that defends your prior argument against the target attack.
</task>

<issue>
{issue}
</issue>

<target>
id: {target_id}
{target_argument}
</target>

<non_repetition>
Do not merely restate your original main argument.
</non_repetition>

<response_contract>
If you can defeat the target, set can_defeat=YES and include Argument and Attack.
Otherwise, set can_defeat=NO and omit Argument and Attack.
</response_contract>
```

---

## 3. 現状からの変更点

### (a) SystemMessage の `<task>` / `<role>` を削る

現状:

```xml
<task>
Construct an argument for your position on the Issue.
</task>
```

提案:

SystemMessage には task / role を置かない。
main / defeat / counter の具体的な手番指示は HumanMessage に置く。

理由:

- `Issue` に対する具体的な手番指示は HumanMessage に置く。
- SystemMessage は全 argument 生成ノードで共通利用する。
- main / defeat / counter の差分を SystemMessage に入れると、テンプレートが分岐して重複が増える。
- HumanMessage と SystemMessage の重複を減らし、指示の衝突余地を下げる。

### (b) schema 固有語彙を `<schema_overlay>` に隔離する

現状の共有ブロックには、`Conc` / `Ass` / `rules` など schema 前提の語彙が混ざっている。
提案では、base は自然言語論証にも構造化論証にも共通する説明だけにし、
schema 版でのみ `<schema_overlay>` を追加する。

これにより、no_schema では `<schema_overlay>` を丸ごと削除すればよい。

### (c) 出力契約を HumanMessage に寄せる

現状の `<output>` は SystemMessage にあるが、main / defeat / counter で必要な出力契約は異なる。

- main: `can_generate` と `Argument`
- defeat / counter: `can_defeat` と `Argument` / `Attack`
- undercut: `can_undercut` と `Argument`

shared SystemMessage に抽象的な出力契約を書くと、結局「relevant availability field」のような
曖昧な表現になる。提案では、具体的な出力契約を各 HumanMessage に置く。
`with_structured_output` の Pydantic schema も併用するため、HumanMessage の契約は
スキーマの補助説明という位置づけにする。

### (d) revision round の non-repetition は HumanMessage に寄せる

main argument の初回生成では、過去の main argument が存在しない。
そのため「繰り返すな」は SystemMessage の常時ルールではなく、
revision round の `integrated_rules` と一緒に HumanMessage に置く。

### (e) 履歴を「質問・指示」と「発話」の2メッセージに分割する

現状は `AIMessage` の `content` に `id`/`round`/`phase`/`status`/`attack`/`target_id`/
`target_statement` と `Argument` を1つの JSON として混在させており、LLM からは
これら全体が「そのエージェントの発話」に見える。

提案では、1ターンを次の2メッセージに分割する。

- `HumanMessage`：そのターンで実際にエージェントへ投げた質問・指示。
  その手番の `target_id` / `target_statement` などは必要に応じて含める。
  後から決まる `status` は過去メッセージには追記せず、次の main 生成時の
  `revision_context` に含める。
- `AIMessage`：そのエージェントの実際の論証（Argument）のみ。

これにより、`AIMessage` = 「そのエージェントが実際に言ったこと」、
`HumanMessage` = 「その発話を引き出した質問・指示」として、LangChain のメッセージモデルに沿って分離される。
この履歴形式は実装上の契約として扱い、SystemMessage では説明しない。

### (f) SystemMessage からプロトコルの流れ説明を外す

現状の `_PROTOCOL_FLOW` は、main / defeat / counter / status / integrated rules まで、
ワークフロー全体の進行を SystemMessage に説明している。

提案では、argument 生成の SystemMessage からこの種のプロトコル説明を外す。
理由は、各ターンの `HumanMessage` に「その時に何を質問・指示したか」が履歴として残るため、
LLM は過去の `HumanMessage` / `AIMessage` のペアから流れを読めるからである。

プロトコル制御そのものは LLM に説明するのではなく、LangGraph の node / edge が担う。
LLM には、その node で必要な局所タスクだけを `HumanMessage` として渡す。

---

### (g) main / defeat / counter で同じ SystemMessage を使う

現状は main / defeat / counter / undercut ごとに SystemMessage が分かれている。
提案では、少なくとも main / defeat / counter は同じ shared SystemMessage を使い、
具体的な手番差分を HumanMessage に寄せる。

- main: `main_instruction(state)`
- defeat: `attack_instruction("defeat", target)`
- counter: `attack_instruction("counter", target)`

これにより、SystemMessage 側の重複・矛盾を減らし、プロトコル変更時の修正範囲を
HumanMessage builder と LangGraph の node / edge に寄せられる。

---

## 4. 実装時の注意

`prompts.py` に落とすときは、shared base SystemMessage と schema overlay を別々の文字列として持つ。

実装イメージ：

```python
ARGUMENT_SYSTEM_BASE = _system(
    identity_and_stance,
    grounding,
    argumentation_rules,
)

ARGUMENT_SYSTEM_NO_SCHEMA = ARGUMENT_SYSTEM_BASE

ARGUMENT_SYSTEM = _system(
    ARGUMENT_SYSTEM_BASE,
    schema_overlay,
)
```

実際には `identity_and_stance` は `agent_system()` 側で付与するなら、
`ARGUMENT_SYSTEM_BASE` には `grounding` 以降だけを入れる。

`main_instruction(state)` / `attack_instruction(...)` は XML 風タグに揃え、`Issue` / `target` /
revision constraints / response contract を HumanMessage に残す。

改訂ラウンドの `main_instruction(state)` は `state.current_proponent` を見て、
agent-specific な `revision_context` を作る。

```python
if state.current_proponent == "AG1":
    previous_main = state.ag1_previous_main_argument  # or argument_records から検索
    defeat_reason = state.ag1_previous_defeat_reason
else:
    previous_main = state.ag2_previous_main_argument
    defeat_reason = state.ag2_previous_defeat_reason
```

`integrated_rules` は同じ共有リストを AG1 / AG2 両方に渡すが、`previous_main` と
`defeat_reason` は現在生成中の agent に対応するものだけを渡す。

---

## 5. 決めるべきこと

- `<schema_overlay>` というタグ名でよいか、`<structured_output_overlay>` のようにより明示的にするか。
- undercut も同じ shared SystemMessage に含めるか、undercut だけは専用 SystemMessage を残すか。
- 履歴の「質問・指示→発話」分割について:
  - 過去ターンの `HumanMessage` は、実際に送った instruction をそのまま保存するか、
    履歴用に短く再構成した instruction を保存するか。
  - 後続ターンで必要な `revision_context` / `target` を、どの程度詳しく HumanMessage に含めるか。
  - 1ターンあたりのメッセージ数が2倍になることによるトークン増・履歴の長さをどう許容するか
    （ラウンドが進むほど影響が大きくなる）。
  - 現在の `state.history: list[ArgumentRecord]` を、LLM 用の `state.history: list[BaseMessage]` と
    簿記用の `state.argument_records: list[ArgumentRecord]` に分ける変更が、`nodes.py` / `defeats.py` /
    最終回答生成に与える影響。
