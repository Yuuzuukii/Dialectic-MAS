import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.agent_migration.agents import Agent

AttackType = Literal["rebut", "undercut"]


class AntecedentSchema(BaseModel):
    from_rules: list[int] = Field(
        default_factory=list,
        description=(
            "Strong premises, given as the numbers (1-based) of EARLIER rules in this Argument "
            "whose consequents this rule relies on. The first rule has none (empty list). "
            "Leave empty when the rule states a claim from your stance without a premise."
        ),
    )
    weak_negation: list[str] = Field(
        default_factory=list,
        description=(
            "Exception clauses ('unless X'): defeasible assumptions of the form 'X is not "
            "the case', held only in the absence of evidence to the contrary. An "
            "undercutting attack defeats one of these by proving that X actually holds."
        ),
    )


class RuleSchema(BaseModel):
    antecedent: AntecedentSchema = Field(
        description="The earlier rules this rule relies on, and its exception clauses."
    )
    consequent: str = Field(description="The claim this rule concludes.")


class ArgumentSchema(BaseModel):
    rules: list[RuleSchema] = Field(
        default_factory=list,
        description=(
            "Finite sequence of rules forming an argument; the final rule is the warrant of "
            "the argument."
        ),
    )


class TargetReference(BaseModel):
    number: int = Field(
        description=(
            "The number of the attacked item, copied from the list shown in the instruction: "
            "for a rebut, a number in the target's conclusions; for an undercut, a number in "
            "the target's assumptions; when the target is listed as numbered sentences, the "
            "sentence number."
        )
    )


class TargetQuote(BaseModel):
    statement: str = Field(
        description=(
            "The sentence or phrase of the target argument that this argument attacks, copied "
            "word for word from the target's text (no paraphrase, no ellipsis, no combining "
            "sentences)."
        )
    )


class AttackMetadata(BaseModel):
    method: AttackType = Field(
        description=(
            "Attack method used by this argument: "
            "'rebut' when a conclusion of this argument contradicts a conclusion of the "
            "target argument; "
            "'undercut' when a conclusion of this argument contradicts an assumption of "
            "the target argument."
        )
    )
    target: TargetReference = Field(
        description="The item of the target argument that this argument attacks, chosen by number."
    )


class AttackMetadataFree(BaseModel):
    method: AttackType = Field(
        description=(
            "Attack method used by this argument: "
            "'rebut' when a claim of this argument directly opposes a claim of the target "
            "argument; "
            "'undercut' when a claim of this argument establishes that a presumption the "
            "target argument relies on by default does not hold."
        )
    )
    target: TargetQuote = Field(
        description="The words of the target argument that this argument attacks, copied from its text."
    )


class NoveltyCheck(BaseModel):
    closest_earlier_id: str | None = Field(
        default=None,
        description=(
            "The id of your own earlier argument in this debate (your main argument or an "
            "earlier counterargument) that your planned counterargument is closest to. Null "
            "only if there is none."
        ),
    )
    adds_new_reason: Literal["YES", "NO"] = Field(
        description=(
            "YES only if your planned counterargument rests on a different ground (one of the "
            "distinct reasons your stance gives for your position, or a genuinely different "
            "consideration) than the grounds your earlier arguments used. NO if it only "
            "elaborates a ground you already used: a further example, mechanism or detail, a "
            "restatement, or the same ground aimed at a different part of the attack."
        )
    )
    new_reason: str = Field(
        default="",
        description=(
            "Name the new ground in one sentence, and which ground of your stance it is. Empty "
            "when adds_new_reason is NO."
        ),
    )


class MainArgumentSchema(BaseModel):
    can_generate: Literal["YES", "NO"] = Field(
        description="determining whether you can make an argument regarding the given issue."
    )
    reason: str = Field(description="Brief reason for the availability decision.")
    Argument: ArgumentSchema | None = Field(
        default=None, description="Required only when can_generate is YES."
    )


class AttackSchema(BaseModel):
    Novelty: NoveltyCheck | None = Field(
        default=None,
        description=(
            "Counterarguments only: fill this in BEFORE deciding can_defeat. Compare your planned "
            "counterargument with your own earlier arguments. Omit for attacks."
        ),
    )
    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    reason: str = Field(
        default="",
        description="Brief reason for the decision: why NO (what blocks you), or what the argument rests on if YES.",
    )
    Argument: ArgumentSchema | None = Field(
        default=None, description="Defeating argument body, omitted when NO."
    )
    Attack: AttackMetadata | None = Field(
        default=None,
        description="Attack made by this argument against a specified item in the target argument, omitted when NO.",
    )


class IntegrationBody(BaseModel):
    consequent: str = Field(
        description=(
            "The shared higher-order decision principle or explicit outcome mapping "
            "that preserves the conclusions supported by both sides' warrants."
        )
    )
    rule: str = Field(
        description=(
            "A single reusable decision rule, generalized from both sides' warrants, "
            "preserving each side's condition-to-conclusion mapping. Use OR only for "
            "alternative conditions that support the same outcome; when conditions support "
            "different outcomes, explicitly map each condition to its corresponding outcome. "
            "When opposing conditions may coexist, compare them using the same evidential "
            "threshold and do not give either side an automatic veto. Do not invent a "
            "precautionary default, burden shift, or tie-breaker absent from the warrants."
        )
    )


class IntegrationSchema(BaseModel):
    Argument: IntegrationBody = Field(description="Integration result.")


class MainArgumentFree(BaseModel):
    can_generate: Literal["YES", "NO"] = Field(
        description="determining whether you can make an argument regarding the given issue."
    )
    reason: str = Field(description="Brief reason for the availability decision.")
    Argument: str | None = Field(
        default=None,
        description="Free natural-language argument. Required only when can_generate is YES.",
    )


class AttackFree(BaseModel):
    Novelty: NoveltyCheck | None = Field(
        default=None,
        description=(
            "Fill this in BEFORE deciding can_defeat. Compare your planned argument with your own "
            "earlier arguments in this debate."
        ),
    )
    can_defeat: Literal["YES", "NO"] = Field(
        description="YES only if a valid rebut or undercut is available."
    )
    reason: str = Field(
        default="",
        description="Brief reason for the decision: why NO (what blocks you), or what the argument rests on if YES.",
    )
    Argument: str | None = Field(
        default=None,
        description="Free natural-language defeating argument, omitted when NO.",
    )
    Attack: AttackMetadataFree | None = Field(
        default=None,
        description="Attack made by this argument against a specified part of the target argument, omitted when NO.",
    )


class IntegrationBodyFree(BaseModel):
    rule: str = Field(
        description=(
            "A single integrated decision rule, expressed in natural language, generalized from "
            "both sides' warrants and preserving each side's condition-to-conclusion mapping, "
            "applicable to future arguments. Use OR only for conditions supporting the same "
            "outcome. When opposing conditions may coexist, compare them symmetrically rather "
            "than giving either side an automatic veto."
        )
    )


class IntegrationFree(BaseModel):
    Argument: IntegrationBodyFree = Field(description="Integration result.")


@dataclass
class Schema:
    main_argument: type[BaseModel]
    attack: type[BaseModel]
    integration: type[BaseModel]


DEFAULT_SCHEMA = Schema(MainArgumentSchema, AttackSchema, IntegrationSchema)
FREE_SCHEMA = Schema(MainArgumentFree, AttackFree, IntegrationFree)


class RebutJudgement(BaseModel):
    attack_conclusion_quote: str = Field(
        description="The conclusion of the attack that comes closest to opposing the target statement, quoted word for word."
    )
    rebuts: bool = Field(
        description="True only if that conclusion directly opposes the target statement: it denies what the target statement asserts."
    )
    reason: str = Field(description="One sentence explaining the judgement.")


class UndercutJudgement(BaseModel):
    undercut_assumption_number: int | None = Field(
        default=None,
        description="The number of ONE listed assumption that the attack undercuts, or null if it undercuts none.",
    )
    attack_conclusion_quote: str = Field(
        default="",
        description="The conclusion of the attack that contradicts that assumption, quoted word for word (empty if none).",
    )
    reason: str = Field(description="One sentence explaining the judgement.")


class PresumptionList(BaseModel):
    presumptions: list[str] = Field(
        default_factory=list,
        description="Presumptions the argument states explicitly, each quoted verbatim from the argument; empty if none.",
    )


class Antecedent(BaseModel):
    strong: list[str] = Field(default_factory=list)
    from_rules: list[int] = Field(default_factory=list)
    weak_negation: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    antecedent: Antecedent
    consequent: str


class ArgumentBody(BaseModel):
    rules: list[Rule] = Field(default_factory=list)


def parse_serialized_payload(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        if "```json" in text:
            start = text.find("```json") + len("```json")
            text = text[start : text.find("```", start)].strip()
        elif "```" in text:
            start = text.find("```") + len("```")
            text = text[start : text.find("```", start)].strip()
        else:
            text = text[text.find("{") : text.rfind("}") + 1].strip()
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except (AttributeError, TypeError, json.JSONDecodeError):
        return {}


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


@dataclass
class Speech:
    type: Literal["main", "defeat", "counter"]
    agent: str
    argument: str
    round: int
    # この発言が属する攻防の proponent。ターン予算の按分に使う
    proponent: str | None = None
    id: str = field(default_factory=lambda: f"arg-{uuid4().hex[:10]}")
    attack: AttackType | None = None
    target_id: str | None = None
    target_field: Literal["Conc", "Ass"] | None = None
    target_statement: str | None = None
    status: str | None = None
    closed_by_budget: bool | None = None
    novelty_note: str | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return parse_serialized_payload(self.argument)

    @property
    def body(self) -> dict[str, Any]:
        body = self.payload.get("Argument", {})
        return body if isinstance(body, dict) else {}

    @property
    def conclusions(self) -> list[str]:
        return _text_items(self.body.get("Conc"))

    @property
    def assumptions(self) -> list[str]:
        items = _text_items(self.body.get("Ass"))
        if items:
            return items
        rules = self.body.get("rules", [])
        if not isinstance(rules, list):
            return []
        assumptions: list[str] = []
        for rule in rules:
            if isinstance(rule, dict) and isinstance(rule.get("antecedent"), dict):
                assumptions.extend(_text_items(rule["antecedent"].get("weak_negation")))
        return assumptions

    def message_content(self) -> str:
        body = self.body
        if not body:
            return self.argument
        envelope: dict[str, Any] = {
            "id": self.id,
            "round": self.round,
            "phase": self.type,
            "agent": self.agent,
        }
        if self.status is not None:
            envelope["status"] = self.status
        if self.attack is not None:
            envelope["attack"] = self.attack
            envelope["target_id"] = self.target_id
            envelope["target_statement"] = self.target_statement
        envelope["Argument"] = body
        return json.dumps(envelope, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "round": self.round,
            "type": self.type,
            "argument": self.argument,
            "support": [],
            "agent": self.agent,
            "proponent": self.proponent,
            "target_id": self.target_id,
            "attack": self.attack,
            "target_field": self.target_field,
            "target_statement": self.target_statement,
            "status": self.status,
            "closed_by_budget": self.closed_by_budget,
        }


@dataclass
class Frame:
    argument: Speech
    entered_by_mutual_defeat: bool = False
    outcome: Literal["open", "won_by_p", "lost_by_p", "undetermined", "contested"] = (
        "open"
    )
    current_attacker: Speech | None = None
    contested_by: Speech | None = None
    closed_by_budget: bool = False


@dataclass
class Defeat:
    attacker_id: str
    target_id: str
    attack: str
    target_field: str | None
    target_statement: str | None
    valid: bool
    reason: str | None


@dataclass(frozen=True)
class AttackMatch:
    method: AttackType
    field: Literal["Conc", "Ass"]
    statement: str | None


@dataclass
class Verdict:
    holds: bool
    reason: str


@dataclass
class Evaluation:
    defeats: bool
    attack: str | None = None
    target_undercuts: str | None = None


_META_CONCLUSION_PATTERNS = (
    "fails to defeat",
    "does not defeat",
    "fail to defeat",
    "fails to undercut",
    "does not undercut",
    "fails to rebut",
    "does not rebut",
    "does not follow from its premises",
    "does not follow from the premises",
    "the target attack",
    "the target argument",
    "is not defeated",
    "is defeated",
)

MAX_REGENERATIONS = 2


def _meta_conclusion_violation(index: int, consequent: str) -> str | None:
    lowered = consequent.lower()
    for pattern in _META_CONCLUSION_PATTERNS:
        if pattern in lowered:
            return (
                f'rule {index + 1}\'s consequent ("{consequent}") states a verdict about '
                f'the dialectical game ("{pattern}") instead of a substantive claim about '
                "the issue"
            )
    return None


def resolve_draft(draft: ArgumentSchema) -> tuple[ArgumentBody, list[str]]:
    rules = draft.rules or []
    consequents = [(rule.consequent or "").strip() for rule in rules]
    violations: list[str] = []
    resolved: list[Rule] = []
    placeholders = {
        "n/a",
        "none",
        "no additional premise needed",
        "no additional rule needed",
    }
    used: set[int] = set()

    if not rules:
        violations.append("the Argument has no rule")

    for index, (rule, consequent) in enumerate(zip(rules, consequents, strict=True)):
        position = index + 1
        if not consequent:
            violations.append(f"rule {position} has an empty consequent")
        else:
            meta = _meta_conclusion_violation(index, consequent)
            if meta is not None:
                violations.append(meta)
        strong: list[str] = []
        valid_numbers: list[int] = []
        for number in rule.antecedent.from_rules or []:
            if (
                isinstance(number, bool)
                or not isinstance(number, int)
                or not 1 <= number < position
            ):
                violations.append(
                    f"rule {position} cites rule {number} as a premise; a premise must be the "
                    "consequent of an EARLIER rule"
                    + (" (the first rule has no premise)" if position == 1 else "")
                )
                continue
            if number not in valid_numbers:
                valid_numbers.append(number)
                strong.append(consequents[number - 1])
                used.add(number)
        weak = [
            item.strip() for item in rule.antecedent.weak_negation or [] if item.strip()
        ]
        if any(item.lower().rstrip(".") in placeholders for item in weak):
            violations.append(f"rule {position} has a placeholder in weak_negation")
        resolved.append(
            Rule(
                antecedent=Antecedent(
                    strong=strong, from_rules=valid_numbers, weak_negation=weak
                ),
                consequent=consequent,
            )
        )

    seen: set[str] = set()
    for consequent in consequents:
        if consequent and consequent in seen:
            violations.append(f'two rules share the same consequent: "{consequent}"')
        seen.add(consequent)

    for index, consequent in enumerate(consequents[:-1]):
        if consequent and index + 1 not in used:
            violations.append(
                f"non-final consequent of rule {index + 1} is never used by a later rule "
                f'(cite it in from_rules): "{consequent}"'
            )
    return ArgumentBody(rules=resolved), violations


def argument_body_json(argument: ArgumentBody) -> str:
    body = argument.model_dump(exclude_none=True)
    rules = body.get("rules", [])
    conclusions: list[str] = []
    assumptions: list[str] = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            consequent = rule.get("consequent")
            if isinstance(consequent, str) and consequent.strip():
                conclusions.append(consequent.strip())
            antecedent = rule.get("antecedent", {})
            if isinstance(antecedent, dict):
                for item in antecedent.get("weak_negation", []) or []:
                    if isinstance(item, str) and item.strip():
                        assumptions.append(item.strip())
    body["Conc"] = conclusions
    body["Ass"] = assumptions
    return json.dumps({"Argument": body}, ensure_ascii=False, indent=2)


_MIN_QUOTE_LENGTH = 3
_QUOTE_MARKS = "\"'“”‘’「」『』"
_ELLIPSIS = re.compile(r"(?:\.\.\.|…)+")


def _field_for(method: str) -> Literal["Conc", "Ass"]:
    return "Conc" if method == "rebut" else "Ass"


def _candidates(target: Speech, method: str) -> list[str]:
    return target.conclusions if method == "rebut" else target.assumptions


def _resolve_target(target: Speech, method: str, number: int) -> str | None:
    options = _candidates(target, method)
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return options[number - 1] if 1 <= number <= len(options) else None


def _normalize(text: str) -> str:
    return text.strip().rstrip(".").strip().lower()


def _normalize_quote(text: str) -> str:
    collapsed = " ".join(text.split()).strip(_QUOTE_MARKS + " ")
    return collapsed.rstrip(".。 ").casefold()


def _quote_in_text(quote: str, text: str) -> bool:
    if _ELLIPSIS.search(quote):
        return False
    wanted = _normalize_quote(quote)
    body = " ".join(text.split()).casefold()
    return len(wanted) >= _MIN_QUOTE_LENGTH and wanted in body


def _numbered(items: list[str]) -> str:
    return "\n".join(f"[{index}] {item}" for index, item in enumerate(items, start=1))


def _options_block(target: Speech, free: bool) -> str:
    if free:
        return ""
    conclusions = target.conclusions
    assumptions = target.assumptions
    return (
        "<target_conclusions>\n"
        f"{_numbered(conclusions) if conclusions else '(none)'}\n"
        "</target_conclusions>\n"
        "<target_assumptions>\n"
        f"{_numbered(assumptions) if assumptions else '(none)'}\n"
        "</target_assumptions>"
    )


def _strip_period(text: str) -> str:
    stripped = text.strip()
    return stripped[:-1] if stripped.endswith(".") else stripped


def _lowercase_first(text: str) -> str:
    if not text:
        return text
    first_word = text.split(" ", 1)[0].rstrip(".,;:")
    if first_word == "I" or (len(first_word) > 1 and first_word.isupper()):
        return text
    return text[0].lower() + text[1:]


def _strip_leading_connective(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    for connective in (
        "therefore,",
        "therefore ",
        "thus,",
        "thus ",
        "hence,",
        "hence ",
    ):
        if lowered.startswith(connective):
            return stripped[len(connective) :].strip()
    return stripped


def _schema_body(argument: Any) -> dict[str, Any] | None:
    if isinstance(argument, str):
        try:
            argument = json.loads(argument)
        except json.JSONDecodeError:
            return None
    if not isinstance(argument, dict):
        return None
    body = argument.get("Argument", argument)
    if isinstance(body, dict) and isinstance(body.get("rules"), list):
        return body
    return None


def _schema_text(body: dict[str, Any]) -> str:
    rules = [rule for rule in body.get("rules", []) if isinstance(rule, dict)]

    def _norm(text: Any) -> str:
        return _strip_period(str(text)).strip().lower()

    consequent_norms = {
        _norm(rule["consequent"]) for rule in rules if rule.get("consequent")
    }
    parts: list[str] = []
    assumptions: list[str] = []
    for index, rule in enumerate(rules):
        antecedent = rule.get("antecedent") or {}
        strongs = [
            _strip_leading_connective(_strip_period(premise))
            for premise in antecedent.get("strong") or []
            if premise and premise.strip() and _norm(premise) not in consequent_norms
        ]
        assumptions += [
            _strip_period(item)
            for item in antecedent.get("weak_negation") or []
            if item and item.strip()
        ]
        consequent = _strip_leading_connective(
            _strip_period(str(rule.get("consequent", "")))
        )
        grounds = ". ".join(strongs)
        is_last = index == len(rules) - 1
        connector = "Therefore," if is_last else "So"
        connected = consequent if is_last else _lowercase_first(consequent)
        if grounds and connected:
            parts.append(f"{grounds}. {connector} {connected}.")
        elif connected:
            parts.append(f"{connector} {connected}.")
        elif grounds:
            parts.append(f"{grounds}.")
    if assumptions:
        parts.append(f"(This relies on the assumption that {'; '.join(assumptions)}.)")
    return " ".join(parts) if parts else "(no argument)"


def render_argument_text(argument: Any) -> str:
    body = _schema_body(argument)
    if body is not None:
        return _schema_text(body)
    if isinstance(argument, str) and argument.strip():
        return argument.strip()
    if argument:
        return json.dumps(argument, ensure_ascii=False)
    return "(no argument)"


def _text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    return "\n".join(str(part) for part in content).strip()


def _root_status(root: Frame) -> tuple[str, bool]:
    if root.outcome == "won_by_p":
        status = "justified"
    elif root.outcome == "lost_by_p" and not root.closed_by_budget:
        status = "overruled"
    else:
        status = "defensible"
    return status, root.closed_by_budget or root.outcome == "undetermined"


class DialecticalArgument:
    def __init__(
        self,
        ag1: Agent,
        ag2: Agent,
        topic: str,
        schema: Schema | None,
        max_turn: int | None,
        judge: Agent,
        max_round: int = 5,
    ):
        self.ag1 = ag1
        self.ag2 = ag2
        self.topic = topic
        # schema=None は no_schema（Argument 本体を自由記述にする）
        self.free = schema is None
        self.schema = schema or FREE_SCHEMA
        # main / defeat / counter の発言数の上限。proponent ごとに折半する（端数は AG1）
        self.max_turn = max_turn
        self.judge = judge
        self.max_round = max_round

        self.history: list[Speech] = []
        self.defeats: list[Defeat] = []
        self.attempt_log: list[dict[str, Any]] = []
        self.integrated_rules: list[str] = []
        self.learned_findings: list[str] = []
        self.revision_context: dict[str, str] = {}
        self.unavailable_reasons: dict[str, str] = {}
        self.thread_status: dict[str, str | None] = {"AG1": None, "AG2": None}
        self.round = 1
        self.proponent = ag1
        self.opponent = ag2
        self.current_main: Speech | None = None
        self.error: str | None = None
        self._decline_reason: str | None = None
        self._presumptions: dict[str, list[str]] = {}

    def _label(self, agent: Agent) -> str:
        return "AG1" if agent is self.ag1 else "AG2"

    def _stance(self, agent: Agent) -> str:
        return agent.system_prompt

    def add_history(self, speech: Speech) -> None:
        self.history.append(speech)

    def _log_attempt(
        self,
        kind: str,
        agent: str,
        target_id: str | None,
        reason: str | None,
        phase: str,
    ) -> None:
        self.attempt_log.append(
            {
                "kind": kind,
                "phase": phase,
                "agent": agent,
                "target_id": target_id,
                "reason": reason or "(no reason given)",
            }
        )

    def _budget_exceeded(self) -> bool:
        if self.max_turn is None:
            return False
        half, remainder = divmod(self.max_turn, 2)
        label = self._label(self.proponent)
        limit = half + remainder if label == "AG1" else half
        # 数えるのは発言者ではなく、誰の main を巡る攻防か
        used = sum(1 for speech in self.history if speech.proponent == label)
        return used >= limit

    def _agent_system(self, speaker: Agent) -> str:
        label = self._label(speaker)
        blocks = [
            "<identity>\n"
            f'You are {label} in this debate. In the message history, turns whose agent/name is "{label}" '
            "are your own past turns; the other agent is your opponent.\n"
            "</identity>",
            self._stance(speaker),
            """<grounding>
- Your values, priorities, and the position you argue for come from your stance; never contradict your stance or adopt priorities it does not contain.
- Where your stance, the target argument, the dialogue history, or the integrated rules already provide the facts or rules that settle a point, argue from those; do not override or replace them with outside knowledge.
- Where they are silent, you may draw on general knowledge — facts, examples, analogies, mechanisms — to support your position or to challenge the other side's reasoning.
</grounding>""",
            """<protocol_flow>
You and the other agent (AG1 and AG2) debate one Issue, each from a fixed stance, over one or more rounds.
A round proceeds as a dialectical thread:
- A proponent states a main argument (phase "main").
- The opponent attacks it with a defeating argument (phase "defeat", via rebut or undercut).
- The proponent defends with a counterargument (phase "counter"). A rebut can be blocked by an undercut.
- The thread closes with one outcome, recorded on the main argument's "status":
    - justified  – the main survives every attack → the debate ends with this answer.
    - overruled  – the main is defeated and cannot be defended.
    - defensible – the two sides defeat each other; the conflict stays unresolved.
When neither side's main is justified, the shared warrants are generalized and merged into reusable
"integrated rules" that BOTH sides accept. In the NEXT round the proponent must build a NEW main argument
grounded in those integrated rules, different from every earlier main and not vulnerable to the same attacks.
The debate ends when a main is justified, or when the round limit is reached (then the final answer is
produced from the debate so far and the integrated rules).
</protocol_flow>""",
            """<argumentation_rules>
- Make clear what you are relying on to support your position.
- Your final position must follow directly from what you have stated, with no implicit logical leap.
- Your final position must clearly express your opinion on the Issue in a specific way.
- Include the specific facts, distinctions, and reasoning your position actually depends on; do not pad with repetition or restate the same point in different words.
</argumentation_rules>""",
        ]
        if not self.free:
            blocks += [
                """<attack_types>
- rebut: a conclusion of the attacker explicitly negates a conclusion (Conc) of the target.
- undercut: a conclusion of the attacker explicitly negates an assumption (Ass) of the target.
</attack_types>""",
                """<schema_overlay>
Represent Argument as a structured object consisting of rules, Conc, and Ass.
- rules is a finite sequence of rules r_1, ..., r_n.
- Each rule has an antecedent and a consequent.
- Antecedents may contain strong premises and weak_negation assumptions (strong and weak literals in Prakken & Sartor's terms).
- A strong premise is the consequent of an EARLIER rule in this Argument, and nothing else. A rule names its strong premises by the numbers of the earlier rules it relies on (from_rules); each premise is then that rule's consequent. A rule that cites no earlier rule has no strong premise. Your stance, the dialogue history, and general knowledge cannot be cited as premises: a claim you take from them must first be stated as the consequent of a rule of its own. Strong premises are not assumptions: never list them in Ass.
- A weak_negation entry is an exception clause ("unless X", "as long as there is no evidence that X"): the rule applies by default and stops applying only if X is shown to hold; it needs no support of its own. Write it as the presumption "X is not the case" (e.g. "no evidence that Y fails here", "Z does not occur in this case"). It must be a specific claim that could in principle be proven false by evidence that X actually holds — an attacker undercuts the Argument by proving X. Use weak_negation wherever your reasoning genuinely rests on the absence of something that would block it (an exception you presume absent, a risk you presume not to occur, an obstacle you presume is not present): when a step of your reasoning holds only as long as nothing blocks it, state that as "X is not the case" rather than silently treating it as given. A weak_negation entry is always a negation; never write a positive assumption ("X is the case") there — a positive claim is not an exception clause: state it as the consequent of a rule. Do not put scope stipulations, definitions, or framing choices ("we are evaluating only Y") in weak_negation — those are not defeasible assumptions and cannot be coherently undercut; state them as the consequent of a rule or fold them into the reasoning directly instead.
- The FIRST rule has no strong premise (from_rules is empty): its consequent is one claim that you hold, taken from your stance (or, where your stance is silent, from the dialogue or general knowledge). It may carry weak_negation entries. A later rule may also have no strong premise, but only to state another claim that you hold in the same way; whenever a later rule cites premises, it cites only earlier rules.
- Conc contains the conclusions derived by the rules.
- Ass contains the weak_negation assumptions used by the rules.
- Every consequent except the final one must be cited by a later rule: the final rule is the warrant of the Argument, and the rules before it lead to it.
- Use as many rules as your reasoning genuinely needs and no more: add a rule whenever it introduces a materially new fact, point, or inferential step that strengthens your case; do not add a rule that merely restates an earlier one.
- Each rule's consequent must state a materially new claim — a new fact, a new point, or a new inferential step — not a paraphrase or near-synonym of an earlier rule's consequent (e.g. "the attack is insufficient" -> "the attack fails to show invalidity" -> "the attack does not defeat the conclusion" is the same claim restated three times, not three rules). If a later rule's consequent would just restate an earlier one in different words, merge them into a single rule instead.
- When attacking (defeat/counter), the conclusions of your Argument (the consequents of its rules) must include the contradiction of the target item you choose in Attack: for a rebut, the contradictory of one of the target's conclusions; for an undercut, the contradictory of one of the target's assumptions. Build it from the claims you hold, through your chain of rules.
- Do not satisfy this by appending a short final rule that merely quotes or paraphrases the target ("The target says X, but Y") while your earlier rules argue a generic, self-contained point that never touches the target. The contradiction of the chosen target item must be what your chain of rules actually establishes.
</schema_overlay>""",
            ]
        blocks.append(
            """<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": "<free-text argument>"}
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to stay consistent with the current round and integrated rules.
</history_format>"""
            if self.free
            else """<history_format>
Prior turns of this debate are provided as preceding messages. Each message's content is a JSON object:
  {"id", "round", "phase", "agent", ["status"], ["attack","target_id","target_statement"], "Argument": {"rules","Conc","Ass"}}
- "phase" is one of main / defeat / counter. "status" (justified/overruled/defensible) appears only on a
  main turn, once its thread has closed; a defeat/counter turn carries no outcome field of its own.
- "attack"/"target_id"/"target_statement" (on defeat/counter) show exactly what was attacked.
- In each rule, "strong" lists the premises, which are the consequents of the earlier rules named in "from_rules".
- A message whose "agent"/name equals YOUR identity is your own past turn; the other agent's are your opponent's.
Use this history to stay consistent with the current round and integrated rules.
</history_format>"""
        )
        return "\n\n".join(block.strip() for block in blocks if block.strip())

    def _history_block(self, numbered: bool = False) -> str:
        entries = []
        for n, speech in enumerate(self.history, start=1):
            prefix = f"[{n}] " if numbered else ""
            entries.append(f"{prefix}{speech.agent}:\n{speech.message_content()}")
        body = "\n\n".join(entries) if entries else "(no turns yet)"
        return f"<history>\n{body}\n</history>"

    def _debater_prompt(
        self, speaker: Agent, human: str, numbered: bool = False
    ) -> str:
        return f"{self._agent_system(speaker)}\n\n{self._history_block(numbered)}\n\n{human}"

    def _defeat_relations_block(self) -> str:
        number = {speech.id: n for n, speech in enumerate(self.history, start=1)}
        start = number.get(self.current_main.id, 1) if self.current_main else 1
        in_thread = {sid for sid, n in number.items() if n >= start}
        won: set[tuple[str, str]] = set()
        failed: set[tuple[str, str]] = set()
        for rel in self.defeats:
            if rel.attacker_id not in in_thread or rel.target_id not in in_thread:
                continue
            (won if rel.valid else failed).add((rel.attacker_id, rel.target_id))

        def order(pair: tuple[str, str]) -> tuple[int, int]:
            return (number[pair[0]], number[pair[1]])

        lines = []
        for attacker, target in sorted(won, key=order):
            mutual = (
                f" (mutual: [{number[target]}] also defeats [{number[attacker]}])"
                if (target, attacker) in won
                else ""
            )
            lines.append(f"[{number[attacker]}] defeats [{number[target]}]{mutual}")
        for attacker, target in sorted(failed - won, key=order):
            lines.append(f"[{number[attacker]}] does not defeat [{number[target]}]")
        body = "\n".join(lines) if lines else "(none yet)"
        return f"<defeat_relations>\n{body}\n</defeat_relations>"

    def _main_instruction(self, label: str) -> str:
        rules = self.integrated_rules
        lines = [
            "<task>",
            f"Round {self.round}. Construct your main argument for the Issue.",
            "</task>",
            "",
            "<issue>",
            self.topic,
            "</issue>",
            "",
            "<issue_answer_scope>",
            "Your main argument must answer the Issue directly.",
            "Every rule consequent must either be an intermediate fact needed to support your direct answer or the direct answer itself.",
            "</issue_answer_scope>",
            "",
            "<stance_coverage>",
            "Before constructing the argument, silently identify every distinct substantive reason, "
            "requirement, condition, affected group, and tradeoff stated in your stance.",
            "Use as many of them as you can genuinely chain into one coherent line of reasoning "
            "toward your direct answer — do not artificially force unrelated reasons into a single "
            "chain just to mention them; only include a reason where it does real work in the chain.",
            "Keep any material number, threshold, exception, or named affected group from the stance "
            "intact when it is part of a reason you use.",
            "</stance_coverage>",
            "",
            "<no_repetition>",
            "Before answering, compare your planned support against everything your side has already "
            "said earlier in this debate, in any role (an earlier main argument, attack, or defense) — "
            "not only earlier main arguments.",
            "If the only support you can construct substantially restates content your side already "
            "presented earlier — the same facts or reasoning, just reworded or repackaged into a new "
            "argument — set can_generate=NO instead of resubmitting it. This applies even if you "
            "yourself introduced that content in a different role (e.g. as an earlier attack).",
            "</no_repetition>",
        ]
        revision_context = self.revision_context.get(label)
        if revision_context or rules:
            lines += ["", "<revision_context>"]
            if revision_context:
                lines += [revision_context, ""]
            else:
                lines += ["This is a revision round.", ""]
            lines.append(
                "Do not repeat the same main argument unless the defeating reason is resolved."
            )
            if rules:
                lines.append(
                    "Ground your NEW main argument in the integrated rules below."
                )
            lines.append("</revision_context>")
            if rules:
                lines += [
                    "",
                    "<integrated_rules>",
                    *[f"- {rule}" for rule in rules],
                    "</integrated_rules>",
                ]
        lines += [
            "",
            "<response_contract>",
            "If you can construct a main argument with a genuinely new point (see <no_repetition>), "
            "set can_generate=YES and include Argument.",
            "Otherwise, set can_generate=NO and omit Argument.",
            "</response_contract>",
        ]
        return "\n".join(lines)

    def _target_block(self, target: Speech) -> str:
        lines = [
            "<target>",
            f"id: {target.id}",
            f"agent: {target.agent}",
            "argument:",
            target.argument,
            "</target>",
        ]
        options = _options_block(target, self.free)
        if options:
            lines.append(options)
        return "\n".join(lines)

    def _target_rules(self) -> list[str]:
        if self.free:
            return [
                "- rebut: one claim you make must directly oppose a claim of the target. In Attack, give "
                "the sentence or phrase of <target> that states the claim you oppose.",
                "- undercut: one claim you make must establish that a presumption the target relies on by "
                "default (an exception it takes to be absent) does not hold. In Attack, give the sentence "
                "or phrase of <target> that states that presumption. Merely asserting the opposite of the "
                "target's conclusion, or arguing that the target's framing/scope is inappropriate, does "
                "not qualify.",
                "- Copy the target's words from <target> word for word: do not paraphrase, shorten with "
                "an ellipsis, or combine sentences.",
            ]
        return [
            "- rebut: one conclusion of your argument (any rule's consequent) must contradict one "
            "conclusion of the target. In Attack, give the number of that conclusion in "
            "<target_conclusions>.",
            "- undercut: one conclusion of your argument must establish that an assumption of the target "
            "(a weak_negation entry, of the form 'X is not the case') does not hold, i.e. prove that X "
            "actually holds. In Attack, give the number of that assumption in <target_assumptions>. "
            "Merely asserting the opposite of the target's conclusion, or arguing that the target's "
            "framing/scope is inappropriate, does not qualify. If <target_assumptions> is empty, you "
            "cannot undercut.",
            "- Choose the target only by its number; never copy its text.",
        ]

    def _attack_instruction(self, purpose: str, target: Speech) -> str:
        counter = purpose == "counter"
        lines = ["<task>"]
        if counter:
            lines.append(
                f"Round {self.round}. The opponent's attack below challenges your position on the issue. "
                "State what you hold to be true about the issue that directly answers this specific "
                "challenge — a substantive claim about the issue, not a verdict about whether the attack "
                "succeeds."
            )
        else:
            lines.append(
                f"Round {self.round}. Attack the target argument below (rebut or undercut). Build your "
                "attack from your own stance: state what you hold to be true about the issue that negates "
                "the target argument's specific claim — a substantive claim about the issue, not a "
                "verdict about whether the target argument is defeated."
            )
        lines += [
            "Each earlier turn is numbered [n]. <defeat_relations> lists which turns of the current thread "
            "have defeated which (and which attempts did not). Take them into account before you write: "
            "see which of your earlier arguments have already defeated, or been defeated by, which; do not "
            "rebuild a move that was already defeated; base your move on what the relations show.",
            "</task>",
            "",
            "<issue>",
            self.topic,
            "</issue>",
            "",
        ]
        if counter and self.current_main is not None:
            lines += [
                "<your_prior_main_argument>",
                f"id: {self.current_main.id}",
                self.current_main.argument,
                "</your_prior_main_argument>",
                "",
            ]
        lines += [
            self._target_block(target),
            "",
            "<content_requirement>",
            "Your Argument's rules must state a substantive position about the issue itself "
            "(facts, causal claims, values, tradeoffs) — never a verdict about the dialectical "
            'game (e.g. "the target attack fails", "X does not defeat Y", "X\'s conclusion '
            'does not follow from its premises"). Whether your argument defeats the target is '
            "determined separately from the Attack field and the defeat-checking logic, not from "
            "how you phrase your conclusion. State your own substantive position, engaging the "
            "target's specific content (see below) — never phrase the conclusion itself as a "
            "verdict about whether that content holds up.",
            "</content_requirement>",
            "",
            "<attack_conditions>",
        ]
        if counter:
            lines.append("- Your counterargument must defeat the target attack.")
        lines += ["- You may use rebut or undercut.", *self._target_rules()]
        if not counter:
            lines.append(
                "- Supporting a different option does not by itself count as negating the target."
            )
        lines.append("</attack_conditions>")
        if counter:
            lines += [
                "",
                "<non_repetition>",
                "You are the proponent: Prakken & Sartor's dialogue game forbids you (but not the "
                "opponent) from making two moves with substantially the same content in this debate — "
                "repeating never helps you, since if the opponent had a move against it the first time, "
                "it has one the second time too.",
                "Before answering, explicitly check your planned counterargument against your original "
                "main argument AND every one of your own earlier counterarguments in this thread — "
                "including ones the opponent has already defeated, and including any of your immediately "
                "preceding retries against this exact same target — even if only the wording, the cited "
                "specifics, or the framing differs. Same underlying conclusion via the same underlying "
                "reasoning counts as a repeat.",
                "A ground is one of the distinct reasons your stance gives for your position (for "
                "example a benefit, a fact about sourcing or evidence, a value). Elaborating a ground "
                "you have already used — adding detail, an example, a more specific mechanism, or "
                "aiming it at a different part of the attack — does not make a new reason.",
                "Record this check in Novelty (filled in before you decide can_defeat): name the "
                "closest of your earlier arguments by its id, and state the new reason your "
                "counterargument adds. If it adds no new reason — only different wording, examples or "
                "framing — set adds_new_reason=NO, and do not make the counterargument.",
                "If the only available counterargument would repeat any of those, set can_defeat=NO.",
                "When more than one distinct reason from your stance could answer this challenge, prefer "
                "the one you have not yet used in this debate — this is how the debate as a whole ends up "
                "covering more of your stance, not any single turn.",
                "</non_repetition>",
            ]
        noun = "counterargument" if counter else "attack"
        lines += [
            "",
            "<response_contract>",
            f"If a valid {noun} exists, set can_defeat=YES and include Argument and Attack.",
            "Otherwise, set can_defeat=NO and omit Argument and Attack.",
            "</response_contract>",
        ]
        return "\n".join(lines)

    def _attack_prompt(self, attacker: Agent, target: Speech, purpose: str) -> str:
        number = {speech.id: n for n, speech in enumerate(self.history, start=1)}
        target_label = (
            f"\n<target_number>[{number[target.id]}]</target_number>"
            if target.id in number
            else ""
        )
        human = (
            f"{self._defeat_relations_block()}{target_label}\n\n"
            f"{self._attack_instruction(purpose, target)}"
        )
        return self._debater_prompt(attacker, human, numbered=True)

    async def _generate_checked(
        self,
        agent: Agent,
        prompt: str,
        schema: type[BaseModel],
        check: Callable[[Any], list[str]],
    ) -> tuple[Any, list[str]]:
        output = await agent.structured(prompt, schema)
        violations = check(output)
        attempts = 0
        while violations and attempts < MAX_REGENERATIONS:
            attempts += 1
            listed = "\n".join(f"- {item}" for item in violations)
            repair = (
                "<rejected>\nYour previous answer was rejected for the following problems:\n"
                f"{listed}\nAnswer again with the same task, fixing exactly these problems.\n</rejected>"
            )
            output = await agent.structured(f"{prompt}\n\n{repair}", schema)
            violations = check(output)
        return output, violations

    def _draft_violations(self, output: Any) -> list[str]:
        draft = getattr(output, "Argument", None)
        if not self.free and isinstance(draft, ArgumentSchema):
            return resolve_draft(draft)[1]
        return []

    def _serialize_argument(self, argument: ArgumentSchema | str) -> str:
        if isinstance(argument, ArgumentSchema):
            return argument_body_json(resolve_draft(argument)[0])
        return str(argument).strip()

    def _declared_statement(self, target: Speech, attack: Any) -> str | None:
        if not self.free:
            return _resolve_target(target, attack.method, attack.target.number)
        statement = str(attack.target.statement).strip()
        return statement if _quote_in_text(statement, target.argument) else None

    async def main_argument(self, speaker: Agent) -> Speech | None:
        label = self._label(speaker)
        if self._budget_exceeded():
            self.unavailable_reasons[label] = "Dialogue turn budget (max_turn) reached."
            return None
        prompt = self._debater_prompt(speaker, self._main_instruction(label))
        output, violations = await self._generate_checked(
            speaker, prompt, self.schema.main_argument, self._draft_violations
        )
        if output.can_generate != "YES":
            self.unavailable_reasons[label] = output.reason or "(no reason given)"
            return None
        if output.Argument is None:
            self.error = (
                "Main argument availability was YES but no Argument was generated."
            )
            return None
        if violations:
            self.unavailable_reasons[label] = (
                "could not produce a well-formed Argument: " + "; ".join(violations)
            )
            return None
        main = Speech(
            type="main",
            agent=label,
            argument=self._serialize_argument(output.Argument),
            round=self.round,
            proponent=label,
        )
        self.add_history(main)
        return main

    async def attack(
        self, attacker: Agent, target: Speech, purpose: str
    ) -> Speech | None:
        prompt = self._attack_prompt(attacker, target, purpose)

        def check(output: Any) -> list[str]:
            if (
                output.can_defeat != "YES"
                or output.Argument is None
                or output.Attack is None
            ):
                return []
            violations = self._draft_violations(output)
            if self._declared_statement(target, output.Attack) is None:
                if self.free:
                    violations.append(
                        "Attack.target.statement is not words copied word for word from the target "
                        "argument's text"
                    )
                else:
                    violations.append(
                        f"Attack.target.number {output.Attack.target.number} is not a number in the "
                        f"list shown for a {output.Attack.method}"
                    )
            return violations

        output, violations = await self._generate_checked(
            attacker, prompt, self.schema.attack, check
        )
        if (
            output.can_defeat != "YES"
            or output.Argument is None
            or output.Attack is None
        ):
            self._decline_reason = output.reason or "(no reason given)"
            return None
        if violations:
            self._decline_reason = (
                "could not produce a well-formed attack: " + "; ".join(violations)
            )
            return None
        novelty = output.Novelty if purpose == "counter" else None
        if novelty is not None and (
            novelty.adds_new_reason != "YES" or not novelty.new_reason.strip()
        ):
            earlier = (
                f" (closest earlier argument: {novelty.closest_earlier_id})"
                if novelty.closest_earlier_id
                else ""
            )
            self._decline_reason = f"Repeats a reason I already used{earlier}; there is no new reason to add."
            return None

        self._decline_reason = None
        method = output.Attack.method
        speech = Speech(
            type="counter" if purpose == "counter" else "defeat",
            agent=self._label(attacker),
            argument=self._serialize_argument(output.Argument),
            round=self.round,
            proponent=self._label(self.proponent),
            attack=method,
            target_id=target.id,
            target_field=_field_for(method),
            target_statement=self._declared_statement(target, output.Attack),
            novelty_note=(
                f"[closest earlier: {novelty.closest_earlier_id}] {novelty.new_reason.strip()}"
                if novelty is not None
                else None
            ),
        )
        self.add_history(speech)
        return speech

    def _argument_block(self, speech: Speech) -> str:
        text = render_argument_text(speech.argument)
        if self.free:
            return text
        conclusions = speech.conclusions
        if not conclusions:
            return text
        return f"Conclusions:\n{_numbered(conclusions)}\n\nFull argument:\n{text}"

    async def judge_rebut(
        self, attack: Speech, statement: str, target: Speech | None = None
    ) -> Verdict:
        out = await self.judge.structured(
            f"""<task>
You are an independent judge of an argumentation dialogue. Decide whether the ATTACK rebuts the TARGET STATEMENT.
</task>

<definition>
The attack rebuts the target statement S when one of the attack's conclusions directly opposes S: it denies what S asserts, so the two cannot both be maintained as the answer to the issue.
Any conclusion of the attack counts, including an intermediate one; it need not be the attack's final conclusion.
A difference of degree or hedging does not prevent a rebut: for example, "X does not reliably happen" opposes "X happens" when it denies what S asserts.
It does NOT count when the attack only supports a different option, narrows the scope of S, questions whether S matters, argues that S is not needed, addresses a different claim than S, or merely disagrees in tone.
Judge the meaning, not the wording or the format: a prose argument and a chain of rules are treated alike.
</definition>

<issue>
{self.topic}
</issue>

<target_statement>
{statement}
</target_statement>

<attack>
{self._argument_block(attack)}
</attack>

<procedure>
1. Quote, word for word, the conclusion of the attack that comes closest to opposing the target statement.
2. Decide whether that conclusion directly opposes the target statement, that is, whether it denies what the target statement asserts.
</procedure>""",
            RebutJudgement,
        )
        return Verdict(bool(out.rebuts), out.reason)

    async def judge_undercut(
        self,
        attack: Speech,
        target: Speech,
        assumptions: list[str],
        presumption_check: bool = False,
    ) -> Verdict:
        if not assumptions:
            return Verdict(False, "the target has no assumption to undercut")
        out = await self.judge.structured(
            """<task>
You are an independent judge of an argumentation dialogue. Decide whether the ATTACK undercuts the TARGET by denying one of the listed ASSUMPTIONS of the target.
</task>

<definition>
An assumption is an exception clause that the target's reasoning takes to hold by default ("X is not the case" / "there is no evidence that X").
The attack undercuts an assumption when the attack's own reasoning establishes that X does hold: one of the attack's conclusions is the contradictory of the assumption.
Any conclusion of the attack counts, including an intermediate one.
It does NOT count when the attack only asserts the opposite of the target's final conclusion, says the target's framing is inappropriate, or states something related to X without establishing X.
Judge only what the attack already says; do not add reasoning that the attack does not contain.
Judge the meaning, not the wording or the format: a prose argument and a chain of rules are treated alike.
"""
            + (
                "Each listed item must be a presumption that the target's reasoning relies on by default (an exception it takes to be absent), not the target's conclusion and not a plain fact it states. An item that is not such a presumption cannot be undercut: do not select it.\n"
                if presumption_check
                else ""
            )
            + f"""</definition>

<issue>
{self.topic}
</issue>

<target>
{self._argument_block(target)}
</target>

<assumptions>
{_numbered(assumptions)}
</assumptions>

<attack>
{self._argument_block(attack)}
</attack>

<procedure>
For each assumption in turn: quote the conclusion of the attack that contradicts it, if there is one, and decide whether the attack's reasoning establishes it.
Then report the number of ONE assumption that the attack undercuts, or null if it undercuts none.
</procedure>""",
            UndercutJudgement,
        )
        number = out.undercut_assumption_number
        holds = (
            isinstance(number, int)
            and not isinstance(number, bool)
            and 1 <= number <= len(assumptions)
        )
        return Verdict(holds, out.reason)

    async def assumptions_for(self, speech: Speech) -> list[str]:
        if not self.free:
            return speech.assumptions
        cached = self._presumptions.get(speech.id)
        if cached is not None:
            return cached
        out = await self.judge.structured(
            f"""<task>
List the presumptions that the argument states explicitly: exception clauses that it takes to hold by default.
</task>

<rules>
- Only phrases that the argument itself marks as a presumption ("unless", "as long as", "provided that", "assuming there is no", "absent evidence", "no evidence that"). Quote each one verbatim from the argument.
- Do not infer presumptions that the argument does not state. Do not list its premises or its conclusions.
- Return an empty list if the argument states none.
</rules>

<argument>
{speech.argument.strip()}
</argument>""",
            PresumptionList,
        )
        text = speech.argument
        found = [
            item.strip()
            for item in out.presumptions
            if item.strip() and item.strip() in text
        ]
        self._presumptions[speech.id] = found
        return found

    async def undercut_relation(self, attack: Speech, target: Speech) -> Verdict:
        return await self.judge_undercut(
            attack, target, await self.assumptions_for(target)
        )

    def _relation(
        self,
        attacker: Speech,
        target: Speech,
        match: AttackMatch | None,
        valid: bool,
        reason: str,
    ) -> Defeat:
        return Defeat(
            attacker_id=attacker.id,
            target_id=target.id,
            attack=match.method if match else attacker.attack or "rebut",
            target_field=match.field if match else attacker.target_field,
            target_statement=match.statement if match else attacker.target_statement,
            valid=valid,
            reason=reason,
        )

    def _target_statement_exists(self, match: AttackMatch, target: Speech) -> bool:
        if match.statement is None:
            return False
        if self.free:
            return _quote_in_text(match.statement, target.argument)
        wanted = _normalize(match.statement)
        return any(
            _normalize(item) == wanted for item in _candidates(target, match.method)
        )

    async def evaluate_attack(self, attacker: Speech, target: Speech) -> Evaluation:
        context = f"{attacker.id} defeats {target.id}"
        if attacker.attack is None:
            self.defeats.append(
                self._relation(
                    attacker,
                    target,
                    None,
                    False,
                    f"{context}: no attack metadata declared by LLM",
                )
            )
            return Evaluation(False)
        match = AttackMatch(
            attacker.attack, _field_for(attacker.attack), attacker.target_statement
        )

        if not self._target_statement_exists(match, target):
            self.defeats.append(
                self._relation(
                    attacker,
                    target,
                    match,
                    False,
                    f"{context}: declared target_statement not present in target",
                )
            )
            return Evaluation(False, attack=match.method)

        attacker.target_id = target.id
        attacker.target_field = match.field
        attacker.target_statement = match.statement
        statement = match.statement or ""

        if match.method == "undercut":
            verdict = await self.judge_undercut(
                attacker, target, [statement], presumption_check=self.free
            )
            if not verdict.holds:
                reason = f"{context}: undercut not established — {verdict.reason}"
            else:
                reason = f"{context}: undercut defeats target — {verdict.reason}"
            self.defeats.append(
                self._relation(attacker, target, match, verdict.holds, reason)
            )
            return Evaluation(verdict.holds, attack=match.method)

        rebut = await self.judge_rebut(attacker, statement, target)
        if not rebut.holds:
            self.defeats.append(
                self._relation(
                    attacker,
                    target,
                    match,
                    False,
                    f"{context}: rebut not established — {rebut.reason}",
                )
            )
            return Evaluation(False, attack=match.method)

        back = await self.undercut_relation(target, attacker)
        if back.holds:
            self.defeats.append(
                self._relation(
                    target,
                    attacker,
                    AttackMatch("undercut", "Ass", None),
                    True,
                    f"{context}: rebut not defeating, the target undercuts it — {back.reason}",
                )
            )
            return Evaluation(False, attack=match.method, target_undercuts=back.reason)
        self.defeats.append(
            self._relation(
                attacker,
                target,
                match,
                True,
                f"{context}: rebut not undercut by the target — {rebut.reason}",
            )
        )
        return Evaluation(True, attack=match.method)

    def _rejection_reason(self) -> str:
        for rel in reversed(self.defeats):
            if not rel.valid and rel.reason:
                return str(rel.reason)
        return ""

    # strictly defeat は SD(C, B) = U(C, B) ∧ ¬U(B, C)（U は undercut。rebut は対称）
    async def _is_mutual_defeat(self, c: Speech, b: Speech) -> bool:
        if c.attack == "undercut":
            back = await self.undercut_relation(b, c)
            mutual = back.holds
            if mutual:
                reason = f"{b.id} defeats {c.id}: undercut — {back.reason}"
            else:
                reason = f"{b.id} does not undercut {c.id} — {back.reason}"
            match = AttackMatch("undercut", "Ass", None) if mutual else None
        else:
            forward = await self.undercut_relation(c, b)
            mutual = not forward.holds
            if mutual:
                reason = f"{b.id} defeats {c.id}: rebut is symmetric and neither undercuts the other"
            else:
                reason = f"{c.id} undercuts {b.id} — {forward.reason}"
            match = AttackMatch("rebut", "Conc", None) if mutual else None
        self.defeats.append(self._relation(b, c, match, mutual, reason))
        return mutual

    async def defend(
        self, argument: Speech, entered_by_mutual_defeat: bool = False
    ) -> Frame:
        frame = Frame(argument, entered_by_mutual_defeat)
        opponent, proponent = self._label(self.opponent), self._label(self.proponent)

        while True:
            # 予算切れは理論上の決着ではないので won_by_p にはしない（defensible になる）
            if self._budget_exceeded():
                frame.outcome = "undetermined"
                return frame
            b = await self.attack(self.opponent, argument, "defeat")
            if b is None:
                frame.outcome = (
                    "contested" if frame.contested_by is not None else "won_by_p"
                )
                self._log_attempt(
                    "no_attack", opponent, argument.id, self._decline_reason, "defeat"
                )
                return frame
            result = await self.evaluate_attack(b, argument)
            if not result.defeats:
                kind = (
                    "rebut_undercut_by_target"
                    if result.target_undercuts is not None
                    else "attack_rejected"
                )
                reason = result.target_undercuts or self._rejection_reason()
                self._log_attempt(kind, opponent, b.id, reason, "defeat")
                continue
            frame.current_attacker = b

            while True:
                if self._budget_exceeded():
                    frame.outcome = "undetermined"
                    return frame
                c = await self.attack(self.proponent, b, "counter")
                if c is None:
                    frame.outcome = "lost_by_p"
                    self._log_attempt(
                        "no_counter", proponent, b.id, self._decline_reason, "counter"
                    )
                    return frame
                if c.novelty_note:
                    self._log_attempt(
                        "novelty_declared", proponent, c.id, c.novelty_note, "counter"
                    )
                result = await self.evaluate_attack(c, b)
                if result.defeats:
                    break
                kind = (
                    "rebut_undercut_by_target"
                    if result.target_undercuts is not None
                    else "attack_rejected"
                )
                reason = result.target_undercuts or self._rejection_reason()
                self._log_attempt(kind, proponent, c.id, reason, "counter")

            mutual = await self._is_mutual_defeat(c, b)
            if mutual:
                self._log_attempt(
                    "mutual_defeat",
                    opponent,
                    c.id,
                    f"{b.id} and {c.id} defeat each other; the branch can only be defensible.",
                    "counter",
                )
            child = await self.defend(c, entered_by_mutual_defeat=mutual)

            if child.outcome in ("won_by_p", "contested"):
                contested = (
                    child.outcome == "contested" or child.entered_by_mutual_defeat
                )
                if contested and frame.contested_by is None:
                    frame.contested_by = b
                frame.current_attacker = None
                continue
            frame.outcome = "lost_by_p"
            frame.closed_by_budget = (
                child.closed_by_budget or child.outcome == "undetermined"
            )
            return frame

    def _thread_finding(self, main: Speech, root: Frame, status: str) -> str | None:
        if status not in {"overruled", "defensible"}:
            return None
        attacker = root.current_attacker or root.contested_by
        if attacker is None:
            return None
        main_conclusion = "; ".join(main.conclusions) or "the previous main argument"
        defeating = "; ".join(attacker.conclusions) or "the defeating argument"
        proponent, opponent = self._label(self.proponent), self._label(self.opponent)
        if status == "overruled":
            return (
                f"{proponent}'s previous main argument ({main_conclusion}) was overruled by "
                f"{opponent}'s {attacker.attack} ({defeating}). "
                "Do not repeat the same main argument unless this defeating reason is resolved."
            )
        return (
            f"{proponent}'s previous main argument ({main_conclusion}) remained defensible, "
            f"with an unresolved conflict against {opponent}'s {attacker.attack} "
            f"({defeating}). "
            "Do not repeat the same main argument as if the conflict were resolved."
        )

    async def run_thread(self, main: Speech) -> str:
        self.current_main = main
        root = await self.defend(main)
        status, closed_by_budget = _root_status(root)
        main.status = status
        main.closed_by_budget = closed_by_budget
        label = self._label(self.proponent)
        self.thread_status[label] = status
        finding = self._thread_finding(main, root, status)
        if finding is not None and finding not in self.learned_findings:
            self.learned_findings.append(finding)
            self.revision_context[label] = finding
        return status

    def extract_warrants(self, main1: Speech, main2: Speech) -> str:
        warrants: dict[str, dict[str, Any]]
        if self.free:
            warrants = {
                "Argument1": {"agent": "AG1", "warrant": main1.argument},
                "Argument2": {"agent": "AG2", "warrant": main2.argument},
            }
            return json.dumps(warrants, ensure_ascii=False, indent=2)

        def warrant(main: Speech) -> dict[str, Any]:
            last_rule = main.body.get("rules", [])[-1]
            return {
                "antecedent": {
                    "strong": last_rule["antecedent"].get("strong", []),
                    "weak_negation": last_rule["antecedent"].get("weak_negation", []),
                },
                "consequent": last_rule["consequent"],
            }

        warrants = {
            "Argument1": {"agent": "AG1", "warrant": warrant(main1)},
            "Argument2": {"agent": "AG2", "warrant": warrant(main2)},
        }
        return json.dumps(warrants, ensure_ascii=False, indent=2)

    async def integrate(self, warrants: str, free: bool | None = None) -> str | None:
        free = self.free if free is None else free
        system = [
            "<role>\n"
            "You are AG1 in this debate.\n"
            "You now act as the synthesis operator for the debate.\n"
            "Your task is to generalize each side's warrant into a reusable condition-to-conclusion "
            "criterion, then integrate both sides' criteria into one reusable rule for the next round.\n"
            "</role>",
            f"<stance>\n{self._stance(self.ag1)}\n</stance>",
            "<integration_principles>\n"
            "- Priority: preserving every distinct substantive requirement from both source stances "
            "outranks abstraction. Abstract the STRUCTURE of each side's warrant (the general "
            "condition-to-conclusion pattern, so the rule is usable by either side in the next round; "
            "do not merely list the warrants) — but never abstract away a specific named entity, legal "
            "or factual characterization, threshold, or affected group that is the substance of a "
            "requirement itself (e.g. keep 'protects an individual right', not just 'affects a right').\n"
            "- Use the source stances as a coverage check: the rule must not silently drop a distinct "
            "substantive requirement from either side, even one a compressed warrant did not repeat, "
            "and even if keeping it means the rule is less general than it could otherwise be.\n"
            "- When the sides support different outcomes, express one decision rule that says which "
            "outcome follows under each condition; do not combine opposing conditions under one OR "
            "and leave their outcomes ambiguous.\n"
            "- If opposing conditions can both be true, adjudicate them symmetrically using the same "
            "evidential threshold for both sides (magnitude, likelihood, reversibility, mitigation); "
            "do not give either side an automatic veto. Do not invent a precautionary presumption, "
            "burden shift, or tie-breaker absent from the warrants; if they do not determine the "
            "balance, preserve that as unresolved.\n"
            "- Do not discard AG2's warrant merely because it conflicts with AG1's stance, and do not "
            "simply restate AG1's own warrant as the result.\n"
            "- Do not choose a winner between the two sides, and do not produce a final answer to the "
            "original Issue.\n"
            "</integration_principles>",
        ]
        if not free:
            system.append(
                "<schema_overlay>\n"
                "Represent the result as one structured rule:\n"
                "- consequent: the shared decision principle or outcome mapping.\n"
                "- rule: a single reusable rule preserving each side's condition-to-outcome mapping. "
                "Use OR only for conditions that support the same outcome.\n"
                "</schema_overlay>"
            )
        output = await self.judge.structured(
            "\n\n".join(system)
            + "\n\n"
            + "\n".join(
                [
                    "<task>",
                    "Generalize the warrants into reusable criteria, then integrate them into one rule.",
                    "</task>",
                    "",
                    "<warrants>",
                    warrants,
                    "</warrants>",
                    "",
                    "<source_stances>",
                    "<ag1_stance>",
                    self._stance(self.ag1),
                    "</ag1_stance>",
                    "<ag2_stance>",
                    self._stance(self.ag2),
                    "</ag2_stance>",
                    "</source_stances>",
                    "",
                    "<response_contract>",
                    "Return exactly one integrated rule.",
                    "The rule must be applicable to future main arguments.",
                    "Do not answer the original Issue.",
                    "</response_contract>",
                ]
            ),
            FREE_SCHEMA.integration if free else self.schema.integration,
        )
        rule = getattr(getattr(output, "Argument", None), "rule", None)
        return rule.strip() if isinstance(rule, str) and rule.strip() else None

    def _transcript(self) -> str:
        number = {speech.id: n for n, speech in enumerate(self.history, start=1)}
        blocks = []
        for n, speech in enumerate(self.history, start=1):
            if speech.type == "main":
                label = f"[Turn {n}] {speech.agent} (new argument)"
            elif speech.target_id in number:
                label = f"[Turn {n}] {speech.agent} (responding to [Turn {number[speech.target_id]}])"
            else:
                label = f"[Turn {n}] {speech.agent} (responding to an earlier turn)"
            blocks.append(f"{label}\n{render_argument_text(speech.argument)}")
        return "\n\n".join(blocks)

    def _last_position(self, label: str) -> str | None:
        for speech in reversed(self.history):
            if speech.agent == label and speech.type == "main":
                return render_argument_text(speech.argument)
        return None

    async def final_answer(self, justified: Speech | None) -> dict[str, Any]:
        integrated: str | None = None
        if justified is not None:
            path = "justified_with_dialogue"
        else:
            position1, position2 = (
                self._last_position("AG1"),
                self._last_position("AG2"),
            )
            if position1 and position2:
                warrants = json.dumps(
                    {
                        "Argument1": {"agent": "AG1", "warrant": position1},
                        "Argument2": {"agent": "AG2", "warrant": position2},
                    },
                    ensure_ascii=False,
                )
                integrated = await self.integrate(warrants, free=True)
            path = "integrated_with_dialogue" if integrated else "dialogue_only"

        blocks = [
            f"Question:\n{self.topic}",
            f"AG1 stance:\n{self._stance(self.ag1)}",
            f"AG2 stance:\n{self._stance(self.ag2)}",
        ]
        if justified is not None:
            blocks.append(
                f"Justified argument:\n{render_argument_text(justified.argument)}"
            )
        if integrated:
            blocks.append(f"Integrated proposal:\n{integrated}")
        blocks.append(
            "Dialogue:\n"
            "The record below shows AG1 and AG2 arguing in turn, each from its own stance. "
            "Turns are numbered in order. Each turn is marked either as a new argument or as a response "
            "to an earlier turn."
            f"\n\n{self._transcript()}"
        )
        user = "\n\n".join(blocks).strip()
        answer = _text(
            await self.judge.chat(
                """<task>
Answer the original question, using the record of the debate between AG1 and AG2.
</task>

<materials>
- The dialogue: always provided. It shows everything both sides argued and how each side responded.
- A justified argument: provided only when the debate reached one. It is an argument that stood
  against every objection raised in the dialogue.
- An integrated proposal: provided only when both sides had a final position to integrate. It is a
  single proposal built from the two sides' final positions.
</materials>

<requirements>
- Lead with a direct answer to the original question.
- If a justified argument is provided, refer to it: it is the conclusion the debate reached.
- If an integrated proposal is provided, refer to it: treat it as the primary basis of the answer.
- Use the dialogue to keep what each side raised and what the other side answered. Preserve every
  material requirement, value, condition, affected group, exception, and tradeoff from both
  stances that remains relevant after the debate.
- Do not independently select a winning side, and do not silently discard one side's material
  requirements simply to make the answer more decisive.
- If the basis you were given is conditional, the final answer may also be conditional rather than
  forcing an artificial unconditional yes/no conclusion. If a conflict genuinely remains
  unresolved, state exactly what remains unresolved.
- Do not mention agents, turns, or the debate process.
</requirements>"""
                f"\n\n{user}"
            )
        )
        return {
            "final_answer": answer,
            "integrated_proposal": integrated,
            "finalization_path": path,
        }

    def _result(
        self, justified: Speech | None, status: str, final: dict[str, Any] | None
    ) -> dict[str, Any]:
        final = final or {}
        return {
            "dialogue_history": [speech.to_dict() for speech in self.history],
            "justified_argument": justified.argument if justified else None,
            "justification_status": status,
            "finalization_path": final.get("finalization_path"),
            "integrated_proposal": final.get("integrated_proposal"),
            "consensus_reached": justified is not None,
            "final_answer": final.get("final_answer"),
            "integrated_rules": self.integrated_rules,
            "debate_round": self.round,
            "ag1_thread_status": self.thread_status["AG1"],
            "ag2_thread_status": self.thread_status["AG2"],
            "main_unavailable_reasons": self.unavailable_reasons,
            "attempt_log": self.attempt_log,
            "defeat_relations": [vars(rel) for rel in self.defeats],
            "agent1_stance": self._stance(self.ag1),
            "agent2_stance": self._stance(self.ag2),
            "error": self.error,
        }

    async def run(self) -> dict[str, Any]:
        while self.round <= self.max_round:
            mains: dict[str, Speech | None] = {"AG1": None, "AG2": None}
            self.thread_status = {"AG1": None, "AG2": None}

            for proponent, opponent in ((self.ag1, self.ag2), (self.ag2, self.ag1)):
                self.proponent, self.opponent = proponent, opponent
                self.current_main = None
                main = await self.main_argument(proponent)  # main argumentを構築
                if self.error:
                    return self._result(None, "error", None)
                if main is None:
                    continue
                mains[main.agent] = main
                if (
                    await self.run_thread(main) == "justified"
                ):  # run_threadで主張の状態を決定
                    status = f"{main.agent.lower()}_main_justified"
                    return self._result(main, status, await self.final_answer(main))

            main1, main2 = mains["AG1"], mains["AG2"]
            if main1 is None or main2 is None:
                break

            try:
                warrants = self.extract_warrants(main1, main2)
            except Exception as exc:
                self.error = f"Warrant抽出中にエラーが発生しました: {exc}"
                return self._result(None, "error", None)
            rule = await self.integrate(warrants)
            if rule is None:
                self.error = "統合結果から新しいルールを抽出できませんでした"
                return self._result(None, "error", None)
            if rule not in self.integrated_rules:
                self.integrated_rules.append(rule)
            self.round += 1

        return self._result(
            None, "fallback_no_consensus", await self.final_answer(None)
        )
