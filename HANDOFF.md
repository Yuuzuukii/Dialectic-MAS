# HANDOFF: Schema / No Schema の生成・評価改善と再評価結果

更新日: 2026-07-27
対象: Claude など、次のコーディングエージェント

## 0. 最重要: 未コミット変更を破棄しない

この作業ツリーには、今回の評価改善に関する重要な変更が残っている。
`git checkout -- .`、`git reset --hard`、`git clean -fd`、安易なstash操作は行わないこと。

直近の `git status --short` は次のとおり。先頭列が `M` / `A` の13ファイルは staged、
折れ線グラフ生成スクリプトは untracked。さらに、この `HANDOFF.md` の上書きが unstaged として
加わる。

```text
M  docs/eval_parse_method.md
M  docs/eval_transcript_format_spec.md
M  docs/implementation_overview.md
M  experiments/eval/scoring/evaluation.py
M  experiments/eval/scoring/evaluation_pairwise.py
M  experiments/eval/scoring/evaluation_ranking.py
M  experiments/eval/scoring/evaluation_rubrics.py
M  src/agent/arguments.py
M  src/agent/prompts.py
M  src/agent/schema/llm_outputs.py
A  tests/unit_tests/test_constraint_preservation_prompt_contract.py
A  tests/unit_tests/test_constructiveness_prompt_contract.py
M  tests/unit_tests/test_eval_transcript_format.py
?? experiments/eval/plots/plot_rubrics_lines.py
```

コミットはまだ作っていない。ユーザーの指示なしに既存差分を取り消したり、まとめ直したりしないこと。

## 1. 今回の目的と現在地

Dialect-MASの4方式を以下の2軸で公平に評価する作業を行った。

- `constructiveness`: 非建設的な応答（対象ずれ、一般論、反復、非適応的な再提案）を避けられているか
- `constraint_preservation`: 両stanceの実質的な要件を最終回答まで保持できているか

対象方式:

- Schema（提案手法）
- No Schema
- MAD
- Free Debate

旧評価ではSchemaが最下位だったが、評価定義、Schema transcriptの見せ方、生成内容を修正し、
Schema / No Schemaを再生成した。その後、4方式を同一の
`gpt-5.4-nano`, `reasoning_effort=high` で各100件、合計400件再評価した。

**再評価とグラフ作成は完了済み。バックグラウンド評価プロセスは残っていない。**

## 2. 実装した変更

### 2-1. Constructiveness評価プロンプト

`experiments/eval/scoring/evaluation_rubrics.py`

- 「良い反論の巧みさ・新規性」ではなく、「非建設的なresponsive moveの回避」を測る定義へ変更。
- 評価単位を objection と revision に明示。
- 失敗モードを次の4つに限定。
  - target mismatch
  - generic response
  - repetition
  - non-adaptive revision
- 明示的なtargetラベルや構造化表示そのものを加点・減点しないよう指定。
- transcript長や失敗の絶対数ではなく、非建設的moveの**割合と深刻度**で採点。
- 採点帯:
  - 9–10: 0–10%
  - 7–8: >10–25%
  - 5–6: >25–50%
  - 3–4: >50–75%
  - 1–2: >75%
- Constructivenessには `include_integrated_rules=False` の入力を渡し、統合フェーズの生成物を
  議論ターンの評価へ混ぜない。

同じ考え方を `evaluation_pairwise.py` / `evaluation_ranking.py` にも反映している。

### 2-2. Schema transcriptのパース・評価者への提示

`experiments/eval/scoring/evaluation.py`

以前はSchemaのrulesを疑似的な散文へ変換していたため、接続詞、重複、句読点、
weak-negationの所属などに不自然さがあった。現在はruleごとの忠実な段階表示へ変更。

```text
Reasoning:
Step 1:
  Given:
  - ...
  Defeasible assumptions:
  - ...
  Supports: ...
Step 2:
  Uses: result from Step 1
  Final conclusion: ...
```

- 先行consequentが後続strongに再利用される場合は `Uses: result from Step N` と表示。
- 攻撃対象はSchema本文へ評価側が文章を捏造せず、全方式共通の
  `declared target — conclusion/defeasible assumption` ラベルとして表示。
- `justified` / `overruled` / `defensible` など、プロトコル内部の勝敗statusは評価者へ見せない。
- 複数argument間は中立的な
  `The preceding exchange has ended. A new argument follows.` で区切る。
- MAD / Free Debateも2ターン目以降は時系列上の応答関係をラベル表示。

詳細仕様は以下。

- `docs/eval_parse_method.md`
- `docs/eval_transcript_format_spec.md`

### 2-3. Schema生成内容のConstructiveness改善

`src/agent/prompts.py`, `src/agent/arguments.py`

- Schemaの攻撃では、まず狙う具体的な弱点を短く生成し、その内容を最初のruleから
  load-bearingに使わせる。
- targetを末尾で引用するだけの「後付け反論」を禁止。
- 各ruleのconsequentに新しい実質的内容を要求し、言い換えだけの重複ruleを禁止。
- rule構造の形式条件を生成プロンプトへ過剰に詰め込まず、決定論的validatorで検査。
  - consequentが空でない
  - meaningfulなstrongまたはweak-negationがある
  - consequent重複がない
  - 非末尾consequentが後続ruleへ接続される
- 違反時だけrepair promptで再生成。

### 2-4. Constraint Preservationの生成改善

`src/agent/prompts.py`, `src/agent/schema/llm_outputs.py`

- main argument生成前にstance内の理由、要件、条件、対象集団、tradeoffを内部的に洗い出し、
  すべてをload-bearingに扱う。
- 汎化と統合へ元の両stanceを再度渡し、coverage checkとして使用。
- 統合ruleは、各criterionのcondition-to-conclusion mappingを保持。
- ORは同じoutcomeを支える条件だけに使用。
- 対立outcomeが共存し得る場合は、magnitude / breadth / likelihood / reversibility /
  mitigationを対称に比較。
- 一方だけへ自動的な拒否権、precautionary default、burden shift、未提示のtie-breakerを
  与えない。
- 最終回答では両stanceの全material itemを明示的に満たす、限定する、またはoverride理由を説明。
- 中間argumentやintegrated ruleで落ちたstance要件は最終回答で復元。
- `AG1`, `AG2`, `integrated rule`, `decision rule` など内部語彙を最終回答へ出さない。

## 3. 再生成したデータ

10トピック:

```text
artificial_intelligence
binge_watching
cell_phones
electric_vehicles
internet
net_neutrality
pokemon_go
ride_sharing
social_media
space_colonization
```

### Schema

元ディレクトリ:

```text
logs/sweep_all_topics_schema_20260726_220312
```

中断・再開の過程で100 unique topic/attemptを回収したが、物理JSONが103件になった。
重複は以下。

- attempts09 / ride_sharing
- attempts10 / ride_sharing
- attempts10 / cell_phones

元ディレクトリは証跡として変更していない。評価には重複を除いたコピーを使用。

```text
logs/sweep_all_topics_schema_20260726_220312_dedup
```

古い重複3件はコピー側から `/tmp/dialect_schema_duplicate_logs` へ移動した。

### No Schema

```text
logs/sweep_all_topics_no_schema_20260726_220317
```

100/100生成済み。

### 比較対象の既存ベースライン

```text
logs/sweep_mad_cost10_002915
logs/sweep_free_debate_cost10_002919
```

MAD / Free Debateは生成し直していない。評価プロンプトだけ最新状態で再実行した。

旧Schema / No Schemaログは以下にあり、因果分解用に利用可能。

```text
logs/sweep_schema_cost10_233448
logs/sweep_no_schema_cost10_002909
```

## 4. 最新の評価結果

評価条件:

```text
model: gpt-5.4-nano
reasoning_effort: high
各方式: 100件（10トピック × setting 1..10）
合計: 400件
各ログにつきConstructivenessとConstraint Preservationを別々に評価
```

結果ファイル:

```text
logs/sweep_all_topics_schema_20260726_220312_dedup/eval_results_rubrics_nano_high_current.json
logs/sweep_all_topics_no_schema_20260726_220317/eval_results_rubrics_nano_high_current.json
logs/sweep_mad_cost10_002915/eval_results_rubrics_nano_high_current.json
logs/sweep_free_debate_cost10_002919/eval_results_rubrics_nano_high_current.json
```

すべて `per_run=100`、各setting `n_valid=10/10` を確認済み。

全10 settingの平均:

| Method | Constructiveness | Constraint Preservation | Quality Average |
|---|---:|---:|---:|
| Schema | 8.31 | **8.19** | 8.250 |
| No Schema | 8.54 | 8.17 | **8.355** |
| MAD | **9.71** | 4.91 | 7.310 |
| Free Debate | 9.56 | 6.99 | 8.275 |

重要な解釈:

- SchemaはConstructivenessでは4方式中最低だが、8.31まで改善し、No Schemaとの差は0.23。
- SchemaはConstraint Preservationで首位（8.19）。
- 総合ではMADを明確に上回り、最下位ではない。
- MADのConstructiveness 9.71 / Preservation 4.91という分離から、評価器が全方式を
  一律に高得点化しただけではない。

## 5. グラフと集計

新規スクリプト:

```text
experiments/eval/plots/plot_rubrics_lines.py
```

注意: 現在untrackedなので、コミット対象に含めるなら明示的にaddすること。

生成済み成果物:

```text
logs/eval_comparison_nano_high_current/rubrics_summary.csv
logs/eval_comparison_nano_high_current/constructiveness.png
logs/eval_comparison_nano_high_current/constraint_preservation.png
logs/eval_comparison_nano_high_current/quality_average_v2.png
logs/eval_comparison_nano_high_current/rubrics_comparison.png
```

`logs/` はgit管理外。画像は目視確認済みで、凡例、軸、線、タイトルの崩れなし。

横軸の意味は方式で異なる。

- Schema / No Schema: attempts 1..10
- MAD / Free Debate: turns 1..10

グラフ再生成コマンド:

```bash
cd /Users/yuzuki/Desktop/Dialect-MAS
env MPLBACKEND=Agg \
  MPLCONFIGDIR=/tmp/dialect-mpl-cache \
  XDG_CACHE_HOME=/tmp/dialect-xdg-cache \
  .venv/bin/python -m experiments.eval.plots.plot_rubrics_lines \
  --schema logs/sweep_all_topics_schema_20260726_220312_dedup/eval_results_rubrics_nano_high_current.json \
  --no-schema logs/sweep_all_topics_no_schema_20260726_220317/eval_results_rubrics_nano_high_current.json \
  --mad logs/sweep_mad_cost10_002915/eval_results_rubrics_nano_high_current.json \
  --free-debate logs/sweep_free_debate_cost10_002919/eval_results_rubrics_nano_high_current.json \
  --out-dir logs/eval_comparison_nano_high_current
```

macOS sandbox環境では `MPLBACKEND=Agg` と書き込み可能なcache pathがないと
Matplotlibがfont cache生成中にexit 134になることがある。

## 6. 検証

今回の変更作業中に以下を確認済み。

- `ruff check`: pass
- `mypy --strict src/ experiments/`: pass
- 評価transcript / prompt contract関連テスト: pass
- 折れ線グラフスクリプト単体のruff: pass
- 評価JSON: 各方式100件、各setting 10/10 valid
- 集計CSV: 40行（4方式 × 10 setting）
- グラフ: 目視確認済み

全unit testには従来からの無関係な失敗がある。
`tests/unit_tests/test_main_argument_availability.py` が旧State名
`main_attempt_count` を参照しており、現行は `attack_attempt_count`。
この既知問題を今回の変更由来と誤認しないこと。

## 7. なぜ改善したと考えられるか

現時点の仮説:

1. **絶対スコアの上昇**
   Constructivenessをraw failure countや「満点は稀」という曖昧な厳格採点から、
   responsive moveに占める失敗割合ベースへ修正した影響が大きい。
2. **Schema固有の改善**
   raw構造や不自然な疑似散文ではなく、rule chain、assumption、targetを忠実に見せたため、
   評価者が実質的な応答関係を追えるようになった。
3. **内容そのものの改善**
   target engagementを最初のruleからload-bearingにしたこと、stance coverageを
   main/generalization/integration/final answerの全段階で保持したことが効いた。

ただし、新ログと新評価プロンプトを同時に使っているため、現状の再評価だけでは
「評価方法の改善」と「生成内容の改善」の寄与を厳密に分離できない。

## 8. 次に行うなら: 因果分解

ユーザーとの直前の話題は「なぜ良くなったのか」。
次の有効な分析は、旧ログを**現在の評価器**で評価すること。

最低限、次の比較を行う。

| 生成ログ | 評価器 | 分かること |
|---|---|---|
| 旧Schema / 旧No Schema | 現在 | 評価定義・パース変更だけの効果 |
| 新Schema / 新No Schema | 現在 | 今回の最終結果 |

旧ログに現在のtarget保存情報がない場合、パース改善の一部を完全には再現できない点に注意。
より厳密には「旧評価コード × 新ログ」も必要だが、旧コードを作業ツリーへcheckoutして
現在の変更を壊してはいけない。必要なら別worktreeまたは一時的なスクリプトで行う。

また、評価はnano/highの単回採点なので、微差（例: SchemaとNo SchemaのPreservation差0.02）を
強い優位性として断定しないこと。複数seed相当の再評価やbootstrap CIが次の統計的確認候補。

## 9. Claudeが最初に行う確認

```bash
cd /Users/yuzuki/Desktop/Dialect-MAS
git status --short
git diff --cached --stat
git diff -- HANDOFF.md experiments/eval/plots/plot_rubrics_lines.py
```

その後、ユーザーの次の依頼に応じる。現時点で再評価、コミット、旧ログのablationは
依頼されていないため、勝手に外部APIを再実行したりコミットしたりしないこと。

| Method | pokemon_go | artificial_intelligence |
|---|---:|---:|
| Schema | 8.80 | 8.00 |
| No Schema | 7.30 | 9.00 |
| MAD | 9.40 | 10.00 |
| Free Debate | 9.50 | 9.90 |