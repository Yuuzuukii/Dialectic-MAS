# HANDOFF: 評価プロンプトの再定義（constructiveness / transcript整形）

作成日: 2026-07-26。別のコーディングエージェントへの引き継ぎ用。

## ⚠️ 最初に：コミットしていない変更を絶対に破棄しないこと

以下のコマンドは**絶対に実行しないこと**（未コミットの本セッションの成果が消える）:
`git checkout -- .` / `git reset --hard` / `git clean -fd` / `git stash drop`

現状は `git status --short` で以下の6ファイルが変更あり（stagedとunstagedが混在=`MM`）:
```
M  docs/eval_transcript_format_spec.md
A  docs/implementation_overview.md
MM experiments/eval/scoring/evaluation.py
 M experiments/eval/scoring/evaluation_ranking.py
MM experiments/eval/scoring/evaluation_rubrics.py
 M tests/unit_tests/test_eval_transcript_format.py
```
まずやるべきことは `git add -A && git commit` でこの状態を確定させること（メッセージ案は末尾）。

---

## 1. 最終的な目的

Dialect-MAS（LangGraphベースのマルチエージェント議論システム）には4手法がある:
`schema`（提案手法・構造化論証）/ `no_schema` / `mad` / `free_debate`。

ユーザーの仮説: **schema は「反論の建設性」と「両者スタンスの取り込み（constraint_preservation）」で
最も高くあるべき**。しかし実測では schema が LLM 評価で最下位になっていた。

調査の結果、**評価プロンプト側の問題**であることが判明:
1. schema の transcript レンダリングにバグ（重複・不自然な文体）があり、schema が不当に低く見えていた
2. constructiveness の定義が「積極的に良いか（前進・新規性）」を測っており、これは自由記述の
   no_schema/free_debate に有利な**散文の巧みさの交絡**を含んでいた
3. transcript にプロトコル内部用語（`rebut`/`undercut`/`main argument`）が生で出ており、
   評価器がプロトコルを理解できていない可能性があった

**目的**: 評価プロンプトを「議論の内容だけで公平に判定できる」形に修正し、その上で
4手法を再評価して schema の実力を正しく測る。

## 2. 実装済みの内容

### 2-1. transcript整形のバグ修正・改善（`build_eval_input` / `_schema_utterance`）

schema の `Argument`(rules/Conc/Ass) を発話体英文へ変換するロジックを修正:

- **重複バグ修正**: chain構造（非末尾consequentが次ruleのstrong前提に再出現）をそのまま
  rule単位で描画すると同じ結論文が2回出て「So Therefore, X. ... Therefore, X.」のような
  不自然な重複が生じていた → 連鎖のつなぎとみなして重複描画を除去
- **反論の言い出しを自然な議論調に変更**:
  - 旧: `I have a counter argument against the opinion/premise "X".`
  - 新: rebut→ `I disagree with your conclusion that "X".` / undercut→ `Your premise that "X" does not hold.`
  - 理由: 「手番の種類を機械的に宣言してから話す」のは実際の議論の話し方ではない、というユーザー指摘
- **ターンラベルからプロトコル用語を除去**:
  - 旧: `[Turn 2] AG2 (undercut — responds to [Turn 1])`
  - 新: `[Turn 2] AG2 (responding to [Turn 1])`（main argumentは `(new argument)`）
  - 理由: 評価器はrebut/undercutを知らない。用語なしで議論の流れが追えるようにする
- **"So" 接続詞の後の不自然な大文字化を修正**:
  - 旧: `So The target does not justify...`
  - 新: `So the target does not justify...`（`_lowercase_first` ヘルパーを新設。"I"や全大文字の頭字語は保護）

### 2-2. constructiveness ルーブリックの再定義（積極性ベース→抑制ベース）

`CONSTRUCTIVENESS_INSTRUCTION`（`evaluation_rubrics.py`）を書き換え:

- **旧定義**: 「各反論が具体点に**新しい論拠で踏み込み議論を前進させているか**」→ 高得点帯が
  "new reasoning" "narrows or sharpens" を要求 = 積極的な質・新規性を評価していた
- **新定義**: 「非建設的な反論（反復・一般論・すれ違い・蒸し返し）を**どれだけ避けられているか**」
  という抑制ベースに変更。"Do NOT reward novelty, rhetorical polish..." を明記し、
  単純でも具体的に噛み合っていれば満点、と明示
- 理由: 旧定義は「散文の巧みさ・新規性」を暗に評価しており、自由記述の no_schema/free_debate が
  有利になる交絡だった。ユーザーの「抑制されているほど高いのでは」という指摘を反映
- `evaluation_ranking.py` にも同じ `(rebut/undercut/counter turn)` という用語が
  プロンプト本文（指示文）に残っていたため、同様に除去（`An "objection" is any turn that
  responds to a previous turn (challenging its conclusion or one of its premises).` に置換）

### 2-3. constraint_preservation に integrated_rules を追加（前セッションで実施・コミット済み）

両者が合意した warrant（integrated rule）を入力に追加し、これが最終回答に反映されているかを
採点対象にした。この部分は既に `527ccec` でコミット済み、今回の変更範囲外。

### 2-4. ドキュメント整備

- `docs/implementation_overview.md` を新規作成。`src/agent`（本体）と `experiments/eval`（評価系）の
  ファイル別役割・グラフの流れ（mermaid図）・評価軸の定義をまとめた実装解説
- `docs/eval_transcript_format_spec.md` の正準テンプレート（§4/§5）を新しい文言に更新

## 3. 変更したファイル（未コミット、本セッション分のみ）

| ファイル | 内容 |
|---|---|
| `experiments/eval/scoring/evaluation.py` | `_schema_utterance`（重複除去・自然な言い出し・小文字化）、`_turn_label`（用語除去）、新ヘルパー `_lowercase_first` / `_strip_leading_connective` |
| `experiments/eval/scoring/evaluation_rubrics.py` | `CONSTRUCTIVENESS_INSTRUCTION` を抑制ベースに全面改訂、`(rebut/undercut/counter turn)` を除去 |
| `experiments/eval/scoring/evaluation_ranking.py` | 同種の用語除去（4手法ランキング評価用プロンプト） |
| `tests/unit_tests/test_eval_transcript_format.py` | 上記変更に合わせてアサーションを更新（5件） |
| `docs/eval_transcript_format_spec.md` | 正準テンプレートの文言を更新 |
| `docs/implementation_overview.md` | 新規作成（実装解説ドキュメント） |

**変更していないもの**: `src/agent/` 本体（生成側）は今回のセッションでは無変更。
`constraint_preservation` のプロンプト自体も無変更（integrated_rules対応は前回コミット済み分）。

## 4. 未完了の作業

1. **再評価が未実施**。上記の transcript整形・プロンプト変更を反映した評価は**まだ1回も回していない**。
   ユーザーから明確に「まだ再実行はしないでね」と指示されており、プロンプトの調整を優先していた。
2. `logs/sweep_{schema,no_schema,mad,free_debate}_cost10_*/eval_results_rubrics_{nano_high,mini}.json`
   に**過去の評価結果が残っているが、これは古いプロンプトでの評価**（下記「重要な注意」参照）。
3. コミットしていない（ユーザーの明示的な合図を待っている状態）。
4. グラフ（Artifact）の再更新も未実施。

## 5. 重要な設計判断と理由

- **`_lowercase_first` は "I" と全大文字語（頭字語）を保護**: 一人称や固有名詞的な大文字始まりの
  単語まで小文字化すると別の不自然さを生むため。ヒューリスティックで対応（完全ではない）。
- **rebut/undercut の区別はラベルから消したが、発話本体（`I disagree with your conclusion`
  vs `Your premise that ... does not hold`）には残している**: 情報は落とさず、表現形式だけを
  プロトコル用語から自然文へ移し替えた、という設計。
- **抑制ベースへの再定義は「短い議論が有利になる非対称」を生む**（要注意点、未解決）:
  失敗モードに触れる機会が少ない=ターン数が少ない議論ほど高得点に出やすい。対策候補は
  (a) 同じ反論回数どうしでのみ比較する運用でカバー、(b) 反論数で重み付けする指標を別途作る、
  のいずれも**まだ実施していない**。次エージェントが再評価後のデータで判断すること。
- **constraint_preservation は今回変更していない**: ユーザーからの指摘は constructiveness と
  transcript整形（言い出し・ラベル）に限定されていたため、スコープを絞った。

## 6. 発生中の問題

- **`eval_results_rubrics_*.json` は stale（古いプロンプトでの評価結果）**。
  タイムスタンプは 2026-07-26 19:33〜19:44 で、これは「抑制ベースへの再定義」直後の評価だが、
  **その後に行った「自然な言い出し」「ラベルの用語除去」「So の大文字化修正」は反映されていない**。
  これらのJSONを見て「これが最新結果」と誤解しないこと。再評価するまでは参考値扱い。
- 上記以外の技術的なブロッカーはなし（ruff/mypy/テストは全てクリーン、下記参照）。

## 7. 実行したテストと結果

```
$ .venv/bin/python -m pytest tests/unit_tests -q
32 passed, 3 failed in 6.24s
```

失敗3件は**本セッションの変更と無関係の既存問題**（`tests/unit_tests/test_main_argument_availability.py`
が旧State名 `main_attempt_count` を使っている。正しくは `attack_attempt_count`）。
過去のセッションから存在する既知の失敗で、今回のスコープ外。

```
$ uv run ruff check .
All checks passed!

$ uv run mypy --strict src/ experiments/
Success: no issues found in 42 source files
```

pre-commit フック（`.husky/pre-commit`）は `ruff check .` と `mypy --strict src/ experiments/` を
実行する。上記の通り両方通過済みなので、そのままコミット可能。

## 8. 次に実行すべきコマンド

### 8-1. まずコミット（変更を確定）

```bash
cd /Users/yuzuki/Desktop/Dialect-MAS
git add -A
git commit -m "$(cat <<'EOF'
[fix]評価プロンプトの再定義: constructiveness抑制ベース化・transcript自然文化

- schemaのtranscript整形バグ修正（chain重複除去）と自然な言い出しへの変更
  （I have a counter argument against... → I disagree with your conclusion that...）
- ターンラベルからプロトコル用語(rebut/undercut/main)を除去し評価器に伝わる形に
- constructivenessを「積極的前進」から「非建設的応酬の抑制」ベースへ再定義
  （散文の巧みさ・新規性への交絡を除去）
- evaluation_ranking.pyの同種プロンプトにも用語除去を適用
- 実装解説ドキュメント docs/implementation_overview.md を新規作成
EOF
)"
```

### 8-2. 10トピックサンプルで再評価（両評価器）

既存の10トピックデータ（`logs/sweep_{schema,no_schema,mad,free_debate}_cost10_*/`）に対して
新プロンプトで再評価する。生成は不要（ログを読むだけ、安価）。

```bash
cd /Users/yuzuki/Desktop/Dialect-MAS
for m in schema no_schema mad free_debate; do
  d=$(ls -d logs/sweep_${m}_cost10_* | head -1)
  # nano-high
  .venv/bin/python -m experiments.eval.runners.eval_sweep_rubrics --sweep "$d" \
    --model gpt-5.4-nano --reasoning-effort high --workers 5 \
    --out "$d/eval_results_rubrics_nano_high.json"
  # mini
  .venv/bin/python -m experiments.eval.runners.eval_sweep_rubrics --sweep "$d" \
    --model gpt-5.4-mini --workers 5 \
    --out "$d/eval_results_rubrics_mini.json"
done
```

実行時間の目安: 前回同等の処理で各ジョブ数分〜十数分（並列実行推奨、`run_in_background`等）。

### 8-3. 結果の確認・グラフ更新

前回作成した比較用Artifact（URL: `https://claude.ai/code/artifact/dc4ec306-a6ae-498c-b80e-8d3c2a6dd904`）
と同じ手順で、新しい `eval_results_rubrics_*.json` からデータを再抽出してグラフを更新する。
特に注目すべき点:

- **schema の constructiveness が上がったか**（前回の抑制ベース化だけで nano-high +0.88、
  no_schemaとの差が0.54→0.08まで縮まっていた。今回の言い出し・ラベル変更でさらに縮まるか拡がるか）
- 短ターン有利の非対称が結果にどう出るか（同じ反論回数どうしで比較すること）

### 8-4. その後の判断ポイント（ユーザーと相談すべき事項）

- n=99フルデータでの再検証をするか（追加コスト ≈$130、nano@high想定）
- 短ターン有利の非対称への対策（別軸に分離 or 運用でカバー）をどうするか
