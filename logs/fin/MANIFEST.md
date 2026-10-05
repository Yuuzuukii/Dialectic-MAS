# logs/fin — 決定版ログ（2026-10-06 作成）

元のフォルダからのコピー。元の `logs/experiment_*` は変更していない。

## ログの出どころ（各 turns10/15/20/25/30 × 5トピック × 3回 = 手法ごと75本、計300本）

| 手法 | 出どころ | 最終回答の作り方 |
|---|---|---|
| schema | experiment_20261004_165642 | 議論全体を中立に統合 → 回答（経路B）、justified は経路A |
| no_schema | experiment_20261004_165642 | 同上 |
| mad | experiment_20261004_165642 | 元のまま（`original_unchanged`） |
| free_debate | experiment_20261002_052448 | 旧方式: 両者の最後の発言から統合ルール1個 → 回答 |

- schema / no_schema の議論本体は experiment_20261004_035427 のもの（165642 は最終回答だけ作り直したコピー）。
- mad の議論本体は experiment_20261002_052448 のもの。

## 評価結果（`turns<N>/eval_result/`、手法ごとに上の出どころの値を1ファイルに統合）

- `atomic_coverage/atomic_coverage_comparison.json`
- `rebuttal_defeat/rebuttal_defeat_comparison.json`（`rebuttals/` に反論ごとの判定）
- `svi_mini/questionnaire_result/svi_comparison.json`（gpt-5.4-mini。SVI の評価はこれだけで、nano は含めない）

## 注意

- 評価の設定は手法間で完全にはそろっていない可能性がある。
  - schema / no_schema / mad の `svi_mini` は、`MODEL=gpt-5.4-mini`、統合ルールを評価者に見せない設定（`EVAL_INCLUDE_INTEGRATED_RULES=0`）で実行したコマンドを渡した。
  - free_debate の `svi_mini` は、同じ設定で再評価したもの（旧方式の最終回答）。
  - `atomic_coverage` と `rebuttal_defeat` の評価モデルと設定は未確認（既定の `.env` の MODEL=gpt-5.4-nano だった可能性が高い）。free_debate は experiment_20261002_052448 の既存の評価。
- 次の評価は含めていない（手法間で揃うログが無いため）: `dialogue_coverage`、`dialogue_tree`、`svi_repeat`（experiment_20261002_052448 にのみある）。nano の SVI（`svi`）は削除した。
- 評価ファイルにモデル名は記録されない。
- フォルダ名は CLAUDE.md の `experiment_<日時>` 規則ではなく、指示により `fin`。

## 直下のグラフ

- `atomic_coverage/`: 手法別・トピック別の棒グラフ（全ターン数を合算、各手法75本）
- `rebuttal_defeat.png` / `.csv`: 設定ターン数ごとの、反論がまだ効く度合い
- `svi_mini/`: mini の SVI の合意スコア C_k（k=0〜0.5、全ターン数を合算）と、AG1・AG2 の満足度の差
