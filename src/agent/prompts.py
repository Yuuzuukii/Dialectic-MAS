class PromptTemplates:
    MAIN_ARGUMENT_AVAILABILITY = """
Issue:
{issue}

Task:
Construct an argument that presents your position on the Issue, if such an argument can be formed from your knowledge.

Output:
- If an argument can be constructed, set can_generate to YES and include Argument.
- If no such argument can be constructed, set can_generate to NO and omit Argument.

Argument Constraints:
- Argument is a finite sequence of rule instances.
- Each rule may use established premises in its strong antecedent and assumptions in its weak_negation antecedent.
- Every strong antecedent used in a non-initial rule must be derived as the consequent of an earlier rule in the same Argument.
- Every consequent except the final consequent must be used to support a later rule in the same Argument.
- Do not include two rules with the same consequent.
- The final rule must derive the conclusion that expresses your position on the Issue.
- Output only rules in Argument; the system derives Conc and Ass from those rules.

{revision_context}
"""


    DEFEATING_ARGUMENT = """
Task:
Construct a defeating argument against the target argument, if possible.

Terms:
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- Output only rules in Argument; the system derives Conc and Ass from those rules.
- If can_defeat is YES, include Argument and Attack.
- If can_defeat is NO, omit Argument and Attack.
- In Attack, declare the method and the exact target Conc or Ass statement attacked by Argument.
"""

    COUNTER_ARGUMENT = """
Task:
Construct a counterargument against the target argument, if possible.

Terms:
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- Output only rules in Argument; the system derives Conc and Ass from those rules.
- Proponent non-repetition rule: do not repeat a previous Proponent argument.
- Repetition means deriving the same conclusion from the same or substantially
  same rules, premises, or warrant.
- A counterargument that only restates the original main argument is not allowed.
- If the only possible counterargument repeats a previous Proponent argument,
  set can_defeat to NO.
- If can_defeat is YES, include Argument and Attack.
- If can_defeat is NO, omit Argument and Attack.
- In Attack, declare the method and the exact target Conc or Ass statement attacked by Argument.
"""

    UNDERCUT_CHECK = """
Task:
Construct an undercutting argument against the target argument, if possible.

Term:
- undercut: Conc(attacker) explicitly negates Ass(target).

Rules:
- Use your stance, background knowledge, and the target argument.
- In one Argument, later rules must be derived from earlier rules.
- Do not include independent side conclusions.
- Output only rules in Argument; the system derives Conc and Ass from those rules.
- If can_undercut is YES, include Argument.
- If can_undercut is NO, omit Argument.
- The system already records the attack type and target; do not output attack metadata.
"""

    VALIDATE_ATTACK = """
Task:
Validate the declared attack.

Terms:
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).
"""

    GENERALIZATION = """
Task:
Generalize the given warrants.

Rules:
- Output reusable criteria.
- Do not mention issue-specific entities.
"""

    INTEGRATION = """
Task:
Integrate the generalized criteria.

Rules:
- Output one reusable rule.
- The rule may be used in a later main argument.
- Do not combine alternative criteria with OR.
- Prefer a balanced criterion that can compare how well later arguments satisfy the criteria.
"""


PROMPTS = {
    "main_argument_availability": PromptTemplates.MAIN_ARGUMENT_AVAILABILITY,
    "defeating_argument": PromptTemplates.DEFEATING_ARGUMENT,
    "counter_argument": PromptTemplates.COUNTER_ARGUMENT,
    "undercut_check": PromptTemplates.UNDERCUT_CHECK,
    "validate_attack": PromptTemplates.VALIDATE_ATTACK,
    "generalization": PromptTemplates.GENERALIZATION,
    "integration": PromptTemplates.INTEGRATION,
}
