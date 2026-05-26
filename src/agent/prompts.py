class PromptTemplates:
    MAIN_ARGUMENT_AVAILABILITY = """
Issue: {issue}

Task: Construct an argument for your position on the Issue.
- You can only state what is stated from your own perspective; you cannot state information that is not part of your perspective.
- An argument is a finite sequence of rules r_1, ..., r_n.
- Each rule: antecedent (strong premises + weak_negation assumptions) → consequent.
- Strong antecedents of r_i (i > 1) must be consequents of earlier rules in the sequence.
- Every non-final consequent must appear as a strong antecedent in a later rule.
- The final conclusion should clearly express your opinion on the Issue and include your "Concise and specific" ideas regarding it.
- Use as few rules as possible. A single rule is sufficient if your stance directly supports your conclusion.
- If an argument can be constructed: can_generate=YES, include Argument.
- If not: can_generate=NO, omit Argument.

{revision_context}
"""

    DEFEATING_ARGUMENT = """
Task: Construct a defeating argument against the target argument.
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).
- You can only state what is stated from your own perspective; you cannot state information that is not part of your perspective.
- The attacker is a finite sequence of rules; later rules must follow from earlier ones.
- Use as few rules as possible. A single rule is sufficient if your stance directly supports your conclusion.
- If can_defeat=YES: include Argument and Attack (method + exact targeted statement).
- If can_defeat=NO: omit Argument and Attack.
"""

    COUNTER_ARGUMENT = """
Task: Construct a counterargument against the target argument.
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).
- You can only state what is stated from your own perspective; you cannot state information that is not part of your perspective.
- The attacker is a finite sequence of rules; later rules must follow from earlier ones.
- Use as few rules as possible. A single rule is sufficient if your stance directly supports your conclusion.
- Non-repetition: do not derive the same conclusion from substantially the same rules or warrant as any of your previous arguments.
- A counterargument that merely restates your original main argument is not allowed.
- If the only possible counterargument repeats one of your previous arguments, set can_defeat=NO.
- If can_defeat=YES: include Argument and Attack (method + exact targeted statement).
- If can_defeat=NO: omit Argument and Attack.
"""

    UNDERCUT_CHECK = """
Task: Construct an undercutting argument against the target argument.
- undercut: Conc(attacker) explicitly negates Ass(target).
- You can only state what is stated from your own perspective; you cannot state information that is not part of your perspective.
- The attacker is a finite sequence of rules; later rules must follow from earlier ones.
- Use as few rules as possible. A single rule is sufficient if your stance directly supports your conclusion.
- If can_undercut=YES: include Argument.
- If can_undercut=NO: omit Argument.
"""

    VALIDATE_ATTACK = """
Task: Validate the declared attack.
- rebut: Conc(attacker) explicitly negates Conc(target).
- undercut: Conc(attacker) explicitly negates Ass(target).
"""

    GENERALIZATION = """
Task: Generalize each warrant into a reusable abstract criterion.
- Abstract away from issue-specific entities.
- For each warrant, identify the underlying value or principle that makes it rationally compelling.
- Express that principle as the criterion's conditions (strong) and conclusion (consequent).
- Record the principle name explicitly.
"""

    INTEGRATION = """
Task: Integrate the generalized criteria into one reusable rule.
- Identify the shared higher-level principle that unifies the underlying values of all criteria.
- Express that principle as a single abstract rule whose antecedent covers each criterion as an alternative sufficient condition (OR).
- The rule should be more abstract than any individual criterion, not merely a list of them.
- Output one rule applicable to future arguments.
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
