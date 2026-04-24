class PromptTemplates:

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
        ],
        "weak_negation": [
          "Assumption that there is no evidence for an argument (not negation of facts) premise 1", 
          "Assumption that there is no evidence for an argument (not negation of facts) premise 2", 
          ...
        ]
      },
      "consequent": "Natural language statement of the conclusion (conclusion only) derived from strong and weak_negation",
    }
  ],
  ...
  "Conc": [
    "consequent of r1", 
    "consequent of r2", 
  ...],
  "Ass": [
    "weak_negation of r1", 
    "weak_negation of r2", 
    ...
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
  - (attack): Attack method (rebut or undercut)
  - antecedent.strong: A list of minimum necessary premises to derive the conclusion (may include consequents from previous rules)
  - antecedent.weak_negation: A list of assumptions that there is no evidence for certain arguments (not negation of facts) necessary to derive the conclusion
  - consequent: Conclusion (conclusion only) derived from strong and weak_negation
- Conc: A list collecting the consequent of each rule
- Ass: A list collecting the weak_negation of each rule

Task:
Determine whether you can defeat the opponent's Argument, and if possible, generate one counterargument.
Answer NO only if you truly cannot counterargue.

Constraint:
For counterarguments, choose one of the following attack methods.
Counterarguments must follow the argumentation structure below.
Counterarguments must ""always"" be stated from your own stance.
Counterarguments must ""never"" reuse your past antecedent.strong.

Attack methods:
・rebut: When your stance semantically contradicts or conflicts with a proposition in the opponent's argument's conclusion (Conc)
  → Construct an inference rule that negates the opponent's conclusion or derives a conclusion incompatible with the opponent's conclusion
  → If the opponent's argument's strong is empty, rebut is not possible.
・undercut: When your stance can provide evidence that a proposition in the opponent's argument's assumption (Ass) is correct
  → Construct an inference rule that negates the weak negation assumption used in the opponent's inference rule, or shows that the assumption does not hold
  → If the opponent's argument's weak_negation is empty, undercut is not possible.

Argumentation structure:
- rules: An array of inference rules. Each rule represents an inference from premises (antecedent) to a conclusion (consequent)
  Important: rules have an order. The consequent of an earlier rule can be used in the antecedent.strong of a later rule.
  Include only the minimum necessary rules to derive the final conclusion (consequent of the last rule).
  - id: Rule identifier (r1, r2, ...)
  - attack: Attack method (rebut or undercut)
  - antecedent.strong: A list of minimum necessary premises to derive the conclusion (may include consequents from previous rules)
  - antecedent.weak_negation: A list of assumptions that there is no evidence for certain arguments (not negation of facts) necessary to derive the conclusion
  - consequent: Conclusion (conclusion only) derived from strong and weak_negation
- Conc: A list collecting the consequent of each rule
- Ass: A list collecting the weak_negation of each rule

    Output only the following JSON:
{
  "can_defeat": "YES or NO",
  "Argument": {
    "attack": "rebut or undercut",
    "rules": [
      {
        "id": "r1",
        "antecedent": {
          "strong": [
            "Minimum necessary premise 1 to derive conclusion", 
            "Minimum necessary premise 2 to derive conclusion", 
            ...
          ],
          "weak_negation": [
            "Assumption that there is no evidence for an argument (not negation of facts) premise 1", 
            "Assumption that there is no evidence for an argument (not negation of facts) premise 2",
            ...
          ]
        },
        "consequent": "For rebut: statement negating opponent's conclusion; For undercut: statement showing opponent's rule cannot be applied",
      }
    ],
    ...
    "Conc": [
      "consequent of r1", 
      "consequent of r2", 
      ...
    ],
    "Ass": [
      "weak_negation of r1", 
      "weak_negation of r2", 
      ...
    ]
  }
}
    """

    CHARACTERIZATION = """
The above are two conflicting arguments, Argument1 and Argument2.
Each has the following meaning.
The argument has the following structure:
  - antecedent.strong: A list representing the properties of the minimum necessary premises to derive the conclusion
  - consequent: The conclusion (conclusion only) derived from strong

Task:
Characterize the given Argument1 and Argument2.
This operation clarifies the characteristics of each of the two conflicting arguments.

Constraint:
Output must follow the argumentation structure below.

Argumentation structure:
- antecedent.strong: A list representing the properties of the minimum necessary premises to derive the conclusion
- consequent: The property of the conclusion (conclusion only) derived from strong

Output only the following JSON:
Output:
{
  "Argument": {
    "C1": {
      "strong": [
        "Property 1 of minimum necessary premises to derive conclusion (do not include expressions uniquely identifying specific objects)",
        "Property 2 of minimum necessary premises to derive conclusion (do not include expressions uniquely identifying specific objects)",
        ...
      ],
      "consequent": "Natural language statement representing the property of the conclusion (conclusion only) derived from strong",
    },
    "C2": {
      "strong": [
        "Property 1 of minimum necessary premises to derive conclusion (do not include expressions uniquely identifying specific objects)",
        "Property 2 of minimum necessary premises to derive conclusion (do not include expressions uniquely identifying specific objects)",
        ...
      ],
      "consequent": "Natural language statement representing the property of the conclusion (conclusion only) derived from strong (do not include expressions uniquely identifying specific objects)",
    }
  }
}
    """

    GENERALIZATION = """
The above are C1 and C2, representing the properties of a pair of conflicting arguments.

Each argument (C1, C2) has the following structure:
Argumentation structure:
- antecedent.strong: A list representing the properties of the minimum necessary premises to derive the conclusion
- consequent: The property of the conclusion (conclusion only) derived from strong

Task:
Based on the given C1 and C2, construct one consensus core E (Generalization result) that both parties can easily accept.

Constraint:
If there are facts (strong) common to both, they must be included.
Do not use the strong of C1 and C2 as they are.
Each premise of the consensus core must be able to encompass both positions.

Output only the following JSON:
Output:
{
  "Argument": {
    "E": {
      "strong": [
        "Consensus core premise (natural language) 1",
        "Consensus core premise (natural language) 2",
        "..."
      ],
      "consequent": "Conclusion (conclusion only) derived from the consensus core"
    }
  }
}
    """

    ANSWER = """
The above are the warrants of two conflicting arguments Argument1 and
Argument2, and the consensus core E of both.
Structure of premise information:
- Warrant of Argument1, Argument2: Premises and conclusions of
individual cases claimed by each agent
- Consensus core E: Property-level rules that both parties can agree
on
Task:
Based on the given consensus core E, present a solution that
satisfies the conditions of E.strong as much as possible, and
make it the final answer.
Constraint:
- Individual conclusions appearing in the warrants of Argument1 and
Argument2 ""must"" not be used as they are in the final answer
- The final answer must be a concrete solution that satisfies E.strong
Output only the following JSON:
{
"final_answer": "Final answer (simple)"
}
    """


PROMPTS = {
    "main_argument": PromptTemplates.MAIN_ARGUMENT,
    "defeating_argument": PromptTemplates.DEFEATING_ARGUMENT,
    "characterization": PromptTemplates.CHARACTERIZATION,
    "generalization": PromptTemplates.GENERALIZATION,
    "answer": PromptTemplates.ANSWER,
}
