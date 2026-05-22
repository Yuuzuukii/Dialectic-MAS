class PromptTemplates:
    LEARNED_FINDINGS = """
Previous discussion result:
- Do not repeat the same recommendation with the same concrete premises or warrant.
- Do not restate a previously defeated or unresolved main argument as if it were new.
- If IntegratedRules are available, use them to build a revised argument instead of copying an earlier one.
"""

    MAIN_ARGUMENT = """
Task:
Decide whether you can construct one main argument for your stance on the Issue.
If you can, set can_generate to YES and construct the Argument.
If you cannot construct a valid main argument, set can_generate to NO and omit Argument.

Rules:
- The final consequent must directly answer the Issue.
- For a purchase Issue, the final consequent should recommend a concrete object to buy.
- A conclusion that only rejects an object, such as "We should not buy X", belongs to a defeating argument, not a main argument.
- Do not repeat a previous main argument.
- If IntegratedRules are available in this round, use at least one of them as the basis of the new main argument.
- In a later round, do not rebuild the same argument from the same concrete premises as your previous main argument.
- A later-round argument may reach the same recommendation only if it explicitly uses a new IntegratedRule to resolve the previous conflict.

Argument requirements:
- Use ordered rules.
- Each rule has antecedent.strong, antecedent.weak_negation, and consequent.
- Conc collects the consequents of the rules.
- Ass collects all weak_negation entries.
"""

    DEFEATING_ARGUMENT = """
Task:
Decide whether you can defeat the target argument. If yes, construct one defeating argument.

Available attacks:
- rebut: your Conc directly contradicts a target Conc.
- undercut: your Conc directly contradicts or invalidates a target Ass.

Constraints:
- Use only your stance, background knowledge, and the target argument.
- Do not invent facts or product properties.
- A different recommendation is not a rebut unless it directly contradicts the target conclusion.
- If the target has no Ass, undercut is impossible.
- If you are the Proponent, do not repeat your previous move in this branch.
- If no valid rebut 1or undercut is available, set can_defeat to NO and omit Argument.

Output shape:
- Put only rules, Conc, and Ass inside Argument.
- Put attack and target only inside Attack.
- Do not put attack or target inside Argument.
"""

    COUNTER_ARGUMENT = """
Task:
Decide whether you can defeat the target argument. If yes, construct one counterargument.

Available attacks:
- rebut: your Conc directly contradicts a target Conc.
- undercut: your Conc directly contradicts or invalidates a target Ass.

Constraints:
- Use only your stance, background knowledge, and the target argument.
- Do not invent facts or product properties.
- A different recommendation is not a rebut unless it directly contradicts the target conclusion.
- If the target has no Ass, undercut is impossible.
- If you are the Proponent, do not repeat your previous move in this branch.
- If no valid rebut or undercut is available, set can_defeat to NO and omit Argument.

Output shape:
- Put only rules, Conc, and Ass inside Argument.
- Put attack and target only inside Attack.
- Do not put attack or target inside Argument.
- The counterargument may later become the target of another defeat check, so its Argument payload must have the same schema as a main argument.
"""

    UNDERCUT_CHECK = """
Task:
Decide whether you can undercut the target argument. If yes, construct one undercutting argument.

Undercut:
- Your Conc must directly contradict or invalidate one target Ass.
- If the target has no Ass, set can_undercut to NO and omit Argument.
- Use only your stance, background knowledge, and the target argument.
- If you are the Proponent, do not repeat your previous move in this branch.

Output shape:
- Put only rules, Conc, and Ass inside Argument.
- Put attack and target only inside Attack.
- Do not put attack or target inside Argument.
"""

    VALIDATE_ATTACK = """
Task:
Validate the declared attack.

Rules:
- rebut is valid only if attacker.Conc directly contradicts target.Conc.
- undercut is valid only if attacker.Conc directly invalidates target.Ass.
- A different recommendation is not a rebut unless it directly contradicts the target conclusion.
"""

    GENERALIZATION = """
Task:
Extract generalized criteria from the two warrants.

Rules:
- Output reusable criteria, not a concrete recommendation.
- Do not mention specific objects such as a, b, or c.
- Preserve the intent of the original warrants.
- Avoid placeholders such as "criterion 1" or "condition 1".
"""

    INTEGRATION = """
Task:
Integrate the generalized criteria into one reusable rule.

Rules:
- Do not output a concrete product recommendation.
- The rule must be reusable in a later main argument.
- Preserve the combined intent of the criteria.
- Avoid placeholders such as "integrated condition", "concrete integrated conditions", and "generalized conclusion".
- Spell out the actual generalized conditions and consequent.
"""


PROMPTS = {
    "learned_findings": PromptTemplates.LEARNED_FINDINGS,
    "main_argument": PromptTemplates.MAIN_ARGUMENT,
    "defeating_argument": PromptTemplates.DEFEATING_ARGUMENT,
    "counter_argument": PromptTemplates.COUNTER_ARGUMENT,
    "undercut_check": PromptTemplates.UNDERCUT_CHECK,
    "validate_attack": PromptTemplates.VALIDATE_ATTACK,
    "generalization": PromptTemplates.GENERALIZATION,
    "integration": PromptTemplates.INTEGRATION,
}
