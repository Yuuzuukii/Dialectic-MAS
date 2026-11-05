"""議論の進め方（architecture.md の run()）を、LLM なしで動かして確認するテスト。

偽の Agent が、あらかじめ決めた発言を返す。各場面で、呼び出しの順（トレース）と、結果、組み立てたプロンプトを確認する。
トレースを見るには: pytest tests/unit_tests/test_protocol_flow.py -s
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from src.agent_migration.argumentation.dialectical import (
    AG1,
    AG2,
    Antecedent,
    Argument,
    Attack,
    CannotArgue,
    CannotAttack,
    DialecticalProtocol,
    MainArgument,
    Not,
    Phase1,
    Rebut,
    Rule,
    Undercut,
    undercuts,
)
from src.agent_migration.argumentation.no_schema import NoSchemaProtocol


# ---- 部品 ----
def R(strong, cons, weak=()):
    return Rule(antecedent=Antecedent(strong_statements=list(strong), weak_statements=list(weak)), consequent=cons)


def A(*rules):
    return Argument(rules=list(rules))


def arg(tag, weak=()):
    """tag ごとに結論が違う argument（事実 → 主張）。"""
    return A(R([], f"fact {tag}"), R([f"fact {tag}"], f"claim {tag}", weak))


def main(a):
    return MainArgument(argument_type="main_argument", argument=a, reason_no_weak_statements="")


def rebut(a, target="t"):
    return Rebut(attack_type="rebut", target=target, argument=a)


def undercut(a, stmt):
    return Undercut(attack_type="undercut", target=Not(negated_statement=stmt), argument=a)


CANNOT_ARGUE = CannotArgue(argument_type="cannot_argue", reason="x")
CANNOT_ATTACK = CannotAttack(attack_type="cannot_attack", reason="x")


class FakeAgent:
    """あらかじめ決めた発言を返す Agent。尽きたら、できない（integrate は尽きたらエラー）。
    spec は、リスト、または i 回目を返す関数。受け取ったプロンプトを calls に残す。"""

    def __init__(self, main=(), attack=(), integrate=(), from_rule=()):
        self.spec = {"main": main, "attack": attack, "integrate": integrate, "from_rule": from_rule}
        self.count = {k: 0 for k in self.spec}
        self.calls: list[dict] = []

    def _next(self, key, default):
        i, spec = self.count[key], self.spec[key]
        self.count[key] += 1
        if callable(spec):
            return spec(i)
        return spec[i] if i < len(spec) else default

    async def structured(self, prompt, schema, system=None):
        self.calls.append({"prompt": prompt, "schema": schema, "system": system})
        if schema is Phase1:
            key = "from_rule" if "You created this new strict rule" in prompt else "main"
            return Phase1(move=self._next(key, CANNOT_ARGUE))
        if schema is Attack:
            return Attack(move=self._next("attack", CANNOT_ATTACK))
        assert schema is Rule
        r = self._next("integrate", None)
        assert r is not None, "integrate の発言が足りない"
        return r

    async def chat(self, prompt, system=None):
        self.calls.append({"prompt": prompt, "schema": None, "system": system})
        return SimpleNamespace(content="ANSWER(fallback)" if "no argument was justified" in prompt else "ANSWER(justified)")


def protocol(ag1: FakeAgent, ag2: FakeAgent, max_turns=20, **kw):
    return DialecticalProtocol(ag1, ag2, issue="ISSUE", theory1="THEORY1", theory2="THEORY2", max_turns=max_turns, **kw)


def run(ag1: FakeAgent, ag2: FakeAgent, max_turns=20):
    result = asyncio.run(protocol(ag1, ag2, max_turns).run())
    print("\n" + "\n".join(result.trace) + f"\n  → turns={result.turns} closed_by={result.closed_by} statuses={result.statuses}")  # noqa: T201
    return result


# ---- defeat の定義（Kido 定義3、4）----
def defeat_relations(a, t, rebut_flag):
    p = protocol(FakeAgent(), FakeAgent())
    return asyncio.run(_rel(p, a, t, rebut_flag))


async def _rel(p, a, t, rebut_flag):
    return (
        await p._defeats(a, t, rebut_flag),
        await p._defeated_back(a, t, rebut_flag),
        await p._strictly_defeats(a, t, rebut_flag),
    )


def test_defeat_definitions():
    p_arg, plain = arg("p"), arg("q")
    weak_holder, killer = arg("w", weak=("x holds",)), A(R([], "x holds"))
    assert undercuts(killer, weak_holder)
    # rebut だけ: 対称（互いに defeat する）→ strictly ではない
    assert defeat_relations(plain, p_arg, True) == (True, True, False)
    # undercut: a は t を defeat し、t は a を defeat しない → strictly
    assert defeat_relations(killer, weak_holder, False) == (True, False, True)
    # undercut と宣言した攻撃は、結論が weak statement と一致しなくても、判定せずに defeat とする
    assert defeat_relations(plain, weak_holder, False) == (True, False, True)
    # 相手が自分を undercut するなら、rebut は defeat しない
    assert defeat_relations(weak_holder, killer, True)[0] is False


def test_undercuts_ignores_case_space_and_period():
    assert undercuts(A(R([], "Anna  is a Minor.")), A(R([], "c", weak=["anna is a minor"])))


# ---- 場面 ----
def test_S1_justified_when_opponent_cannot_attack():
    r = run(FakeAgent(main=[main(arg("m1"))]), FakeAgent())
    assert r.closed_by == "justified" and r.statuses[0] == "justified" and r.turns == 2
    assert r.final_answer == "ANSWER(justified)"


def test_S2_overruled_when_proposer_cannot_reply():
    r = run(FakeAgent(main=[main(arg("m1"))]), FakeAgent(main=[main(arg("m2"))], attack=[rebut(arg("b1"))]))
    assert r.statuses == {0: "overruled", 2: "justified"} and r.closed_by == "justified"


def test_S3_reinstated_by_undercut():
    b1 = arg("b1", weak=("a is out of stock",))
    a2 = A(R([], "a is out of stock"))
    r = run(FakeAgent(main=[main(arg("m1"))], attack=[undercut(a2, "a is out of stock")]), FakeAgent(attack=[rebut(b1)]))
    assert r.statuses[0] == "justified" and r.turns == 5
    assert [m.role for m in r.history] == [AG1, AG2, AG1]


def test_S4_proposer_gets_one_attempt_and_non_strict_defeat_is_overruled():
    # ag1 の返答は rebut だけ（対称で、strictly defeat にならない）。やり直さず、その場で overruled。
    r = run(
        FakeAgent(main=[main(arg("m1"))], attack=lambda i: rebut(arg(f"r{i}"))),
        FakeAgent(attack=[rebut(arg("b1"))]),
        max_turns=10,
    )
    assert r.statuses[0] == "overruled"
    assert any("P は strictly defeat できなかった" in t for t in r.trace)
    # strictly defeat できなかった返答は、履歴に入らず、invalid_attempts に 1 回だけ残る（対象は ag2 の攻撃＝履歴 1、主張は履歴 0）
    assert [m.role for m in r.history][:2] == [AG1, AG2]
    assert len(r.history) == 2  # ag1 の返答は、履歴に入っていない
    assert len(r.invalid_attempts) == 1
    first = r.invalid_attempts[0]
    assert first["role"] == AG1 and first["declared"] == "rebut" and first["reason"] == "strictly defeat でない"
    assert first["target_index"] == 1 and first["main_index"] == 0
    assert first["content"]["attack_type"] == "rebut" and first["content"]["argument"]["rules"]


def test_overruled_main_lets_the_other_side_present_a_main_argument():
    extra = {"integrate": [R([], "claim c")], "from_rule": [main(arg("m4"))]}
    ag1 = FakeAgent(main=[main(arg("m1"))], attack=lambda i: rebut(arg(f"r{i}")), **extra)
    ag2 = FakeAgent(main=[main(arg("m2"))], attack=[rebut(arg("b1"))], **extra)
    r = run(ag1, ag2, max_turns=10)
    roles_of_main = [(m.role, i) for i, m in enumerate(r.history) if m.kind == "main"]
    assert roles_of_main[0][0] == AG1 and any(role == AG2 for role, _ in roles_of_main)  # ag2 にも、主張の番が回る
    assert r.statuses[0] == "overruled"


def test_thread_limit_is_floor_of_half_and_integrated_main_counts_only_attacks():
    # max_turns=5 → 主張ごとの上限は 2: main_argument() の1回 + attack() の1回。
    r = run(FakeAgent(main=[main(arg("m1"))], attack=lambda i: rebut(arg(f"r{i}"))), FakeAgent(attack=lambda i: rebut(arg(f"b{i}"))), max_turns=5)
    assert any("この主張の上限（2）に到達" in t for t in r.trace)
    assert [m.role for m in r.history][:2] == [AG1, AG2]  # ag1 の主張 + ag2 の攻撃 1回だけ


def test_proposer_with_a_valid_reply_earlier_is_still_overruled_when_next_reply_fails():
    # O の 2 回目の攻撃に、P が rebut だけ（strictly でない）で返す → 前に有効な返答があっても overruled。
    r = run(
        FakeAgent(main=[main(arg("m1"))], attack=[undercut(A(R([], "w1")), "w1"), rebut(arg("r2"))]),
        FakeAgent(attack=[rebut(arg("b1", weak=("w1",))), rebut(arg("b2"))]),
    )
    assert r.statuses[0] == "overruled" and len(r.invalid_attempts) == 1
    # P が、何も作らずにできないと言うなら、overruled
    r2 = run(FakeAgent(main=[main(arg("m1"))]), FakeAgent(attack=[rebut(arg("b1"))]))
    assert r2.statuses[0] == "overruled"


def test_proposer_reply_that_does_not_defeat_is_not_counted():
    # O の攻撃（結論 q）が、P の返答（weak statement に q）を undercut する → P の rebut は、O を defeat しない。
    o_attack = rebut(A(R([], "q")))
    p_reply = rebut(A(R([], "z", weak=["q"])))
    r = run(FakeAgent(main=[main(arg("m1"))], attack=[p_reply, CANNOT_ATTACK]), FakeAgent(attack=[o_attack]))
    assert r.statuses[0] == "overruled" and len(r.invalid_attempts) == 1


def test_S5_cannot_present_with_both_mains_then_integrate_and_justified():
    # ag1 が、2つ目の main argument を出せない。履歴に両者の main があるので、ag1 が、すぐ統合する。
    r = run(
        FakeAgent(main=[main(arg("m1"))], attack=[CANNOT_ATTACK, rebut(arg("c1"))], integrate=[R(["fact m1"], "claim c")], from_rule=[main(arg("m3"))]),  # 1回目: b1 に返せない / 2回目: m2 を攻撃
        FakeAgent(main=[main(arg("m2"))], attack=[rebut(arg("b1"))]),
    )
    assert r.closed_by == "justified" and r.final_answer == "ANSWER(justified)"
    assert any(".integrate" in t for t in r.trace)
    assert [m.kind for m in r.history][-2:] == ["integrate", "main"]


def test_S6_turn_limit_integrates_without_evaluating():
    r = run(
        FakeAgent(main=[main(arg("m1")), main(arg("m3"))], attack=[CANNOT_ATTACK, rebut(arg("c1"))], integrate=[R([], "claim c")], from_rule=[main(arg("m4"))]),
        FakeAgent(main=[main(arg("m2"))], attack=[rebut(arg("b1"))]),
        max_turns=7,
    )
    assert r.closed_by == "turn_limit" and r.justified_index is None
    assert any("ag1 が統合（評価しない）" in t for t in r.trace)
    assert r.final_answer == "ANSWER(fallback)"


def test_S7_one_sided_no_integration():
    # ag2 に main argument がない。両者が続けて出せなくても、統合はせず、議論を終える。
    r = run(FakeAgent(main=[main(arg("m1"))]), FakeAgent(attack=[rebut(arg("b1"))]))
    assert r.closed_by == "no_more_arguments" and r.statuses == {0: "overruled"}
    assert not any(".integrate" in t for t in r.trace)


# ---- プロンプトの組み立て ----
def test_prompts_are_assembled_from_the_design_doc():
    ag1, ag2 = FakeAgent(main=[main(arg("m1"))]), FakeAgent(attack=[rebut(arg("b1"))])
    r = run(ag1, ag2)
    first = ag1.calls[0]
    assert first["schema"] is Phase1
    assert first["system"].startswith("You are agent 1. You are arguing with agent 2.")
    assert "The issue of this argumentation is:\nISSUE" in first["system"]
    assert "You have these theory on the issue:\nTHEORY1" in first["system"]
    assert "An argument is a finite sequence of rules such that:" in first["system"]
    assert "The argumentation so far:\n[]" in first["system"]
    assert "make new main arguments based on it." in first["system"]
    # defeat / strictly defeat（Kido 定義4）と、justified / overruled / defensible（定義5）の定義は、フェーズの説明の直後に入る
    assert "A1 strictly defeats A2 iff A1 defeats A2 and A2 does not defeat A1." in first["system"]
    assert first["system"].rstrip().endswith("A is defensible if A is neither justified nor overruled.")
    assert "is justified if no argument defeats A or if every argument which defeats A is also strictly defeated" in first["system"]
    assert first["prompt"].startswith("Now it is phase 1.\nMake your main argument")
    # ag2 の攻撃: 対象の argument が、ユーザープロンプトに入る。システムプロンプトの履歴に、main が入る。
    attack_call = ag2.calls[0]
    assert attack_call["schema"] is Attack and attack_call["system"].startswith("You are agent 2. You are arguing with agent 1.")
    assert "You have these theory on the issue:\nTHEORY2" in attack_call["system"]
    assert "The other agent's argument:\n" + json.dumps(arg("m1").model_dump(), ensure_ascii=False, indent=2) in attack_call["prompt"]
    assert '"role": "ag1"' in attack_call["system"] and "claim m1" in attack_call["system"]
    # 最終回答: ag1 が書く。フェーズの説明と、argument の書き方指示は入れない。履歴に地位が付く。
    final = ag1.calls[-1]
    assert final["schema"] is None and final["prompt"].startswith("Now the argumentation is over")
    assert "Argumentation consists of two phases" not in final["system"] and "An argument is a finite sequence" not in final["system"]
    assert '"status": "overruled"' in final["system"] or '"status": "justified"' in final["system"]
    assert r.final_answer in ("ANSWER(justified)", "ANSWER(fallback)")


def test_integrate_prompt_contains_both_warrants_and_final_prompt_switches():
    ag1 = FakeAgent(main=[main(arg("m1"))], attack=[CANNOT_ATTACK, rebut(arg("c1"))], integrate=[R([], "claim c")], from_rule=[main(arg("m3"))])
    ag2 = FakeAgent(main=[main(arg("m2"))], attack=[rebut(arg("b1"))])
    r = run(ag1, ag2)
    integrate_call = next(c for c in ag1.calls if c["schema"] is Rule)
    assert json.dumps(arg("m2").warrant().model_dump(), ensure_ascii=False, indent=2) in integrate_call["prompt"]
    assert json.dumps(arg("m1").warrant().model_dump(), ensure_ascii=False, indent=2) in integrate_call["prompt"]
    assert "Create a new strict rule C from the two warrants." in integrate_call["prompt"]
    from_rule_call = [c for c in ag1.calls if c["schema"] is Phase1][-1]
    assert "You created this new strict rule" in from_rule_call["prompt"] and "claim c" in from_rule_call["prompt"]
    assert ag1.calls[-1]["prompt"].startswith("Now the argumentation is over. Write") and "no argument was justified" not in ag1.calls[-1]["prompt"]
    assert r.closed_by == "justified"


# ---- no schema 版 ----
class FreeAgent:
    """chat() だけを持つ Agent。キーごとに、文章を順に返す。プロンプトの種類は、ユーザープロンプトで見分ける。"""

    def __init__(self, main=(), attack=(), integrate=(), from_rule=(), final="FINAL"):
        self.spec = {"main": list(main), "attack": list(attack), "integrate": list(integrate), "from_rule": list(from_rule)}
        self.final = final
        self.calls: list[dict] = []

    async def chat(self, prompt, system=None):
        self.calls.append({"prompt": prompt, "system": system})
        if prompt.startswith("Now the argumentation is over"):
            return SimpleNamespace(content=self.final)
        key = (
            "from_rule" if "You created this new strict rule" in prompt
            else "integrate" if "Create a new strict rule C" in prompt
            else "attack" if prompt.startswith("Now it is phase 2.")
            else "main"
        )
        spec = self.spec[key]
        return SimpleNamespace(content=spec.pop(0) if spec else "I cannot do it.")


class FakeJudge:
    """判定用 Agent。プロンプトの文面で、判定の種類を見分けて、あらかじめ決めた規則で答える。"""

    def __init__(self, undercut_pairs=(), rebut_default=True):
        self.undercut_pairs = set(undercut_pairs)  # (x の中の語, y の中の語)
        self.rebut_default = rebut_default
        self.calls: list[str] = []

    async def chat(self, prompt, system=None):
        self.calls.append(prompt)
        assert system is None
        if prompt.startswith("The following is an agent's reply."):
            reply = prompt.split("\n", 1)[1].rsplit("\nDoes the reply", 1)[0]
            return SimpleNamespace(content="Yes." if "cannot" in reply else "No.")
        if prompt.startswith("Argument X:"):
            x, y = prompt.split("Argument X:\n", 1)[1].split("\n\nArgument Y:\n", 1)
            y = y.split("\n\nDoes X")[0]
            if "undercut" in prompt.split("\n\n")[-1]:
                return SimpleNamespace(content="yes" if any(a in x and b in y for a, b in self.undercut_pairs) else "no")
            return SimpleNamespace(content="yes" if self.rebut_default else "no")
        if prompt.startswith("Argument:\n"):
            return SimpleNamespace(content="WARRANT OF: " + prompt.split("Argument:\n", 1)[1].split("\n\nWrite the warrant")[0])
        raise AssertionError(prompt)


def free_protocol(ag1, ag2, judge, max_turns=20):
    return NoSchemaProtocol(ag1, ag2, issue="ISSUE", theory1="T1", theory2="T2", max_turns=max_turns, judge=judge)


def run_free(ag1, ag2, judge, max_turns=20):
    r = asyncio.run(free_protocol(ag1, ag2, judge, max_turns).run())
    print("\n" + "\n".join(r.trace) + f"\n  → turns={r.turns} closed_by={r.closed_by} statuses={r.statuses}")  # noqa: T201
    return r


def test_free_S1_justified_when_opponent_says_cannot():
    r = run_free(FreeAgent(main=["I argue for X."]), FreeAgent(attack=["I cannot attack it."]), FakeJudge())
    assert r.closed_by == "justified" and r.statuses == {0: "justified"} and r.turns == 2
    assert r.final_answer == "FINAL"


def test_free_prompts_have_no_schema_instructions_and_judge_has_no_system_prompt():
    ag1, ag2, judge = FreeAgent(main=["I argue for X."]), FreeAgent(attack=["I cannot attack it."]), FakeJudge()
    run_free(ag1, ag2, judge)
    first = ag1.calls[0]
    assert "An argument is a finite sequence of rules" not in first["system"]
    assert "You speak in the form of an argument" not in first["system"]
    assert first["system"].startswith("You are agent 1.") and first["prompt"].startswith("Now it is phase 1.")
    assert "The argumentation so far:\n[" in first["system"]
    assert "I argue for X." in ag2.calls[0]["prompt"]  # 攻撃の対象の文章が、そのまま入る
    assert judge.calls and all(c.startswith(("The following is an agent's reply.", "Argument X:", "Argument:")) for c in judge.calls)
    assert "Does the reply say that the agent cannot do it? Answer yes or no." in judge.calls[0]


def test_free_rebut_only_is_symmetric_and_never_strict():
    # judge: undercut は常に no、rebut は常に yes。ag1 の返答は、無効 → やり直さず overruled。
    ag1 = FreeAgent(main=["claim 1"], attack=[f"reply {i}" for i in range(10)])
    ag2 = FreeAgent(attack=["objection 1"])
    r = run_free(ag1, ag2, FakeJudge(), max_turns=6)
    assert r.statuses == {0: "overruled"} and any("P は strictly defeat できなかった" in t for t in r.trace)


def test_free_undercut_reinstates_and_status_is_justified():
    # ag2 の反論に、ag1 が undercut（judge が yes）で返し、ag2 は返せない → 別の攻撃も探せない → justified
    judge = FakeJudge(undercut_pairs=[("out of stock", "price")])
    ag1 = FreeAgent(main=["claim 1"], attack=["camera a is out of stock"])
    ag2 = FreeAgent(attack=["price is too high"])
    r = run_free(ag1, ag2, judge)
    assert r.statuses[0] == "justified" and [m.role for m in r.history] == [AG1, AG2, AG1]


def test_free_integrate_uses_extracted_warrants_and_passes_text_through():
    ag1 = FreeAgent(main=["main of ag1"], attack=["I cannot attack it.", "attack on m2"], integrate=["NEW RULE TEXT"], from_rule=["new main"])
    ag2 = FreeAgent(main=["main of ag2"], attack=["attack on m1"])
    judge = FakeJudge()
    r = run_free(ag1, ag2, judge)
    integrate_call = next(c for c in ag1.calls if "Create a new strict rule C" in c["prompt"])
    assert "WARRANT OF: main of ag2" in integrate_call["prompt"] and "WARRANT OF: main of ag1" in integrate_call["prompt"]
    from_rule_call = next(c for c in ag1.calls if "You created this new strict rule" in c["prompt"])
    assert "NEW RULE TEXT" in from_rule_call["prompt"]
    assert [m.kind for m in r.history][-2:] == ["integrate", "main"] and r.history[-2].content == "NEW RULE TEXT"


def test_opponent_rebut_that_the_target_undercuts_is_not_recorded_and_treated_as_no_attack():
    # O の rebut を、M が undercut し返せる（O の weak statement が M の結論）→ defeat でない。履歴に入らず、やり直しもなく、justified。
    m = A(R([], "x holds"))
    r = run(FakeAgent(main=[main(m)]), FakeAgent(attack=[rebut(arg("w", weak=("x holds",)))]))
    assert r.statuses[0] == "justified"
    assert [m.kind for m in r.history] == ["main"] and len(r.invalid_attempts) == 1 and r.invalid_attempts[0]["role"] == AG2


def test_opponent_undercut_declaration_is_trusted_even_if_conclusion_does_not_match():
    bad = undercut(A(R([], "something else")), "w1")
    r = run(FakeAgent(main=[main(arg("m1", weak=("w1",)))]), FakeAgent(attack=[bad]))
    assert [m.kind for m in r.history][:2] == ["main", "attack"] and not r.invalid_attempts and r.statuses[0] != "justified"


def test_cannot_attack_reason_is_kept_in_the_trace():
    r = run(FakeAgent(main=[main(arg("m1"))]), FakeAgent())  # ag2 は CANNOT_ATTACK（reason="x"）
    assert any(t.endswith("attack → できない（鎖の長さ 1）: x") for t in r.trace)
