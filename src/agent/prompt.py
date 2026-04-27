class PromptTemplates:

    # For constructing main arguments (common to AG1 and AG2)
    MAIN_ARGUMENT = """
    Task:
    Based on the given Issue and your stance, construct one main Argument representing your position.

    Constraint:
    The main Argument must follow the structure of argumentation below.
    The main Argument must recommend exactly one buying option as the final conclusion.
    Do not include side conclusions about rejecting other options unless they are strictly necessary premises for the single final buying conclusion.
    The last rule's consequent must be one sentence of the form "We should buy ...".
    Do not output multiple independent recommendations in one main Argument.

    Argumentation structure:
      - rules: An array of inference rules. Each rule represents an inference from premises (antecedent) to a conclusion (consequent)
        Important: rules have an order. The consequent of an earlier rule can be used in the antecedent.strong of a later rule.
        Include only the minimum necessary rules to derive the final conclusion (consequent of the last rule).
        - id: Rule identifier (r1, r2, ...)
        - antecedent.strong: A list of natural language statements representing the minimum necessary premises to derive the conclusion (may include consequents from previous rules)
        - consequent: A natural language statement of the conclusion (conclusion only) derived from antecedent.strong
      - Conc: A list collecting the consequent of each rule

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

Attack method:
・rebut: When your stance semantically contradicts or conflicts with a proposition in the opponent's argument's conclusion (Conc)
  → Construct an inference rule that negates the opponent's conclusion or derives a conclusion incompatible with the opponent's conclusion
  → If the opponent's argument's strong is empty, rebut is not possible.

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
        "consequent": "Statement negating the opponent's conclusion or deriving an incompatible conclusion",
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
Extract generalized buying criteria from the two warrants.

Constraint:
- Output generalized criteria, not a concrete product recommendation.
- Do not mention specific objects such as a, b, or c.
- Each criterion must preserve the intent of at least one warrant while remaining reusable for a future main argument.
- Express the result as argument-style criteria that can later be integrated.
- Do not use placeholders such as "criterion 1", "criterion 2", "condition 1", or "condition 2" as actual content.
- Use concrete natural-language buying conditions.

Output only the following JSON:
Output:
{
  "Argument": {
    "Generalization": {
      "criteria": [
        {
          "id": "g1",
          "strong": [
            "Generalized buying criterion 1",
            "Generalized buying criterion 2"
          ],
          "consequent": "A generalized buying conclusion derived from the criterion"
        }
      ],
      "summary": "Short summary of the reusable buying criteria"
    }
  }
}
    """

    INTEGRATION = """
The above are the original warrants and the generalized buying criteria derived from them.

Task:
Integrate the generalized buying criteria into one new buying rule that can be appended to both agents' stance and reused by the main argument generation prompt.

Constraint:
- Do not output a concrete recommendation or product name.
- Output one reusable rule about when we should buy something.
- The rule must be phrased so it can be added directly to a stance, like "If ..., we should buy it."
- The rule must be more general than the original warrants while still preserving their combined intent.
- Do not use placeholders such as "integrated buying condition 1" or "integrated buying condition 2".
- The `strong` entries and the `rule` must contain concrete natural-language conditions derived from the given criteria.

Output only the following JSON:
{
  "Argument": {
    "Integration": {
      "strong": [
        "Integrated buying condition 1",
        "Integrated buying condition 2"
      ],
      "consequent": "we should buy it",
      "rule": "If integrated buying condition 1 and integrated buying condition 2, we should buy it."
    }
  }
}
    """


PROMPTS = {
    "main_argument": PromptTemplates.MAIN_ARGUMENT,
    "defeating_argument": PromptTemplates.DEFEATING_ARGUMENT,
    "generalization": PromptTemplates.GENERALIZATION,
    "integration": PromptTemplates.INTEGRATION,
}
