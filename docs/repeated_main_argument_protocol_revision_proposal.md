# 主張ループ化（repeated main argument）プロトコル修正案

## 0. 背景・要望

現状のプロトコルは、各 round で

1. AG1 が main argument A を1回だけ生成し、そのスレッド（attack/defense）が走る。
2. スレッドの結果が `justified` でなければ、（AG1 が再度主張する機会を与えずに）即座に AG2 の main thread に切り替わる。
3. AG2 のスレッドも `justified` でなければ、（AG2 が再度主張する機会を与えずに）即座に統合（extract_warrants → generalize → integrate）に進む。

という「各エージェント1主張・1スレッドのみ」の構成になっている。

これを次のように変更したい。

1. **AG1**: あるメインスレッドの結果が `justified` 以外（`overruled` / `defensible`）で決まったとき、AG2 に移る前に、AG1 に**別の main argument**を出させる。これを AG1 の `can_generate_main` が `NO`（もう新しい主張がない）を返すまで繰り返す。`NO` になった時点で初めて AG2 に手番を渡す。
2. **AG2**: 同様に、AG2 のメインスレッドの結果が `justified` 以外で決まったとき、統合フェーズに進む前に、AG2 に別の main argument を出させる。AG2 の `can_generate_main` が `NO` を返すまで繰り返す。`NO` になった時点で初めて統合フェーズに進む。
3. **non-repetition rule**: 現状「2周目（revision round = `integrated_rules` がある round）」の main argument 生成時にしか与えていない non-repetition 指示（「前回の main argument を繰り返すな」）を、**同一ラウンド内での2回目以降の main argument 生成**にも与える。

いずれも `justified` で終わったスレッドがあれば、その時点で即座に debate を終了し最終回答を生成する点は変更しない（合意成立を最優先する点は不変）。

---

## 1. 現状の状態遷移（要約）

```
can_generate_main(AG1)
  ├─ available=NO  → finish                       ← (A) 全体終了
  ├─ finalize_mode → finalize_fallback
  └─ available=YES → o_defeat_a (A生成)

o_defeat_a … validate_b_defeats_a … p_counter_b … validate_c_defeats_b … validate_b_defeats_c
  └─ complete_thread(status)
       ├─ status == "justified" → generate_final_answer            ← debate 終了（合意）
       └─ status in {overruled, defensible}
            ├─ key=="ag1" && ag2_thread_status is None
            │     → current_proponent=AG2 に切替 + 状態リセット      ← (B) AG2 へ強制移行
            └─ それ以外 → 何もしない

route_after_thread
  ├─ current_thread_status == "justified" → generate_final_answer
  ├─ ag1_thread_status と ag2_thread_status が両方 not None
  │     → extract_warrants（統合フェーズへ）                          ← (C) 統合へ強制移行
  └─ else → can_generate_main
```

- (A): AG1 が一度も主張できない場合、即 `finish`（degenerate ケース）。
- (B): AG1 のスレッドが `justified` 以外で終わった**瞬間**に AG2 に切替。AG1 はリトライできない。
- (C): AG2 のスレッドが `justified` 以外で終わった**瞬間**に統合へ。AG2 はリトライできない。

---

## 2. 新しい状態遷移（提案）

```
can_generate_main(current_proponent)
  ├─ available=NO
  │     ├─ current_proponent == AG1 → advance_to_ag2 → can_generate_main(AG2)
  │     └─ current_proponent == AG2
  │           ├─ ag1_main_argument と ag2_main_argument が両方 not None
  │           │     → extract_warrants（統合フェーズへ）
  │           └─ どちらかが None → finish（degenerate ケース。現状(A)相当）
  ├─ finalize_mode → finalize_fallback
  └─ available=YES → o_defeat_a (新しい main 生成)

o_defeat_a … validate_b_defeats_a … p_counter_b … validate_c_defeats_b … validate_b_defeats_c
  └─ complete_thread(status)
       ├─ status == "justified" → generate_final_answer            ← debate 終了（合意）
       └─ status in {overruled, defensible}
            → （proponent 切替も統合への遷移も行わない。記録だけ更新）

route_after_thread
  ├─ current_thread_status == "justified" → generate_final_answer
  └─ else → can_generate_main(同じ current_proponent で再試行)
```

ポイント:

- **proponent の切替**と**統合への遷移**は、これまで `complete_thread` / `route_after_thread` が「スレッド結果」に基づいて決めていたが、新設計では `can_generate_main` の `available=NO`（=「もう新しい主張がない」）に基づいて決める。
- `route_after_thread` は「`justified` なら終了、それ以外なら同じ proponent で `can_generate_main` に戻る」だけになり、大幅に単純化される。
- AG1 / AG2 とも「`justified` になるまで」または「`can_generate_main` が `NO` を返すまで」、同じ proponent のまま main argument を出し続けるループになる。

---

## 3. ノード・エッジの変更内容

### 3.1 新規ノード `advance_to_ag2`

AG1 が `can_generate_main` で `NO` を返した（=もう新しい main argument がない）ときに、AG2 の手番へ切り替えるための状態リセットを行うノード。現状 `complete_thread` 内にあった「AG2 への切替」ブロック（[nodes.py:133-152](../src/agent/nodes.py#L133-L152)）をほぼそのまま移植する。

```python
async def advance_to_ag2(state: Any) -> dict[str, Any]:
    """AG1 がこれ以上 main argument を生成できなくなったとき、AG2 の手番に切り替える."""
    return {
        "current_proponent": "AG2",
        "current_opponent": "AG1",
        "active_agent": "AG2",
        "current_argument": None,
        "current_thread_status": None,
        "main_attempt_count": 0,
        "b_argument": None,
        "c_argument": None,
        "d_argument": None,
        "b_argument_id": None,
        "c_argument_id": None,
        "d_argument_id": None,
        "b_defeats_a": None,
        "c_defeats_b": None,
        "b_defeats_c": None,
        "c_strictly_defeats_b": None,
        "debate_stage": "ag2_main_thread",
    }
```

グラフ上は `advance_to_ag2 → can_generate_main` の無条件エッジを1本追加するだけでよい（`can_generate_main` は `state.current_proponent` を見て動くため）。

### 3.2 `complete_thread` の簡略化（[nodes.py:98-153](../src/agent/nodes.py#L98-L153)）

`status in {"defensible", "overruled"}` のときに proponent を AG2 へ切替していたブロックを削除する。`{key}_thread_status` の更新、`learned_findings` / `{key}_revision_context` の更新（= non-repetition 指示の元データ）は維持する。

```python
def complete_thread(
    state: Any,
    status: str,
    extra_history: list[ArgumentRecord] | None = None,
) -> dict[str, Any]:
    key = "ag1" if state.current_proponent == "AG1" else "ag2"
    main_id = state.current_argument.id if state.current_argument else None
    records = _annotate_main_status(
        [*_records(state), *(extra_history or [])], main_id, status
    )
    update: dict[str, Any] = {
        "current_thread_status": status,
        "argument_records": records,
        "dialogue_history": dialogue_history(records),
        f"{key}_thread_status": status,
    }

    finding = thread_finding(state, status)
    if finding is not None and finding not in state.learned_findings:
        update["learned_findings"] = [*state.learned_findings, finding]
        update[f"{key}_revision_context"] = finding

    if status == "justified":
        update["justified_argument"] = (
            state.current_argument.argument if state.current_argument else None
        )
        update["justification_status"] = f"{key}_main_justified"
        update["consensus_reached"] = True
    elif status == "overruled":
        update["justification_status"] = f"{key}_main_overruled"

    # proponent 切替・統合への遷移は route_after_can_generate_main 側で
    # can_generate_main の available=NO を見て判断するため、ここでは行わない。
    return update
```

### 3.3 `route_after_can_generate_main` の変更（[edges.py:8-16](../src/agent/edges.py#L8-L16)）

```python
def route_after_can_generate_main(state: Any) -> str:
    """主張生成の可否判定後の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.main_argument_available is False:
        if state.current_proponent == "AG1":
            return "advance_to_ag2"
        return "extract_warrants"
    if state.finalize_mode:
        return "finalize_fallback"
    return "o_defeat_a"
```

- `current_proponent == "AG1"` で `NO` → 必ず `advance_to_ag2`（AG1 が一度も主張できなかった場合も含む。AG2 にチャンスを与える）。`finalize_mode` のチェックより先にこの分岐が評価されるため、AG1 が `NO` の場合はラウンド上限に関わらず AG2 に手番を渡す。
- `current_proponent == "AG2"` で `NO` → 常に `extract_warrants`（統合）へ。AG1・AG2 がともに一度も main argument を生成できていない degenerate ケースは、`extract_warrants` 側の既存チェック（`ag1_main_argument is None or ag2_main_argument is None` → `{"error": ...}`）に委ね、`route_after_synthesis_step` 経由で `finish_with_error` になる。新たな特別分岐は設けない。

### 3.4 `route_after_thread` の変更（[edges.py:72-80](../src/agent/edges.py#L72-L80)）

```python
MAX_MAIN_ARGUMENT_ATTEMPTS = 2  # 1ラウンド・1 proponent あたりの main argument 試行回数の上限（安全装置）


def route_after_thread(state: Any) -> str:
    """1スレッド分の議論終了後、次の遷移先を決める."""
    if state.error:
        return "finish_with_error"
    if state.current_thread_status == "justified":
        return "generate_final_answer"
    # justified 以外（overruled / defensible）→ 試行回数の上限に達していなければ
    # 同じ proponent に別の main argument を試させる。
    if state.main_attempt_count < MAX_MAIN_ARGUMENT_ATTEMPTS:
        return "can_generate_main"
    # 上限に達した場合は can_generate_main を呼ばず、available=NO のときと同じ遷移を行う。
    if state.current_proponent == "AG1":
        return "advance_to_ag2"
    return "extract_warrants"
```

「両エージェントのスレッドが完了したら統合へ」という分岐は不要になる（3.3 の `route_after_can_generate_main` 側に移った）。

### 3.5 `workflow.py` のグラフ定義変更（[workflow.py:125-238](../src/agent/workflow.py#L125-L238)）

- `.add_node("advance_to_ag2", advance_to_ag2)` を追加。
- `can_generate_main` の条件分岐に `"advance_to_ag2": "advance_to_ag2"` を追加し、`"finalize_fallback"`/`"finish"`/`"finish_with_error"`/`"o_defeat_a"`/`"extract_warrants"` も含めた分岐先一式を `route_after_can_generate_main` の戻り値に対応させる（`"extract_warrants"` は現在 `route_after_thread` 側にしかないため、`can_generate_main` の分岐先に新規追加）。
- `.add_edge("advance_to_ag2", "can_generate_main")` を追加。
- `route_after_thread` の条件分岐先に `{"generate_final_answer": ..., "can_generate_main": ..., "advance_to_ag2": ..., "extract_warrants": ..., "finish_with_error": ...}` を設定する（§3.4 の上限到達時の遷移先を含む）。

### 3.6 新規 state フィールド `main_attempt_count`

1ラウンド・1 proponent あたりの main argument 試行回数（安全装置、§3.4）をカウントするためのフィールドを `State`（[workflow.py](../src/agent/workflow.py)）に追加する。

```python
main_attempt_count: int = 0
```

- **インクリメント**: `can_generate_main` が `available=True` で新しい main argument を実際に生成したとき、`+1` する。
- **リセット**:
  - `advance_to_ag2`（AG1 → AG2 への切替時）で `0` に戻す（§3.1 のコード参照）。
  - `add_integrated_rule`（次ラウンド開始時、`current_proponent` を `AG1` に戻す箇所）で `0` に戻す。

これにより、「AG1 が同ラウンド内で最大 `MAX_MAIN_ARGUMENT_ATTEMPTS`（=2）回まで main argument を試す → 上限に達したら AG2 へ」「AG2 も同様に最大2回 → 上限に達したら統合へ」という安全装置が、`can_generate_main` の `NO` 判定とは独立に機能する。

---

## 4. プロンプト変更：non-repetition rule の適用範囲拡大

### 4.1 現状（[prompts.py:296-348](../src/agent/prompts.py#L296-L348) `main_instruction`）

`<revision_context>` ブロック（non-repetition 指示を含む）は `state.integrated_rules`（= `rules`）が非空のとき、つまり**2周目以降の revision round** にしか出ない。

`ag{1,2}_revision_context` 自体は `complete_thread`（[nodes.py:116-119](../src/agent/nodes.py#L116-L119)）で、スレッドが `overruled`/`defensible` になるたびに「直前の main argument は〜で defeat された。同じ主張を繰り返すな」という文言として設定されている。つまり**データはラウンド1の時点でも既に存在する**が、`main_instruction` が `rules` 非空のときしか参照していない。

### 4.2 変更後

`revision_context`（現在の proponent に対応するもの）が存在する場合は、`integrated_rules` の有無に関わらず `<revision_context>` ブロックを出す。`<integrated_rules>` ブロックと「Ground your NEW main argument in the integrated rules below.」の文言は `rules` が非空の場合のみ追加する。

```python
def main_instruction(state: Any) -> str:
    issue = state.question
    rules = getattr(state, "integrated_rules", []) or []
    debate_round = getattr(state, "debate_round", 1)
    lines = [
        "<task>",
        f"Round {debate_round}. Construct your main argument for the Issue.",
        "</task>",
        "",
        "<issue>",
        issue,
        "</issue>",
    ]

    revision_context = (
        getattr(state, "ag1_revision_context", None)
        if getattr(state, "current_proponent", "AG1") == "AG1"
        else getattr(state, "ag2_revision_context", None)
    )

    if revision_context or rules:
        block = ["", "<revision_context>"]
        if revision_context:
            block += [revision_context, ""]
        else:
            block += ["This is a revision round.", ""]
        block.append(
            "Do not repeat the same main argument unless the defeating reason is resolved."
        )
        if rules:
            block.append("Ground your NEW main argument in the integrated rules below.")
        block.append("</revision_context>")
        lines += block

        if rules:
            lines += [
                "",
                "<integrated_rules>",
                *[f"- {rule}" for rule in rules],
                "</integrated_rules>",
            ]

    lines += [
        "",
        "<response_contract>",
        "If you can construct a main argument, set can_generate=YES and include Argument.",
        "Otherwise, set can_generate=NO and omit Argument.",
        "</response_contract>",
    ]
    return "\n".join(lines)
```

挙動の変化:

| ケース | rules | revision_context | 旧 | 新 |
|---|---|---|---|---|
| Round 1, 1回目の main | 空 | None | なし | なし |
| Round 1, 2回目以降の main（直前 thread が overruled/defensible） | 空 | あり | なし | `<revision_context>`（integrated_rules 言及なし） |
| Round ≥2, 1回目の main | 非空 | あり（前ラウンド由来） | `<revision_context>` + `<integrated_rules>` | 同じ |
| Round ≥2, 1回目の main（revision_context が何らかの理由で未設定） | 非空 | None | `<revision_context>`（"This is a revision round."）+ `<integrated_rules>` | 同じ |

---

## 5. エッジケースの確認（フロー図で確認済み）

1. **AG1 が一度も主張できない（`can_generate_main` が初回から NO）**
   旧: 即 `finish`。
   新: `advance_to_ag2` で AG2 に手番を渡す。AG2 が主張できれば AG2 のループが走る。AG2 も一度も主張できなければ次項。

2. **AG2 が一度も主張できない（`can_generate_main` が初回から NO）**
   常に `extract_warrants`（統合）へ進む。AG1 も一度も主張できていなかった場合（= 両者とも main argument ゼロの degenerate ケース）は、`extract_warrants` 内の既存チェックが `{"error": "AG1またはAG2のmain argumentが見つかりません"}` を返し、`route_after_synthesis_step` 経由で `finish_with_error` になる。特別な分岐は追加しない。
   AG1 のみ main argument を持っていた場合は、`extract_warrants` がそのまま AG1 側の warrant のみで処理を続行する（既存ロジックのまま。AG2 側の warrant 抽出で例外になる場合は既存の `except` 節でエラー化される）。

3. **`finalize_mode`（ラウンド上限到達）との関係**
   `available=NO` の分岐を `finalize_mode` チェックより先に評価するため、AG1 が `NO` の場合はラウンド上限に関わらず常に `advance_to_ag2`（AG2 にチャンスを与える）。`available=YES` のときだけ `finalize_mode` を見るため、`add_integrated_rule` 直後（`current_proponent=AG1`）に `finalize_mode=True` の round では、AG1 が1つ main を生成できれば `finalize_fallback` に直行する（ループに入らない）。これは現状と同じ。
   「AG1 が `finalize_mode` の round で `NO` を返したら AG2 に fallback を作らせる」という新しい挙動は、フロー図のとおり意図した拡張として確定。

4. **ループの停止保証**
   AG1 / AG2 の「`justified` になるまで or `can_generate_main` が `NO` を返すまで」のループは、`main_instruction` に追加される non-repetition 指示と、LLM 自身が "新しい main argument がもうない" と判断して `can_generate=NO` を返すことに依存する。理論上は1ラウンド内で AG1 が何度も `YES` を返し続ける可能性があり、ラウンド全体のターン数上限（`max_turns`）は**ラウンド数**にしか効いていないため、1ラウンド内の主張回数には上限がない。
   → 安全策として、1ラウンド・1 proponent あたりの main argument 試行回数に上限 `MAX_MAIN_ARGUMENT_ATTEMPTS = 2` を設け、超えたら `can_generate_main` を呼ばずに強制的に `advance_to_ag2` / `extract_warrants` に進める（§3.4, §3.6 で確定）。

---

## 6. 既存テストへの影響

- [tests/unit_tests/test_main_argument_availability.py:101-127](../tests/unit_tests/test_main_argument_availability.py#L101-L127)
  `test_can_generate_main_finishes_when_no_new_main_argument` は `current_proponent` 未指定（デフォルト `"AG1"`）で `available=False` のとき `route_after_can_generate_main(...) == "finish"` を期待している。
  → 新設計では AG1 かつ `available=False` は `"advance_to_ag2"` になるため、このテストの期待値を更新する必要がある。AG2 側で `finish` になるケース（`ag1_main_argument`/`ag2_main_argument` が両方 None）の新規テストも追加する。

- [tests/unit_tests/test_main_argument_availability.py:129-157](../tests/unit_tests/test_main_argument_availability.py#L129-L157)
  `test_can_generate_main_routes_to_generation_when_available` は `available=True, finalize_mode=False` で `"o_defeat_a"` を期待。変更なし（影響なし）。

- `main_instruction` 関連のテスト（[test_main_argument_availability.py:31-98](../tests/unit_tests/test_main_argument_availability.py#L31-L98)）は `rules` が空 / 非空の2ケースのみで `revision_context` 未設定の状態を前提にしている。`revision_context` が設定された状態（同ラウンド内リトライ）でのテストケースを追加する。

- 統合フローのテスト（route_after_thread / complete_thread 周辺、`tests/unit_tests/test_main_argument_availability.py` 以外にもあれば）で、「AG1 thread が overruled で終わったら AG2 に切り替わる」という旧仕様を直接アサートしている箇所があれば、新仕様（同じ proponent に戻る）に合わせて修正する。

---

## 7. 実装ステップ（チェックリスト）

1. `workflow.py`（State 定義）
   - [ ] `main_attempt_count: int = 0` を `State` に追加（§3.6）。
2. `nodes.py`
   - [ ] `advance_to_ag2` ノードを追加（§3.1）。`main_attempt_count` を `0` にリセットする。
   - [ ] `can_generate_main` で、新しい main argument を生成した（`available=True`）ときに `main_attempt_count` を `+1` する（§3.6）。
   - [ ] `complete_thread` から proponent 切替ブロックを削除（§3.2）。
   - [ ] `add_integrated_rule` で `main_attempt_count` を `0` にリセットする（§3.6）。
3. `edges.py`
   - [ ] `route_after_can_generate_main` を §3.3 の内容に変更。
   - [ ] `route_after_thread` を §3.4 の内容（`MAX_MAIN_ARGUMENT_ATTEMPTS = 2` の上限チェックを含む）に変更。
4. `workflow.py`（グラフ定義）
   - [ ] `advance_to_ag2` ノードをグラフに追加し、エッジを接続（§3.5）。
   - [ ] `can_generate_main` の分岐先に `"advance_to_ag2"` と `"extract_warrants"` を追加。
   - [ ] `route_after_thread` の分岐先に `"advance_to_ag2"` / `"extract_warrants"` を追加し、`"finish"` を削除。
5. `prompts.py`
   - [ ] `main_instruction` を §4.2 の内容に変更。
6. テスト
   - [ ] §6 の既存テスト更新。
   - [ ] AG1 ループ（複数 main → advance_to_ag2）の統合テストを追加。
   - [ ] AG2 ループ（複数 main → extract_warrants）の統合テストを追加。
   - [ ] `main_attempt_count` が上限（2）に達したときに `can_generate_main` を呼ばずに次へ遷移することを確認するテストを追加。
   - [ ] 同ラウンド内リトライ時の `main_instruction` に non-repetition が出ることを確認するテストを追加。

§5-1〜5-3、および「統合 → 次ラウンドのAG1へ戻る既存の多ラウンド構造は変更しない」点、§5-4（試行回数の上限＝2）は、フロー図でのレビューと協議により確定済み。オープンな論点は残っていない。
