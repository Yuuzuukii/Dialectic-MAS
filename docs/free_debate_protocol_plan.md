# 自由討議（Free Debate）ベースライン 実装計画書

## 目的

現在の比較は「schema（構造化出力）」と「no_schema（自由記述だが弁証法プロトコルは同一）」の2条件のみである。
弁証法プロトコル（rebut/undercut/justified等の状態遷移、warrant抽出、integrated rule生成）を導入すること自体の優位性を示すには、
**弁証法プロトコルを使わない、素朴な多エージェント対話**を第3のベースラインとして追加する必要がある。

先生のコメント:
> No schemaとの比較だけでなく，弁証法プロトコルを使わない自由議論の場合とも比較しましょう．そうするとお互い主張し合うので，合意できない可能性がありますが，
> 弁証法プロトコルと同じ繰返し回数で終了し，最終案を作成させましょう．できれば，multiagentのノーマルな対話プロトコルがあればそれを使う．

採用する文献: Du et al., "Improving Factuality and Reasoning in Language Models through Multiagent Debate" (arXiv:2305.14325, ICML 2024)。
ローカルに公式実装を取得済み: `/Users/yuzuki/Desktop/llm_multiagent_debate`。

## 参照実装の調査結果

`gsm/gen_gsm.py` / `biography/gen_conversation.py` を確認した。両タスクで共通する設計:

- `agents`体（論文では3）が、それぞれ**独立した会話履歴**（`agent_contexts[i]`）を持つ。
- `rounds`回のラウンドをループする。各ラウンド・各エージェントについて:
  - ラウンド0（最初）は素のタスク質問のみ。
  - ラウンド1以降は、**他の全エージェントの直前ラウンドの発言**を `Agent response: \`\`\`...\`\`\`` という形でそのまま提示し、
    「これらを参考に回答を更新してください」と指示する（`construct_message`、[gen_gsm.py:6-19](../../llm_multiagent_debate/gsm/gen_gsm.py)）。
  - 構造化出力・攻撃/防御ラベル（rebut/undercut等）は一切無い。各エージェントは自分の会話履歴に追記し続けるだけ。
- **最終回答の決定はタスクによって扱いが異なる**:
  - GSM/MMLU（正解が1つに決まるタスク）: 生成スクリプトでは何もせず、各エージェントの最終ラウンドの回答から正規表現で答えを抜き出し、`eval_gsm.py`/`eval_mmlu.py`側で事後的に**多数決**（`most_frequent`、[eval_gsm.py:87,109-119](../../llm_multiagent_debate/gsm/eval_gsm.py)）を取って精度を計算する。
  - biography（自由記述・正解が1つに決まらないタスク）: **統合や多数決は一切無い**。`eval_conversation.py`は各エージェントの最終回答を個別に事実確認し、精度を平均するだけで、複数エージェントの回答を1つにまとめるステップ自体が存在しない（[eval_conversation.py:69-112](../../llm_multiagent_debate/biography/eval_conversation.py)）。biographyタスクの`final=True`分岐（[gen_conversation.py:42-43](../../llm_multiagent_debate/biography/gen_conversation.py)）も、各エージェントが**自分の回答を**他者の回答を見て更新するだけで、エージェント間の統合ステップではない。
  - **本研究の「正解のない論題を議論する」設定は、原論文ではbiography（自由記述タスク）に近いが、biographyにはそもそも複数回答を1つに統合する仕組みが無い。** つまり後述の「最終ラウンド後に統合プロンプトで1つの回答を生成する」設計は、多数決の置き換えではなく、**原論文がカバーしていない部分を新規に設計するもの**である。

### このリポジトリへの適用上の注意（重要な相違点）

Du et al.の設定は「同一タスクに対しN(≥3)体の同質なエージェントが**独立に**回答し、多数決で決める」という、正解のある問題（数学・伝記の事実性）向けの設計である。
一方、本研究は「**固定された対立スタンスを持つ2エージェント**（AG1/AG2）が、正解のない論題について議論する」設定であり、多数決は意味を持たない。
したがって、以下の点は元実装からの**意図的な改変**として明記する。

- エージェント数: 3→**2**（既存のAG1/AG2スタンス設計を維持）。2体だと多数決は機能しない（1票対1票で決まらない）ため、**多数決は採用しない**。
- 最終回答の決定: 多数決ではなく、**最終ラウンド後に明示的な統合プロンプトで1つの回答を生成**（既存の`FINAL_ANSWER_NO_CONSENSUS_SYSTEM`相当の役割）。ジャッジエージェントの追加も検討したが、既存のAG1/AG2 2エージェント構成をそのまま保てる統合プロンプト方式を採用する。
- ラウンド数: 固定`rounds`→既存の`max_turns`と揃え、schema/no_schemaと同じ回数で打ち切る
- ラウンド内の発話順序: Du et al.と同じ**並列（simultaneous-talk）**方式。各ラウンドでAG1・AG2は「前ラウンド終了時点の履歴」を見て**同時に**主張を生成する（同一ラウンド内で相手の発言を見てから自分が発言する、という順序依存は持たせない）。
- **system messageの追加**: 原論文4タスク（math/gsm/mmlu/biography、いずれも`gen_*.py`で確認済み）は**system roleのメッセージを一切使わない**（`{"role": "user", "content": "<task>"}`から始まる、無人格な同質エージェント）。本実装は`agent_system(stance, agent, FREE_DEBATE_TURN_SYSTEM)`で`SystemMessage`（identity + stance + style指示）を付与する。これは必然的な改変であり、原論文の「同じ問題を解く同質なエージェント」には人格付けが不要だが、本研究の「固定対立スタンスを持つAG1/AG2」はsystem messageでスタンスを明示しない限りそもそも対立する立場で議論させられないため。

## 既存実装との関係

既存グラフ（[workflow.py:133-249](../src/agent/workflow.py)）はrebut/undercut/justified/overruled/defensibleという弁証法特有の状態遷移を持つ。
自由討議はこれらの概念を一切使わないため、**既存グラフを拡張せず、別の小さなグラフを新設する**。
既存グラフに分岐を追加すると、弁証法ロジックとの混在によりプロンプト・状態の矛盾が混入するリスクが高い（CLAUDE.mdの「矛盾した指示を消すことが最重要」という方針に反する）。

## 実装方針

### 1. 新規モジュール `src/agent/free_debate.py`

- 専用の軽量 `State`（dataclass）を定義する。既存`State`からの流用は最小限（`question`, `agent1_stance`, `agent2_stance`, `max_turns`）に留め、
  `rebut/undercut/justified`系のフィールドは持たない。

```python
@dataclass
class FreeDebateState:
    question: str
    agent1_stance: str
    agent2_stance: str
    max_turns: int = _int_env("MAX_TURNS", 5)
    round: int = 1
    history: list[BaseMessage] = field(default_factory=list)       # LLM再送用（Du et al.同様、エージェント別ではなく対話全体を共有）
    dialogue_history: list[dict[str, Any]] = field(default_factory=list)  # ログ用
    final_answer: str | None = None
    error: str | None = None
```

  - Du et al.はエージェントごとに**別々の会話履歴**を持つが、本実装は既存システムの`dialogue_history`ログ形式（[evaluation.pyの`_format_turn`](../src/eval/evaluation.py)がそのまま読める形）に揃えるため、
    **両エージェントが同じ対話履歴を共有し、互いの発言を交互に追記していく**形にする（既存no_schemaの履歴の持ち方に近い）。実質的には Du et al. の「他者の発言を提示する」操作と等価。

- ノード: `ag_turns`（AG1・AG2を1ノード内で並列に呼び出す）の1つのみ。
  - 各ラウンド開始時点の`state.history`（前ラウンドまでの両者の発言）はAG1・AG2に**同一の入力**として渡す。AG1向け呼び出しとAG2向け呼び出しは`asyncio.gather`等で並列実行し、互いの「このラウンドの新しい発言」を見せない（Du et al.の`agent_contexts_other`が常に「前ラウンドまで」の発言である構造と同じ）。
  - 両者の出力が揃った時点で、両方を同時に`state.history`/`dialogue_history`へ追記する。
  - 共通ヘルパ `_turn_prompt(state, agent, opponent)`:
    - ラウンド1（最初の発言）: 「論題とあなたのスタンスを述べ、最初の主張をしてください」
    - ラウンド2以降: 「これまでの対話履歴（相手の前ラウンドまでの発言を含む）を踏まえて、自身の主張を更新してください」（Du et al.の`construct_message`の2エージェント・並列版）
  - プロンプトは新規の`PromptTemplates`エントリを追加するが、既存の`_GROUNDING`（[prompts.py:23-28](../src/agent/prompts.py)）は流用してよい（スタンスに基づいて議論する、という土台は弁証法と共通）。
    `_ARGUMENTATION_RULES`・`_SCHEMA_OVERLAY`・`_ATTACK_TYPES`・`_PROTOCOL_FLOW`は**使わない**（rebut/undercut等の概念を持ち込まないため）。

- ループ制御: `route_after_ag_turns`
  - `state.round < state.max_turns` なら `round += 1` して `ag_turns` に戻る。
  - `state.round >= state.max_turns` なら `finish` へ。

- `finish`（最終回答の決定。**追加のLLM呼び出しは行わない**）:
  - 原論文（math/gsm/mmlu/biography全タスク）は固定ラウンドの「主張→修正」を繰り返すだけで生成スクリプトは終了し、追加のLLM呼び出しは一切無い。最終ラウンドの各エージェントの発言がそのまま結果として保存され、複数エージェントの回答をどう扱うか（多数決／個別採点）は評価スクリプト側に委ねられる。
  - 本研究では2エージェント構成で多数決が機能しないため、当初は「両者の主張を踏まえて1つの回答に統合する」専用LLM呼び出しを追加する設計を検討したが、**原論文に忠実に、追加の統合ステップは設けない**ことに決定した。
  - 代わりに、**最終ラウンドのAG1の発言を、そのまま`final_answer`として扱う**。生成主体をAG1に固定する理由は変わらず、既存の弁証法プロトコルで合意に至らない暫定回答が常にAG1のスタンスで生成されること（[arguments.py:300-309](../src/agent/arguments.py)）に倣う。

- `graph_free_debate = StateGraph(FreeDebateState)...compile(name="Free Debate")`としてentry pointを分離する。グラフは`ag_turns`（ループ）→`finish`のみの2ノード構成。

### 2. 早期終了（収束判定）は入れない方針を提案

ReConcileのような「各ラウンド後に収束判定して早期終了」も検討したが、まずは**Du et al.の素朴な実装に忠実に、固定ラウンド数で必ず最後まで回す**方針とする。
理由: 早期終了ロジックを入れると「どう収束を判定するか」という新たな設計・プロンプトが必要になり、弁証法プロトコルとの比較対象がぶれる。
今回の主目的は「弁証法プロトコルの構造（rebut/undercut/justified/integration）を導入する価値」を測ることなので、ベースラインはできるだけ単純にする。

**決定: 早期終了は入れない。**

### 3. ログ・実行スクリプト

既存の`schema`/`no_schema`と同じ枠組みに乗せる。

- `src/dialogue/common.py`:
  - `_run_topic_once`相当の`_run_free_debate_topic_once`を追加（`method="free_debate"`）。
    `graph`の代わりに`graph_free_debate`を呼ぶ点のみ異なる。
  - `run_free_debate_topic_once()`を公開関数として追加（`run_schema_topic_once`/`run_no_schema_topic_once`と同じ引数シグネチャ）。
  - 出力ファイル名は`output_path()`がそのまま`free_debate_<timestamp>.json`にしてくれる（method名をファイル名に埋め込む実装のため変更不要）。

- `src/dialogue/run_loop_sweep_free_debate.py`（新規、`run_loop_sweep_no_schema.py`がベース）:
  - **`max_main_argument_attempts`軸は存在しない**（自由討議にmain argument再試行の概念がないため）。
  - sweep対象は`max_turns`のみ（`PROTOCOL_MAX_TURNS = (1, 5, 10)`）の**3パターン**。
  - ディレクトリ構成は`turns{T:02d}_attempts01`（既存パターンと揃える）。`eval_sweep.py`の`turns(\d+)_attempts\d+`正規表現がそのまま通る。

### 4. 評価スクリプトの対応

- `src/eval/evaluation.py`:
  - `build_eval_input`の`mode`に`"free_debate"`を追加できるようにする。
  - 新規`FREE_DEBATE_METHOD_CONTEXT`を追加（「この実行はディベートプロトコルも構造化出力も使わない、素朴な多エージェント対話。各ターンは自由文。攻撃ラベル(rebut/undercut)の概念は無い」と明記）。
  - `_format_turn`はno_schemaと同じ自由文表示で良い（属性追加不要、文字列ならそのまま表示される実装のため）。

- `src/eval/eval_sweep.py`:
  - `mode = "no_schema" if method in {...} else "schema"`の判定（[eval_sweep.py:188-189](../src/eval/eval_sweep.py)）を3分岐に拡張:
    ```python
    if method in {"no_schema", "no-schema"}:
        mode = "no_schema"
    elif method == "free_debate":
        mode = "free_debate"
    else:
        mode = "schema"
    ```
  - 集計（`_aggregate_by_group`）は現状turns単位のみで、method区別をしていない点は既知の課題（[既存の会話で指摘済み]）。3手法比較時にはここも見直しが必要。

- `src/eval/plot_sweep.py`:
  - 現在`pivot[["schema", "no_schema"]]`に固定（[plot_sweep.py:53-56](../src/eval/plot_sweep.py)）。`free_debate`列も含めて3本の棒グラフにする変更が必要。

## 決定事項（確定）

1. **ディレクトリ命名**: `turns{T:02d}_attempts01`で既存パターンと揃える（`eval_sweep.py`の正規表現をそのまま使えるようにするため）。
2. **早期終了（収束判定）**: 入れない。Du et al.に忠実に、`max_turns`まで必ず固定ラウンド数を回す。
3. **最終回答の決定方法**: 多数決・ジャッジ・追加の統合LLM呼び出しは無し。原論文に忠実に、**最終ラウンドのAG1の発言をそのまま`final_answer`とする**（生成主体をAG1に固定する理由は、提案手法の合意なし暫定回答と同じ扱いに揃えるため）。
4. **対話履歴の持ち方**: 両エージェント共有1本の履歴（既存no_schemaの履歴形式と同じ）。
5. **ラウンド内の発話順序**: AG1・AG2は各ラウンドで**並列**に生成する（同一ラウンド内で相手の発言を先に見ることはない）。

## 実装タスク一覧

1. `src/agent/free_debate.py` 新規作成（State / ノード / グラフ）
2. `src/agent/prompts.py` に自由討議用プロンプト（`FREE_DEBATE_TURN_SYSTEM`, `FREE_DEBATE_FINAL_ANSWER_SYSTEM`等）を追加
3. `src/dialogue/common.py` に `run_free_debate_topic_once` 追加
4. `src/dialogue/run_loop_sweep_free_debate.py` 新規作成
5. `src/eval/evaluation.py` に `FREE_DEBATE_METHOD_CONTEXT` と3分岐対応を追加
6. `src/eval/eval_sweep.py` の method判定を3分岐に拡張
7. `src/eval/plot_sweep.py` を3本比較（schema / no_schema / free_debate）に拡張
8. 既存topicで動作確認（1トピック・少ないラウンド数でスモークテスト）
