
def evaluate_with_llm(response: dict, evaluator_model) -> dict:
    """
    Evaluate a dialectical reasoning output using an LLM as evaluator.
    Returns a dictionary with numeric scores (1–10) and model info.
    """
    prompt = f"""
    You are an evaluator LLM. Your task is to rate the following dialectical reasoning output on a scale from 1 to 10 for each of the following:

    1. Clarity – Are the ideas clearly expressed? Is the language fluent and understandable?
    2. Coherence – Does the final synthesis follow logically from the initial opinion and counterarguments?
    3. Originality – Does the synthesis demonstrate novel insight, creative framing, or non-obvious conclusions?
    4. Dialecticality – Does the response meaningfully integrate both perspectives, showing fair reasoning and synthesis?

    Scoring rubric:
    - 9–10: Outstanding – excellent quality for the axis
    - 7–8: Good – solid, with minor issues
    - 5–6: Adequate – average quality, some issues
    - 1–4: Weak – lacking clarity, logic, originality, or synthesis

    IMPORTANT: Rate strictly. Perfect scores are rare.

    Evaluate the following reasoning:

    Question:
    {response['question']}

    Initial Opinion:
    {response['initial_opinion']}

    Counterarguments:
    {response['counterarguments']}

    Final Synthesis:
    {response['final_synthesis']}

    Respond ONLY with a JSON object in the format:
    {{
      "clarity": <int>,
      "coherence": <int>,
      "originality": <int>,
      "dialecticality": <int>,
      "evaluator_model": "{evaluator_model.model}"
    }}
    """.strip()

    try:
        raw = evaluator_model.invoke(prompt)
        import json
        scores = json.loads(raw)
        return scores
    except Exception as e:
        print(f"⚠️ Evaluation failed: {e}")
        return {
            "clarity": None,
            "coherence": None,
            "originality": None,
            "dialecticality": None,
            "evaluator_model": evaluator_model.model
        }

def compute_final_evaluation(scores: dict, values_info: dict) -> dict:
    """
    Generate a summary evaluation label based on quality scores, values, and anomalies.

    Returns:
        {
            "label": "Excellent reasoning",
            "summary": "...",
            "scores": {...},
            "values_detected": [...],
            "anomalies_detected": [...]
        }
    """

    clarity = scores.get("clarity", 0)
    coherence = scores.get("coherence", 0)
    originality = scores.get("originality", 0)
    dialecticality = scores.get("dialecticality", 0)

    values = values_info.get("values", [])
    anomalies = values_info.get("anomalies", [])

    num_values = len(values)
    num_anomalies = len(anomalies)

    avg_score = sum([clarity, coherence, originality, dialecticality]) / 4

    # Decide final label
    if avg_score >= 8 and num_anomalies == 0 and num_values >= 2:
        label = "Excellent reasoning"
    elif avg_score >= 7 and num_anomalies <= 1 and num_values >= 1:
        label = "Good reasoning with minor issues"
    elif avg_score >= 5 and num_anomalies <= 2:
        label = "Acceptable but needs improvement"
    else:
        label = "Problematic reasoning"

    # Generate short explanation
    summary = (
        f"Average score: {avg_score:.1f}/10 | "
        f"Values: {num_values} | Anomalies: {num_anomalies}"
    )

    return {
        "label": label,
        "summary": summary,
        "scores": scores,
        "values_detected": values,
        "anomalies_detected": anomalies
    }

