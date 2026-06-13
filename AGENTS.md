# AGENTS.md

このプロジェクト（Dialect-MAS）は LangGraph ベースのマルチエージェント議論システムで、
LLM は `langchain_openai` 経由で **GPT-5 / gpt-5-mini / gpt-5.4-nano**（一部 gpt-4o）を使用する。
プロンプトは [src/agent/prompts.py](src/agent/prompts.py) と
[src/agent/prompt_builders.py](src/agent/prompt_builders.py) に集約され、
LLM 呼び出しは [src/agent/llm.py](src/agent/llm.py) で `with_structured_output` を使った
構造化出力（Pydantic スキーマ）として実装されている。

以下は OpenAI 公式の
[GPT-5 Prompting Guide](https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide)
に基づくプロンプト設計のベストプラクティスである。このプロジェクトの GPT-5 系プロンプトを
書く・直すときは必ずこれに従うこと。

---

## 0. このプロジェクトでまず効くポイント（要約）

- **GPT-5 では `temperature` を渡さない**（[llm.py](src/agent/llm.py) は既に `gpt-5` 始まりでは
  temperature を除外している）。代わりに `reasoning_effort` と `verbosity` で挙動を制御する。
- プロンプト内の**矛盾した指示を消す**ことが GPT-5 では最重要。矛盾は推論トークンを浪費させる。
- 指示は **XML 風タグ**（`<persistence>`, `<context_gathering>` 等）でセクション化すると追従性が上がる。
- 構造化出力（`with_structured_output`）を使っているので、スキーマと自然言語の指示を矛盾させない。
- エージェントの「探索しすぎ／止まらない」挙動は **停止条件（early stop / escape hatch）**で制御する。

---

## 1. API パラメータ

| パラメータ | 役割 | 値と使い分け |
|---|---|---|
| `reasoning_effort` | 推論の深さ・探索量 | `minimal` / `low` / `medium`(既定) / `high`。複雑で多段なタスクは上げ、単純で速度優先なら下げる |
| `verbosity` | **最終回答の長さ**（推論長ではない） | `low` で簡潔、`high` で詳細。コード生成だけ局所的に上げるのが定石 |
| `previous_response_id` | 直前の推論コンテキスト再利用（Responses API） | ツール呼び出しをまたいで CoT を引き継ぎ、レイテンシと精度を両立 |

- `reasoning_effort` を上げる＝より自律的・粘り強い。下げる＝より速く・局所的。
- 分離可能なタスクは**複数ターンに分割**して effort を節約する。
- `verbosity` は API でグローバルに設定しつつ、特定箇所だけ自然言語で上書きできる。

---

## 2. エージェントの積極性（Agentic Eagerness）の制御

### 2-1. 積極性を下げる（速く・局所的に）

- `reasoning_effort` を下げる。
- 探索の基準を明示し、無関係なツール呼び出しを減らす。
- **ツール呼び出し回数の上限**（例: 最大2回）を決める。
- 不確実でも進める **escape hatch（逃げ道）** を与える。

```xml
<context_gathering>
Goal: Get enough context fast. Parallelize discovery and stop as soon as you can act.
Method:
- Start broad, then fan out to focused subqueries.
- In parallel, launch varied queries; read top hits per query.
- Avoid over searching for context.

Early stop criteria:
- You can name exact content to change.
- Top hits converge (~70%) on one area/path.
</context_gathering>
```

### 2-2. 積極性を上げる（自律的・粘り強く）

- `reasoning_effort` を上げる。
- **persistence パターン**でターンを途中で返さないよう指示する。

```xml
<persistence>
- You are an agent - please keep going until the user's query is completely
resolved, before ending your turn and yielding back to the user.
- Only terminate your turn when you are sure that the problem is solved.
- Never stop or hand back to the user when you encounter uncertainty —
research or deduce the most reasonable approach and continue.
- Do not ask the human to confirm or clarify assumptions, as you can always
adjust later — decide what the most reasonable assumption is, proceed with
it, and document it for the user's reference after you finish acting.
</persistence>
```

---

## 3. ツール・プリアンブル（Tool Preambles）

長時間タスクで進捗をユーザーに伝えるためのパターン。

```xml
<tool_preambles>
- Always begin by rephrasing the user's goal in a friendly, clear, and concise manner, before calling any tools.
- Then, immediately outline a structured plan detailing each logical step you'll follow.
- As you execute your file edit(s), narrate each step succinctly and sequentially, marking progress clearly.
- Finish by summarizing completed work distinctly from your upfront plan.
</tool_preambles>
```

---

## 4. 知能・指示追従の最適化

### 4-1. ステアラビリティ（操縦性）
GPT-5 は冗長度・トーン・ツール呼び出し挙動の指示に非常に敏感。指示は具体的に書けばその通り動く。

### 4-2. Verbosity の制御
- `verbosity` は**最終回答の長さ**を制御する（推論の長さではない）。
- グローバルは `low`、コードツールだけ局所的に高 verbosity、が定番。
- 長い会話では追従が薄れるため、**Markdown 等の整形指示を 3〜5 メッセージごとに再注入**する。

### 4-3. Markdown 整形
GPT-5 の API 応答は既定で Markdown を避ける。必要なら明示的に指示する：

```
- Use Markdown **only where semantically correct** (e.g., `inline code`, ```code fences```, lists, tables).
- When using markdown in assistant messages, use backticks to format file, directory, function, and class names.
- Use \( and \) for inline math, \[ and \] for block math.
```

### 4-4. 最小推論（Minimal Reasoning）
レイテンシ重視・GPT-4.1 移行組向けの `minimal` reasoning_effort。性能を保つには：
1. 回答冒頭に思考要約（箇条書き）を入れる。
2. ツールプリアンブルで継続的に進捗を出させる。
3. ツール指示を最大限に曖昧さなく書き、persistence リマインダを入れる。
4. 実行前に明示的なプランニングをさせる。

```
Remember, you are an agent - please keep going until the user's query is
completely resolved, before ending your turn and yielding back to the user.
Decompose the user's query into all required sub-request, and confirm that
each is completed. Do not stop after completing only part of the request.
Only terminate your turn when you are sure that the problem is solved.

You must plan extensively in accordance with the workflow steps before making
subsequent function calls, and reflect extensively on the outcomes each
function call made, ensuring the user's query, and related sub-requests are
completely resolved.
```

---

## 5. 指示の矛盾を避ける（GPT-5 で最重要）

矛盾した指示があると、GPT-5 は調停に推論トークンを浪費し、追従が不安定になる。

- 悪い例: 「明示的同意なしに予約するな」と「患者に連絡せず最速枠を自動割当せよ」の併存。
- 悪い例: 「常に患者プロファイルを先に参照」と「緊急時はあらゆる手順の前に EMERGENCY として
  エスカレート」の併存。

**解決策:**
- 指示の**優先順位（ヒエラルキー）を明示**する。
- 矛盾ルールに**例外条項**を足す（例: 「緊急時は lookup をせず即座に 911 案内へ」）。
- OpenAI の **prompt optimizer ツール**で矛盾・曖昧さを洗い出す。

> このプロジェクトでは、[prompts.py](src/agent/prompts.py) のルール列挙
> （「never derive...」「Use as few rules as possible」等）が増えるほど矛盾が混入しやすい。
> 新ルール追加時は既存ルールとの衝突を必ず確認すること。

---

## 6. メタプロンプティング（GPT-5 に自分のプロンプトを直させる）

```
When asked to optimize prompts, give answers from your own perspective -
explain what specific phrases could be added to, or deleted from, this prompt
to more consistently elicit the desired behavior or prevent an undesired one.

Here's a prompt: [PROMPT]

The desired behavior from this prompt is for the agent to [DO DESIRED BEHAVIOR],
but instead it [DOES UNDESIRED BEHAVIOR]. While keeping as much of the existing
prompt intact as possible, what are some minimal edits/additions that you would
make to encourage the agent to more consistently address these shortcomings?
```

---

## 7. コーディング性能の最大化

### 7-1. フロントエンド推奨スタック（参考）
- フレームワーク: Next.js (TypeScript) / React / HTML
- スタイル/UI: Tailwind CSS, shadcn/ui, Radix Themes
- アイコン: Material Symbols, Heroicons, Lucide
- アニメーション: Motion
- フォント: Inter, Geist, Mona Sans, IBM Plex Sans, Manrope

### 7-2. ゼロからの一発生成（self-reflection）
高品質な one-shot 生成には、内部ルーブリックを作らせて反復させる：

```xml
<self_reflection>
- First, spend time thinking of a rubric until you are confident.
- Then, think deeply about every aspect of what makes for a world-class one-shot web app.
  Use that knowledge to create a rubric that has 5-7 categories.
  This rubric is critical to get right, but do not show this to the user. This is for your purposes only.
- Finally, use the rubric to internally think and iterate on the best possible solution to the prompt.
  If your response is not hitting the top marks across all categories, start again.
</self_reflection>
```

### 7-3. 既存コードベースの規約に合わせる（code_editing_rules）

```xml
<code_editing_rules>
<guiding_principles>
- Clarity and Reuse: Every component and page should be modular and reusable. Avoid duplication.
- Consistency: The UI must adhere to a consistent design system.
- Simplicity: Favor small, focused components and avoid unnecessary complexity.
- Demo-Oriented: The structure should allow for quick prototyping.
- Visual Quality: Follow a high visual quality bar.
</guiding_principles>
<frontend_stack_defaults>
- Framework: Next.js (TypeScript) / Styling: TailwindCSS / UI: shadcn/ui
- Icons: Lucide / State: Zustand
- Directory: /src/app, /components, /hooks, /lib, /stores, /types, /styles
</frontend_stack_defaults>
<ui_ux_best_practices>
- Visual Hierarchy: Limit typography to 4–5 font sizes and weights.
- Color: Use 1 neutral base and up to 2 accent colors.
- Spacing: Always use multiples of 4 for padding and margins.
- State Handling: Use skeleton placeholders or animate-pulse for data fetching.
- Accessibility: Use semantic HTML and ARIA roles where appropriate.
</ui_ux_best_practices>
</code_editing_rules>
```

### 7-4. Cursor のチューニング知見
- グローバル `verbosity` は `low`、コード出力だけ高 verbosity にする。
  > "Write code for clarity first. Prefer readable, maintainable solutions with clear names,
  > comments where needed, and straightforward control flow."
- ユーザー確認より**先回りの実装**を促す（提案は承認/却下されるだけなので積極的でよい）。
- 「THOROUGH／maximize context understanding」のような過剰な指示は**ツール呼びすぎ**を招くので避け、
  代わりに控えめな停止条件を与える：

```xml
<context_understanding>
If you've performed an edit that may partially fulfill the USER's query, but you're not confident,
gather more information or use more tools before ending your turn.
Bias towards not asking the user for help if you can find the answer yourself.
</context_understanding>
```

---

## 8. エージェント型コーディングのベストプラクティス

### 8-1. 徹底検証の指示（SWE-Bench 流）
```
Always verify your changes extremely thoroughly. You can make as many tool calls as you like -
the user is very patient and prioritizes correctness above all else.
Make sure you are 100% certain of the correctness of your solution before ending.

IMPORTANT: not all tests are visible to you in the repository, so even on problems you think are
straightforward, you must double and triple check your solutions to ensure they pass edge cases
covered in hidden tests, not just the visible ones.
```

### 8-2. 探索フェーズ
```xml
<exploration>
If you are not sure about file content or codebase structure pertaining to the user's request,
use your tools to read files and gather information: do NOT guess or make up an answer.

Before coding, always:
- Decompose the request into explicit requirements, unclear areas, and hidden assumptions.
- Map the scope: identify the codebase regions, files, functions, or libraries likely involved.
- Check dependencies: frameworks, APIs, config files, data formats, versioning concerns.
- Resolve ambiguity proactively based on repo context and conventions.
- Define the output contract: deliverables, expected outputs, API responses, CLI behavior, tests.
- Formulate an execution plan: research steps, implementation sequence, testing strategy.
</exploration>
```

### 8-3. 検証フェーズ
```xml
<verification>
Routinely verify your code works as you work through the task, especially deliverables.
Don't hand back to the user until you are sure the problem is solved.
Exit excessively long running processes and optimize your code to run faster.
</verification>
```

### 8-4. ツール定義の方針
- ファイル編集は GPT-4.1 版に合わせた `apply_patch` 実装を使う。
- ツールは「4関数・端末なし」（`apply_patch` / `read_file` / `list_files` / `find_matches`）か
  「2関数・端末ネイティブ」（`run` / `send_input`）のいずれかが定石。
- ツールの説明（description）は曖昧さなく、いつ・どう呼ぶかを明記する。

---

## 9. Responses API と推論コンテキスト再利用

- `previous_response_id` で直前の推論トレースを次リクエストへ渡せる。
- 効果: Tau-Bench Retail で 73.9% → 78.2% の有意な改善。
- ツール呼び出しごとにプランを作り直さずに済み、CoT トークン節約・レイテンシ改善・精度向上。

---

## 10. 早見表

| 目的 | パラメータ/タグ | 値・アクション |
|---|---|---|
| 速く処理 | `reasoning_effort` | low / medium |
| 自律的に粘る | `reasoning_effort` | high＋`<persistence>` |
| 回答を短く | `verbosity` | low（コードだけ high） |
| 低レイテンシ | `reasoning_effort` | minimal＋明示プランニング |
| 推論再利用 | `previous_response_id` | Responses API で使用 |
| 進捗の可視化 | `<tool_preambles>` | ユーザー透明性向上 |
| 探索の暴走防止 | `<context_gathering>` | early stop / escape hatch |
| 既存規約順守 | `<code_editing_rules>` | コードベースのパターンに合わせる |
| 一発生成の品質 | `<self_reflection>` | 内部ルーブリックで反復 |
| 矛盾の除去 | （プロンプト見直し） | 優先順位の明示・例外条項・prompt optimizer |
