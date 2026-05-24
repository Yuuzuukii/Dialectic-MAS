# 評価スクリプト実装計画

## 目的

`/Users/yuzuki/Desktop/dialectical-agent/` の評価処理を、Dialect-MAS の対話結果に適用する。

参照先リポジトリは既存研究として扱うため、評価プロンプトの内容は変更しない。変更するのは、Dialect-MAS 側の出力を参照先評価関数が期待する入力形式へ変換する部分のみとする。

## 参照する評価処理

参照先リポジトリの主な評価関数は以下。

- `/Users/yuzuki/Desktop/dialectical-agent/evaluation.py`
  - `evaluate_with_llm(response, evaluator_model)`
  - `compute_final_evaluation(scores, values_info)`
- `/Users/yuzuki/Desktop/dialectical-agent/value_detector.py`
  - `ValueDetector.analyze_reasoning(...)`

最初の実装では、LLM による 4 軸評価である `evaluate_with_llm()` の再利用を優先する。

## 評価入力の対応

参照先の `evaluate_with_llm()` は、以下の辞書を入力として期待している。

```python
{
    "question": str,
    "initial_opinion": str,
    "counterarguments": str,
    "final_synthesis": str,
}
```

Dialect-MAS の `result/dialogue_result.json` から、次のように対応づける。

| 参照先フィールド | Dialect-MAS 側の値 |
| --- | --- |
| `question` | `result["question"]` |
| `initial_opinion` | `dialogue_history` 内の最初の `type == "main"` の主張 |
| `counterarguments` | `dialogue_history` 内の `type in {"defeat", "counter"}` の主張を時系列で結合 |
| `final_synthesis` | `justified_argument`。なければ `final_rebuttal`、それもなければ最後の主張 |

この対応づけにより、参照先の評価プロンプトを変更せずに Dialect-MAS の対話結果を評価できる。

## 追加するファイル

### `src/evaluation/adapter.py`

Dialect-MAS の出力を、参照先評価関数の入力形式に変換する。

主な責務:

- `dialogue_result.json` の読み込み
- `dialogue_history` 内の argument JSON の整形
- `question / initial_opinion / counterarguments / final_synthesis` 形式への正規化
- 将来的な `per-argument` 評価に備えた共通処理の分離

想定する関数:

```python
def load_dialogue_result(path: str) -> dict:
    ...


def normalize_for_reference_evaluator(result: dict) -> dict:
    ...


def normalize_argument_text(argument: str | dict | None) -> str:
    ...
```

### `src/evaluation/model_adapter.py`

参照先の `evaluate_with_llm()` は evaluator model に以下のインターフェースを期待している。

```python
evaluator_model.invoke(prompt)
evaluator_model.model
```

Dialect-MAS 側の LLM 実装と接続するため、薄い adapter を用意する。

```python
class EvaluatorModelAdapter:
    def __init__(self, llm, model: str):
        self.llm = llm
        self.model = model

    def invoke(self, prompt: str) -> str:
        result = self.llm.invoke(prompt)
        return result.content if hasattr(result, "content") else str(result)
```

### `scripts/evaluate_dialogue_result.py`

CLI から評価を実行するスクリプト。

主な責務:

- 入力 JSON の指定
- 参照先リポジトリパスの指定
- 参照先 `evaluation.py` の読み込み
- Dialect-MAS 出力の正規化
- `evaluate_with_llm()` の実行
- 評価結果の保存

想定コマンド:

```bash
uv run python scripts/evaluate_dialogue_result.py \
  --input result/dialogue_result.json \
  --reference-repo /Users/yuzuki/Desktop/dialectical-agent \
  --output result/evaluation_result.json
```

## 評価モード

### 1. `final` モード

対話全体を 1 件の推論結果として評価する。

最初に実装するモードとする。

入力対応:

- `initial_opinion`: 最初の main argument
- `counterarguments`: defeat / counter argument の列
- `final_synthesis`: justified argument

### 2. `per-argument` モード

各主張を単位として評価する。

将来的に追加する。参照先プロンプトは変更せず、各評価単位を `initial_opinion / counterarguments / final_synthesis` に写像する。

例:

- ある `main` argument を `initial_opinion` とする
- その main に対する `defeat` / `counter` を `counterarguments` とする
- 最終的に正当化された主張、またはその時点の到達点を `final_synthesis` とする

## 出力形式

最初の実装では JSON 出力を基本とする。

```json
{
  "source": "result/dialogue_result.json",
  "mode": "final",
  "normalized_input": {
    "question": "...",
    "initial_opinion": "...",
    "counterarguments": "...",
    "final_synthesis": "..."
  },
  "scores": {
    "clarity": 8,
    "coherence": 7,
    "originality": 6,
    "dialecticality": 8,
    "evaluator_model": "..."
  }
}
```

複数結果を比較する必要が出た場合は、後から CSV 出力を追加する。

## 実装手順

1. `src/evaluation/adapter.py` を作成する。
2. `result/dialogue_result.json` を参照先入力形式へ変換できるようにする。
3. `src/evaluation/model_adapter.py` を作成する。
4. `scripts/evaluate_dialogue_result.py` を作成する。
5. 参照先 `evaluation.py` を import し、`evaluate_with_llm()` をそのまま呼ぶ。
6. `result/evaluation_result.json` に評価結果を保存する。
7. 変換処理の単体テストを追加する。
8. 必要に応じて `per-argument` モードを追加する。

## テスト方針

### 単体テスト

対象:

- `normalize_argument_text()`
- `normalize_for_reference_evaluator()`

確認すること:

- `dialogue_history` から最初の main argument を抽出できる
- defeat / counter argument を時系列で結合できる
- `justified_argument` を `final_synthesis` として使える
- `justified_argument` がない場合に fallback できる

### 手動確認

以下のコマンドで評価を実行し、JSON が保存されることを確認する。

```bash
uv run python scripts/evaluate_dialogue_result.py \
  --input result/dialogue_result.json \
  --reference-repo /Users/yuzuki/Desktop/dialectical-agent \
  --output result/evaluation_result.json
```

確認項目:

- `normalized_input` に空文字が入っていない
- `scores` に 4 軸の値が入っている
- 参照先の評価プロンプトを変更していない

## 注意点

参照先の `evaluate_with_llm()` は、LLM の返答を `json.loads(raw)` で直接解析する。そのため、LLM が JSON 以外のテキストを返すと評価に失敗する。

ただし、プロンプト内容は変更しない方針のため、まずは以下の対応に留める。

- 評価失敗時に raw response を保存する
- 失敗した入力も保存する
- プロンプトの文言は変更しない

## 変更しないもの

- `/Users/yuzuki/Desktop/dialectical-agent/evaluation.py` の評価プロンプト
- 評価軸
  - `clarity`
  - `coherence`
  - `originality`
  - `dialecticality`
- スコア基準
- 参照先研究リポジトリ内の既存ロジック

## 将来的な拡張

- `per-argument` 評価
- 複数 `dialogue_result.json` の batch 評価
- CSV 出力
- `ValueDetector` による価値・異常検出の併用
- `compute_final_evaluation()` による最終ラベル付け
