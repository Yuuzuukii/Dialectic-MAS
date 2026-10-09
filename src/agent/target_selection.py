"""攻撃の対象の指定と、その実在の確認.

- schema: 攻撃側 LLM に対象の文を書き写させると、一字一句の一致が保てないので、対象の論証から
  選べる文の一覧（rebut は結論 Conc、undercut は仮定 Ass）を番号つきで見せ、番号だけを答えさせる。
  番号から文を復元するのはコードなので、対象が実在するかは、番号の範囲の確認だけで決まる。
- no_schema: 論証が自由文で、選ぶ一覧がないので、攻撃側に、対象の文（またはフレーズ）を、対象の本文から
  書き写して出させる。実在の確認は、その文が対象の本文に含まれるか（空白と大文字小文字を揃えて）の照合。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schema.state import ArgumentRecord

_MIN_QUOTE_LENGTH = 3
_QUOTE_MARKS = "\"'“”‘’「」『』"
_ELLIPSIS = re.compile(r"(?:\.\.\.|…)+")


def is_schema(mode: str) -> bool:
    """Return True for the schema condition (anything other than no_schema)."""
    return mode != "no_schema"


def field_for(method: str) -> str:
    """攻撃の種類から、対象の欄（rebut=Conc、undercut=Ass）を返す."""
    return "Conc" if method == "rebut" else "Ass"


def candidates(target: ArgumentRecord, method: str) -> list[str]:
    """List the sentences a schema attack of this kind may target (numbered from 1, in this order)."""
    return target.conclusions if method == "rebut" else target.assumptions


def resolve_target(target: ArgumentRecord, method: str, number: int) -> str | None:
    """Restore the target sentence from its number (schema); None if out of range."""
    options = candidates(target, method)
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return options[number - 1] if 1 <= number <= len(options) else None


def _normalize_quote(text: str) -> str:
    """空白をまとめ、前後の引用符と句点を外し、大文字小文字を揃える."""
    collapsed = " ".join(text.split()).strip(_QUOTE_MARKS + " ")
    return collapsed.rstrip(".。 ").casefold()


def _normalize_body(text: str) -> str:
    return " ".join(text.split()).casefold()


def quote_in_text(quote: str, text: str) -> bool:
    """no_schema で、攻撃側が出した対象の文（フレーズ）が、対象の本文に含まれるか.

    省略記号で途中を省いたものは、書き写しではないので、認めない。
    """
    if _ELLIPSIS.search(quote):
        return False
    wanted = _normalize_quote(quote)
    return len(wanted) >= _MIN_QUOTE_LENGTH and wanted in _normalize_body(text)


def _numbered(items: list[str]) -> str:
    return "\n".join(f"[{index}] {item}" for index, item in enumerate(items, start=1))


def options_block(target: ArgumentRecord, mode: str) -> str:
    """攻撃側に見せる、番号つきの選択肢のブロック（schema のみ。no_schema は、選択肢がないので空）."""
    if not is_schema(mode):
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
