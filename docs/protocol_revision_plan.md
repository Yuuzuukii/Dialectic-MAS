# プロトコル改修計画書

## 目的

以下の仕様変更を `Dialect-MAS` に反映する。

1. プロトコルの終了条件を変更する  
   - 変更前: 主張が defeat された時、または最終回答が生成された時
   - 変更後: 主張 (`main argument`) が justified された時
2. 攻撃手法を変更する  
   - 変更前: `rebut`, `undercut`
   - 変更後: `rebut` のみ
3. 統合フェーズの出力スキーマを変更する  
   - 変更前: 自由記述
   - 変更後: `Argument` スキーマ
4. 統合フェーズの終了点を変更する
   - 変更前: 合意核から最終回答まで生成する
   - 変更後: 合意核に相当する「買う条件」の生成で終了する

## 統合フェーズの用語整理

統合フェーズのメソッド名は以下のように扱う。

- warrant から判断基準を抽出 → `generalization`
- 判断基準を統合して合意核を作成 → `integration`
- 統合フェーズでは `answer` を生成しない
- `integration` の出力は、新しいスタンスへ追加可能な「買う条件」とする

## 対象ファイル

- `src/agent/graph.py`
- `src/agent/prompt.py`
- `main.py`
- 必要に応じて `src/agent/schema/outputs/schema.py`

## 前提

- 統合フェーズで使う `Argument` スキーマの正確な定義は、非表示スライドの内容に従う。
- 実装前に、少なくとも以下を明確化する必要がある。
  - justified / defeated の厳密な判定条件
  - `Argument` スキーマの必須項目
  - 統合後に新ルールをどちらのスタンスへ追加するか、または共有スタンスとして扱うか

## 修正方針

### 1. 終了条件の変更

- `graph` の終了条件を「主張 (`main argument`) が justified された時」のみに統一する。
- `justified` は「`main argument` に対して `rebut` できない状態」と定義する。
- `defeated` は「`main argument` を唱えた側が反論できない状態」と定義する。
- `defeated` はその議論スレッドの終了条件ではあるが、プロトコル全体の終了条件ではない。
- `justified` 到達後は統合フェーズに進み、「買う条件」を生成した時点で終了する。
- 最終回答の生成は統合フェーズでは行わず、後続の通常の main argument 生成に委ねる。

### 2. 攻撃手法の制限

- `DEFEATING_ARGUMENT` プロンプトから `undercut` を削除する。
- attack method は常に `rebut` であることを明記する。
- `undercut` 前提の制御ロジックが残っていれば削除または置換する。

### 3. 統合フェーズ出力のスキーマ化

- `GENERALIZATION`, `INTEGRATION` の各プロンプト出力を `Argument` スキーマ準拠に変更する。
- 自由記述を許可している箇所を廃止し、JSON のみを出力する制約へ統一する。
- `INTEGRATION` の出力は、具体的な製品名や回答文ではなく、「もし X なら買う」のような判断条件のルールとして表現する。
- 統合で得られた新ルールは、次の main argument 生成時に stance へ追加して使う。

## 実施タスク

### タスク1: 現行フローの整理

- `src/agent/graph.py` の状態遷移を棚卸しする。
- 以下のノードの役割を整理する。
  - `ag1_main`
  - `ag2_attack_ag1`
  - `ag1_counter_ag2`
  - `ag2_main`
  - `ag1_attack_ag2`
  - `ag2_counter_ag1`
  - `extract_warrants`
  - `generalize`
  - `integrate`
  - `early_finish`
  - `finish_with_error`

### タスク2: justified 終了条件への変更

- 各反論ノードの分岐条件を見直す。
- `main argument` に対して `rebut` できないと判定された時点を `justified` として扱う。
- `defeated` はスレッド終了として扱い、必要に応じて次フェーズへ遷移させる。
- `extract_warrants -> generalize -> integrate` の経路を、`justified` 到達後の終端経路として整理する。
- 統合後は `answer` を生成せず終了する。
- 終了時に最低限保持すべき情報を定義する。
  - `dialogue_history`
  - justified された `main argument`
  - justified に至った判定時点
  - 最終 rebut
  - 統合で生成された「買う条件」

### タスク3: 不要状態の削減

- 統合フェーズを廃止する場合、`State` から以下を削除する。
  - `warrant_result`
  - `generalization_result`
  - `integration_result`
  - `answer`
  - `synthesis`
- 併せて、不要な route 関数とノード定義を削除する。
- 統合フェーズを維持する場合は、`justified` / `defeated` を明示的に表現する状態項目と、新ルール保持用の状態項目の追加を検討する。

### タスク4: 攻撃手法を rebut のみに変更

- `src/agent/prompt.py` の `DEFEATING_ARGUMENT` を修正する。
- 修正内容:
  - `undercut` の説明削除
  - `attack` は `rebut` のみと記載
  - 出力 JSON 内でも `attack: rebut` に固定
- `src/agent/graph.py` 内の `undercut` 前提ロジックを確認する。
- `_is_rebut_without_weak_negation(...)` の必要性を再評価する。

### タスク5: 統合フェーズスキーマ変更

- 統合フェーズでは、以下のプロンプトを `Argument` スキーマ準拠に変更する。
  - `GENERALIZATION`
  - `INTEGRATION`
- すべての出力を `Output only JSON` に統一する。
- 必要なら `src/agent/schema/outputs/schema.py` に対応スキーマを追加する。
- `INTEGRATION` は「買う条件」を rule として返す仕様にする。
- `ANSWER` プロンプトは統合フェーズから切り離すか、未使用化する。

### タスク6: 統合ルールの stance 反映

- `integration` の出力から、新しい rule を stance に追加する仕組みを設計する。
- 追加先の候補:
  - AG1 / AG2 の双方に同じ rule を追加
  - 共通 stance / shared context として保持
- 次回の main argument 生成時に、既存 stance と統合 rule の両方を system prompt に含める。
- 追加された rule が重複しないように正規化方針を決める。

### タスク7: API 出力調整

- `main.py` の `public_result(...)` を新仕様に合わせて調整する。
- `synthesis` を返さない場合はレスポンス構造を更新する。
- 返却候補:
  - `dialogue_history`
  - `justified_argument`
  - `justification_status`
  - `final_rebuttal`
  - `integrated_rule`
  - `error`

### タスク8: 動作確認

- rebut 成立時に即終了することを確認する。
- 反論ループが不要に継続しないことを確認する。
- `undercut` が生成されないことを確認する。
- 統合フェーズの出力が `Argument` スキーマ準拠の「買う条件」になっていることを確認する。
- 統合で生成した rule が stance に追加され、次の main argument 生成で参照されることを確認する。
- API レスポンスが新仕様に一致することを確認する。

## 想定リスク

- justified / defeated の定義が曖昧なままだと、終了判定が実装依存になる。
- `Argument` スキーマが未確定だと、統合フェーズの修正が暫定実装になる。
- `undercut` を除外すると、既存のプロトコル制御ロジックに不要部分が残る可能性がある。
- 統合 rule の stance 追加先が曖昧だと、次回の議論生成結果が不安定になる。

## 実装順序

1. justified / defeated 判定仕様の確定
2. `graph.py` の状態遷移修正
3. `prompt.py` の `DEFEATING_ARGUMENT` 修正
4. `undercut` 依存ロジックの削除または置換
5. `GENERALIZATION` / `INTEGRATION` のスキーマ対応
6. 統合 rule の stance 反映方式を実装
7. `main.py` のレスポンス調整
8. 動作確認

## 確認事項

- justified は「`main argument` に対して `rebut` できない時」でよいか
- defeated は「`main argument` を唱えた側が反論できない時」でよいか
- defeated はプロトコル終了ではなく次フェーズ遷移条件として扱う認識でよいか
- 統合で生成した rule は AG1 / AG2 の双方に追加するか、共通 stance として持つか
- 非表示スライドの `Argument` スキーマ定義を実装時に参照可能か
