# schema条件（nano統一版）が最下位になる原因の調査報告

> 対象: `logs/sweep_all_topics_{schema,no_schema,mad,free_debate}_nano_unified`
> （対話生成: 全4手法 gpt-5.4-nano に統一 / 評価器: gpt-5.4-mini）
> 期間: 2026-07-18 〜 2026-07-19

---

## 1. 問題設定

4手法（schema / no_schema / mad / free_debate）を同一条件（gpt-5.4-nano で対話生成、
gpt-5.4-mini で評価）で比較したところ、**schema が旧ルーブリック4軸・新ルーブリック
（Constructiveness）のいずれでもほぼ全ての設定ステップで最下位**だった。事前に
schema には「攻撃は相手の具体的な内容に踏み込め」という engage 指示を追加していたが、
それでも解消しなかった。

| 手法 | Coherence | Originality | Dialecticality | Validity | quality_avg | Constructiveness | Constraint Pres. |
|---|---:|---:|---:|---:|---:|---:|---:|
| no_schema | 5.788 | 4.514 | 5.801 | 4.894 | 5.248 | 6.824 | 7.402 |
| mad | 6.299 | 4.440 | 6.567 | 5.557 | 5.716 | 6.616 | 5.994 |
| free_debate | 6.614 | 4.790 | 6.264 | 5.796 | 5.867 | 6.456 | 7.268 |
| **schema（元データ）** | **5.445** | 4.487 | **5.360** | **4.462** | **4.939** | **6.197** | 7.092 |

（各手法とも全設定ステップ n=990 の平均。Constraint Preservation のみ mad が
最下位だが、これは別トピックであり本報告の対象外。）

schema だけがトークン消費も他手法の2〜3倍多いにもかかわらず低スコア、という
非効率な状態だった。

---

## 2. 調査の進め方

原因を「評価プロンプト側」「実装（生成）側」の両方から切り分けるため、以下の順で
仮説を1つずつ検証した。検証は各回 297件（99トピック × attempts{1,5,10} の3コンボ）
の小規模再実行で行い、効果が確認できた場合のみ全量（990件）で再確認する方針とした。

---

## 3. 検証した仮説と結果

### 3.1 プロンプト強化（engage 指示の具体化）

**仮説**: 既存の engage 指示（「相手の内容に踏み込め」）が抽象的すぎて、モデルが
「最初の rule で自分のスタンス由来の一般論を並べ、末尾に取ってつけた1行の橋渡し
rule を足すだけ」で形式的に満たしてしまっている（実ログで確認済み）。指示をより
具体的にすれば直る。

**実施内容**（[prompts.py](../src/agent/prompts.py) `_SCHEMA_OVERLAY`）:
- 「最初の rule の antecedent から相手の具体的内容に踏み込め、末尾の取ってつけた
  rule では代替できない」と明記。
- `attack_instruction` の `defeat` 分岐に、`counter` 分岐にはあった
  `<non_repetition>`（同じ攻撃の繰り返し禁止・可能なら can_defeat=NO にする逃げ道）
  を追加。

**結果**: quality_average **+0.05**（4.910 → 4.957）。ノイズ水準。

### 3.2 二段階生成（弱点の先出し）

**仮説**: `Attack.target`（攻撃対象の参照）と `Argument.rules`（反論の中身）が
1回の生成で並行に埋まるため、両者の間に構造的な依存関係がない。本体生成の前に
「狙う弱点」を一度言語化させる軽量な生成ステップを挟めば、対象への言及が本体の
推論の前提条件になる。

**実施内容**（[arguments.py](../src/agent/arguments.py) `_target_engagement_point`,
[prompts.py](../src/agent/prompts.py) `target_engagement_instruction`）:
- schema条件の攻撃生成（defeat/counter）の直前に、`chat_text` で「1〜2文で、
  狙う具体的な弱点を先に言語化させる」呼び出しを追加。
- その結果を `<target_engagement_point>` ブロックとして本体生成の指示に埋め込む。

**結果**: quality_average **+0.09**（4.910 → 4.997）。ノイズ水準。追加の生成コール
分だけトークン消費は増加（+20%）。

### 3.3 評価器のスタイルバイアス検証

**仮説**: 評価テキストへの変換（`_schema_utterance`）が定型文（
`"X. (This relies on the assumption that Y.) Therefore, Z."`）で、内容とは無関係に
「機械的で読みにくい」という理由で evaluator（gpt-5.4-mini）から減点されている
のではないか。

**検証方法**: 同一の対話ログ（v3の297件、対話生成は再利用しコストゼロ）に対して、
情報量を一切変えずに文体だけ自然にした別テンプレート（`Contrary to the assumption
that "...", ...`）を作り、同じログを2通りの文体で評価し直して比較した
（結果: [eval_style_bias_check.json](../logs/sweep_all_topics_schema_nano_unified_v3_engage/eval_style_bias_check.json)）。

**結果**: 差は **±0.02〜0.05**、ノイズ水準。**評価器のスタイルバイアスは否定された**。
schemaの低スコアは文体の問題ではなく、内容そのものの問題であることが確認できた。

### 3.4（参考・不採用）reasoning_effort の引き上げ

**背景**: [llm.py](../src/agent/llm.py) が GPT-5 系呼び出しで `reasoning_effort` を
一度も指定しておらず、CLAUDE.md 自身が明記する GPT-5 の挙動制御（temperature の
代わりに reasoning_effort/verbosity を使う）が適用されていなかったことが判明。
未指定時は OpenAI API 側の既定値 `medium` が使われる。

**実施内容**: schema条件の Argument 生成呼び出しのみ `reasoning_effort="high"` を
指定（他手法は `medium` のまま）。

**結果**: quality_average **+0.39**（4.910 → 5.303）、Dialecticality **+0.52**
（5.343 → 5.867、他手法の水準にかなり近づく）。これまでで唯一、ノイズ水準を
明確に超える効果だった。ただしトークン消費は倍近くに増加（+85%）。

**不採用の理由**: 「モデルに与える計算資源（推論予算）を増やせばスコアが上がる」
というのは、schema という手法設計そのものの優劣を検証する上で公平な比較になら
ない、との判断でコードには反映していない（他手法は `medium` のまま据え置き）。
実験結果としてのみ記録する。

### 3.5 履歴への攻撃メタデータ復元（実装バグ修正）

**発見**: `prompts.py` に `_HISTORY_FORMAT`（対話履歴のJSON構造をモデルに説明する
ブロック）が定義されているのに、どの SYSTEM プロンプトからも参照されておらず
完全に死んでいた。実装（[arguments.py](../src/agent/arguments.py)
`argument_message_content`）を確認すると、モデル自身の会話履歴（AIMessage）には
`ArgumentRecord.body`（`rules`/`Conc`/`Ass`）だけが渡され、**同じレコードが保持して
いる `attack`（rebut/undercut）・`target_id`・`target_statement` が履歴から完全に
欠落**していた。つまり schema 条件では、モデルは過去のターンを振り返っても
「どれが誰の何を攻撃したものか」を構造的には読み取れず、生の JSON 断片の並びから
推測するしかない状態だった。

**実施内容**:
- `argument_message_content` を、`id`/`round`/`phase`/`agent`/`status`/`attack`/
  `target_id`/`target_statement` を含む envelope + `Argument` 本体を返すよう修正
  （no_schema は従来通り自由記述テキストのまま、影響なし）。
- 死んでいた `_HISTORY_FORMAT` を schema 用 `ARGUMENT_SYSTEM` に組み込み、この
  envelope の読み方をモデルに説明。

**結果**: quality_average **+0.10**（4.910 → 5.007）。ノイズ水準。ただし追加の
API 呼び出しやトークン膨張を伴わない（+6%）、保持していたのに使っていなかった
情報を正しく渡すだけの修正であり、スコアへの影響とは独立に**正当なバグ修正**
として採用。

---

## 4. まとめ表（schema条件、attempts{1,5,10}の3コンボ、n=297）

| バリエーション | Coherence | Originality | Dialecticality | Validity | quality_avg | Constructiveness | 総トークン |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 元 | 5.380 | 4.493 | 5.343 | 4.423 | 4.910 | 6.173 | 65,995 |
| v2 プロンプト強化 | 5.453 | 4.577 | 5.283 | 4.503 | 4.957 | 6.303 | 77,778 |
| v3 二段階生成 | 5.423 | 4.643 | 5.397 | 4.530 | 4.997 | 6.197 | 79,313 |
| v5 履歴メタデータ修正 | 5.473 | 4.610 | 5.443 | 4.497 | 5.007 | 6.193 | 69,765 |
| （参考）v4 reasoning_effort=high | 5.643 | 4.950 | 5.867 | 4.757 | 5.303 | 6.503 | 121,990 |
| 参考: no_schema（同3コンボ） | 5.853 | 4.607 | 5.877 | 4.973 | 5.330 | 6.820 | 30,151 |

---

## 5. コードに反映した修正（現在の実装）

1. **`prompts.py` `_SCHEMA_OVERLAY`**: engage 指示を具体化（最初の rule から踏み込め、
   末尾の取ってつけた rule では代替不可）。
2. **`prompts.py` `attack_instruction`（defeat分岐）**: `<non_repetition>` を追加し
   counter 分岐と条件を揃えた。
3. **`prompts.py` `target_engagement_instruction` / `arguments.py`
   `_target_engagement_point`**: 攻撃本体生成の前に、狙う弱点を一段階先に
   言語化させる二段階生成を追加。
4. **`arguments.py` `argument_message_content`**: 履歴に attack/target メタデータ
   を含む envelope を渡すよう修正し、死んでいた `_HISTORY_FORMAT` を schema の
   SYSTEM プロンプトに組み込んだ。
5. **`nodes.py` `o_defeat_a` の docstring**: 実装（`generate_attack`）と矛盾していた
   「2回目以降は指示を変える」という記述を、実際の挙動（指示は不変・
   has_new_point で事後フィルタ）に合わせて修正。

`reasoning_effort` の変更（3.4）はコードには反映していない（実験結果としてのみ
本報告に記録）。

---

## 6. 考察

1. **評価器側のバイアスは否定できた**（3.3）。schema の低スコアは、評価テキストへ
   の変換や評価プロンプトの問題ではなく、gpt-5.4-nano が ASPIC+ 的な構造化
   スキーマの下で実際に生成する論証内容そのものの質に起因する。
2. **プロンプト・生成ワークフロー側の3つの介入（3.1, 3.2, 3.5）は、いずれも
   個別には妥当な設計判断・バグ修正でありながら、スコアへの効果はノイズ水準
   （+0.05〜+0.10）にとどまった**。3つとも「効くはず」という筋の通った仮説
   だったが、実測ではどれも決定打にならなかった。
3. **唯一、明確な効果が出たのは reasoning_effort の引き上げ（3.4, +0.39）**
   だった。これは、schema 条件が要求するタスク（複数 rule の連鎖を組み立てながら
   相手の具体的内容に踏み込む、という複合的な構成タスク）が、no_schema/mad/
   free_debate の単一自由記述より本質的に難しく、デフォルトの推論予算
   （medium）では nano クラスのモデルに対して不足している可能性を示唆する。
4. ただし本方針では「モデルの計算資源を増やす」ことを fair な比較の破壊とみなし、
   採用を見送っている。したがって **現時点のコードでは、schema の絶対スコアを
   大きく押し上げる修正は見つかっていない**。3.1/3.2/3.5 は妥当な改善として
   コードに残しているが、他手法とのギャップ自体はほぼ埋まっていない。

---

## 7. 今後の検討事項

- 3.1・3.2・3.5 を**同時に併用**した場合の相乗効果は未検証（個別には小さくても
  組み合わせで閾値を超える可能性はゼロではないが、これまでの傾向からは大きな
  期待はしにくい）。
- schema 条件のタスク自体が nano クラスのモデルにとって本質的に難しい複合タスク
  である可能性（3.4 の結果が示唆）をどう扱うか（ASPIC+ 構造は研究上の理由で
  維持する前提のため、モデル側の対応は本報告の範囲外）。
- 全量（990件）での確定再評価は、3.1/3.2/3.5 を統合した状態でまだ実施していない。
