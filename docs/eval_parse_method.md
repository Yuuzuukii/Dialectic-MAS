# 評価用トランスクリプト：完全なパース方法（改訂・実例つき）

> 本書は [eval_transcript_format_spec.md](eval_transcript_format_spec.md)（計画書）の
> **現状反映＋実例版**。「評価LLMに渡す前に、各手法の発話をどう1つの形へ正規化するか」を、
> 実際のログから取り出した before/after で示す。主張（main）と反論（attack）の両方を扱う。

---

## 0. 現状サマリ（2026-07-10 時点）

| 層 | 状態 |
|---|---|
| `src/eval/evaluation.py`（整形ロジック） | ✅ **実装済み**。`_format_turn_unified` / `_schema_utterance` / `_turn_label` が攻撃対応込みで動く |
| `src/dialogue/common.py` の `_speech_log`（保存フィールド） | ✅ **修正済み**。`id/type/attack/target_id/target_field/target_statement/status` を保持する |
| `src/agent/schema/state.py` の `to_dialogue_dict()`（メタ情報の源） | ✅ 元から `attack/target_*/status` を持つ |
| **評価に使った schema/no_schema ログ（`sweep_all_topics_*_20260706`）** | ⚠️ **`_speech_log` 修正前に生成された古いログ**。`{agent, argument}` しか無く、攻撃メタ情報が欠落している |

**結論**：パイプライン（生成→保存→整形）は完成しているが、**いま評価に使っている
schema/no_schema ログだけが修正前で古い**。そのため下記「反論の完全パース」が
実ログでは発火せず、反論が主張と同じ体裁でフラット化している（＝ dialecticality/validity
で不利になっている疑いの直接原因）。**schema/no_schema を再生成すれば解消する。**

新規生成では実際にメタ情報が入ることを確認済み（本書の実例はすべて現行コードで
`datasets/Sports/golf.json` を新規生成した実データ）。

---

## 1. 出力フォーマット（全手法共通）

1ターン = **ラベル行 + 発話本体** の2行。

```
[Turn N] AGENT (種別・攻撃対象の注記)
<発話本体：一人称の言い切り。根拠 → Therefore, 結論>
```

- 採点プロンプト（`SCORING_INSTRUCTION`）は4手法で**完全に同一**。違うのは本体の作り方だけ。
- schema だけ JSON を機械変換する。no_schema/mad/free_debate は**原文そのまま**、ラベル行だけ揃える。
- 描画言語は議論本文と同じ英語。

---

## 2. schema：JSON → 発話体への完全パース

`argument` は `{"Argument": {"rules":[{antecedent:{strong,weak_negation}, consequent}], "Conc":[], "Ass":[]}}`。

| JSON要素 | 出力での役割 |
|---|---|
| 全 rule の `antecedent.strong` | 根拠。`". "` で連結 |
| `antecedent.weak_negation` | `(This relies on the assumption that …)` として末尾に付記 |
| 最後の rule の `consequent` | `Therefore, <結論>.` |
| ターンの `type`（main / defeat / counter） | ラベルの種別 |
| ターンの `attack`（rebut / undercut） | 反論冒頭文の生成トリガ |
| `target_field`（`Conc` / `Ass`） | 反論対象が「opinion（結論）」か「premise（前提）」か |
| `target_statement` | 反論冒頭文に埋め込む「攻撃された文そのもの」 |
| `target_id` | ラベルの `responds to [Turn X]` へ解決（id→ターン番号マップ） |

### 2.1 主張（main argument）

**生JSON:**
```json
{"Argument":{"rules":[{"antecedent":{
  "strong":[
    "Golf involves significant physical exertion (…burns over 1,400 calories).",
    "Golf requires considerable skill (…coordinated muscle engagement of the swing…).",
    "Golf is competitive (tournament play presents difficult contests…)."],
  "weak_negation":["There is no defining requirement that golf lacks physical exertion, skill, or competition."]},
  "consequent":"Golf is a sport."}],
  "Conc":["Golf is a sport."],
  "Ass":["There is no defining requirement that golf lacks physical exertion, skill, or competition."]}}
```

**パース後（評価LLMに渡る形）:**
```
[Turn 1] AG1 (main argument)
Golf involves significant physical exertion (e.g., playing 18 holes while carrying clubs
burns over 1,400 calories). Golf requires considerable skill (…). Golf is competitive (…).
(This relies on the assumption that There is no defining requirement that golf lacks
physical exertion, skill, or competition.) Therefore, Golf is a sport.
```

### 2.2 反論（attack：undercut / rebut）

反論は**発話本体の冒頭に一文の定型文**を足して「相手の何に反論しているか」を明示する。
攻撃対象の文（`target_statement`）を直接埋め込むだけの最小構成。ターン番号を参照しないので、
並行リトライがあっても常に正しい（§6の複雑なラベル機構は不要。§6参照）。

- `attack == "undercut"`（`target_field == "Ass"`、＝相手の仮定への反論）→ 冒頭 `I object to the opponent's assumption: "{target_statement}".`
- `attack == "rebut"`（`target_field == "Conc"`、＝相手の主張への反論）→ 冒頭 `I object to the opponent's claim: "{target_statement}".`

**生JSON（AG2 が Turn1 の前提を undercut）:**
```json
// turn メタ: type=defeat, attack=undercut, target_id=arg-…(Turn1),
//            target_field=Ass,
//            target_statement="There is no defining requirement that golf lacks physical exertion, skill, or competition."
{"Argument":{"rules":[{"antecedent":{
  "strong":[
    "To count as a sport …, the activity must involve enough physical exertion and consistently competitive play rather than mostly skill with large variance from external chance.",
    "Golf requires too little physical exertion to meet that bar, burning far fewer calories per hour than vigorous sports (e.g., soccer or basketball)."],
  "weak_negation":["Golf's low-exertion, less-consistently-competitive, chance-affected nature can be ignored when deciding whether it is a sport."]},
  "consequent":"Golf is not a sport."}], "Conc":["Golf is not a sport."], "Ass":[…]}}
```

**パース後（評価LLMに渡る形）:**
```
[Turn 2] AG2 (undercut — responds to [Turn 1])
I object to the opponent's assumption: "There is no defining requirement that golf lacks
physical exertion, skill, or competition". To count as a sport …, the activity must involve
enough physical exertion and consistently competitive play rather than mostly skill with
large variance from external chance. Golf requires too little physical exertion to meet that
bar, burning far fewer calories per hour than vigorous sports (e.g., soccer or basketball).
(This relies on the assumption that Golf's low-exertion, … nature can be ignored when
deciding whether it is a sport.) Therefore, Golf is not a sport.
```

> ラベル行 `(undercut — responds to [Turn 1])` は補助。核心は本体冒頭の
> `I object to the opponent's assumption: "…"` の一文で、これが「相手の〇〇という仮定に
> 反論がある」という当初イメージそのもの。`target_statement` を直接使うので堅牢。

### 2.3 ⚠️ 現在の古いログだと反論がこう潰れる（＝問題の実体）

`_speech_log` 修正前のログ（`{agent, argument}` のみ）では `attack`/`target_*` が無く、
反論冒頭文もラベルの種別も**発火しない**。同じ Turn 2 がこうなる：

```
[Turn 2] AG2:
To count as a sport …, the activity must involve enough physical exertion … Golf requires
too little physical exertion … (This relies on the assumption that …) Therefore, Golf is
not a sport.
```

→ 評価器には「独立した別の主張」に見え、**どのターンの何への反論かが完全に消える**。
main と反論が見分けられない。これを4軸すべて、とりわけ dialecticality/validity で不利に
働くと見ている。

---

## 3. no_schema / mad / free_debate：原文そのまま＋ラベル

自由記述なので機械抽出はしない（後付けLLM要約は新たなバイアス源なので採用しない）。
**本体は原文のまま**、ラベル行だけ揃える。

- **no_schema**：攻撃メタ情報があるので、ラベル側に攻撃対象を明示（本体には出ないため）。
  ```
  [Turn 2] AG2 (undercut — responds to [Turn 1] — attacks the premise "…")
  <no_schema の自由文をそのまま>
  ```
- **mad / free_debate**：`attack` は常に None。ラベルは種別のみ。
  ```
  [Turn 2] AG2:
  <自由文をそのまま。反論は地の文で "AG1 keeps arguing that … but that misses …" のように自然に書かれている>
  ```
  - 反論構造が本体の自然文に埋め込まれているため、そもそも失われる情報がない
    （schema/no_schema と違い attack 概念を持たない）。**無変更が正しい。**

---

## 4. 実装の要点（既に実装済みだが要点として）

- `build_eval_input` で `dialogue_history` を1回舐めて **id → ターン番号マップ** を作り、
  `target_id` を `[Turn X]` に解決する（[evaluation.py:120](../src/eval/evaluation.py#L120)）。
- schema の JSON 判定は `isinstance(argument, dict) and argument["Argument"]["rules"]`。
  文字列なら原文パス（no_schema/mad/free_debate）。
- 第三者の報告調（"The agent concluded …"）は使わず、一人称の言い切りにする。

---

## 5. 残課題（要対応・優先順）

1. **【必須】schema/no_schema の再生成。** 現行コードは正しいが、評価に使っている
   `sweep_all_topics_schema_20260706` / `no_schema_20260706` が修正前ログのため、
   反論パース（§2.2）が効いていない。再生成 → nano再評価で dialecticality/validity が
   どう動くか確認する。これが「schema が負けたのは表現力か論理か」の切り分けにも直結。
2. **【polish】weak_negation の文法。** 現状 `assumption that There is no …` のように
   `that` の直後に大文字＋完全文が続き硬い。`target_statement`/weak_negation は文単位なので、
   先頭小文字化 or `— namely, "…"` 形式にすると自然になる。
3. **【polish】複数 weak_negation の連結。** 現状 `;` 区切りで1つの `(This relies on
   the assumption that …)` に詰め込む。数が多いと読みにくいので、undercut の対象（`target_statement`
   と対応）だけは別枠にすると validity 判定がしやすい。
4. **【判断】status（justified/overruled/defensible）の描画。** ログには保存するが、
   評価 transcript に出すと schema/no_schema にしか無い情報が採点に影響し公平性を崩す。
   既定は非描画（[eval_transcript_format_spec.md §8](eval_transcript_format_spec.md) の未解決事項のまま）。

---

## 6. 【不採用】役割ラベル・リトライ番号・ト書き案

当初、`objects to [Turn X]` / `defends [Turn Y] against [Turn X]` のような**役割ラベル**、
リトライの `attempt k of n`、決着の**ト書き**（justified→"withstood every objection" 等）を
足す案を検討したが、**不採用**とする。

**理由**：
- これらはいずれも `target_id → ターン番号` の解決を必要とし、schema の並行リトライ生成では
  defeat と counter が互いの `id` を参照し合う（実ログで `objects to [Turn 5]` のような
  **前方参照バグ**が発生）。線形化を先に解かないと信頼できない。
- そもそも目的（「相手の何に反論しているか」を評価器に伝える）は、§2.2 の**本体冒頭の
  定型文**だけで達成できる。定型文は `target_statement`（攻撃された文そのもの）を直接
  埋め込むため、ターン番号を一切参照せず、並行リトライがあっても常に正しい。

**採用する最小構成**（＝当初イメージ「相手の〇〇という仮定に反論がある」）：
- undercut → `I object to the opponent's assumption: "{target_statement}".`
- rebut → `I object to the opponent's claim: "{target_statement}".`
- ラベル行は `[Turn N] AG (undercut — responds to [Turn X])` 程度の補助に留める
  （前方参照が起きても本体の定型文で対象が分かるので致命的でない）。

> 役割の区別・リトライ表示・決着ト書きは、この最小構成でスコアが十分改善しなかった場合の
> **次の一手候補**として保留する（線形化を解いてから）。

---

## 付録：JSON要素 → 出力 早見表

| 種別 | ラベル行 | 本体冒頭 |
|---|---|---|
| main (`type=main`) | `[Turn N] AG (main argument)` | （なし）`<grounds>. Therefore, <conc>.` |
| undercut (`attack=undercut`, `target_field=Ass`) | `[Turn N] AG (undercut — responds to [Turn X])` | `I object to the opponent's assumption: "{target_statement}". …` |
| rebut (`attack=rebut`, `target_field=Conc`) | `[Turn N] AG (rebut — responds to [Turn X])` | `I object to the opponent's claim: "{target_statement}". …` |
| no_schema 攻撃 | `[Turn N] AG (種別 — responds to [Turn X] — objects to the opponent's {claim\|assumption}: "…")` | 原文そのまま |
| mad / free_debate | `[Turn N] AG:` | 原文そのまま |
