"""攻撃の対象の指定（target_selection）の単体テスト.

schema は、番号から文を復元する。no_schema は、攻撃側が書き写した文が、対象の本文に含まれるかを確かめる。
"""

from __future__ import annotations

import json

from agent.schema.state import ArgumentRecord
from agent.target_selection import (
    candidates,
    field_for,
    options_block,
    quote_in_text,
    resolve_target,
)


def _schema_record() -> ArgumentRecord:
    payload = {
        "Argument": {
            "rules": [],
            "Conc": ["We should buy a", "a is cheap"],
            "Ass": ["a stays in stock"],
        }
    }
    return ArgumentRecord(type="main", argument=json.dumps(payload), support=[], agent="AG1")


def test_schema_numbers_index_conclusions_for_rebut_and_assumptions_for_undercut() -> None:
    record = _schema_record()

    assert resolve_target(record, "rebut", 2) == "a is cheap"
    assert resolve_target(record, "undercut", 1) == "a stays in stock"
    assert candidates(record, "rebut") == ["We should buy a", "a is cheap"]
    assert field_for("rebut") == "Conc" and field_for("undercut") == "Ass"


def test_numbers_out_of_range_or_not_integers_do_not_resolve() -> None:
    record = _schema_record()

    assert resolve_target(record, "rebut", 0) is None
    assert resolve_target(record, "rebut", 3) is None
    assert resolve_target(record, "undercut", 2) is None
    assert resolve_target(record, "rebut", True) is None  # type: ignore[arg-type]
    assert resolve_target(record, "rebut", "1") is None  # type: ignore[arg-type]


def test_restored_statement_is_the_exact_text_of_the_target() -> None:
    record = _schema_record()

    assert resolve_target(record, "rebut", 1) in record.conclusions


def test_options_block_numbers_the_items_from_one_for_schema() -> None:
    block = options_block(_schema_record(), "schema")

    assert "<target_conclusions>\n[1] We should buy a\n[2] a is cheap\n</target_conclusions>" in block
    assert "<target_assumptions>\n[1] a stays in stock\n</target_assumptions>" in block


def test_options_block_marks_empty_lists() -> None:
    record = ArgumentRecord(
        type="main",
        argument=json.dumps({"Argument": {"rules": [], "Conc": ["c"], "Ass": []}}),
        support=[],
        agent="AG1",
    )

    assert "<target_assumptions>\n(none)\n</target_assumptions>" in options_block(record, "schema")


def test_no_schema_has_no_options_to_choose_from() -> None:
    record = ArgumentRecord(type="main", argument="We should buy a.", support=[], agent="AG1")

    assert options_block(record, "no_schema") == ""


TEXT = "We should buy a. It is cheap!\nThis assumes a stays in stock."


def test_a_copied_sentence_or_phrase_is_found_in_the_text() -> None:
    assert quote_in_text("It is cheap!", TEXT)
    assert quote_in_text("This assumes a stays in stock", TEXT)  # 句点は問わない
    assert quote_in_text("assumes a stays in stock", TEXT)  # フレーズでよい


def test_whitespace_case_and_surrounding_quotes_are_ignored() -> None:
    assert quote_in_text('  "we  should\nbuy a"  ', TEXT)
    assert quote_in_text("“IT IS CHEAP”", TEXT)


def test_a_paraphrase_or_an_elided_quote_is_not_found() -> None:
    assert not quote_in_text("a is inexpensive", TEXT)
    assert not quote_in_text("We should ... a stays in stock", TEXT)
    assert not quote_in_text("We should… stock", TEXT)


def test_too_short_or_empty_quotes_are_not_accepted() -> None:
    assert not quote_in_text("", TEXT)
    assert not quote_in_text("a", TEXT)
