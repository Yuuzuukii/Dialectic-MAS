# 評価用transcriptの現行パース方法

この文書は、4手法の実行ログを評価LLMへ渡す直前に
`experiments/eval/scoring/evaluation.py` が行う正規化を説明する。

## 1. 基本方針

- 全手法を `[Turn N] AGENT (...)` という共通ラベルで時系列に並べる。
- schemaだけは構造化JSONを決定論的に表示へ変換する。
- no_schema / mad / free_debateの発話本文は変更しない。
- パーサーは新しい根拠や反論文を生成せず、ログに存在する情報だけを表示する。
- 自然な散文に見せることより、rule・仮定・結論・応答関係の忠実な保持を優先する。
- 内部statusを「勝った／耐えた」などの評価的なト書きとして表示しない。

## 2. 共通ターンラベル

### 新しい主張

```text
[Turn 1] AG1 (new argument)
```

### schema / no_schemaの攻撃

```text
[Turn 2] AG2
(responding to [Turn 1]; declared target — conclusion: "...")
```

または、

```text
[Turn 2] AG2
(responding to [Turn 1]; declared target — defeasible assumption: "...")
```

`declared target`は、攻撃側が`target_statement`として宣言した文である。
パーサーは、その文が参照先の`Conc`または`Ass`に実在すると断定しない。
存在しない対象やfield違いを、別の文へ黙って置換して有効な攻撃に見せることもしない。

### mad / free_debate

先頭以外はプロトコル上、直前の相手ターンを見た上で生成されるため、次のように示す。

```text
[Turn 2] AG2 (responding to [Turn 1])
```

本文はログの自然文をそのまま使う。

## 3. schema Argumentの表示

入力は次の構造を持つ。

```json
{
  "Argument": {
    "rules": [
      {
        "antecedent": {
          "strong": ["..."],
          "weak_negation": ["..."]
        },
        "consequent": "..."
      }
    ],
    "Conc": ["..."],
    "Ass": ["..."]
  }
}
```

評価表示では、ruleごとに次の要素を保持する。

```text
Reasoning:
Step 1:
  Given:
  - <strong premise>
  Defeasible assumptions:
  - <weak_negation item>
  Supports: <intermediate consequent>

Step 2:
  Uses: result from Step 1
  Given:
  - <new strong premise>
  Defeasible assumptions:
  - <weak_negation item>
  Final conclusion: <final consequent>
```

### strong

`antecedent.strong`は`Given`に原文のまま列挙する。
描画側でピリオドを追加したり、先頭文字の大小を変えたりしない。

### weak_negation

各ruleの`weak_negation`は、そのrule内の`Defeasible assumptions`に置く。
全rule分を一つの長い括弧へまとめない。これにより、どの推論段階がどの仮定に
依存するかを保持する。

### consequent

非末尾ruleのconsequentは`Supports`、末尾ruleは`Final conclusion`として表示する。
モデルが先頭に埋め込んだ`Therefore,` / `Thus,` / `Hence,`だけは、表示ラベルと
重複するため除く。それ以外の本文は変えない。

### rule連鎖

先行ruleのconsequentと後続ruleのstrongが完全一致する場合、同じ文を二重表示せず、
次のように参照する。

```text
Uses: result from Step 1
```

先行consequentと一致しないstrongは省略しない。未来のruleや同じruleのconsequentと
偶然一致するだけのstrongも、先行結果として扱わない。

## 4. 攻撃本文へ文を追加しない理由

以前はschema攻撃の先頭に、パーサーが次の文を追加していた。

```text
I disagree with your conclusion that "...".
Your premise that "..." does not hold.
```

この方式には以下の問題があった。

- `target_statement`が参照先に存在しなくても、本物の結論・前提であると断定してしまう。
- 生成本文自身の`The target's ...`と重複する。
- schemaだけに、エージェントが実際には生成していない自然文を加える。

現在は攻撃対象を共通ラベルの`declared target`へ移し、schema本文にはrulesだけを表示する。

## 5. スレッド境界とintegrated rule

次のmain argumentが実在するときだけ、中立的な境界を挿入する。

```text
— The preceding exchange has ended. A new argument follows.
```

`justified` / `overruled` / `defensible`という内部statusや、
`withstood every objection`のような勝敗を示す文は評価者へ渡さない。

`include_integrated_rules=True`の場合だけ、対応する共有ルールを境界へ追加する。
Constructivenessは`include_integrated_rules=False`で構築するため、共有ルール本文を見ない。
Constraint Preservationはtranscriptではなく、別ブロックのintegrated rulesを使用する。

## 6. パーサーが修復しないもの

以下は生成内容またはプロトコル出力の品質であり、評価前のパーサーが黙って直してはならない。

- `target_statement`が参照先Argumentに存在しない。
- `target_field`が`Conc` / `Ass`の実際の所在と一致しない。
- ruleの根拠が対象へ噛み合っていない。
- weak_negationの文面が、argumentの意図と意味的に矛盾している。
- `The target`などのメタ表現が過剰に繰り返されている。
- 根拠・結論自体が冗長、不正確、または論理的に弱い。

これらをパーサーが要約・言い換え・置換すると、提案手法の実際の出力品質を隠すためである。

## 7. 関連実装

- `evaluation.py::_schema_utterance`: schema rulesの表示
- `evaluation.py::_turn_label`: 応答関係とdeclared target
- `evaluation.py::build_eval_input`: 時系列化、スレッド境界、integrated rule制御
- `evaluation_rubrics.py::evaluate_rubrics`: ConstructivenessとConstraint Preservationの入力分離
- `tests/unit_tests/test_eval_transcript_format.py`: 正準表示の単体テスト
