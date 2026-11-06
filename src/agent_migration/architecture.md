# 設計

# DialecticalProtocol

## スキーマ

### Argument

class Antecedent(BaseModel):
    strong_statements: list[str] = Field(
        description="List the strong statements in the antecedent of the rule.\n\n"
        "Each strong statement must be the consequent of an earlier rule in the argument."
    )
    weak_statements: list[str] = Field(
        description="List the statements in the antecedent of the rule that have weak negation, "
        "with the weak negation removed.\n\n"
        "A defeasible rule can contain assumptions that are not warranted: "
        "weak negation is used to express explicit exceptions.\n\n"
        "'If A then B' is different from 'If A then B, unless the contrary can be shown'.\n\n"
        "For example, a person who cannot be shown to be a minor has the capacity to perform legal acts, "
        "'unless the law provides otherwise'.\n\n"
        "Here the weak statement is 'the person is a minor', not 'the person is not a minor'.\n\n"
        "The negation of each weak statement is an assumption of the argument.\n\n"
        "The acceptance of an argument depends on the acceptance of its assumptions."
    )

class Rule(BaseModel):
    antecedent: Antecedent = Field(
        description="Write the statements at the left of the arrow, joined by 'and'.\n\n"
        "A rule may have no statements here. "
        "Such a rule expresses an unconditional statement."
    )
    consequent: str = Field(
        description="Write the statement at the right of the arrow.\n\n"
        "Written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )

class Argument(BaseModel):
    rules: list[Rule] = Field(
        description="Write the rules of your argument in order.\n\n"
        "The rules can be chained together, and the argument is 'grounded' in the facts. "
        "A rule with no antecedent is a fact."
    )

    def conclusions(self) -> list[str]:
        return [r.consequent for r in self.rules]

    def assumptions(self) -> list[Not]:
        # assumption = weak statement の否定（P&S 定義2.3）。Argument には持たせず、weak_statements から導く。
        return [Not(negated_statement=w) for r in self.rules for w in r.antecedent.weak_statements]

class Not(BaseModel):
    negated_statement: str = Field(
        description="Write the statement that is negated.\n\n"
        "One of your conclusions is this very statement."
    )

undercut の成立: Undercut.target.negated_statement が、攻撃側 argument の conclusions のどれかと一致し、
かつ相手の assumptions() のどれかと一致すること（assumption の否定 = 否定の否定で元の文）。

argumentの書き方指示
'''
An argument is a finite sequence of rules.

The rules are chained together. Every strong statement in the antecedent of a rule is the consequent of an earlier rule. A subtlety is that in doing so, weak statements may be ignored.

Every rule except the last is used by a later rule: its consequent is a strong statement in the antecedent of a later rule. In this way the argument is a sequence of the minimum number of rules for deducing the consequent of the last rule. We call the last rule the warrant of the argument.

No two rules in the argument have the same consequent.
'''

### Attack

class Rebut(BaseModel):
    attack_type: Literal["rebut"]
    target: str = Field(
        description="Write one of the conclusions of the other agent's argument.\n\n"
        "It must be the negation of one of your conclusions."
    )
    argument: Argument

class Undercut(BaseModel):
    attack_type: Literal["undercut"]
    target: Not = Field(
        description="Write one of the assumptions of the other agent's argument.\n\n"
        "It must be the negation of one of your conclusions."
    )
    argument: Argument

class CannotAttack(BaseModel):
    attack_type: Literal["cannot_attack"]
    reason: str = Field(description="Explain why you cannot make an attack.")

class Attack(BaseModel):
    move: Rebut | Undercut | CannotAttack = Field(
        description="Use Rebut to contradict one of the conclusions of the other agent's argument.\n\n"
        "Use Undercut to contradict one of the assumptions of the other agent's argument.\n\n"
        "Use CannotAttack if you cannot make an attack."
    )

### Phase 1

class MainArgument(BaseModel):
    argument_type: Literal["main_argument"]
    argument: Argument
    reason_no_weak_statements: str = Field(
        description="If no rule of your argument has a weak statement, you must write here why you did not use any weak statement.\n\n"
        "Leave it empty only if your argument has a weak statement."
    )

class CannotArgue(BaseModel):
    argument_type: Literal["cannot_argue"]
    reason: str = Field(description="Explain why you cannot make an argument.")

class Phase1(BaseModel):
    move: MainArgument | CannotArgue

integrate() の出力は Rule（既存のスキーマ）。「統合できない」の出口は置かない。
warrant は Argument の最後の rule（機械的に取る）:
    def warrant(self) -> Rule:
        return self.rules[-1]

## プロンプト構成

システムプロンプト（main_argument()、integrate()、main_argument_from_rule()、attack() のとき。final_answer() には、議論全体の説明（目的・argumentの書き方指示・フェーズ・定義）を入れない。履歴には地位を付け、最後に置く）
'''
You are agent 1. You are arguing with agent 2.

The issue of this argumentation is:
{論題}

You have these theory on the issue:
{theory}

Roughly, the idea of argumentational reasoning is that a statement is believable if it can be argued successfully against attacking arguments. In other words, whether or not a rational agent believes in a statement depends on whether or not the argument supporting this statement can be successfully defended against the counterarguments.

You speak in the form of an argument, following this format.
{argumentの書き方指示}

Argumentation consists of two phases.

In phase 1, you and the other agent make your main arguments whose conclusions address the issue. In phase 2, you make arguments defeating the other agent's arguments.

In each phase, you make arguments from your own theory. If you cannot make an argument from your own theory, you do not make one. No two arguments you present have the same content.

In phase 1, if you can make no argument not yet presented, then you create new strict rules by applying the proposed reasoning method and make new main arguments based on it.

An argument A1 defeats an argument A2 in two cases: when A1 undercuts A2, or when A1 rebuts A2 and A2 does not undercut A1.

A1 strictly defeats A2 when A1 defeats A2 and A2 does not defeat A1.

An argument is justified if no argument defeats it, or if every argument that defeats it is also strictly defeated.

An argument is overruled if it is defeated by the justified argument. An argument is defensible if it is neither justified nor overruled.

The argumentation so far:
{議論の履歴}
'''

ユーザープロンプト（行動ごとに変える）

## エージェントが持つメソッド

- main_argument()
  Phase1 のスキーマに則って出力する

プロンプト
'''
Now it is phase 1.

Make your main argument whose conclusions address the issue. If you cannot make a main argument, you cannot argue.
'''

- integrate()
  Rule を出力する。入力は、両者の warrant と自身のスタンス
  出せない場合（CannotArgue）に、履歴に両者の main argument があれば呼ぶ

プロンプト
'''
Now it is phase 1.

You can make no argument not yet presented. Create a new strict rule C from the two warrants.

Your warrant:
{自分の warrant}

The other agent's warrant:
{相手の warrant}

When you face a conflict, you try to search for a solution that takes into account your intentions as much as possible and does not take into account unintentional considerations. Further, if you and the other agent show willingness to compromise, you meet each other halfway.

C can be one of three kinds. If both warrants follow from C together with your stance, C is a collaboration. If one warrant follows but the other does not, C is a concession. If neither warrant follows, C is a compromise.

Choose the kind you can achieve, in this order: collaboration, concession, compromise.
'''

- main_argument_from_rule()
  integrate() のあとに呼ぶ。Phase1 のスキーマに則って出力する

プロンプト
'''
Now it is phase 1.

You created this new strict rule by applying the proposed reasoning method:
{新しい rule}

Make your new main argument based on it.
'''

- attack()
  入力は、攻撃の対象の argument（履歴の最後とは限らないので、プロンプトに入れる）

プロンプト
'''
Now it is phase 2.

In phase 2, you make an argument defeating the other agent's argument. If the other agent's argument does not contradict your own theory, there is nothing to defeat.

The other agent's argument:
{攻撃の対象の argument}

There are two ways of attack: by stating an argument with a contradictory conclusion, or by stating an argument with a conclusion providing an 'unless' clause of the other argument.

To rebut, contradict a conclusion: one of your conclusions is the negation of one of the conclusions of the other agent's argument.

To undercut, contradict an assumption. An assumption of the other agent's argument is the negation of one of its weak statements. The negation of a negation is the original statement, so you contradict the assumption by deriving that weak statement itself: one of your conclusions is one of the weak statements of the other agent's argument.

If you can make neither of these attacks, you cannot attack.
'''

- final_answer()
  スキーマは使わず、自由な文章で出力する。
  履歴には、各 argument の地位（justified / overruled / defensible）を、プロトコルが機械的に付ける。
  議論の流れを先に書かせ、そのあとに回答を書かせる（流れは、最終回答の本文の前半に入れる）。

プロンプト（justified があるとき）
'''
Now the argumentation is over. Write your final answer to the issue in plain text. Begin with the flow of the argumentation: which opinions were put forward, which objections were raised, and how each was answered. Then give your answer to the issue.
'''

プロンプト（上限に達して、justified がないとき）
'''
Now the argumentation is over, but no argument was justified. Write your final answer to the issue in plain text. Begin with the flow of the argumentation: which opinions were put forward, which objections were raised, and how each was answered. Then state what remains undecided, and what is known.
'''

## プロトコルが持つ関数（機械的。LLM もジャッジも使わない）

- undercuts(x, y)
  x が y を undercut するか（Kido 定義3）。x の結論のどれかが、y の weak statement のどれかと一致するか。
  一致は、大文字小文字・空白・末尾のピリオドをそろえて比べる。

def undercuts(x: Argument, y: Argument) -> bool:
    weak = {norm(w) for r in y.rules for w in r.antecedent.weak_statements}
    return any(norm(c) in weak for c in x.conclusions())

## 全体

- run()

用語

- ターン: main_argument() と attack() の1回の呼び出し。上限（max_dialogue_turns）は、この合計で数える。
  上限の確認は、呼び出しの前に行う（許された最後の呼び出しの結果は、使う）。
- 1つの主張が使えるターン: 上限の半分（上限 // 2）。1つの主張 = 主張を出した main_argument() と、その地位が決まるまでの attack()。
  半分に達したら、その主張は defensible で打ち切り、相手の主張の番に移る（1つの鎖が上限を使い切って、相手の主張の番が来ないのを防ぐ）。
  統合から出した主張は、main_argument_from_rule() を数えないので、attack() だけを数える。
  integrate()、main_argument_from_rule()、final_answer() は、数えない。
- 履歴: {"role": "ag1" | "ag2", "content": LLM の出力（スキーマのまま）} の列。「出せない」は入れない。地位は持たせない。
- 宣言: 攻撃のときに、LLM が選んだ種類（rebut / undercut）。

攻撃の判定（機械的。undercuts() を使う）。a が t を攻撃したとき、
    aはtをdefeat = 宣言 == "undercut" or (宣言 == "rebut" and not undercuts(t, a))   # 宣言は信じる。undercut は defeat。rebut は、既出の t が undercut し返せるかを機械的に見る
    tはaをdefeat = undercuts(t, a) or (宣言 == "rebut" and not undercuts(a, t))   # rebut は対称
    aはtをstrictly defeat = aはtをdefeat and not tはaをdefeat
（no schema 版は宣言がないので、aはtをdefeat = undercuts(a, t) or (rebuts(a, t) and not undercuts(t, a))。どちらも判定用 LLM の答え）
求められる関係は、O は defeat、P は strictly defeat（P&S 定義4.5）。
宣言（rebut / undercut）は、そのとおりに信じる。判定するのは、既出の argument 同士の関係（相手が undercut し返せるか）だけ。
求められる関係を満たさない攻撃は、履歴に入れない（対話の move ではない）。ログの invalid_attempts にだけ残す
（分析用。動く側にも最終回答にも見せない）。残すもの: 動いた側、宣言、理由、鎖の中の対象の履歴番号、主張の履歴番号、LLM の出力。
- O の攻撃が defeat でない: 「攻撃できない」と同じ扱い。やり直しはない。
- P の返答が strictly defeat でない: P は 1 回だけなので、やり直さず、その場で overruled。

run():
    履歴 = []; ターン数 = 0; 手番 = ag1; 出せなかった連続 = 0; justified = None
    while true:
        // phase 1
        if 上限到達: → 終了処理
        主張 = main_argument(手番)
        if 主張 == "できない":
            if 履歴に両者の main argument がある: → 統合(手番)   # 出せない側が、すぐ統合する
            出せなかった連続 += 1
            if 出せなかった連続 == 2: → 終了処理               # 両者が続けて出せず、統合もできない
            手番 = 相手(手番); continue
        出せなかった連続 = 0; 履歴に記録(主張)
        // phase 2
        地位 = 地位を決める(主張, 手番)
        if 地位 == "justified": justified = 主張; → 終了処理
        手番 = 相手(手番)

地位を決める(M, P):      # M は P の main argument。O = 相手(P)
    鎖 = [M]; 使ったターン = 1      # M を出した main_argument() の1回（統合から出した M は 0）
    while true:
        動く側 = O if len(鎖) が奇数 else P
        if 上限到達 or 使ったターン >= 上限 // 2: return "defensible"
        X = attack(動く側, 鎖[-1]); 使ったターン += 1
        if X != "できない" and X が求められる関係を満たさない:
            invalid_attempts に残す（履歴には入れない）; X = "できない"相当
        if X == "できない":
            if 動く側 == O:
                if len(鎖) == 1: return "justified"       # M を defeat する argument がない
                鎖 = [M]; continue          # P の最後の動きは undefeated。O は M への別の攻撃を探す
            else:
                return "overruled"       # P は strictly defeat できなかった
        鎖.append(X); 履歴に記録(X)

統合(統合者, 評価する):   # 上限に達したときは、評価する = false（ag1 が統合する）
    if どちらかに main argument がない: → 終了処理
    C = integrate(統合者, 自分の最後のmain argumentのwarrant, 相手の最後のmain argumentのwarrant)   # warrant は rules[-1]
    履歴に記録(C)
    新主張 = main_argument_from_rule(統合者, C)
    if 新主張 == "できない": → 終了処理
    履歴に記録(新主張)
    if 評価する and 地位を決める(新主張, 統合者) == "justified": justified = 新主張
    → 終了処理                                            # 統合は1回だけ

終了処理:
    if 上限到達 and justified == None and 未統合: 統合(ag1, 評価する = false)
    履歴の各 main argument に、地位（justified / overruled / defensible）を付ける。評価していないものは defensible
    if justified: final_answer（justified があるとき）
    else:         final_answer（上限に達して、justified がないとき）

## no schema 版（実装: argumentation/no_schema.py。流れは DialecticalProtocol を継承し、LLM を呼ぶ部分と判定だけを差し替える）

流れと、各行動のユーザープロンプトは、スキーマ版と同じ。スキーマ（structured output）と、argument の書き方指示だけを抜く。
エージェントの出力は、文章（agent.chat()）。履歴の content も、その文章。攻撃の種類（rebut / undercut）は、宣言させない（判定用の LLM が、文章から読み取る）。
流れが必要とする判定は、判定用の LLM（JUDGE_MODEL）にさせる。システムプロンプトは付けない。答えは、yes / no の文字（先頭の単語で読む）。
これらの呼び出しは、ターンに数えない。品質は判定しない（条件分岐のためだけ）。

- できないと言っているか（main_argument() / attack() / main_argument_from_rule() の出力）
  '''
  The following is an agent's reply.
  {出力の文章}
  Does the reply say that the agent cannot do it? Answer yes or no.
  '''
- undercuts(x, y)
  '''
  Argument X:
  {x}

Argument Y:
{y}

Does X undercut Y? X undercuts Y if one of the conclusions of X contradicts an assumption of Y, that is, a statement that Y takes to hold only because there is no evidence to the contrary. Answer yes or no.
'''

- 攻撃の種類の読み取り（宣言の代わり。rebut か undercut かだけ。攻撃が成立するかは判定しない）
  '''
Argument X:
{x}

Argument Y:
{y}

The agent stated X to attack Y. Does X attack Y by rebutting it or by undercutting it? X rebuts Y if one of the conclusions of X is the negation of one of the conclusions of Y. X undercuts Y if one of the conclusions of X contradicts an assumption of Y, that is, a statement that Y takes to hold only because there is no evidence to the contrary. Answer rebut or undercut.
  '''
  読み取った種類を、スキーマ版の宣言と同じに扱う: undercut なら defeat、rebut なら、既出の相手が undercut し返せるか（undercuts(x, y)）だけを見る。

- warrant の取り出し（integrate() の入力にする）
  '''
  Argument:
  {argument}

Write the warrant of this argument: the last step, which states what the argument finally concludes, together with what that conclusion is based on. Copy it as it is stated.
'''

integrate() の出力は、文章（新しい rule）。main_argument_from_rule() には、その文章をそのまま入れる。

## 比較手法（free_debate / mad / mad_synthesis）

既存実装（src/agent/）の同名の手法を、この実装に写す。実装: argumentation/free_debate.py、mad.py、mad_judge.py。
議論だけが違い、統合と最終回答は、今のもの（no schema 版と同じ。NoSchemaProtocol を継承して使う）を使う。

議論（free_debate と mad で共通）

- ag1 → ag2 の順に、交代で発言する（1発言 = 1ターン）。上限は max_turns（発言の数。確認は、発言の前）。
- 各発言の LLM 出力は DebateTurn(argument, has_new_point)（agent.structured）。1ラウンド目の has_new_point は True 固定。
  2ラウンド目以降の指示に、新規性の逃げ道（既存の文のまま）を付ける。ag2 の発言のあと、両者の has_new_point が False なら、上限の前でも終わる。
- 発言用のシステムプロンプト: identity + theory + grounding（既存の文）+ これまでの議論（履歴の JSON）。
  既存は、履歴を、チャットのメッセージで渡していた。ここでは、他の手法と同じく、システムプロンプトの履歴に入れる。
- 発言の指示: free_debate は「相手の発言を踏まえて、主張する」。mad は「相手の直前の主張に argue against する」（既存の文）。
  既存の指示の「above」は、「in the debate so far」に直す。

終わり方

- free_debate、mad_synthesis: 今の統合（各陣営の最後の発言を warrant として、integrate() → main_argument_from_rule()、評価しない）→ 今の final_answer()（justified なしのほう）。
- mad: 議論に参加しない judge が、議論全体から最終回答を書く（既存の MAD_JUDGE の文）。統合はしない。judge は、議論の書き手と同じモデル（既存と同じ）。
- 履歴の発言は kind = "turn"（地位は付けない）。
