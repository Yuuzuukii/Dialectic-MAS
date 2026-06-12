# 統合アルゴリズム比較メモ

## 対象

- 参考文献: `/Users/yuzuki/Desktop/大学院書類/研究/kido_kurihara.pdf`
- 比較対象: `docs/protocol_revision_plan.md:1` の修正計画を適用した後の想定実装

## 結論

修正計画適用後の想定実装は、現状より論文に近づく。  
ただし、**なお論文そのものの論理アルゴリズムとは一致しない**。

近づく点は次の通り。

- 終了条件が `final answer` 生成ではなく **`main argument` の justified** へ寄る
- 攻撃手法が `rebut` のみに整理され、論文の `main argument` の tenability 評価に近づく
- 統合フェーズが
  - `generalization`: warrant から判断基準を抽出
  - `integration`: 判断基準を統合して合意核を作成
  - `answer`: 最終回答を生成
  という形で再整理される

それでも差が残る点は次の通り。

- 論文は clause / implication に対する **specialization / generalization の論理計算**
- 想定実装は `Argument` スキーマを使っても、依然として **LLM プロンプトによる生成**
- 論文は統合結果から **新しい main argument を立て、その justified を評価**
- 想定実装計画では `answer` が **最終回答生成** のままで、再度 argumentation に戻すとは明記されていない

したがって評価としては、

- **論文の流れにはかなり近づく**
- **ただしアルゴリズムの中核は依然として別物**

が妥当である。

---

## 論文アルゴリズムの要点

論文の中心は、対立する 2 つの立場 `A`, `B` と背景知識 `Γ` から、

1. `A` を specialize して `α` を得る
2. `B` を specialize して `β` を得る
3. `α` と `β` の両方を説明できる `C` を generalize で得る
4. `C` をもとに新しい argument を立てる
5. その `main argument` が rebut 不能になれば justified とみなす

という流れで、新しい解を構成する点にある。

### 1. specialization がしていること

論文では specialization は単なる抽象化ではない。  
元の主張を、背景知識を使って **統合可能な形へ論理的に変形する操作**である。

アルゴリズム 1, 3 の役割は概念的には次のように読める。

- `A` から導ける中間表現 `α` を作る
- `B` から導ける中間表現 `β` を作る
- ただし背景知識 `Γ` だけから自明には出てこない
- 後段の generalization で結び付けやすい表現に寄せる

camera 例では、これは元の warrant を、そのままの対象物記述ではなく、  
`user-friendly` や `long battery life` のような、合意核へ接続できる基準へ変換する働きを持つ。

### 2. generalization がしていること

論文の generalization は「2 つの要素をよい感じにまとめる」ことではない。  
`α` と `β` の両方を説明できる clause `C` を **含意条件付きで構成する操作**である。

概念的な条件は次の形で表せる。

- `{C} ∪ Γ |= α`
- `{C} ∪ Γ |= β`

つまり `C` は、

- 片方の specialized warrant を説明できる
- 他方の specialized warrant も説明できる

という共通基盤である。

### 3. justified がしていること

論文では、プロトコルの終了条件は `final answer` の文字列出力ではない。  
終了条件は **`main argument` が justified されること**である。

論文の定義では、`A` が justified であるとは、

- `A` を defeat する argument が存在しない
- あるいは `A` を defeat する argument があっても、それが strict defeat される

場合である。

今回の修正計画では、運用上の定義として

- justified = `main argument` に対して `rebut` できない

と置いている。  
これは論文の厳密な defeat semantics を簡略化したものだが、**終了条件を argument の tenability に戻す**点では方向が合っている。

---

## 修正計画適用後の想定統合フェーズ

修正計画では、統合フェーズの用語は次のように整理される。

- `generalization`: warrant から判断基準を抽出
- `integration`: 判断基準を統合して合意核を作成
- `answer`: 最終回答を生成

また、全出力を `Argument` スキーマ準拠に寄せる計画になっている。`docs/protocol_revision_plan.md:1`

### 想定される処理

#### 1. `extract_warrants`

- 各 `main argument` の warrant を取り出す

これは論文の「mutually defeating arguments の warrant を材料にする」という前提と整合的である。

#### 2. `generalization`

- warrant から、統合に使う判断基準を抽出する

これは論文でいう specialization に**役割上は近い**。  
ただし論文では clause の変形であり、想定実装では `Argument` スキーマに沿っても **LLM に判断基準を記述させる**方式である。

#### 3. `integration`

- 両者の判断基準を統合し、合意核を構築する

これは論文の generalization に**目的上はかなり近い**。  
ただし、論文のように

- least generalization
- generalized subsumption
- entailment 条件

で計算するわけではなく、プロンプトに基づく生成である点が本質的に異なる。

#### 4. `answer`

- 合意核から最終回答を生成する

ここは論文との重要な分岐点である。  
論文では、合意核を支える **新しい main argument** が立てられ、それが justified かどうかで評価される。  
修正計画では、`answer` は名前の通り **最終回答生成** の段階として整理されている。

つまり、想定実装は

- 合意核を作る
- そこから解答を出す

までは論文に近いが、

- その解答を新しい `main argument` として再投入して justified を確認する

とはまだ書かれていない。

---

## 一致する点

### 1. 終了条件の方向

- 論文: `main argument` が justified された時にプロトコルが終わる
- 想定実装: `main argument` が justified された時にプロトコルが終わる

ここは現状より明確に論文へ近づいている。

### 2. warrant 起点で統合する点

- 論文: 互いに対立する argument の warrant を材料に新しい解を作る
- 想定実装: warrant から判断基準を抽出し、統合して合意核を作る

この流れは対応している。

### 3. 合意核を経由して新しい解を作る点

- 論文: specialized warrant を generalize して新しい解を構成する
- 想定実装: `generalization` と `integration` を経て合意核を作り、`answer` に接続する

処理段階の役割分担は、かなり整合する。

### 4. rebut 中心の設計へ寄る点

- 論文の negotiation 例でも、最終的な tenability は rebut 関係を軸に読むのが自然
- 想定実装も `undercut` を削除し、`rebut` に統一する

これは論文の複雑な defeat 定義を簡略化しているが、設計意図は理解しやすくなる。

---

## 一致しない点

### 1. `generalization` は論文の specialization ではない

修正計画後の `generalization` は「warrant から判断基準を抽出する」工程である。  
これは役割としては論文の specialization に近いが、内容は別である。

論文の specialization は、

- resolution
- refinement operator
- generalized subsumption

を使う論理操作である。

一方、想定実装は

- warrant を読み
- そこから判断基準を `Argument` スキーマで表現させる

という生成処理である。  
**論理的に specialze した clause を計算しているわけではない**。

### 2. `integration` は論文の generalization を保証しない

論文の generalization では、合意核 `C` が

- `{C} ∪ Γ |= α`
- `{C} ∪ Γ |= β`

を満たす必要がある。

修正計画後の `integration` は、`Argument` スキーマになっても、

- 片方の判断基準を本当に説明できるか
- 他方の判断基準も説明できるか

を機械的には検証しない。  
したがって、**意味的にもっともらしい合意核**は作れても、**論文の意味での generalization** にはならない。

### 3. 背景知識の利用が計算ではなく条件文のまま

論文では背景知識 `Γ` / `Δ` は、

- specialization の導出
- generalization の成立判定

に直接入る。

修正計画では `Argument` スキーマ化の方針はあるが、背景知識を

- entailment check
- refinement search
- candidate filtering

に使うとは書かれていない。  
従って、背景知識はなお **推論器の入力** ではなく **LLM プロンプトの文脈** に留まる可能性が高い。

### 4. `answer` が新しい `main argument` になるとは限らない

論文では、統合で得た核から **新しい main argument** を作る。  
それが rebut 不能となって初めて justified される。

修正計画では `answer` は依然として「最終回答を生成」である。  
この書き方だと、`answer` の出力は

- concrete solution

であって、

- rebut 対象となる `Argument`
- warrant を伴う新たな `main argument`

になるとは読めない。

ここは論文との大きな差分である。

### 5. justified の定義は論文の簡略版

論文の justified は defeat / strict defeat を含む再帰的な argumentation semantics で定義される。

修正計画では

- justified = `main argument` に対して `rebut` できない

としている。  
これは運用上わかりやすいが、論文の定義よりかなり強く単純化されている。

---

## 対応関係の整理

### 論文の処理

1. main argument 同士が対立する
2. どちらも justified でないことが確認される
3. 互いの warrant を対象に specialization する
4. specialized warrant を generalization する
5. そこから新しい main argument を作る
6. その main argument が justified される

### 修正計画適用後の想定処理

1. main argument 同士が対立する
2. rebut のやり取りで justified / defeated を判定する
3. warrant を抽出する
4. `generalization` で判断基準を抽出する
5. `integration` で合意核を作る
6. `answer` で最終回答を生成する

### 差分の要約

- 論文は **判断基準の統合結果を新しい argument に戻す**
- 想定実装は **判断基準の統合結果を answer に変換して終える**

この差は残る。

---

## プロンプト設計との対応評価

### `generalization`

評価: **役割対応はあるが、アルゴリズム不一致**

- 良い点:
  - warrant から統合可能な判断基準を作る意図は論文の specialization に近い
- 足りない点:
  - clause 変形ではない
  - entailment 制約がない
  - background knowledge を使った refinement ではない

### `integration`

評価: **狙いは近いが、論理保証がない**

- 良い点:
  - 両者を受け入れられる合意核を構成する目的は論文の generalization に近い
- 足りない点:
  - least generalization ではない
  - generalized subsumption を使わない
  - 片側・他側の判断基準を本当に説明できる保証がない

### `answer`

評価: **論文とはなお距離がある**

- 良い点:
  - 合意核から新しい解を具体化する意図は論文と近い
- 足りない点:
  - 生成物が `main argument` ではない可能性が高い
  - justified 判定の対象に戻す設計が見えていない

---

## まとめ

修正計画を適用すると、統合フェーズは

- warrant を基点にする
- 判断基準を抽出する
- 合意核を構成する
- justified を終了条件にする

という点で、論文の構成にかなり近づく。

ただし、論文の本質は

- clause レベルの specialization
- entailment による generalization
- 新しい main argument の justified 判定

にある。  
修正計画後も、これらが

- `Argument` スキーマ付きの LLM 生成
- 明示的な論理検証なし
- `answer` で最終回答を返す設計

のままであれば、**論文のアルゴリズムを実装したことにはならない**。

したがって最終評価は、

- **現状よりは論文に近い**
- **しかし論文準拠とはまだ言えない**

である。
