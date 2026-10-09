# logs/real_final マニフェスト

SVI 合意スコア（C_k）の折れ線グラフ（`eval_result/svi/consensus/svi_consensus_k_lines.png`）に使ったログと、
その評価結果をまとめたもの（2026-10-09 作成）。元のフォルダは変更していない（コピーのみ）。

## 構成

```
real_final/
├── turns<N>/                        N = 10, 15, 20, 25, 30（max_dialogue_turns）
│   ├── raw_dialogue/<カテゴリ>/<トピック>/<NN>_<method>_<日時>.json   5手法 x 5トピック x 3回 = 各75本（計375本）
│   └── eval_result/<指標>/*.json    5手法をまとめたもの（下表）
├── eval_result/
│   ├── svi/                         svi_comparison_5methods.json, consensus/（折れ線・差の棒グラフ・csv）
│   └── used_turns/                  使用ターン数の折れ線と csv
├── argument_network.html            schema / no_schema の議論の木のビューア（150本。他3手法は含まない）
├── SUMMARY.md                       集計表（make_summary.py が、このフォルダのデータだけから生成）
├── make_summary.py
└── MANIFEST.md
```

## ログの出どころ

| 手法 | 元のフォルダ | 本数 |
|---|---|---|
| schema | logs/experiment_20261009_103401 | 75 |
| no_schema | logs/experiment_20261009_103401 | 75 |
| free_debate | logs/final（元は logs/fin） | 75 |
| mad | logs/final（元は logs/fin） | 75 |
| mad_synthesis | logs/final（元は logs/experiment_20261006_175518） | 75 |

schema / no_schema は、Prakken & Sartor の論証の作り方、外部 judge による攻撃の成立判定、strictly defeat の判定、
proponent の再試行（ターン数に数える）を入れた実装での実行（トピック5件: artificial_intelligence, animal_dissection,
election_day, alternative_energy, american_socialism / 3回 / 各ターン設定）。
logs/final にある旧実装の schema / no_schema は、入れていない。

## 評価結果の出どころ

評価は、新しく回し直したものと、既存のものを、そのまま集めたもの（5手法分を、ここでは再評価していない）。
各 JSON は、手法ごとの元の結果を、この5手法の分だけ取り出して連結した（`detail` を連結、`summary` は手法をキーに統合）。

| 指標 | schema / no_schema | free_debate / mad | mad_synthesis |
|---|---|---|---|
| svi（評価モデル gpt-5.4-mini 相当※） | experiment_20261009_103401 | logs/fin（svi_mini） | experiment_20261006_175518（svi_mini） |
| atomic_coverage | experiment_20261009_103401 | logs/fin | logs/final（今回評価） |
| turn_novelty / argument_update / reframing / counterargument_respect | experiment_20261009_103401 | logs/final | logs/final |

※ free_debate / mad / mad_synthesis の既存の評価が、今回と同じ評価モデル・プロンプトの版かは、確認できていない。
   論文に載せる前に、評価時の設定を確認すること。

## 注意

- 判定ログ（`judge_stats`、`attempt_log`、`discarded_drafts`）は、schema / no_schema の raw_dialogue の中にある。
- 反復率は、木のある手法（schema / no_schema）と木のない手法で、構造が違うため、直接の比較には注意が必要。judge の
  「反復」判定は、境界例の抜き取り確認で、緩い疑いがあった（確認は未完了）。
- 反論への敬意（DQI）は、schema の表現（規則の連鎖）に不利な形式の偏りがある。
- 予算に届かず終了した議論: schema 1本、no_schema 6本（いずれも最終回答は生成されている）。
- 評価していないもの: 正当化の水準（天井のため）、建設的な政治（スクリプトなし）、attack_validity（新ログ）。
