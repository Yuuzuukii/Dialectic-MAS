# 調査書（Codex によるレビュー用）— 2026-10-08

Dialect-MAS（LangGraph による弁証法的マルチエージェント議論）の、実装の修正・実験・評価の現状と、
**確認してほしい点**をまとめる。数値は、このセッションでログから計算したもので、
計算していないもの・読んでいないものは「未確認」と書いた。

## 0. 目的と立場

- RQ（研究者の言い方）: schema（論証の構造化: rules / Conc / Ass と、仮定 weak_negation）を導入すると、
  LLM 同士の議論に特有の「同型の反論の繰り返し」を抑え、新しい論点を多く出せるのではないか。
- 当初の「合意までのターン数の削減」は、成立しなかった。
- 現時点で、**schema の優位は、どの指標でも検出できていない**（§4）。論文では、この事実を正直に書く方針。
- 手法: schema / no_schema（構造なし）/ free_debate / mad（/ mad_synthesis）。生成は gpt-5.4-nano、評価は gpt-5.4-mini。
- 理論の土台: Prakken & Sartor (1997) の dialogue game（Def 2.15–2.16, 3.4, 4.5–4.7）。
  統合は Kido & Kurihara（対立する2者の立場 A, B から、双方を含む C を作る）。

## 1. 実装の変更（すべて未コミット。一部はステージ済み）

作業ルール（CLAUDE.md §11）: 実験・評価は、ユーザーがターミナルで実行する。ここでは回さない。

### 1.1 カウンターは、反論1つにつき1つ（Def 4.5–4.6 に沿う）
- `src/agent/nodes.py`: `_counter_failed`。C が B を defeat しないときは、フレームを `lost_by_p`（overruled）で閉じ、作り直さない。
- `src/agent/edges.py`: `route_after_validate_proponent_move` は、C が B を defeat したときだけ `opponent_move`、それ以外は `pop_and_propagate`。
- 修正前は、失敗したカウンターを、予算の許す限り何度も作り直していた（schema で同じ反論に連続カウンターが出ていた）。

### 1.2 相互 defeat は、閉じずに続ける（論文にない拡張）
- `validate_proponent_move`: C が B を defeat し、B も C を defeat する（相互）場合、C を子フレームとして push して続ける。
  `attempt_log` に `mutual_defeat` を記録。
- `DialogueNode`（`src/agent/schema/state.py`）: `outcome="contested"`、`entered_by_mutual_defeat`、`contested_by` を追加。
  O が C を攻撃できずに手詰まりになったとき、その枝は `contested`（defensible、予算切れではない）で閉じる。
- 動機: 修正前は「相互 defeat を overruled」にしていた。Def 3.4 では、相互 defeat は justified でも overruled でもない（defensible）。
- 注意: 論文の対話（Def 4.5–4.7）は justified の証明手続きで、相互 defeat の C は P の手として認められない。
  続ける処理は、状態（overruled / defensible）を求めるための拡張。

### 1.3 defeat 関係と発言番号を、攻撃の手番に渡す
- `src/agent/arguments.py`: `numbered_history`（発言に `[n]` を付ける）、`defeat_relations_block`（現在のスレッドの
  `[x] defeats [y]`、相互は `(mutual: …)`、不成立は `does not defeat`）。`build_attack_messages` で手番指示の直前に入れる。
- `src/agent/prompts.py`: `_DEFEAT_RELATIONS_NOTE`（「defeat の関係を読み、defeat 済みの主張を攻撃しない」旨）。
- schema と no_schema に、同じ形で渡す（攻撃種別は伏せる）。

### 1.4 最終回答の共通の作り方（schema / no_schema / free_debate / mad_synthesis）
- 新規 `src/agent/final_answer.py`:
  - 統合案: 各陣営の最後の主張から作る（schema / no_schema は最後の `main`、free_debate / mad は最後の発言）。
    統合には、既存の `generate_integration`（`output_mode="no_schema"` の自由文）を使う。
  - 最終回答: 議論全体の中立な書き起こし（`dialogue_transcript.format_transcript`）＋（あれば）統合案、（あれば）justified な論証。
    プロンプトは1つで、「渡されている場合は参照する」。
  - 経路: `justified_with_dialogue` / `integrated_with_dialogue` / `dialogue_only`（どちらかの陣営に main がないとき）。
- 接続: `nodes.generate_final_answer`、`free_debate.py` と `mad.py` の `integrate` / `generate_final_answer`。mad の judge 版は元のまま。
- ログ: `integrated_proposal`、`finalization_path`。
- 旧方式（`two_path_finalization.py` ほか）は、過去ログの再現用に残してある。

### 1.5 その他のスクリプト
- `experiments/dialogue/runners/refinalize_unified_final.py`: 既存ログの最終回答だけを、1.4 で作り直す。mad は `mad_synthesis` として出力。
- `experiments/dialogue/runners/refinalize_last_statements.py`: 旧方式（最後の発言から統合ルール）の作り直し。
- `experiments/eval/runners/eval_pairwise.py`: 回答だけの対比較（AG1・AG2 の立場から、両順序）。
- `experiments/eval/runners/eval_turn_novelty.py`: 各発言が、同じ陣営の過去の発言に新しい理由を足しているか（**未実行**）。
- テストは 121 件が通る（`.venv/bin/pytest tests/unit_tests`）。`ruff` と `mypy --strict src` も通る。

## 2. 実験とログ（`logs/`）

| フォルダ | 内容 | 実装の状態 |
|---|---|---|
| `fin/` | 旧実装の決定版（300 本: schema・no_schema・free_debate・mad 各75。評価も統合済み）。`MANIFEST.md` 参照 | blocker あり（旧）、schema/no_schema は経路 B（議論全体の統合） |
| `experiment_20261007_153928` | 50 本（schema/no_schema × 5 ターン数 × 5 トピック × 1 回）。blocker なし、カウンター制限なし | 修正前 |
| `experiment_20261007_164404` | 44 本。カウンター1回 | 1.1 |
| `experiment_20261007_183206` | 10 本（20 ターン）。+ defeat 関係の block | 1.1 + 1.3 |
| `experiment_20261007_204149` | 10 本（20 ターン）。+ 相互 defeat の修正 | 1.1–1.3 |
| `experiment_20261007_213516` | **150 本**（10〜30 ターン × 5 トピック × 2 手法 × 3 回）。現行実装の議論。最終回答は旧の経路 B | 1.1–1.3 |
| `experiment_20261008_065358` | 213516 の schema / no_schema と、fin の free_debate / mad(→mad_synthesis) の**最終回答だけを 1.4 で作り直した 300 本** | 1.4 |
| `experiment_20261006_201913`, `_175518` | 旧方式にそろえた schema/no_schema、mad_synthesis（旧） | 旧 |

- 各ログ: `turns<N>/raw_dialogue/<カテゴリ>/<トピック>/[NN_]<method>_<日時>.json`。
- 議論の木: `experiment_*/argument_network.html`（`plot_argument_network`）。

## 3. 評価の進め方

- SVI: 4項目（Instrumental Q1–Q4、Q3 は逆転）の平均 `mean`、AG1・AG2 の項目差の平均 `gap`、合意スコア `C_k = mean − k·gap`（k=0.5）。
  mini で評価。ターン数 × トピックのセル（25）の平均の対応あり差と、95% 信頼区間で比較。
- Atomic Coverage: 立場文を原子的な主張に分け、最終回答に残っている割合。
- 回答だけの対比較: 2つの最終回答を、AG1・AG2 の立場から、両順序で比べる。
- accepts（`logs/fin_test2`）: 反論を最終回答がどれだけ取り入れたか（Jev）。

## 4. 結果（検証済みの数値）

### 4.1 SVI C_k（k=0.5、全ターン数、gpt-5.4-mini）
| 条件 | schema | no_schema | free_debate | mad |
|---|---|---|---|---|
| fin（旧実装、各75） | 3.63 | 3.57 | 3.19 | 2.68 |
| 213516（現行の議論、最終回答は旧の経路 B）| 3.27（75） | 3.51（74） | — | — |

セル平均の対応あり差（25 セル、95% CI）:
- fin: schema − no_schema = **+0.05 ± 0.25**
- 213516: schema − no_schema = **−0.24 ± 0.20**
- 213516 schema − fin free_debate = +0.07 ± 0.25 ／ 213516 no_schema − fin free_debate = +0.32 ± 0.20
- 213516 schema − fin mad = +0.59 ± 0.22 ／ 213516 no_schema − fin mad = +0.83 ± 0.23
- 213516 schema − fin schema = −0.36 ± 0.22 ／ 213516 no_schema − fin no_schema = −0.06 ± 0.19
- 新実装で schema が下がった原因は、**未特定**（修正が複数入っている）。

### 4.2 最終回答の作り方をそろえた条件（`experiment_20261008_065358`、各75本、mini）
| 手法 | 満足度 | gap | C_k |
|---|---|---|---|
| schema | 3.41 | 0.85 | 2.99 |
| no_schema | 3.76 | 1.00 | 3.26 |
| free_debate | 3.93 | 1.12 | 3.37 |
| mad_synthesis | 3.88 | 0.93 | 3.41 |
| （参考）mad の judge 版（fin） | 3.45 | 1.55 | 2.68 |

セル平均の対応あり差（C_k、25 セル、95% CI）:
- schema − no_schema = **−0.27 ± 0.17** ／ schema − free_debate = **−0.38 ± 0.18** ／ schema − mad_synthesis = **−0.42 ± 0.19**
- no_schema − free_debate = −0.11 ± 0.20 ／ no_schema − mad_synthesis = −0.15 ± 0.20 ／ free_debate − mad_synthesis = −0.04 ± 0.22
- mad_synthesis − mad（judge）= **+0.73 ± 0.25**（最終回答の作り方の効果）
- ターン別 C_k: schema は 10 ターン 3.23 から 30 ターン 2.75 へ下がる（no_schema 3.30 → 3.08、free_debate 3.45 → 3.39）。各セル15本。
- Atomic Coverage: schema 0.779 / no_schema 0.798 / free_debate 0.804 / mad_synthesis 0.727。schema − no_schema = −0.019 ± 0.036。
- 回答だけの対比較（300判定）: schema 47.7% / no_schema 50.7% / tie 1.7%。順序で結果が変わる判定が多い（一致は50〜77%）。

**解釈**: 最終回答をそろえても、弁証法の議論（schema / no_schema）は、free_debate・mad_synthesis より合意性が高いとは言えない。
schema は、そろえた条件で最も低い。旧の経路 B（議論全体の統合のみ）と、旧方式（最後の発言のみ）で、約0.7の差があったことの、
交絡は解消された（旧方式は 2.89、経路 B は 3.27 / 3.51）。

#### schema が低い理由の調査（4.2 の続き。原因は未特定）
- 項目別平均（AG1・AG2）: Q1（望む結果が得られたか）schema 2.65 / no_schema 3.15 / free_debate 3.28 / mad_synthesis 3.26。
  Q2〜Q4 も schema が低い（Q2 3.23 vs 3.57、Q3 3.35 vs 3.67、Q4 4.41 vs 4.66）。Q1 が 2 以下の評価は schema 92/150、no_schema 69/150。
- 陣営別: AG1 は schema 3.49 / no_schema 3.97、AG2 は 3.33 / 3.55。
- 低評価の理由は、「回答が条件つき・未解決で、自分の立場を明確に支持していない」が多い。ただし、回答の冒頭 400 字に条件語を含む割合は、
  schema 0.49 / no_schema 0.53 / free_debate 0.58 / mad_synthesis 0.73 で、schema が条件つきになりやすいわけではない。
  「未解決」系の語を含む回答は schema 93% / no_schema 87%。
- 議論の構造（overruled の主張が多い）は、満足度を説明しない。陣営の最後の main が overruled の場合の満足度は schema 3.43、
  defensible の場合は 3.41（差なし）。no_schema の defensible は 3.79。最後の main の状態が同じでも、schema が低い。
- 回答の長さ（schema 6699 字、no_schema 6113 字）、統合案の長さ（2197 字と 2045 字）に大きな差はない。
- 経路別（schema）: integrated 72 本 3.42、justified 2 本 3.12、dialogue_only 1 本 3.25。
- 次に疑う点（未検証）: schema の「最後の main」を文章に直した入力が、統合案の質に影響している可能性。
  schema と no_schema の統合案・最終回答を、同じトピックで全文を読み比べる必要がある。

### 4.3 評価のぶれ
- 同じ10本のログを2回評価すると、C_k の差は平均 0.60、最大 2.00。1回の評価は、±0.6 ほどぶれる。

### 4.4 その他の指標
- Atomic Coverage（10〜30 ターン、約75本）: 213516 は schema 0.754 / no_schema 0.738。fin は 0.824 / 0.864 / free_debate 0.816 / mad 0.555
  （fin の評価モデルは nano だった可能性があり、**直接比較不可**）。
- 回答だけの対比較: fin（300判定）は schema 50.0% / no_schema 49.0%。213516（296判定）は schema 45.3% / no_schema 53.7%。順序の影響が大きい。
- accepts（fin_test2、各75）: schema 0.700 / no_schema 0.680 / free_debate 0.666 / mad 0.492。schema − no_schema = +0.020 ± 0.034。

### 4.5 議論の構造（213516）
- main の回数: schema 270（1本あたり 3.60）、no_schema 224（2.99）。
- main の状態: schema = overruled 98 / defensible（予算切れ）122 / defensible（相互 defeat）48 / justified 2。
  no_schema = overruled 40 / 139 / 42 / 3。overruled の割合は 36% と 18%。
- justified は 149 本中 5 本。いずれも早期終了（7〜27 ターン）。
- 手の種類（20 ターン）: schema は rebut 約 15 に対して undercut 約 1。no_schema は rebut 約 6〜7 に対して undercut 約 8〜11。
  schema で undercut が少ないのは、仮定（weak_negation）が約 25% の論証にしかないため。
- どちらも縦に長い木（1つの手への子は最大 1〜2）。**木の形では、2手法を区別しにくい。**

### 4.6 「同型の反論の繰り返し」（RQ の核心）— 結論は出ていない
- TF-IDF で、発言と自分の過去発言との最大類似度: schema 0.161 / no_schema 0.077（213516）。
  ただし schema の論証は、立場文の文を前提として毎回置く形式なので、**形式による見かけの差の可能性が高い**。
- 質的に読んだ: 213516 の 20 ターン run 01 の10本。**各発言の先頭約 200 文字だけ**。
  schema は冒頭の定型文の繰り返しが多く、論点の幅は広い。no_schema は直前の前提を突いて掘り下げる連鎖。
  この読み方は**弱い**（末尾の結論・後半の規則を読んでいない）。結論として使えない。
- `eval_turn_novelty` は、全文を使って判定する。**未実行**。

## 5. 実装・実験で分かっている性質（レビューで見てほしい土台）

- `ask_attack_extends`（B の作者に「B は新しいカウンター C にも及ぶか」を聞く）は、論文にない LLM 判定。
  カウンターの約 85% で「及ばない」と答え、C が B を strictly defeat した扱いになる。相互 defeat と判定されるのは約 15〜19%。
  論文の defeat は、2つの論証の関係だけで決まる。
- 優先順位（Def 2.15 の `≮`）は、このプロジェクトでは持たない（削除済み）。そのため rebut は対称で、論文に厳密に従うと、
  結論が対立する rebut 同士は相互 defeat になる。優先順位を LLM の判定で与える案（根拠の確かさ・具体性など）は、議論しただけで**未実装**。
- no_schema では、`ask_existing_undercut`（すでにある論証が相手の rebut を undercut しているかの確認）が常に「いいえ」。
  schema は、宣言された仮定（weak_negation）がある場合だけ確認する。この非対称は、設計どおりだが、手の種類の差に効いている。
- ログは、run の終了時に1回だけ保存。途中経過は残らない。reasoning が 128000 トークンに達すると、その run は失敗する（約 5%）。
  API 呼び出しにタイムアウトが無く、応答が止まるとプロセスが待ち続けた例があった。
- 議論の早期終了: どちらかが新しい main を出せないと終わる設計。213516 では約16%が、上限より2ターン以上短く終わった。

## 6. Codex に見てほしい点

### 6.1 実装の正しさ
1. `validate_proponent_move` と `pop_and_propagate`（1.1, 1.2）が、Def 4.5–4.7 と Def 3.4 の意図に沿っているか。
   特に、`contested_by` の伝播（相互 defeat を通った枝の後で、別の B' を strict に退けても、A が justified にならず defensible になるか）、
   `thread_finding` の変更、`last_counter_strictly_defeated` の名前（相互 defeat でも True になる）。
2. `defeat_relations_block` の範囲（現在の main 以降の発言だけ）と、`numbered_history` の番号と `argument_records` の対応が、
   手番ごとにずれないか（`history` と `argument_records` の件数が合わないときは番号を付けない設計）。
3. `final_answer.py` の `last_position` が、schema / no_schema（`type == "main"`）と、free_debate / mad（`type` なし）で、
   意図どおりに最後の主張を取るか。main のない陣営があるときの扱い。
4. 統合の指示（`integration_instruction`）は、「元の問いに答えず、将来の main に使える規則を1つ出す」という文言を含む。
   これを最終回答の主な根拠にすることの妥当性。
5. 公平性: schema と no_schema で、履歴の形（schema は JSON の封筒、no_schema は自由文）以外に、有利・不利を生む違いが無いか。

### 6.2 評価の妥当性
1. SVI が ±0.6 ぶれる中で、25 セルの対応あり差と 95% CI の使い方は適切か。同じログの複数回評価を、組み込むべきか。
2. `eval_svi_final.py` は、1本でも例外が出ると、そのターン数の結果が全部失われる。10・15 ターンで一度起きた（再現せず）。
3. `eval_turn_novelty.py` の判定基準・プロンプトが、「同型の反論の繰り返し」を測るのに適切か。schema を文章に直した形での公平性。
4. fin の Atomic Coverage の評価モデルと、現行の評価モデルの差。

### 6.3 主張と証拠のずれ
1. §4 の結果から、論文に書ける主張と書けない主張の線引き。最終回答の作り方をそろえた §4.2 では、弁証法の議論が free_debate・
   mad_synthesis より高いとは言えず、schema は低い。「弁証法の議論の導入で合意性が上がる」「schema が優位」は書けない、と判断している。
2. RQ（繰り返しの抑制）が、データから支持されないとき、どう再設定するか（たとえば「論点の幅」）。

## 7. 未実施・保留

- schema が、そろえた条件で低い理由の特定（統合案・最終回答の全文の読み比べ）。
- `eval_turn_novelty` の試運転と本番。
- 1本の落ちた run を補った後の、213516 の議論の木（150 本）は作成済み。
- 優先順位の LLM 判定（Jev による比較、別管理）は、設計だけ。論文の基準（Wachsmuth らの論証の質、UKPConvArg など）は、記憶に基づく候補で、未確認。
- 論文（`/Users/yuzuki/Desktop/AAMAS/ja/paper_ja.tex`）の表 4・§6 は、旧の数値のまま。
- コミットはしていない（ユーザーが行う）。

## 8. 主なファイル

- 実装: `src/agent/{nodes,edges,workflow,arguments,prompts,final_answer,free_debate,mad,dialogue_transcript}.py`, `src/agent/schema/state.py`
- 実験: `experiments/dialogue/runners/{run_protocol_check,refinalize_unified_final,refinalize_last_statements}.py`, `experiments/dialogue/common.py`
- 評価: `experiments/eval/runners/{eval_svi_final,eval_atomic_coverage_final,eval_pairwise,eval_turn_novelty,eval_rebuttal_defeat}.py`
- 可視化: `experiments/eval/plots/plot_argument_network.py`
- テスト: `tests/unit_tests/`（`test_dialogue_tree`, `test_final_answer`, `test_defeat_relations_prompt`, `test_turn_novelty` など）
- 既存の記録: `docs/research_progress/`（`results_and_limitations_2026-10-06.md`, `paper_draft_ja_2026-10-07.md`）、`logs/fin/MANIFEST.md`
