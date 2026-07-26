# 評価用対話履歴フォーマット統一 仕様書

## 1. 目的

現在、LLM評価器（`src/eval/evaluation.py`）に渡す対話履歴は、手法（schema / no_schema /
mad / free_debate）ごとに表現形式がバラバラである：

- schema: `{"Argument": {"rules": [...], "Conc": [...], "Ass": [...]}}` という生JSON
- no_schema: 自由記述の自然文（ただし内部で premise/conclusion 相当を書いている）
- mad / free_debate: 自由記述の自然文（premise/conclusion の区別自体がない）

さらに、schema/no_schema は「このターンがどのターンの何を、どんな種類の攻撃
（rebut/undercut）で狙ったか」という情報を、保存ログの時点で失っている
（`src/dialogue/common.py` の `_speech_log` が `agent`/`argument` 以外を破棄しているため）。

この2つの問題（① 表現形式の不統一、② 攻撃関係メタ情報の欠落）が、LLM評価器にとって
schema の可読性を著しく下げ、Validity 軸を中心にスコアを不当に押し下げている疑いがある
（詳細は本ドキュメント末尾「背景となった調査」を参照）。
V
本仕様は、評価器に渡す対話履歴を **手法によらず同じ形の日本語文**に正規化し、かつ
攻撃関係（誰の何に対する rebut/undercut か）を明示することを目的とする。

ただし正規化した文は「〇〇という根拠をもとに、〇〇という結論を出しました」のような
第三者視点の報告調ではなく、**エージェント自身の発話として読める文体**（根拠と結論を
「だから」「したがって」のような接続語で直接つなぐ、一人称的な言い切りの文）にする
（§4参照）。報告調は対話のログというより実験結果の要約のように読めてしまい、
Coherence/Dialecticalityの判定にも不自然な印象を与えるため。

## 2. 対象範囲

**本仕様の変更はすべて未実施（計画のみ）。承認後に一括で実装する。**

| 変更する | 変更しない |
|---|---|
| 評価器に渡す transcript の整形ロジック（`build_eval_input` / `_format_turn`） | `SCORING_INSTRUCTION` の採点基準文言（軸の定義は変更しない） |
| ログ保存時に破棄している attack メタ情報の保持（`_speech_log`） | 生成グラフ本体のロジック・グラフ構造（`src/agent/nodes.py` 等） |
| `_ARGUMENTATION_RULES` の語彙書き換え（ラベル化誘発の除去、§5.2.1） | mad / free_debate の生成プロンプト（無変更。原論文に忠実な最小限プロトコルという設計を維持） |
| `_GROUNDING` の単一ルール化（スタンス優先＋知識解放、§5.3。**トピックによるモード分離はしない**） | schema の構造強制（`_SCHEMA_OVERLAY`、無変更） |
| 最終回答プロンプトの provisional / no consensus 除去（§5.4） | — |

grounding・argumentation_rules は schema/no_schema 共有ブロックであり、プロンプトは
全トピック共通の単一のものを使う（プロトコルの同一性を守る）。
**対話生成をやり直すのは schema / no_schema のみ**（mad/free_debateは
既存ログのまま評価だけ再実行、§7参照）。

## 3. データ層の変更

### 3.1 `_speech_log` の修正（`src/dialogue/common.py`）

現状:

```python
def _speech_log(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"agent": record.get("agent"), "argument": record.get("argument")}
        for record in history
    ]
```

`ArgumentRecord.to_dialogue_dict()`（`src/agent/schema/state.py:170-184`）は本来
`id` / `type` / `target_id` / `attack` / `target_field` / `target_statement` / `status`
を持っている。`_speech_log` はこれらを次のフィールドまで残すように拡張する:

```python
def _speech_log(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        "id", "agent", "type", "argument",
        "attack", "target_id", "target_field", "target_statement",
        "status",
    )
    return [
        {k: record.get(k) for k in keys if record.get(k) is not None}
        for record in history
    ]
```

設計意図（何のためにどのカラムを残すか）:

- **`target_*`（攻撃対象カラム）**: `Argument` スキーマ自体（rules/Conc/Ass）は変更
  しない。その1つ上のレイヤーであるログエントリに、攻撃系の発話（defeat/counter/
  undercut）が**どの前提・結論を狙ったのか**を残す。これが無いと、schemaを自然文に
  変換する際（§4.2/§5.1）の
  `I have a counter argument against the opinion {…}` の `{…}` に代入するものが
  存在しなくなる。`target_statement`（狙われた文そのもの）が代入元、`target_field`
  （Conc / Ass）が「結論への反論か前提への反論か」の使い分け元、`target_id` が
  Turn番号への解決元。
- **`status`（主張の状態）**: main argument のスレッド決着
  （justified / overruled / defensible）は `complete_thread` →
  `_annotate_main_status` で該当 main の record に書き込まれている
  （`src/agent/nodes.py`）。現状の `_speech_log` はこれも捨てているため、ログから
  「この主張は最終的にどうなったのか」が読めない。保存対象に含める。

mad / free_debate はこの関数を経由しない経路（`src/dialogue/common.py:462`, `:519`）で
保存されており、そもそも `to_dialogue_dict()` 相当の dict をそのまま使っているため
変更不要（`id`/`type`/`attack` 等のキーが元から存在しないか None のまま）。

### 3.2 影響: 既存ログの再生成が必要

この変更は**保存フォーマットの変更**なので、現在の `logs/sweep_all_topics_schema_*`,
`logs/sweep_all_topics_no_schema_*` は対象キーを持たない。評価用に正しい transcript を
作るには、schema/no_schema のログを本仕様の実装後に**再生成**する必要がある
（3回目の sweep 実行になる）。

## 4. 統一フォーマット定義

評価器に渡す1ターン分のテキストは、次の2行構成に統一する。1行目は誰が・何に対して
発話しているかのメタ情報（ラベル）、2行目が**エージェント自身の発話**（根拠と結論を
接続語で直接つなぐ、一人称的な言い切りの文。「〜という結論を出しました」のような
第三者の報告調にはしない）:

```
[Turn N] AGENT (種別・攻撃対象の注記)
<根拠>。したがって、<結論>。
```

### 4.1 main argument（最初の主張、攻撃ではない）

```
[Turn 1] AG1 (main argument)
画質と電池持ちが十分な機種を選ぶべきだ。したがって、入門〜中級のミラーレスを候補にすべきだ。
```

### 4.2 攻撃ターン（defeat / counter、target情報あり）

攻撃であることと対象をラベル（1行目）だけに留めず、**発話本体（2行目）の冒頭にも
反論であることを明示する一文を入れる**（対話らしさを優先し、ラベルとの多少の重複は許容する）:

```
[Turn 2] AG2 (undercut — responds to [Turn 1])
「少なくとも画質と電池持ちの最低ラインを満たす必要がある」という前提に対して反論がある。実際の撮影では使いやすさの方が失敗要因になりやすい。したがって、使いやすさを優先すべきだ。
```

- `attack` が `rebut` の場合: 発話冒頭 `「target_statement」という結論に対して反論がある。`
- `attack` が `undercut` の場合: 発話冒頭 `「target_statement」という前提に対して反論がある。`
- 続けて `<根拠>。したがって、<結論>。`（§4.1と同じ組み立て）を接続する。
- 冒頭文の `{target_statement}` への代入元は、§3.1 で保存するログの `target_statement`
  カラム。`target_field`（Conc / Ass）が「結論/前提」の使い分け元。**この2カラムが
  ログに無いと代入するものが存在しない**ため、§3.1 の `_speech_log` 拡張が本節の
  前提条件になる。
- ラベル（1行目）は `(種別 — responds to [Turn X])` 程度の軽い情報に簡略化してよい
  （対象の中身は発話本体に出ているので、ラベル側は「何ターン目への応答か」という
  参照だけで十分）。
- 接続語は「したがって」を既定とするが、根拠が複数ある場合や元の文体に応じて
  「だから」「よって」などに置き換えてよい。
- 本仕様の例文は日本語だが、**実際の描画は議論本文の言語（英語）**で行う。英語の
  正準テンプレート:
  - main: `{grounds}. Therefore, {conclusion}.`
  - rebut: `I have a counter argument against the opinion "{target_statement}". {grounds}. Therefore, {conclusion}.`
  - undercut: `I have a counter argument against the premise "{target_statement}". {grounds}. Therefore, {conclusion}.`

> **この「反論がある」冒頭文はschemaの機械的組み立て（§5.1）にのみ適用する。**
> no_schema/mad/free_debateは元の発話をそのまま使う方針（§5.2）のままなので、
> エージェントが実際には言っていない文をこちらで捏造して先頭に足すことはしない
> （ラベル行での注記のみ）。生成プロンプト側にも同様の誘導は追加しない（§5.2.1参照）。

- `target_id` から `[Turn X]` を引くための **id→ターン番号のマップ** を、transcript 整形時に
  transcript 全体を1回舐めて構築する（`build_eval_input` 内のローカル処理でよい、恒久的な
  状態を持たせる必要はない）。

## 5. 手法別の抽出ロジック

### 5.1 schema（機械的に抽出可能）

`argument` は次の形の JSON 文字列:

```json
{
  "Argument": {
    "rules": [
      {"antecedent": {"strong": [...], "weak_negation": [...]}, "consequent": "..."},
      ...
    ],
    "Conc": [...],
    "Ass": [...]
  }
}
```

- **結論** = 最後の rule の `consequent`（＝そのargumentの最終的な warrant）。
- **根拠** = 全ruleの `antecedent.strong` を結合したもの。`weak_negation`（未検証の前提）が
  存在する場合は「（ただし〇〇という前提に依存）」として根拠の末尾に付記する。
- 複数ruleがある場合（中間推論ステップがある場合）は、根拠を
  `strong[0] → strong[1] → ... → 結論` のように矢印でつないでもよいが、まずは
  「全rulesのstrongをまとめて根拠、最終consequentを結論」という単純な1行整形から始める
  （複雑化は後回し）。
- 組み立ては §4 の発話体フォーマットに従う（描画言語は議論本文と同じ英語）。
  - main argument（`type == "main"`、`attack` が None）:
    `f"{grounds}. Therefore, {conclusion}."`
  - 攻撃ターン（`type` が `defeat`/`counter`、`attack`/`target_field`/`target_statement` あり）:
    `f"I have a counter argument against the {'opinion' if target_field == 'Conc' else 'premise'} \"{target_statement}\". {grounds}. Therefore, {conclusion}."`
  - いずれも第三者の報告調（`〜という結論を出しました` / `The agent concluded ...`）は使わない。
- **主張の状態（status）**: main argument の record に `status`
  （justified / overruled / defensible）が §3.1 で保存されるようになる。評価用
  transcript にこれを描画するかは §8 の未解決事項（プロトコル内部語彙を評価者に
  見せると手法固有の情報になるため、既定では**描画しない**。ログには常に残す）。

### 5.2 no_schema / mad / free_debate（評価時ではなく生成時に誘導する）

これらは自由記述の自然文であり、評価器に渡す**直前**に「根拠」と「結論」を文字列処理
だけで正確に分離することはできない。評価の後付けでLLMに要約・再構成させる案
（Phase 2として一度検討）は、追加のLLM呼び出しコスト・latency・要約による意味の
ズレという新しいバイアス源を持ち込むため採用しない。

評価時のtranscript整形は、no_schema/mad/free_debateについては**元のテキストをそのまま
使い、攻撃メタ情報の注記行だけを揃える**（schemaのような機械的な根拠/結論抽出はしない）:

```
[Turn 2] AG2 (undercut — [Turn 1] の前提「少なくとも画質と電池持ちの最低ラインを満たす必要がある」を攻撃)
<no_schemaの自由文をそのまま（生成プロンプトの誘導により、根拠→結論の形になっているはず）>
```

mad / free_debate は `attack` が常に None なので、注記は `(main argument)` 相当の
`(turn N)` のみで、target注記は付かない。

#### 5.2.1 プロンプト変更について（当初案から撤回・縮小）

当初、no_schema/mad/free_debateすべてに「根拠から論理的に結論を導け」という指示
（`_LIGHT_REASONING_HINT`）を追加する案を検討したが、以下の理由で**撤回**した。

**そもそも追加の指示が必要か再検討した結果:**

- **mad / free_debate には追加しない。** これらは今回問題になっている
  「transcriptが読みにくくてスコアが低い」という現象自体と無関係（現状すでに
  4手法中もっともスコアが高い＝既に自然な流れる文章として書けている）。
  `free_debate.py` のコメントにある「原論文に忠実な最小限プロトコル、独自のstyle指示は
  付与しない」という設計意図を崩してまで手を入れる理由がない。**無変更のままにする。**
- **no_schema にも新規の指示は追加しない。** `ARGUMENT_SYSTEM_NO_SCHEMA`
  （`_GROUNDING` + `_ARGUMENTATION_RULES`、L107-110）には既に「premisesを述べよ」
  「結論は推論から直接導け」という指示があり、根拠→結論の論理展開はすでに要求済み。
  ここに輪をかけて指示を追加するのは重複。

**むしろ既存指示の語彙そのものが原因なので、それを取り除く:**

実際のno_schemaの出力を見ると、"Premises/assumptions:\n1) ...\nConclusion:\n..." のように
**見出しラベル付きで書いてしまっている**ケースが確認できた（`artificial_intelligence`
トピックの実ログで確認済み）。原因は明確で、`_ARGUMENTATION_RULES`（L30-37）が
以下のように **"premises"/"assumptions"/"conclusion" という単語を指示文にそのまま
使っている**ため、モデルがその単語をそのまま出力の見出しとして echo している:

```python
# 現状（schema/no_schema 共有）
_ARGUMENTATION_RULES = """\
<argumentation_rules>
- State the premises and assumptions you rely on.
- Do not introduce new factual claims as strong premises; each strong premise must be stated or directly derived from your stance, the target argument, prior dialogue history, or integrated rules.
- The conclusion must follow directly from the stated reasoning, with no implicit logical leap.
- The final conclusion must clearly express your opinion on the Issue in a concise and specific way.
- Be concise; do not pad the reasoning with repetition.
</argumentation_rules>"""
```

「ラベルを使うな」という禁止文を後から足すのではなく、**誘発している単語自体を
言い換えて取り除く**（禁止のパッチではなく、原因そのものの除去）:

```python
# 修正後（schema/no_schema 共有）
_ARGUMENTATION_RULES = """\
<argumentation_rules>
- Make clear what you are relying on to support your position.
- Do not introduce new factual claims; everything you rely on must be stated or directly derived from your stance, the target argument, prior dialogue history, or integrated rules.
- Your final position must follow directly from what you have stated, with no implicit logical leap.
- Your final position must clearly express your opinion on the Issue in a concise and specific way.
- Be concise; do not pad the reasoning with repetition.
</argumentation_rules>"""
```

- 「premises and assumptions」→「what you are relying on」、「conclusion」→
  「your final position」のように、名詞としてラベル化されやすい単語を避けた
  言い回しに置き換えただけで、要求している内容（根拠を明示し、そこから論理的に
  結論を導く）自体は変えていない。
- **schemaへの影響はない。** schemaは `_SCHEMA_OVERLAY`（L39-51）が独自に
  「strong premises」「weak_negation assumptions」「Conc」という語彙を再定義して
  構造化出力を強制しているため、`_ARGUMENTATION_RULES` 側の語彙を変えても
  schemaの出力品質には影響しない（`_SCHEMA_OVERLAY` が既に自己完結している）。
- no_schemaは元々この語彙に依存する理由がなかった（自由記述なので、あえて
  "premise"/"conclusion" というラベル的な単語を与える必要はない）。

> **結論**: mad/free_debateは無変更。no_schemaは新規指示の追加でも禁止文の追加でもなく、
> `_ARGUMENTATION_RULES`（schema/no_schema共有ブロック）の語彙自体を、ラベル化されにくい
> 言い回しに書き換える。

### 5.3 Grounding ルールの分離（strict / open）

#### 背景

現状の grounding 制約は2箇所にある:

- `_GROUNDING`: 「価値観・優先順位はスタンス由来。general knowledge はスタンスを満たす
  選択肢・理由の特定に役立つ場合のみ使用可」
- `_ARGUMENTATION_RULES`: 「新しい事実主張を導入するな。依拠するものはすべて stance /
  target / 対話履歴 / integrated rules から述べるか直接導け」

ログ監査の結果:

- **実トピックでは、スタンス文の字面コピーはほぼ発生していない**（文類似度>0.75 の
  ほぼコピーは schema/no_schema 各3件中 0〜2%）。懸念された「スタンス文の組み合わせ
  生成」にはなっていない。
- ただし**新規概念の導入密度に明確な勾配**がある（スタンスにない内容語 / 1000文字:
  schema 29.0 < no_schema 38.2 < mad 45.7 < free_debate 52.2）。「新事実禁止」が
  外部知識の持ち込みを抑制している（ゼロにはしていないが、baselineの55〜75%に留まる）。
- mad の「豊かさ」を監査すると、大半はスタンス自体に書かれた具体的事実の忠実な展開
  （Title IX・NCAA等はスタンスに明記されていた）で、スタンスにない補強材料
  （フィギュアスケートとの類比等）も「結論・価値観はスタンスに忠実なまま、支持理由
  だけ外部調達」というパターン。**スタンスの価値観自体から逸脱した事例は見つかって
  いない**。

一方、`datasets/scenarios/` 配下の4トピック（camera / camera_logic / curry /
curry_logic）は、スタンスがルール集合そのものである**正当性検証用の合成論理パズル**
であり、ここでは「スタンスに書かれたことから論証する」ことがプロトコルの正しさの
検証条件になっている。

#### 設計方針: モード分離はしない。単一ルールを、検証をクリアするギリギリまで緩める

> 当初「scenariosはstrict / 一般トピックはopen」というトピック種別によるモード分離を
> 検討したが、**撤回**した。トピックによってプロンプトが変わるのは実質的に別プロトコル
> になってしまうため。grounding は全トピック共通の**単一ルール**とし、その文言を
> 「正当性検証（camera/curry）が引き続き成立するギリギリのライン」まで緩める。

鍵となる観察: scenarios のスタンスは選択肢（a/b/c）について**完結したルール・事実の
集合**であり、一般トピックのスタンスは主張と論点の列挙で**多くを語っていない**。
したがって「スタンス側に判断材料があるならそれを優先し、書かれていない部分は一般知識で
補ってよい」という**優先順位ルール**にすれば、単一の文言のまま、scenariosでは事実上
厳密に（スタンスが全てを決めているので上書き余地がない）、一般トピックでは広く
（スタンスが沈黙している支持材料の部分に知識が入る）振る舞う。

書き換え案（`_GROUNDING` を置き換え、`_ARGUMENTATION_RULES` の「新事実禁止」行は削除）:

```python
_GROUNDING = """\
<grounding>
- Your values, priorities, and the position you argue for come from your stance; never contradict your stance or adopt priorities it does not contain.
- Where your stance, the target argument, the dialogue history, or the integrated rules already provide the facts or rules that settle a point, argue from those; do not override or replace them with outside knowledge.
- Where they are silent, you may draw on general knowledge — facts, examples, analogies, mechanisms — to support your position or to challenge the other side's reasoning.
</grounding>"""
```

- 1行目: 結論・価値観のスタンス固定（従来より明確化）。
- 2行目: **スタンス優先原則**。scenariosではスタンスが全論点を settle しているので、
  実質的に従来のstrictな挙動になる。
- 3行目: スタンスが沈黙している部分の知識解放。一般トピックの支持材料はほぼここに
  該当する。
- 統計・引用の捏造ガード（"Do not invent precise statistics..."）を足すかは要判断
  （幅広さ優先なら入れない）。

#### 検証条件（実装時に必須）

この文言変更は「単一ルールで両立できる」という仮説に基づくので、full sweep の前に
**scenarios 4トピックでのスモークテスト**を行い、以下を目視確認する:

- 論証がスタンスのルール（「カレー味なら食べるべき」等）から導かれていること
- 外部知識（「麺類は健康的」等）がスタンスのルールを**上書き**していないこと
- defeat/counter が従来どおり成立し、justified/overruled/defensible の判定が
  シナリオの期待と一致すること

クリアできなければ2行目の文言を強める方向で調整する（モード分離には戻らない）。

#### 並行攻撃の理解（補足）

プロトコル上、Opponent の defeating argument (B) は1つのmain argument (A) に対して
複数回（リトライで別候補を）生成され、それぞれが defeat できるか検証される。
`dialogue_history` 上で同一エージェントの発話が連続するのはこの並行/リトライ生成の
痕跡であり、多ターンの会話ではない。grounding の知識解放（3行目）はこのリトライにも
効く: 外部知識が使えれば、リトライ時に**異なる角度のB**を作る材料が増える（現状の
制約下では、リトライBがスタンスの同じ材料から作られるため同型になりやすい）。

### 5.4 最終回答プロンプトから「provisional / no consensus」を除去する

弁証法議論は**内部の推論過程**であり、ユーザーに見えるのは最終回答のみ。現状の
`FINAL_ANSWER_NO_CONSENSUS_SYSTEM` は「暫定であること・合意に至らなかったことを
明示せよ」と指示しており、実測で schema 80.5% / no_schema 85.7% の最終回答が
「Provisional answer / no consensus」で始まる（mad 0% / free_debate 0.2%）。
これはユーザーを困惑させるうえ、評価でも決定的な回答を出す baseline に対して
構造的に不利になる。

変更内容（`src/agent/prompts.py`）:

1. `FINAL_ANSWER_NO_CONSENSUS_SYSTEM`: `<context>`（合意に至らなかった旨）を削除し、
   以下に置き換える:

```python
    FINAL_ANSWER_NO_CONSENSUS_SYSTEM = _system(
        "<task>\n"
        "Based on the debate so far, write the final answer to the original question. "
        "Weigh the strengths of both sides' reasoning and commit to the best-supported "
        "answer, stating it directly with its supporting rationale. If integrated rules "
        "are provided below, ground your answer in them.\n"
        "</task>",
        "<style>\n"
        "The debate above is internal reasoning; the reader sees only your answer. "
        "Do not mention the debate process, the agents, rounds, or whether agreement "
        "was reached. Write the answer as a direct, self-contained response to the "
        "question.\n"
        "</style>",
    )
```

2. `FINAL_ANSWER_NO_CONSENSUS_USER`: 「No consensus was reached within the debate
   limit.」の行と「(not agreed upon by both sides)」の注記を削除する
   （`Most developed argument from the debate:` に簡略化）。

3. `_PROTOCOL_FLOW`（現状未使用の定義だが整合のため）: 「then a provisional,
   no-consensus answer is produced」→「then the final answer is produced from the
   debate so far and the integrated rules」。

## 6. 実装箇所

**注: 本仕様の変更はすべて未実施**（計画のみ。実装は本仕様の承認後に一括で行う）。

| ファイル | 変更内容 |
|---|---|
| `src/dialogue/common.py` | `_speech_log` を §3.1 の通り拡張（攻撃対象カラム `attack`/`target_id`/`target_field`/`target_statement` と、主張の決着 `status` を保存） |
| `src/eval/evaluation.py` | `_format_turn` を廃止し、新関数 `_format_turn_unified(turn, id_to_turn_no)` に置き換え。schemaのJSONは§5.1のロジックで根拠/結論を抽出、それ以外は§5.2の通り原文＋注記のみ |
| `src/eval/evaluation.py` | `build_eval_input` 内で `id → [Turn N]` のマップを構築し、`_format_turn_unified` に渡す |
| `src/agent/prompts.py` | ① `_ARGUMENTATION_RULES` の文言を、ラベル化を誘発しない言い回しに書き換え＋「新事実禁止」行を削除（§5.2.1, §5.3）。② `_GROUNDING` を §5.3 のスタンス優先の単一ルールに書き換え（モード分離はしない。State へのフラグ追加も不要）。③ 最終回答プロンプトの provisional / no consensus 除去（§5.4）。mad/free_debate（`MAD_TURN_SYSTEM` / `FREE_DEBATE_TURN_SYSTEM`）は無変更 |

`SCORING_INSTRUCTION` 自体（採点基準・軸の定義）は変更しない。

## 7. ロールアウト手順

1. `_speech_log` を修正（§3.1）。
2. `prompts.py` を一括修正: `_ARGUMENTATION_RULES` の書き換え（§5.2.1）、
   `_GROUNDING` の単一ルール化（§5.3）、最終回答プロンプトの provisional 除去（§5.4）。
   mad/free_debateのプロンプトは変更しない。
3. `evaluation.py` の transcript 整形を書き換え（§6）。
4. 単体テストで、サンプルのschema JSON 1件・no_schema 1件・mad 1件を整形し、
   期待通りの出力になることを確認（schemaは§4/§5.1のテンプレート、他は原文＋注記）。
5. **scenarios 4トピックでスモークテスト**（§5.3の検証条件）: 新しい `_GROUNDING` の
   下で正当性検証が引き続き成立することを確認してから full sweep に進む。
6. **対話生成をやり直すのは schema / no_schema のみ**（`_speech_log`修正・プロンプト
   変更の反映のため）。**mad / free_debate は生成プロンプトを変更しないので、
   既存ログのまま評価だけ再実行する**（前回と同じ扱い）。
7. 4手法とも新しいtranscript整形で評価し、Validity軸を中心にスコアの変化を確認する。

## 8. 未解決事項・オプション

- **複数rule argumentの根拠の粒度**: 全rulesのstrongを単純結合するか、ruleごとに
  段階的に見せるか。まずは単純結合で様子を見て、評価者が中間推論を無視しているようなら
  段階表示に切り替える（実例で確認済み: 中間ruleのstrongが直前ruleのconsequentの
  言い換えである場合、結論と隣接して重複が生じる。今回は許容範囲として単純結合のまま
  進める）。
- **weak_negation（未検証の前提）の扱い**: 根拠に含めるか、別枠で「この主張が前提とする
  未検証の仮定」として明示するか。undercutの対象になるのはこの部分なので、
  target_statement と対応が取れるよう、できれば別枠で明示した方がVaidity判定がしやすい。
- **語彙の書き換えが実際にラベル化を止めるか**: `_ARGUMENTATION_RULES` の書き換え後、
  実際のno_schema出力で "Premise 1:" / "Conclusion:" 等のラベルが本当に消えているか、
  再生成後に目視確認する。効果が薄ければ、"position" 等の別の単語がまた新たなラベルとして
  echo されていないかも合わせて確認し、さらに言い換えを調整する。
- **status を評価用 transcript に描画するか**: `status`（justified / overruled /
  defensible）はログには常に保存する（§3.1）が、評価用 transcript への描画は既定では
  行わない。プロトコル内部の自己判定を評価者に見せると、schema/no_schema にだけ存在する
  情報が採点に影響し、手法間の公平性を再び崩しうるため。分析用途（プロトコル挙動の
  デバッグ・集計）ではログの status を直接使う。
- **【保留・次の一手候補】transcript への「ト書き」挿入**: 本仕様（自然文変換＋攻撃
  対象の明示）だけでスコアが改善しなかった場合に試す。プロトコル内部の出来事
  （攻撃のリトライ / スレッド決着 / 統合フェーズ）を、プロトコル用語を使わない日常語の
  記述行として transcript に挿入し、評価者が議論の流れ（急に別の反論が始まる・急に
  統合される）を追えるようにする案。決着の写像例: justified →「claim withstood every
  objection」、overruled →「claim could not be defended」、defensible →「both
  positions remained standing」。統合のト書きには `integrated_rules` のログ保存
  （現状未保存）が追加で必要になる。採点基準（SCORING_INSTRUCTION）は共通のまま、
  transcript 側の自己記述として行うので公平性の線は守られる、という整理。

## 背景となった調査（参考）

- 実際に評価器へ渡っているschemaのtranscriptは、フィールド名の説明もtarget情報もない
  生JSONの羅列だった（`SCHEMA_METHOD_CONTEXT` 削除後）。
- 保存ログ自体（`_speech_log`）が `agent`/`argument` 以外を破棄しており、
  schema/no_schemaとも「どのターンが何を攻撃したか」の情報を評価器に渡せていなかった。
- mad/free_debateはこの問題の影響を受けない（attack概念を持たないため、
  そもそも失われている情報がない）。これが、schema/no_schemaが軒並み
  mad/free_debateよりスコアが低い傾向と整合する。
