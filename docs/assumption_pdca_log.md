# Assumption（weak statement）の PDCA ログ

目的: schema の議論で、エージェントが weak statement（assumption）を、P&S の意味で使うようにする。
測るもの（probe_pdca.py、3トピック × 3回、約45回の呼び出し/周）:
- A: main argument に weak statement がある割合（基準 50% 以上）
- B: 固定の論証（weak statement 付き）への攻撃のうち、有効な undercut の割合（基準 50% 以上、宣言 undercut かつ結論が weak statement そのもの）
- C: O の攻撃と P の返答に weak statement がある割合（基準 30% 以上）
停止: A・B・C を2回続けて満たす / 20周 / 累計 $1.0 / 3周続けて改善なし。最後に別の2トピックで1回確認する。
権限: ユーザーが、probe の実行、文言の修正（文献の語を優先、必要なら意味を解釈して書く）を許可（2026-11-05）。
直してよい文: weak_statements と Undercut.target の説明、MAIN_ARGUMENT_USER / ATTACK_USER / MAIN_ARGUMENT_FROM_RULE_USER。
独自文（文献にない文）は「【独自】」と印を付ける。

## 周1（基準: B1 + W1 + 説明文、変更なし）
A 3/18 (17%)、B 0/9（宣言 undercut も 0）、C 0/18。固定の論証に weak statement があっても、攻撃はすべて rebut。main の weak は、B1 の引用句（'The contrary can be shown ...'）をそのまま写したものが目立つ。$0.0286

## 周2
変更（文献）: ATTACK_USER に P&S 2.4 の文を追加:「Attacks on assumptions do not only always succeed, but are also always stronger than an attack on a conclusion: ...」（原文の先頭を、'attacks' に直しただけ）
結果: A 3/18、B 1/9（宣言 undercut 2。有効 1。無効の1件は結論が「W is not warranted」）、C 0/18。O の undercut 2、P の undercut 1 が出た（周1は 0）。$0.0283

## 周3
変更（文献）: ATTACK_USER の Undercut の項の直後に、P&S 序論の文を追加:「…by stating an argument with a conclusion providing an 'unless' clause of the other argument.」
結果: A 4/18、B 0/9（宣言 undercut 0）、C 1/18（P 1）。O の undercut は 1/9。n が小さく、周2との差は、ノイズの範囲。$0.0288

## 周4
変更【独自】: ATTACK_USER に追加:「First look at the weak statements of the other agent's argument. If your theory lets you derive one of them, make an undercut.」（意味の解釈: undercut は、相手の weak statement を、自分の理論から導けるときに選ぶ）
結果: A 2/18、B 1/9（宣言 undercut 2）、C 1/18。O の undercut 6/9、P の undercut 3/9 に増えたが、main に weak statement がほとんどなく、undercut の対象がない攻撃が多いとみられる（指示が、対象のない undercut を誘っている）。$0.0296

## 周5
変更: 
- MAIN_ARGUMENT_USER の B1 の文を差し替え:「A defeasible rule can contain assumptions that are not warranted.」（P&S 2.1 の文）＋【独自】「For each rule, consider which exception to it you take to be absent unless the contrary can be shown, and write that exception as a weak statement in the antecedent of the rule.」
- ATTACK_USER の周4の文を差し替え【独自】:「An argument without weak statements cannot be undercut. If the other agent's argument has a weak statement that your theory lets you derive, make an undercut.」（undercut の前提を明示。P&S 定義2.8 の読み）
結果: A 14/18 (78%)、B 0/9、C 0/18、O の undercut 1/9、P の undercut 2/9。A は基準を超えた（周5の main の変更が効いた）。ただし、weak statement の約半数が、「there is no evidence that X」の形（statement 自体に否定を含める＝『証拠がない』の読みを文に写してしまう）。undercut の2件は、対象に weak statement がない（無効）。$0.0294
probe に D を追加: weak statement が、否定・『証拠がない』の形でない割合（正規表現）。基準 70% 以上を、成功条件に足す。

## 周6
変更【独自、P&S 例 2.4 の意味の解釈】: weak_statements の説明に追加:「For example, for the rule 'a person who cannot be shown to be a minor has legal capacity', the weak statement is 'the person is a minor'.」（例 2.4 の `~x is a minor ⇒ x has legal capacity` から。weak statement は、否定を含まない文で、例外そのもの）
結果: A 10/18 (56%)、B 0/9（宣言 undercut 2）、C 1/18、D（旧）8/27。D を作り直し: P&S 例 2.18・4.1（`~¬OJ is innocent`、`~¬e is admissible evidence`）は、weak statement に強い否定（¬）を含める形なので、「It is not the case that X」は正しい形。誤りは、「there is no evidence that X」を statement に写すこと（~ がすでにそう読む）。新 D = そうでない割合: 周5 20/32 (62%)、周6 20/27 (74%)。基準 70% 以上。周6の例が D に効いた。
観察: 攻撃側は、固定の論証の weak statement を、「結論に出す」のでなく、「否定して」しまう（'Student loan debt does not strain ...'）。O が undercut を、weak statement のない相手に使う例もあった。$0.0301

## 周7
変更【独自、P&S 2.1 の意味の解釈】: ATTACK_USER の Undercut の項を差し替え:「The other agent's argument assumes that each of its weak statements does not hold, unless the contrary can be shown. You contradict the assumption by showing that one of its weak statements holds: one of your conclusions is that weak statement itself, word for word.」
結果: A 12/18 (67%) ✓、B 1/9（宣言 undercut 1）、C 0/18、D 21/29 (72%) ✓。A と D は基準を満たした。B と C が未達。固定の論証を攻撃する ag2 は、自分の立場に合う rebut を選ぶ。$0.0282

## 周8
変更【独自】: ATTACK_USER の B1 の文を、MAIN_ARGUMENT_USER と同じ文に差し替え（C を上げるため。main では、この文で A が 17% → 67〜78%）:「A defeasible rule can contain assumptions that are not warranted. For each rule of your argument, consider which exception to it you take to be absent unless the contrary can be shown, and write that exception as a weak statement in the antecedent of the rule.」
結果: A 13/18 (72%) ✓、B 2/9 (22%)、C 0/17、D 15/27 (56%)。C が動かない。P&S 定義から、P が strictly defeat できるのは、O の攻撃（rebut）に weak statement があり、P がそれを undercut するときだけ。O の攻撃は、短い rebut（結論を否定する2〜3規則）で、例外を書かない。$0.0289

## 周9
変更: ATTACK_USER の周8の文を、箇条書きの後ろから、冒頭の段落の直後（In phase 2, ... の次）に移動。文は同じ。
結果: A 13/18 (72%) ✓、B 2/9 (22%)、C 5/18 (28%、O 2 / P 3)、D 30/34 (88%) ✓。C が動いた（冒頭に移した効果）。B の測り方を直す: protocol は、宣言ではなく、結論が weak statement と一致するか（undercuts()）で undercut を判定する。宣言が rebut でも、結論に weak statement を含めれば、機械的には undercut（周9 の college#3）。B を、機械的な undercut の割合に変更。$0.0316

## 周10
変更【独自、周4の文＋周5の文の合成】: ATTACK_USER の最後の指示を差し替え:「First look at the weak statements of the other agent's argument. An argument without weak statements cannot be undercut. If it has a weak statement that your theory lets you derive, make an undercut; otherwise, make a rebut.」
結果: A 12/18 (67%) ✓、B 0/9、C 4/18 (22%)、D 15/28 (54%)。周1〜10の B は、0〜3/9 の範囲（周9だけ 3/9=機械判定）で、文言を変えても、ほぼ動かない。n=9 では、周ごとの差は、ノイズ（A の 56〜78%、D の 54〜88% も同様）。$0.0302

## 周11
変更【独自】: Attack.move の説明で、Undercut を先に書き、条件を明示:「Use Undercut if your attack consists in contradicting one of the assumptions of the opponent's argument, that is, if the opponent's argument has a weak statement that you can establish. Use Rebut if ...」
結果: A 13/18 (72%) ✓、B 1/9 (11%) ✗、C 7/18 (39%) ✓、D 24/32 (75%) ✓。B だけが未達。成功例は、攻撃側の stance に、weak statement とほぼ同じ文があるとき。$0.0297

## 周12
変更【独自】: ATTACK_USER の指示に、JSON の欄との対応を明記:「…the weak statements of the other agent's argument: they are the 'weak_statements' in the antecedents of its rules.」
結果: A 10/18 (56%) ✓、B 1/9、C 3/18 (17%)、D 14/24 (58%)。周ごとの変動が大きい（A 56〜78%、C 6〜39%、D 54〜88%）ので、文言の差を、1周で判断できない。
再集計（周1〜12）: 固定の論証への B は、0〜3/9 で動かない。一方、周5以降（main に weak が増えた後）、O の攻撃のうち、weak statement を持つ main への攻撃（9件中5〜8件）で、undercut を宣言したのは、1〜3件。宣言した undercut の約半数が、機械的に有効（対象に weak があり、結論が weak statement と一致）。固定の論証は、weak statement が「攻撃側に有利な例外」の形で、実際の議論（主張者が、自分の前提を、否定されないと見なす形）より、難しい可能性がある。
O は、defeat すれば足りるので（P&S 定義4.5）、rebut で済ませるのは、誤りではない。undercut の頻度でなく、undercut を使うときの正しさが、本来の関心とも読める。

## 周13・14（再測定: 周12 と同じ文言のまま、2回）
結果（周12 と同じ文言の3回）: A 56/72/72% ✓、B 1/2/0 of 9 ✗、C 3/5/3 of 17-18 (22%) ✗、D 58/74/67% (66%) ✗（基準 70%）。A だけが安定して基準を超えた。$0.0266 / $0.0276 / $0.0261。累計は約 $0.41。

## 周15
変更【独自、P&S 2.1 の意味の解釈】: weak_statements の例を延長:「…the weak statement is 'the person is a minor', not 'there is no evidence that the person is a minor': the weak negation already says that there is no evidence.」
結果: A 11/18 (61%) ✓、B 0/9、C 7/18 (39%) ✓、D 22/33 (67%) ✗。D の失敗は、weak statement の文頭に「There is no evidence that ...」を書くもの（周13〜15 で 9〜11件）。周15 の否定例が、その句を、かえって誘った可能性がある。$0.0293

## 周16
変更: 周15 の追加を取り消し（例は周6 の形に戻す）。【独自、P&S 2.1 の意味の解釈】weak_statements の説明の、P&S の読み『A weak statement reads as 'there is no evidence that the statement is the case'』を、「A weak negation means that the statement is assumed not to hold unless the contrary can be shown」に差し替え（「there is no evidence」の句を、description から外す）。
結果: A 8/18 (44%) ✗、B 0/9、C 1/16 (6%) ✗、D 15/15 (100%) ✓。weak statement は、すべて、否定を含まない（または、It is not ...の）普通の文になった（形は改善）。ただし、使う数が減った（「there is no evidence」の句が、weak statement を書く手がかりにもなっていた可能性）。$0.0295

## 周17（再測定: 周16 と同じ文言）
結果: A 12/18 (67%) ✓、B 0/9、C 5/18 (28%)、D 24/27 (89%) ✓。周16+17（同文言）の合算: A 20/36 (56%) ✓、C 6/34 (18%) ✗、D 39/42 (93%) ✓、B 0/18 ✗。$0.0284

## 周18
変更【独自】: ATTACK_USER の Undercut の項の末尾を具体化:「…word for word: write a rule whose consequent is that statement, from the facts of your own theory.」（B を上げるため）
結果: A 8/18 (44%)、B 1/9（宣言 undercut 2）、C 3/18 (17%)、D 19/19 (100%)。B に効果なし。$0.0277
判断: 周16〜18 の文言（「there is no evidence」の句を外した版）は、D が 95% 前後、A が 52% 前後（基準 50%）で、B と C は基準に届かない。「there is no evidence」を残す版は、A 67%・D 66% で、statement に「証拠がない」を写す形が増える。意味の正しさを優先して、前者を残す。

## 周19（別の2トピックでの確認: alternative_energy, election_day。周18 と同じ文言）
結果（別の2トピック）: A 3/12 (25%)、B 0/6、C 2/12 (17%)、D 7/7 (100%)。A が、学習に使った3トピックより低い（トピックによる差。過学習の可能性）。$0.0182

## 周20（最終の測定: 5トピック全部、周18 と同じ文言。文言の変更なし）
結果: A 15/30 (50%) ✓（ぎりぎり）、B 0/15 ✗、C 1/28 (4%) ✗、D 28/28 (100%) ✓。$0.0454

## 終了（20周に到達）
基準 A・B・C・D のうち、A と D を満たした（A はぎりぎり）。B と C は、満たせなかった。累計費用: 約 $0.60（エージェントのモデルのみ。判定用モデルは使っていない）。
残した文言: weak_statements の説明（P&S 2.1・2.4・序論の文と、例 2.4 に基づく例。『there is no evidence』の句は外した）、MAIN_ARGUMENT_USER・ATTACK_USER の例外の文、ATTACK_USER の undercut の説明。差分は `git diff src/agent_migration/argumentation/dialectical.py`。
