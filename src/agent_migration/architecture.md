# 設計

# DialecticalProtocol
## スキーマ

### Argument
class Antecedent(BaseModel):
    strong_statements: list[str] = Field(
        description="The strong statements in the antecedent of the rule. "
        "Each strong statement in the antecedent of a rule is the consequent of "
        "some earlier rule. "
        "Written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )
    weak_statements: list[str] = Field(
        description="The statements in the antecedent of the rule that have weak negation, "
        "with the weak negation removed. "
        "A weak statement reads as 'there is no evidence that the statement is the case'. "
        "…a person who cannot be shown to be a minor… "
        "'If A then B, unless the contrary can be shown'… "
        "…'unless the law provides otherwise'. "
        "Written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )

class Rule(BaseModel):
    antecedent: Antecedent = Field(
        description="The conjunction at the left of the arrow. "
        "Note that a rule may have zero statements in its antecedents. "
        "Such a rule can be used to express an unconditional statement."
    )
    consequent: str = Field(
        description="The statement at the right of the arrow, "
        "written in a casual style: 'x is earlier than y' is our variant of the "
        "more standard logical notation Earlier(x, y)."
    )


class Argument(BaseModel):
    rules: list[Rule] = Field(
        description="A finite sequence of rules: a sequence of rules "
        "that can be chained together, and that is 'grounded' in the facts. "
        "When no antecedent exists in the rule we call it a fact."
    )

    def conclusions(self) -> list[str]:
        return [r.consequent for r in self.rules]

    def assumptions(self) -> list[Not]:
        # assumption = weak statement の否定（P&S 定義2.3）。Argument には持たせず、weak_statements から導く。
        return [Not(negated_statement=w) for r in self.rules for w in r.antecedent.weak_statements]

class Not(BaseModel):
    negated_statement: str = Field(description="The statement that is negated. One of your conclusions is this very statement.")

undercut の成立: Undercut.target.negated_statement が、攻撃側 argument の conclusions のどれかと一致し、
かつ相手の assumptions() のどれかと一致すること（assumption の否定 = 否定の否定で元の文）。

argumentの書き方指示
'''
An argument is a finite sequence of rules such that:
1. For every rule in the sequence, for every strong statement in the antecedent of the rule
   there is an earlier rule in the sequence whose consequent is that strong statement.
2. For every rule in the sequence except the last, there is a later rule in the sequence
   whose antecedent has the consequent of the rule as a strong statement.
3. No two distinct rules in the sequence have the same consequent.
Condition 2 ensures that argument is a sequence of the minimum number of rules for deducing consequent of the last rule.
Further, we call the last rule a warrant of the argument.
Condition (1) says that arguments are formed by chaining rules together. A subtlety is that in doing so, weak statements may be ignored.
'''

### Attack
class Rebut(BaseModel):
    attack_type: Literal["rebut"]
    target: str = Field(description="One of the conclusions of the opponent's argument, which is the negation of one of your conclusions.")
    argument: Argument

class Undercut(BaseModel):
    attack_type: Literal["undercut"]
    target: Not = Field(description="One of the assumptions of the opponent's argument, which is the negation of one of your conclusions")
    argument: Argument

class CannotAttack(BaseModel):
    attack_type: Literal["cannot_attack"]
    reason: str = Field(description="The reason why you cannot make an attack.")

class Attack(BaseModel):
    move: Rebut | Undercut | CannotAttack = Field(
        description="Use Rebut if your attack consists in contradicting one of the conclusions of the opponent's argument. "
        "Use Undercut if your attack consists in contradicting one of the assumptions of the opponent's argument. "
        "Use CannotAttack if you cannot make an attack."
    )

### Phase 1
class MainArgument(BaseModel):
    argument_type: Literal["main_argument"]
    argument: Argument

class CannotArgue(BaseModel):
    argument_type: Literal["cannot_argue"]
    reason: str = Field(description="The reason why you cannot make an argument.")

class Phase1(BaseModel):
    move: MainArgument | CannotArgue

integrate() の出力は Rule（既存のスキーマ）。「統合できない」の出口は置かない。
warrant は Argument の最後の rule（機械的に取る）:
    def warrant(self) -> Rule:
        return self.rules[-1]


## プロンプト構成
システムプロンプト（main_argument()、integrate()、main_argument_from_rule()、attack() のとき。final_answer() には、議論全体の説明と、argumentの書き方指示を入れない。履歴には地位を付ける）
'''
You are agent 1. You are arguing with agent 2.

The issue of this argumentation is:
{論題}

You have these theory on the issue:
{theory}

You speak in the form of an argument, following this format.
{argumentの書き方指示}

The argumentation so far:
{議論の履歴}

Argumentation consists of two phases. In phase 1, you and the other agent make your main arguments whose conclusions address the issue. In phase 2, you make arguments defeating the other agent's arguments. In each phase, you make arguments from your own theory. No two arguments you present have the same content. If you cannot make an argument from your own theory, you do not make one. In phase 1, if you can make no argument not yet presented, then you create new strict rules by applying the proposed reasoning method and make new main arguments based on it.
'''

ユーザープロンプト（行動ごとに変える）
## エージェントが持つメソッド
- main_argument()
Phase1 のスキーマに則って出力する


プロンプト
'''
Now it is phase 1.
Make your main argument whose conclusions address the issue.
If you cannot make a main argument, you cannot argue.
'''

- integrate()
Rule を出力する。入力は、両者の warrant と自身のスタンス
出せない場合（CannotArgue）に、履歴に両者の main argument があれば呼ぶ

プロンプト
'''
Now it is phase 1.
You can make no argument not yet presented.
Create a new strict rule C from the two warrants.
Your warrant:
{自分の warrant}
The other agent's warrant:
{相手の warrant}
When you face a conflict, you try to search for a solution that takes into account your intentions as much as possible and does not take into account unintentional considerations. Further, if you and the other agent show willingness to compromise, you meet each other halfway.
There are three kinds of C:
- collaboration: from C, together with your stance, both warrants follow.
- concession: from C, together with your stance, one warrant follows but the other does not.
- compromise: from C, together with your stance, neither warrant follows.
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
There are two ways of attack:
- Rebut: contradicting a conclusion. One of your conclusions is the negation of one of the conclusions of the other agent's argument.
- Undercut: contradicting an assumption. An assumption of the other agent's argument is the negation of one of its weak statements. The negation of a negation is the original statement, so you contradict the assumption by deriving that weak statement itself: one of your conclusions is one of the weak statements of the other agent's argument.
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
    aはtをdefeat = undercuts(a, t) or (宣言 == "rebut" and not undercuts(t, a))
    tはaをdefeat = undercuts(t, a) or (宣言 == "rebut" and not undercuts(a, t))   # rebut は対称
    aはtをstrictly defeat = aはtをdefeat and not tはaをdefeat
宣言が "undercut" でも undercuts(a, t) が false なら、a は t を defeat しない。
無効な攻撃 = 求められる関係（O は defeat、P は strictly defeat）を満たさない。
無効な攻撃は、履歴に入れない（対話の move ではない。P&S 定義4.5）。ログの invalid_attempts にだけ残す
（分析用。動く側にも最終回答にも見せない）。残すもの: 動いた側、宣言、理由、鎖の中の対象の履歴番号、主張の履歴番号、LLM の出力。

run():
    履歴 = []; ターン数 = 0; 手番 = ag1; 出せなかった連続 = 0; justified = None
    while true:
        // phase 1
        if 上限到達: → 終了処理
        主張 = main_argument(手番)
        if 主張 == "できない":
            出せなかった連続 += 1
            if 出せなかった連続 == 2: → 統合(手番)        # 両者とも出せない。2回目に出せなかった側が統合する
            手番 = 相手(手番); continue
        出せなかった連続 = 0; 履歴に記録(主張)
        // phase 2
        地位 = 地位を決める(主張, 手番)
        if 地位 == "justified": justified = 主張; → 終了処理
        手番 = 相手(手番)

地位を決める(M, P):      # M は P の main argument。O = 相手(P)
    鎖 = [M]; Pの返答数 = 0; 使ったターン = 1      # M を出した main_argument() の1回（統合から出した M は 0）
    while true:
        動く側 = O if len(鎖) が奇数 else P
        if 上限到達 or 使ったターン >= 上限 // 2: return "defensible"
        X = attack(動く側, 鎖[-1]); 使ったターン += 1
        if X == "できない":
            if 動く側 == O:
                if len(鎖) == 1: return "justified"       # M を defeat する argument がない
                鎖 = [M]; Pの返答数 = 0; continue          # P の最後の動きは undefeated。O は M への別の攻撃を探す
            else:
                return "overruled" if Pの返答数 == 0 else "defensible"
        if 動く側 == P and Xが鎖[-1]をdefeat: Pの返答数 += 1   # P が defeat した返答の数。相互 defeat で無効になったものは数える。defeat していないものは数えない
        if X が無効: continue                             # 動く側は、もう一度出す
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
エージェントの出力は、文章（agent.chat()）。履歴の content も、その文章。攻撃の種類（rebut / undercut）は、宣言させない。
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

- rebuts(x, y)    # スキーマ版では「宣言が rebut か」。defeat の式の「宣言 == rebut」を置き換える
'''
Argument X:
{x}

Argument Y:
{y}

Does X rebut Y? X rebuts Y if one of the conclusions of X is the negation of one of the conclusions of Y. Answer yes or no.
'''

- warrant の取り出し（integrate() の入力にする）
'''
Argument:
{argument}

Write the warrant of this argument: the last step, which states what the argument finally concludes, together with what that conclusion is based on. Copy it as it is stated.
'''

integrate() の出力は、文章（新しい rule）。main_argument_from_rule() には、その文章をそのまま入れる。
