class PromptTemplates:
    LEARNED_FINDINGS = """
    Previous discussion result:
    - As a result of the previous discussion, your earlier claim was rejected for the following reasons.
    - You must take these rejection reasons into account when generating the next argument or rebuttal.
    - Because the earlier claim was rejected, you must not continue to assert the same rejected claim unless the rejection reason is explicitly resolved in your new argument.
    """

    # For constructing main arguments (common to AG1 and AG2)
    MAIN_ARGUMENT = """
    Task:
    Based on the given Issue and your stance, construct one main Argument representing your position.

    Constraint:
    The main Argument must follow the structure of argumentation below.

    Argumentation structure:
      - rules: An array of inference rules. Each rule represents an inference from premises (antecedent) to a conclusion (consequent)
        Important: rules have an order. The consequent of an earlier rule can be used in the antecedent.strong of a later rule.
        Include only the minimum necessary rules to derive the final conclusion (consequent of the last rule).
        - id: Rule identifier (r1, r2, ...)
        - antecedent.strong: A list of natural language statements representing the minimum necessary premises to derive the conclusion (may include consequents from previous rules)
        - antecedent.weak_negation: A list of natural language statements representing assumptions that there is no evidence for certain arguments (not negation of facts) necessary to derive the conclusion
        - consequent: A natural language statement of the conclusion (conclusion only) derived from strong and weak_negation
      - Conc: A list collecting the consequent of each rule
      - Ass: A list collecting the weak_negation of each rule

    Output only the following JSON:
    {
    "Argument": {
      "rules": [
        {
          "id": "r1",
          "antecedent": {
            "strong": [
              "Minimum necessary premise 1 to derive conclusion", 
              "Minimum necessary premise 2 to derive conclusion", 
              ...
            ]
          },
          "consequent": "Natural language statement of the conclusion (conclusion only) derived from antecedent.strong",
        }
      ],
      ...
      "Conc": [
        "consequent of r1", 
        "consequent of r2", 
      ]
    }
    }
    """
    
    # For determining defeatability and constructing counterarguments (common to AG1 and AG2)
    DEFEATING_ARGUMENT = """
The above is the opponent's argument.
Each has the following meaning.
The argument has the following structure:
- rules: An array of inference rules. Each rule represents an inference from premises (antecedent) to a conclusion (consequent)
  Important: rules have an order. The consequent of an earlier rule can be used in the antecedent.strong of a later rule.
  Include only the minimum necessary rules to derive the final conclusion (consequent of the last rule).
  - id: Rule identifier (r1, r2, ...)
  - attack: Attack method (rebut)
  - antecedent.strong: A list of minimum necessary premises to derive the conclusion (may include consequents from previous rules)
  - consequent: Conclusion (conclusion only) derived from antecedent.strong
- Conc: A list collecting the consequent of each rule

Task:
Determine whether you can defeat the opponent's Argument, and if possible, generate one counterargument.
Answer NO only if you truly cannot counterargue.

Constraint:
Counterarguments must follow the argumentation structure below.
Counterarguments must ""always"" be stated from your own stance.
Counterarguments must ""never"" reuse your past antecedent.strong.
Counterarguments must use only the rebut attack method.
Counterarguments must use only facts that are explicitly available from your own stance, the provided background knowledge, or the opponent's argument.
Do not invent new facts, hidden conditions, or unstated product properties.
Do not introduce premises that contradict your own stance or the provided discussion context.
If you cannot explicitly negate the opponent's conclusion using those available facts, answer NO.
The final consequent must directly reject the opponent's final recommendation, rather than propose a different recommendation.

Attack method:
・rebut: When your stance semantically contradicts or conflicts with a proposition in the opponent's argument's conclusion (Conc)
  → Construct an inference rule that explicitly negates the opponent's conclusion
  → If the opponent's argument's strong is empty, rebut is not possible.
  → The negation must be justified by available facts, not by fabricated facts.

Argumentation structure:
- rules: An array of inference rules. Each rule represents an inference from premises (antecedent) to a conclusion (consequent)
  Important: rules have an order. The consequent of an earlier rule can be used in the antecedent.strong of a later rule.
  Include only the minimum necessary rules to derive the final conclusion (consequent of the last rule).
  - id: Rule identifier (r1, r2, ...)
  - attack: Attack method (rebut)
  - antecedent.strong: A list of minimum necessary premises to derive the conclusion (may include consequents from previous rules)
  - consequent: Conclusion (conclusion only) derived from antecedent.strong
- Conc: A list collecting the consequent of each rule

    Output only the following JSON:
{
  "can_defeat": "YES or NO",
  "Argument": {
    "attack": "rebut",
    "rules": [
      {
        "id": "r1",
        "antecedent": {
          "strong": [
            "Minimum necessary premise 1 to derive conclusion", 
            "Minimum necessary premise 2 to derive conclusion", 
            ...
          ]
        },
        "consequent": "Statement explicitly negating the opponent's conclusion",
      }
    ],
    ...
    "Conc": [
      "consequent of r1", 
      "consequent of r2", 
      ...
    ]
  }
}
    """

    GENERALIZATION = """
The above are the warrants of two conflicting arguments, Argument1 and Argument2.

Each warrant has the following structure:
Argumentation structure:
- antecedent.strong: A list of the minimum necessary premises to derive the conclusion
- consequent: The conclusion (conclusion only) derived from the premises

Task:
Extract generalized criteria from the two warrants.

Constraint:
- Output generalized criteria, not a concrete recommendation.
- Do not mention specific objects such as a, b, or c.
- Each criterion must preserve the intent of at least one warrant while remaining reusable for a future main argument.
- Express the result as argument-style criteria that can later be integrated.
- Do not use placeholders such as "criterion 1", "criterion 2", "condition 1", or "condition 2" as actual content.
- Use concrete natural-language conditions, but do not hard-code a domain-specific action unless that action is explicitly required by the given warrants.

Output only the following JSON:
Output:
{
  "Argument": {
    "Generalization": {
      "criteria": [
        {
          "id": "g1",
          "strong": [
            "A concrete generalized condition derived from a warrant",
            "Another concrete generalized condition derived from a warrant"
          ],
          "consequent": "A generalized conclusion derived from the criterion"
        }
      ]
    }
  }
}
    """

    INTEGRATION = """
The above are the original warrants and the generalized criteria derived from them.

Task:
Integrate the generalized criteria into one new reusable rule that can be appended to both agents' stance and reused by the main argument generation prompt.

Constraint:
- Do not output a concrete recommendation or product name.
- Output one reusable rule about when the conclusion should follow from the integrated conditions.
- The rule must be phrased so it can be added directly to a stance, using a generalized consequent derived from the warrants instead of a fixed action.
- The rule must be more general than the original warrants while still preserving their combined intent.
- Do not use placeholders such as "integrated condition 1" or "integrated condition 2".
- The `strong` entries and the `rule` must contain concrete natural-language conditions derived from the given criteria.
- Do not hard-code a domain-specific action unless that action is explicitly required by the given warrants.

Output only the following JSON:
{
  "Argument": {
    "Integration": {
      "strong": [
        "A concrete integrated condition derived from the criteria",
        "Another concrete integrated condition derived from the criteria"
      ],
      "consequent": "A generalized conclusion derived from the integrated conditions",
      "rule": "If the concrete integrated conditions hold, then the generalized conclusion follows."
    }
  }
}
    """


PROMPTS = {
    "learned_findings": PromptTemplates.LEARNED_FINDINGS,
    "main_argument": PromptTemplates.MAIN_ARGUMENT,
    "defeating_argument": PromptTemplates.DEFEATING_ARGUMENT,
    "generalization": PromptTemplates.GENERALIZATION,
    "integration": PromptTemplates.INTEGRATION,
}
