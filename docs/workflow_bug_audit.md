# ワークフロー実装バグ調査メモ

このドキュメントは `src/agent/workflow.py` / `nodes.py` / `edges.py` /
`argumentation_model.py`（旧 `defeats.py`、schema / no_schema 共通の弁証法プロトコル
グラフ）に関する調査・修正の記録。**1〜3節は実装済み**（`defeats.py` は
`argumentation_model.py` にリネーム済み、`run_defeat_subgraph` → `evaluate_attack`、
`DefeatSubgraphResult` → `AttackEvaluation`）。以下の記述中の `defeats.py`/
`run_defeat_subgraph` 等への言及は調査当時の名称であり、現在のコードでは上記の新名称に
置き換わっている。

---

## 1. `validate_b_defeats_c` の reverse defeat 判定が C の内容を見ていない（実装済み）

### 想定している仕様（ユーザー確認済み）

strict defeat の判定は「AG1のカウンター(C)がAG2の攻撃(B)を破り、かつAG2がCの内容に対して
有効な新しい反論を組み立てられない」という意味であるべき。つまり **C の具体的な内容を見て、
AG2 側がそれに対して有効な攻撃を新たに生成できるかどうかを判定する** 必要がある。

### 実際の実装

`validate_b_defeats_c()`（[nodes.py:330-357](../src/agent/nodes.py#L330)）→
`run_strict_defeat_subgraph()`（[defeats.py:166-201](../src/agent/defeats.py#L166)）の
reverse 判定 (`B defeats C?`) は、

```python
reverse = await run_defeat_subgraph(
    state, y, x, reverse_defender,   # attacker=B, target=C
    blocker_generator=blocker_generator,
    allow_generated_blocker=False,
    persist_metadata=False,
)
```

を呼んでいるが、`run_defeat_subgraph` 内の `attack_from_metadata(attacker)`
（[defeats.py:50-54](../src/agent/defeats.py#L50)）は **B が A を攻撃した時点で
LLM が宣言した静的なメタデータ（attack種別・target_statement）をそのまま読むだけ**で、
C の内容は一切参照していない。さらに `allow_generated_blocker=False` のため、
B の攻撃が `rebut` であっても AG1（proponent）側に新しい防御(undercut)を
生成させる機会が与えられない。

結果として、B に有効な攻撃メタデータが存在する限り `reverse.defeats` は
**実質的に常に True** になり、`strictly_defeats = not reverse.defeats` は
**ほぼ常に False** になる。つまり `validate_b_defeats_c` を通る経路では
ほぼ "defensible" にしかならず "justified" に到達しにくい。

### 状況証拠

- `State`（[workflow.py:104](../src/agent/workflow.py#L104)）に `d_argument` という
  フィールドが定義されているが、**これを生成するノードがどこにも存在しない**
  （`None` にリセットするだけ）。これは「C に対する AG2 の新しい反論(D)を生成する」
  ステップが実装されずに残された設計漏れである可能性が高い。

### 修正方針（実装済み・2回目の見直し版）

新しい論証(D)を生成する方式は不採用とした。理由は、(1) 新しい論証を生成すると、
理論上はそのDにもさらに反論が必要になり無限再帰の問題を再生産してしまう、
(2) ASPIC+ 文献に対して忠実でなくなる、ため。

代わりに、**新しい論証は生成せず、Bの作者であるAG2自身に「Bは（相手が新たに作った）
Cも同様に攻撃するか」をYES/NOで直接質問する**方式にする。

```
p_counter_b で C が生成される
  ↓
validate_c_defeats_b（C defeats B?）→ defeats=True なら…
  ↓
【新】ask_b_attacks_c: AG2（Bの作者）に
  「あなたの反論Bは、相手の新しいカウンターCも同様に攻撃しますか」と
  YES/NOで尋ねる（新しい論証は生成しない、構造化YES/NO出力のみ）
  ├─ NO  → complete_thread(state, "justified")（Bの攻撃はCには及ばない＝strictly defeat成立）
  └─ YES → Bの攻撃はCにも及ぶと確認された ↓
       従来通り run_defeat_subgraph(attacker=b_argument, target=c_argument,
                                     defender=current_proponent,
                                     blocker_generator=generate_undercut,
                                     allow_generated_blocker=True)
       で defeat 判定を行う
       ├─ defeats=False → justified
       └─ defeats=True  → defensible
```

### 質問する相手をAG1ではなくAG2にした理由

最初の案では「AG1（Cの作者）に、Bは自分のCも攻撃するか」と尋ねる想定だったが、
これはCが破られると困る側に自己判定させることになり、AG1には「NO」と答える
自己利益的なインセンティブが生まれる。

既存の実装（`can_defeat`/`can_undercut`等）は一貫して**攻撃を仕掛ける側
（attacker）に自己判定させる**設計になっている。この既存パターンとの整合性のため、
「Bを作った当人であるAG2」に「Bの攻撃範囲がCにも及ぶか」を聞く方式に変更した。

### 実装内容

- 新規スキーマ `AttackExtendsOutput`（[llm_outputs.py](../src/agent/schema/llm_outputs.py)）
  を追加。YES/NO一問だけのシンプルな構造化出力で、新しい`ArgumentRecord`は生成しない。
- 新規関数 `ask_attack_extends()`（[arguments.py](../src/agent/arguments.py)）が、
  Bの作者（attacker）に上記スキーマでYES/NOを尋ねる。
- 既存の未使用フィールド `d_argument`/`d_argument_id` は削除した
  （`workflow.py`のState定義、`nodes.py`の各リセット箇所）。
- `validate_b_defeats_c()`（[nodes.py](../src/agent/nodes.py)）を、
  「`ask_attack_extends`でNOなら即justified、YESなら従来の`evaluate_attack`
  （旧`run_defeat_subgraph`）で判定」という実装に置き換えた。
  `run_strict_defeat_subgraph`/`StrictDefeatSubgraphResult`は不要になったため削除。
- `route_after_validate_b_defeats_c`（[edges.py](../src/agent/edges.py)）は
  `current_thread_status`のみを見る既存の実装のままで変更不要だった
  （ステータスの決定方法が変わっただけで、ルーティング自体の判定条件は変わらないため）。
- 影響範囲の実測: `b_defeats_c`/`c_strictly_defeats_b`を使った"justified"到達率の
  before/after比較は未実施（必要なら別途sweep再実行で確認）。

---

## 関連ファイル

- `src/agent/workflow.py` — State 定義・グラフ構築
- `src/agent/edges.py` — 条件分岐ルーティング
- `src/agent/nodes.py` — 各ノードの処理本体
- `src/agent/argumentation_model.py`（旧 `defeats.py`） — Argumentation Model の攻撃判定処理
- `logs/sweep/artificial_intelligence/` — 旧ワークフローで評価済みのsweep結果（外側ループ
  再設計後に再評価が必要）

---

## 2. プロトコルの外側ループ再設計（実装済み）

ユーザー提示のフローチャートに基づき、現行のラウンド管理・リトライ管理・AG1↔AG2の
ハンドオフ構造を作り直す。**「主張→相手が攻撃→strict defeat判定」という現行のサブスレッド
（`o_defeat_a`/`p_counter_b`/`validate_b_defeats_a`/`validate_c_defeats_b`/
`validate_b_defeats_c`、上記1.の問題を含む）はそのまま「Argumentation Model」という
1つのブラックボックスとして内包し、その外側だけを再設計する。**

### 新しい外側ループ（確定版）

```
Start
  ↓
「プロトコル周以上?」(ラウンド数が上限に達したか)
  yes → 最終回答 → End
  no  ↓
「主張n回以上?」(AG1の主張試行回数が上限nに達したか) ──yes──┐
  no                                                          │
  ↓                                                           │
AG1「主張が作れるか」                                          │
  no  ─────────────────────────────────────────────────────────┤
  yes ↓                                                       │
  主張(AG1) → [Argumentation Model]                            │
  （内部で現行のdefeat/counter/strictly-defeatサブスレッドが走り、  │
   justified/defensible/overruled等を判定する。詳細は1.参照）     │
  ↓                                                           │
「主張がjustified?」(1つ目、AG1の主張に対する判定)                │
  yes → 最終回答 → End                                        │
  no  → 「主張n回以上?」(AG1)に戻る（AG1がリトライ）              │
                                                               ↓
                                        「主張m回以上?」(AG2の主張試行回数が上限mに達したか) ──yes──┐
                                          no                                                        │
                                          ↓                                                         │
                                        AG2「主張が作れるか」                                        │
                                          no  ───────────────────────────────────────────────────────┤
                                          yes ↓                                                     │
                                          主張(AG2) → [Argumentation Model]                          │
                                          ↓                                                         │
                                        「主張がjustified?」(2つ目、AG2の主張に対する判定)            │
                                          yes → 最終回答 → End                                       │
                                          no  → 「主張m回以上?」(AG2)に戻る（AG2がリトライ）          │
                                                                                                     ↓
                                                                                            「統合」→「回数リセット」
                                                                                                     ↓
                                                                                  「プロトコル周以上?」に戻る（次ラウンド）
```

このように、ラウンド上限到達チェック（「プロトコル周以上?」）がループの先頭で他のどの判定
よりも先に、無条件で行われる構造になっているため、旧ワークフローで発生していた
「ラウンド上限到達の判定が、別の判定（主張可否）に競合して無視される」という
カテゴリのバグ自体が構造的に発生し得なくなる。

### 現行実装とのポイントの違い

- **AG1とAG2が同時に攻撃合戦をするのではなく、AG1がリトライしてjustifiedになるまで
  粘り、ダメならAG2にバトンタッチしてAG2がリトライする**という、明確な順番制・
  ハンドオフ構造になる。
- 「主張が作れるか」がno（主張を生成できない）の場合は、「主張n回以上」のyesと同じ扱いで
  次の担当（AG2）に進む。
- AG1・AG2どちらかの主張が`justified`になった時点で、相手の番を待たずに即終了する。
- 両者ともリトライを使い切ってもjustifiedにならなければ「統合」→「回数リセット」して
  次のラウンドへ進む（ここは現行の`add_integrated_rule`相当）。
- 「Argumentation Model」内部（現行のB/C/D論証によるrebut/undercutのやり取り）は
  この再設計の対象外で、そのまま使う。ただし1.で指摘した`validate_b_defeats_c`の
  reverse判定の問題はこの内部に残るため、別途修正が必要。

### 実装方針（確定・実装済み）

- AG1用(n)・AG2用(m)の上限値は**分離しない**ことに決定。`main_attempt_count`/
  `max_main_argument_attempts`は既存のまま維持する（ハンドオフ時に`advance_to_ag2`が
  `main_attempt_count`を0にリセットする既存の挙動により、AG1・AG2は元々別々の予算を
  同じ上限値で使っていたため、分離する実益がないと判断）。
- 「統合」フェーズ（`extract_warrants → generalize → integrate → add_integrated_rule`）
  の内容は変更せず、既存ロジックをそのまま再利用する。
- 変更したのは「ラウンド上限到達チェック」の位置のみ：新規ルーティング関数
  `route_round_entry`（[edges.py](../src/agent/edges.py)）を追加し、`START`直後と
  `add_integrated_rule`直後の両方から呼ぶ。`state.debate_round > state.max_turns`なら
  主張可否判定を経由せず`finalize_fallback`（→`generate_final_answer`）に直行する。
  旧`finalize_mode`フィールドと旧`route_after_add_integrated_rule`は削除した。
- `finalize_fallback`は1節の修正時点で既に「直前のmain argumentがあればそれを、
  なければ`integrated_rules`の最後の要素を土台にする」形になっており、そのまま使える。

---

## 3. 用語の統一（実装済み）

フローチャート上の「Argumentation Model」という呼称と、現行コードの命名が一致していな
かったため、関数名・ファイル名まで含めてリネームした。

### 対応表（旧 → 新）

| 旧 | 新 |
|---|---|
| `src/agent/defeats.py` | `src/agent/argumentation_model.py` |
| `run_defeat_subgraph()` | `evaluate_attack()` |
| `DefeatSubgraphResult` | `AttackEvaluation` |
| `run_strict_defeat_subgraph()` / `StrictDefeatSubgraphResult` | 削除（1節の修正で不要化） |
| ログ接頭辞 `[defeat_subgraph]` | `[argumentation_model]` |

`attack_from_metadata`/`AttackMatch`/`relation`/`BlockerGenerator`/`TargetField` は
「subgraph」を含まない名称のため変更していない。`o_defeat_a`/`p_counter_b`/
`validate_b_defeats_a`/`validate_c_defeats_b`/`validate_b_defeats_c`等のノード名・
`justified`/`overruled`/`defensible`等のステータス名も変更していない（フローチャートの
「Argumentation Model」はこれらのノード群をまとめた概念であり、個々のノード名自体に
「subgraph」という語は含まれていなかったため）。

呼び出し側（`src/agent/nodes.py`）と既存テスト
（`tests/unit_tests/test_defeat_subgraphs.py`, `test_undercut_logging.py`）も
新名称に追従済み。
