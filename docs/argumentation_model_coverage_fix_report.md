# schema/no_schemaの「スタンス網羅性」低迷の原因調査と修正報告

> 対象ブランチ: `feature/argumentation-model-rebuild`
> 対象実装: 対話木（dialogue tree）ベースの再帰的弁証法プロトコル（`src/agent/nodes.py`,
> `src/agent/argumentation_model.py`, `src/agent/prompts.py` ほか）
> 評価データ: `docs/results/topic_scores.csv` / `docs/results/topic_scores.png`
> （6トピック × 5回 × 4手法、`logs/final_gpt54nano_turns10/final_comparison.json`）

このドキュメントは、schema（構造化論証） / no_schema（自由記述） / mad（相互反論型ベースライン）
/ free_debate（自由討議ベースライン）の4手法比較において、schema・no_schemaが
「最終回答に両者のスタンスをどれだけ反映できているか」（stance coverage / constraint
preservation）で劣勢だった問題を調査し、修正した経緯をまとめる。他のAI・第三者が
この調査の妥当性を検証できるよう、仮説→検証→反証→再修正という試行錯誤の過程も
省略せず記録する。

---

## 1. 問題設定

対話木への再構築（AND/OR探索による dialogue tree の実装）後、4手法を同一条件
（gpt-5.4-nano, `reasoning_effort=medium`, `max_dialogue_turns=10`）で比較したところ、
schema・no_schemaのcoverage率（後述）がfree_debateに劣り、特にschemaはコストが
他手法の3〜8倍にもかかわらず優位性を示せていなかった。

評価指標は当初、holisticな4軸スコア（Coherence/Originality/Dialecticality/Validity）
と、Constructiveness（対話の応酬が建設的か）/ Constraint Preservation（最終回答が
両者の要求を汲み取れているか）の2軸を使っていたが、調査の過程で以下の理由から
Constructivenessは評価対象から外した:

- schemaのdialogue treeは、opponentが同一対象への複数回の反撃を試みる
  （リトライ）構造を持つ。この際、失敗した試行がtranscript上に「誰からも
  参照されない孤立ターン」として残る。
- これを外部評価者（LLM judge）に見せると、「同じ相手への複数回の発言」
  「片方が無視された発言」に見え、構造的に不利な評価を受ける。
- mad/free_debateにはこの構造（同一フレームへの複数回試行）が存在しないため、
  そもそも評価の土俵が揃っていない。

代わりに、**Coverage**（両者のstance文から機械的に抽出した主張項目
`You believe ...`が最終回答で扱われているかを項目ごとに独立してLLMに二値判定
させる、`experiments/eval/scoring/evaluation_coverage.py`）と、**Constraint
Preservation**（最終回答が両stanceの要求を公平に汲み取れているかのholistic
1-10評価、debate_transcriptは見せない）の2軸を主指標とした。

---

## 2. 既存研究（Prakken & Sartor 1997）との整合性チェックで見つかった問題

調査の過程で、実装が既存研究（Prakken & Sartor, *Argument-based extended logic
programming with defeasible priorities*, 1997）の定義から逸脱している箇所が
複数見つかった。coverage問題とは独立した論点だが、同時に修正した。

### 2.1 非反復ルールをopponent側にも誤って適用していた

Prakken & Sartorのdialogue game（Definition 4.5, 条件2）は次の通り:

> If Player_i = Player_j = P and i ≠ j, then Arg_i ≠ Arg_j

非反復制約は**proponent (P) にのみ**課される。論文はこれが意図的な非対称設計
であることも明記している:

> "It is easy to see that a non-repetition rule will not harm P... On the other
> hand, O must have the possibility to repeat moves..."
> (Example 4.4: Oに非反復を強制すると、本来 *defensible*（未決着）であるべき
> 論証が誤って *justified* 判定になることを示す)

実装（修正前）は、`generate_attack`の出力スキーマに`has_new_point`
（「このフレーム内の既存の試みと比べて実質的に新しい角度か」の自己申告）
を持たせ、**opponent側（`purpose="defeat"`）のリトライにのみ**この判定を
強制していた。文献の規定とは逆の側に非反復を課していたことになる。

**対応**: `has_new_point`フィールドと関連チェックを完全に削除
（`src/agent/schema/llm_outputs.py`, `src/agent/arguments.py`）。
non-repetitionはproponent側（`purpose="counter"`, `attack_instruction`の
`<non_repetition>`ブロック）の指示文だけで扱う方針に統一した。

### 2.2 攻撃対象の宣言を無条件に信用していた

LLMが宣言する`target_statement`（「相手のどの結論/前提を攻撃したか」）が、
対象の実際のConc/Assに存在するかを検証していなかった。Definition 2.8の
attack関係は論証の実際の内容から客観的に決まるものであり、攻撃側の自己申告を
無条件に信じてよい理由にはならない。

**対応**: `target_statement_exists()`を追加し、宣言された文言が対象の
Conc（rebutの場合）/Ass（undercutの場合）に実際に存在するかを決定論的に検証
（`src/agent/argumentation_model.py`）。存在しない場合は「攻撃メタデータなし」
と同様に扱い、defeatを成立させない。

### 2.3 `max_attack_attempts`（フレームごとの攻撃リトライ上限）の撤廃

この上限はPrakken & Sartorの理論には存在しない実装上の安全装置だった。
`max_dialogue_turns`（対話全体の絶対ターン数上限）で既にリソース制約が
かかっているため、フレーム単位の上限は二重の制約として不要と判断し撤廃
（`src/agent/workflow.py`, `src/agent/nodes.py`）。

---

## 3. Coverage低迷の直接的原因の特定と修正

### 3.1 仮説1（棄却）: 対話の深さ不足

最初の仮説は「dialogue treeの探索深さ（depth）が浅く、schemaは1つのフレームの
攻防に予算を使い切ってしまい、スタンスの他の論点に触れる余地がない」だった。

実測（`_reconstruct_depths`, `experiments/dialogue/common.py`）では、修正前
schemaは9回中depth=1到達が4回、depth=0止まりが5回で、確かに探索は浅かった。
しかし、`max_attack_attempts`撤廃後（depth到達率は7/9に改善）もcoverage率の
改善幅は限定的で、depth不足だけでは説明がつかなかった。

### 3.2 仮説2（採用）: main論証の「一点集中」制約

`main_instruction`の`<stance_coverage>`ブロック（修正前）:

```
Do not front-load all of them into this single argument. Select the single
reason that most directly and decisively answers the Issue, and develop only
that one with real support...
Leave your stance's other distinct reasons available for later in the debate:
if this argument is defeated or the debate continues, a later argument can
introduce one of them as genuinely new content...
```

main論証（1つのArgument）は**stanceの中から1つの理由だけを選んで構築せよ**、
残りは「後のラウンド」に温存せよ、という指示になっていた。

これを疑う根拠になったのが、**free_debate（自由討議ベースライン）が
schema/no_schemaよりcoverageが高かった**という観測である。free_debateの
ターン生成指示には「1点に絞れ」という制約が一切なく、実際のログでは
Turn1（AG1の初回発言）だけでAG1のstance4項目が全部出ていた:

```
Turn 1 (AG1): "AI can make everyday life more convenient... help students and
professionals work faster... improves accessibility for marginalized groups...
strengthen workplace safety..."
```

一方schema/no_schemaのmain論証は、この「一点集中」指示のため、1本のArgumentが
stance全4項目中1〜2項目しかカバーしていなかった（実測で確認済み）。

**「後のラウンドに温存する」という設計は、実際には機能していなかった**:
実測では、schemaのmain論証は9回中9回とも`main_argument_count=2`のまま
（AG1・AG2各1本ずつ）で、一度も「2巡目のmain」（revision round）に到達
していなかった。5ターン/サイドという予算のほとんどが、1つのB（相手の攻撃）
を撃退できるcounterを見つけるための試行錯誤に消費され、温存した論点を
出す機会が実際には一度も訪れていなかった。

### 3.3 検証: free_debateへの「小出し制約」追加実験

「free_debateの優位はターン制約の違い（小出し禁止 vs 制約なし）による不公平な
比較ではないか」という疑いを検証するため、まず**free_debate側に**
schema/no_schemaと同じ「1ターン1論点」制約を追加して再実験した。

結果、free_debateのcoverageはほぼ変化しなかった（0.926 → 0.903、誤差圏内）。
理由は、free_debateの10ターン（5ターン/サイド）は、1点ずつでも4項目を
出し切るのに十分な余裕があったため。つまり**制約の有無そのものより、
「その制約下で自分の持ち番のうち何ターンを新規内容の生成に使えるか」**が
決定的だった。schemaは同じ5ターンでも、AND/OR探索のリトライ・検証に
ターンを消費するため、新規内容を出せる実効ターン数がfree_debateより少なく、
制約の影響をより強く受けていた。

### 3.4 修正: 一点集中制約の撤廃

上記の検証を踏まえ、**schema/no_schemaのmain_instructionから「1点に絞れ」
という制約を撤廃**した（`<stance_coverage>`, `src/agent/prompts.py`）:

```
Use as many of them as you can genuinely chain into one coherent line of
reasoning toward your direct answer — do not artificially force unrelated
reasons into a single chain just to mention them; only include a reason
where it does real work in the chain.
```

「chainとして正当に繋がる範囲でなら複数の理由を使ってよい」という指示に
変更した。同時に、一貫性のため、3.3で追加したfree_debateの制約は撤回し、
mad（元々制約なし）を含めた4手法すべてを「小出し制約なし」に統一した。

### 3.5 副次的な修正（同時に実施）

- **`_target_engagement_point`の削除**: 攻撃生成の前に「狙う弱点を先に言語化
  させる」追加のLLM呼び出し。過去の検証（`docs/schema_nano_underperformance_report.md`
  §3.2）で効果はノイズ水準（+0.09）、コストは+20%と判明していたため削除。
  攻撃生成1回あたりのAPI呼び出しが半減し、コスト削減にも寄与した。
- **最終回答生成時のdialogue_history二重エスケープ修正**: `generate_final_answer`
  が`json.dumps(state.dialogue_history)`する際、各レコードの`argument`フィールド
  （schemaでは既にJSON文字列）がエスケープされた1行の文字列になり、最終回答を
  書くモデル自身にとって読みにくい入力になっていた。パースし直してから埋め込む
  よう修正し、あわせて`_HISTORY_FORMAT`相当の説明を最終回答生成のSYSTEM
  プロンプトにも追加した（従来は追加されていなかった）。
- **統合プロンプトの矛盾解消**: `_INTEGRATION_SYSTEM_BASE`が「issue固有の実体
  から抽象化せよ」と「具体的要件を落とすな」という矛盾した指示を含んでおり、
  実際に"Second Amendmentが個人の権利を保護する"という具体的な法的性質が
  抽象化で失われる事例を確認した。「要件保持を抽象化より優先する」という
  優先順位を明記した。

---

## 4. 結果

### 4.1 数値（6トピック × 5回、`n=30`/手法）

詳細は`docs/results/topic_scores.csv`、グラフは`docs/results/topic_scores.png`。

| 手法 | coverage率 | constraint_preservation | 平均トークン | 平均コスト |
|---|---:|---:|---:|---:|
| **schema** | **0.989** (SD 0.042) | 7.80 (SD 0.96) | 231,548 | $0.0646 |
| free_debate | 0.943 (SD 0.077) | **8.03** (SD 0.81) | 29,983 | $0.0122 |
| no_schema | 0.936 (SD 0.113) | 7.80 (SD 0.96) | 76,951 | $0.0262 |
| mad | 0.633 (SD 0.171) | 4.90 (SD 1.40) | 32,508 | $0.0117 |

修正前（3トピック×3回、`n=9`、一点集中制約あり）との比較:

| | 修正前 | 修正後 | 変化量 |
|---|---:|---:|---:|
| schema coverage | 0.819 | 0.989 | **+0.170** |
| schema constraint_preservation | 7.556 | 7.80 | +0.244（誤差圏内に近い） |

**schemaはcoverage率で4手法中トップに立ち（6トピック中4トピックでcoverage=1.0、
SD=0）、修正前の最下位から逆転した。** コストは依然として最も高いが、
トークン数は`_target_engagement_point`削除の効果で約17%減少した
（277,630 → 231,548）。

### 4.2 直接的な因果関係の裏付け（main論証1本あたりのカバー項目数）

「一点集中制約の撤廃」という原因と「coverage改善」という結果を直接結びつける
ため、main論証1本が実際に何個のstance項目に触れているかを機械的に集計した:

| | 制約撤廃後 | 一点集中（修正前） |
|---|---|---|
| 典型的な値 | 3/3, 4/4（ほぼ全項目） | 1/3〜2/4（半分以下） |

制約撤廃後は、main論証1本あたりのカバー項目数がほぼ倍増しており、
「ターン数を増やした」「探索が深くなった」といった別の要因ではなく、
**main論証そのものが最初から幅広い観点を取り込むようになったこと**が
coverage改善の直接的な機序であると確認できた。

### 4.3 内容の妥当性確認（考察レベルの結論を避けるため）

数値上のcoverage改善が「キーワードの詰め込み」のような見せかけではなく、
実質的な統合であることを、個別ログの読み込みで確認した
（例: `alternative_energy`トピック、coverage=6/6）。main論証は複数の独立した
論点（renewable先進国の実例／実現可能性／nuclearの補完）を1つの推論chainに
自然に統合しており、無理な接続は見られなかった。最終回答も"Yes, but..."
形式で各論点に実質的に踏み込んでいた。

---

## 5. 未解決の論点・今後の検討事項

### 5.1 coverageとconstraint_preservationの乖離

上記4.3と同じ`alternative_energy`の例は、coverage=6/6（満点）でありながら
constraint_preservation=5（低め）だった。全体平均でもcoverage改善幅
（+0.170）に対し、constraint_preservation改善幅（+0.244 *10点満点中*、
実質誤差圏内）は明確に見劣りする。

**coverageは項目ごとの二値判定（言及されているか）、constraint_preservation
は最終回答の重み付けの公平性を問うholistic判定**であり、測っているものが
異なる。今回の修正は前者（main論証が扱える論点の幅というボトルネック）を
直接解消したが、後者（統合・最終回答段階での公平な重み付け）には手を
付けておらず、そちらは改善していない。両者は別問題として切り分けて
今後検討する必要がある。

### 5.2 「単一障害点」リスクは理論的に未解決

一点集中制約を撤廃したことで、1つのArgumentが複数の独立した論点を1本の
chainに束ねるようになった。Prakken & Sartorの論証構造（Definition 2.2）は
単一の連結したchainを前提とし、undercutは無条件に成立する（Definition 2.16）
ため、**理論上は「chain中の1つの弱い前提を攻撃されるだけで、無関係な
他の複数の論点も巻き添えで defeat される」**というリスクが残る。

実際に生成された18件のログを確認した限り、resolved（overruled/justified）
に至った攻撃はすべて「最終的な統合結論」そのものを狙っており、束ねた
individual sub-premiseを狙い撃ちして巻き添えにするケースは観測されな
かった。ただしこれは、評価に使ったgpt-5.4-nanoというモデルが、たまたま
「一番目立つ最終結論」を攻撃する傾向にあった可能性が高く、**理論的な
リスクが解消されたことの証明ではない**。より戦略的なモデルでは、この
巻き添えリスクが顕在化する可能性がある。

### 5.3 サンプルサイズと統計的検出力

`n=30`(6トピック×5回)は、以前の`n=9`(3トピック×3回)での分散分解の結果
（トピック内SD ≈ 0.163、トピック間SD ≈ 0.056 — トピック内のブレの方が
約3倍大きい）を踏まえ、繰り返し回数を優先する設計で選定した。文献
（LLM評価の再現性に関する複数の研究）では、単発評価（n=1）の判定一致率は
86.6%にとどまり、95%の一致率には最低11回、分散の大きい設問では15回以上の
繰り返しが必要とされる。今回のn=5/トピックはこの目安に近いが、
検出力計算では「schema vs free_debateの現在の僅差（0.056）」を統計的に
確実に検出するには100回超のサンプルが必要という試算もあり、今回観測された
順位（schema > free_debate > no_schema > mad）の細かい差については、
なお慎重な解釈が必要である。

---

## 6. 変更したファイル（参考）

- `src/agent/schema/llm_outputs.py` — `has_new_point`フィールド削除
- `src/agent/arguments.py` — `has_new_point`チェック削除、
  `_target_engagement_point`削除、`generate_final_answer`のdialogue_history
  二重エスケープ修正
- `src/agent/argumentation_model.py` — `target_statement_exists()`追加
- `src/agent/nodes.py` — `max_attack_attempts`チェック撤廃
- `src/agent/workflow.py` — `max_attack_attempts`フィールド削除
- `src/agent/prompts.py` — `<stance_coverage>`の一点集中制約撤廃、
  `<non_repetition>`をproponent側に整理、統合プロンプトの優先順位明記、
  `_HISTORY_FORMAT`等の文言修正、未使用ブロック（`_PROTOCOL_FLOW`,
  `_ATTACK_TYPES`, `_HISTORY_FORMAT_FREE`）を実際にSYSTEMプロンプトへ組み込み
- `src/agent/free_debate.py` — ペース制約を一時追加したのち、一貫性のため撤回
- `tests/unit_tests/*` — 上記変更に伴うテスト更新
