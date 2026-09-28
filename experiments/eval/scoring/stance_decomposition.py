"""stance文を、依存構造解析（spaCy）に基づき機械的に節単位へ分解する.

evaluation_coverage.py の extract_stance_items は stance の "You believe ..." 行を
そのまま1項目として扱うため、1行に複数の主張（事実＋因果＋評価的結論など）が
含まれていても分割されない。本モジュールは、LLMによる言い換え・幻覚を避けつつ
項目の粒度を上げるため、係り受け解析で以下の構造的な境界だけを分割点とする:

- advcl / relcl / acl（従属節・関係節）: "X, so Y" "X, making Y" "Y that/which Z" 等
- conj（等位接続で並列された名詞句・修飾語）: "poverty, debt, and reliance" 等

分割は構文構造のみに基づき、原文の語をそのまま再配置するだけで、LLMによる
書き換え・新規語の生成は行わない（決定論的・再現可能）。
"""

from __future__ import annotations

import re
from functools import lru_cache

import spacy
from spacy.tokens import Doc, Token

_CLAUSE_DEPS = {"advcl", "relcl", "acl"}
_LEADING_CONNECTIVES = {
    "so",
    "while",
    "making",
    "who",
    "whom",
    "which",
    "that",
    "because",
    "since",
    "as",
    "though",
    "although",
    "if",
    "when",
    "creating",
}


@lru_cache(maxsize=1)
def _nlp() -> spacy.language.Language:
    return spacy.load("en_core_web_sm")


def _subtree_span(token: Token) -> tuple[int, int]:
    subtree = list(token.subtree)
    return min(t.i for t in subtree), max(t.i for t in subtree)


def _is_nested_in(token: Token, ancestors_with_span: list[tuple[int, int]]) -> bool:
    for lo, hi in ancestors_with_span:
        if lo <= token.i <= hi:
            return True
    return False


def _top_level_clause_candidates(doc: Doc) -> list[Token]:
    """advcl/relcl/acl のうち、他の候補の部分木に含まれない最上位のものだけを返す."""
    all_candidates = [t for t in doc if t.dep_ in _CLAUSE_DEPS]
    all_candidates.sort(key=lambda t: -(_subtree_span(t)[1] - _subtree_span(t)[0]))
    kept: list[Token] = []
    kept_spans: list[tuple[int, int]] = []
    for t in sorted(all_candidates, key=lambda t: t.i):
        span = _subtree_span(t)
        if _is_nested_in(t, kept_spans):
            continue
        kept.append(t)
        kept_spans.append(span)
    return kept


def _conj_groups(doc: Doc, exclude_spans: list[tuple[int, int]]) -> list[list[Token]]:
    """等位接続(conj)で繋がれた名詞句・修飾語のグループを、除外済み範囲の外から集める.

    動詞同士のconj（並列の主節）はここでは対象外とする（意味が変わりやすいため）。
    """
    groups: list[list[Token]] = []
    seen: set[int] = set()
    for tok in doc:
        if tok.i in seen or _is_nested_in(tok, exclude_spans):
            continue
        if tok.dep_ != "conj" or tok.pos_ == "VERB" or tok.head.pos_ == "VERB":
            continue
        # tok はconjチェーンの一員。チェーンの先頭（conjでない祖先）を探す。
        head = tok.head
        while head.dep_ == "conj":
            head = head.head
        if _is_nested_in(head, exclude_spans):
            continue
        members = [head] + [c for c in head.conjuncts]
        members = sorted(set(members), key=lambda t: t.i)
        if len(members) < 2 or any(m.i in seen for m in members):
            continue
        for m in members:
            seen.add(m.i)
        groups.append(members)
    return groups


_TRAILING_DANGLERS = re.compile(
    r"[,;:\-–—]+\s*(and|or|while|so|which|that|who|when)?\s*$", re.IGNORECASE
)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"^[,;:\s]+", "", text)
    # 節を機械的に切り出した際に残る、宙ぶらりんの接続語・カンマ・ダッシュを文末から除去する
    # （例: "..., health insurance coverage, and" -> "..., health insurance coverage"）。
    prev = None
    while prev != text:
        prev = text
        text = _TRAILING_DANGLERS.sub("", text).strip()
    if text and not text.endswith((".", "!", "?")):
        text += "."
    return text[0].upper() + text[1:] if text else text


def _strip_leading_connective(text: str) -> str:
    words = text.split()
    while words and words[0].lower().strip(",") in _LEADING_CONNECTIVES:
        words = words[1:]
    return " ".join(words)


def _has_explicit_subject(token: Token) -> bool:
    return any(c.dep_ in ("nsubj", "nsubjpass", "expl") for c in token.subtree)


def _strip_you_believe_prefix(doc: Doc) -> tuple[tuple[int, int], Token]:
    """'You believe/support/oppose ...' の先頭を除いた本体の範囲と、本体の主動詞トークンを返す."""
    root = next((t for t in doc if t.dep_ == "ROOT"), doc[0])
    if root.lemma_.lower() in ("believe", "support", "oppose", "think", "hold"):
        comp = next(
            (c for c in root.children if c.dep_ in ("ccomp", "xcomp")), None
        )
        if comp is not None:
            lo, hi = _subtree_span(comp)
            return (lo, hi), comp
    return (0, len(doc) - 1), root


def decompose_stance_line(line: str) -> list[str]:
    """stanceの1行を、依存構造解析に基づき複数の原子的主張に機械的に分解する.

    LLMを使わず、spaCyの依存構造から (1) 従属節/関係節 (advcl/relcl/acl) と
    (2) 並列された名詞句/修飾語 (conj) を分割点として抽出する。元の語順・語彙を
    そのまま使い、言い換えは一切しない。
    """
    doc = _nlp()(line.strip())
    (body_lo, body_hi), body_root = _strip_you_believe_prefix(doc)

    clause_candidates = [
        t for t in _top_level_clause_candidates(doc) if body_lo <= t.i <= body_hi
    ]
    clause_spans = [_subtree_span(t) for t in clause_candidates]

    conj_groups = _conj_groups(doc, clause_spans)
    conj_spans: list[tuple[int, int]] = []
    for group in conj_groups:
        lo = min(_subtree_span(m)[0] for m in group)
        hi = max(_subtree_span(m)[1] for m in group)
        conj_spans.append((lo, hi))

    removed_spans = clause_spans + conj_spans

    def _outside_removed(i: int) -> bool:
        return not any(lo <= i <= hi for lo, hi in removed_spans)

    main_tokens = [doc[i] for i in range(body_lo, body_hi + 1) if _outside_removed(i)]
    main_text = _clean("".join(t.text_with_ws for t in main_tokens))

    main_subject = ""
    subj_tok = next(
        (c for c in body_root.children if c.dep_ in ("nsubj", "nsubjpass")), None
    )
    if subj_tok is not None:
        s_lo, s_hi = _subtree_span(subj_tok)
        main_subject = _clean(
            "".join(doc[i].text_with_ws for i in range(s_lo, s_hi + 1) if _outside_removed(i))
        ).rstrip(".")
    if not main_subject:
        # nsubj/nsubjpass の子が見つからない場合（動名詞主語等）のフォールバック:
        # main節の定形動詞（ccomp/xcomp/ROOTで、かつ本体の直接の述語）より前の部分を主語句とみなす。
        clause_verb = next(
            (
                t
                for t in main_tokens
                if t.pos_ == "VERB"
                and t.dep_ in ("ccomp", "xcomp", "ROOT")
                and t.i != body_root.i
            ),
            None,
        )
        if clause_verb is not None:
            main_subject = _clean(
                "".join(
                    t.text_with_ws for t in main_tokens if t.i < clause_verb.i
                )
            ).rstrip(".")

    items: list[str] = [main_text] if main_text else []

    for t in clause_candidates:
        lo, hi = _subtree_span(t)
        raw = "".join(doc[i].text_with_ws for i in range(lo, hi + 1))
        stripped = _strip_leading_connective(raw)
        if not _has_explicit_subject(t) and main_subject:
            stripped = f"{main_subject} {stripped}"
        items.append(_clean(stripped))

    for group in conj_groups:
        coord_lo = min(_subtree_span(m)[0] for m in group)
        coord_hi = max(_subtree_span(m)[1] for m in group)
        # conjの連鎖(poverty -conj-> debt -conj-> reliance)では、先行メンバーのsubtreeが
        # 後続メンバーのsubtreeを包含してしまう。トークン順に並べ、各メンバーの「自分の
        # 範囲」を「自分のsubtree開始 〜 次のメンバーの開始直前」に限定して重複を防ぐ。
        ordered = sorted(group, key=lambda t: t.i)
        exclusive_spans: dict[int, tuple[int, int]] = {}
        for idx, member in enumerate(ordered):
            own_lo, own_hi = _subtree_span(member)
            if idx + 1 < len(ordered):
                # 次のメンバー自身の修飾語（compound等）を巻き込まないよう、次メンバーの
                # subtreeの開始位置（＝次メンバーの修飾語込みの開始点）の直前で打ち切る。
                next_lo, _ = _subtree_span(ordered[idx + 1])
                own_hi = min(own_hi, next_lo - 1)
            exclusive_spans[member.i] = (own_lo, own_hi)

        for member in group:
            m_lo, m_hi = exclusive_spans[member.i]
            rebuilt_tokens = []
            for i in range(body_lo, body_hi + 1):
                if coord_lo <= i <= coord_hi:
                    if m_lo <= i <= m_hi:
                        rebuilt_tokens.append(doc[i])
                    continue
                if any(
                    lo <= i <= hi
                    for lo, hi in removed_spans
                    if (lo, hi) != (coord_lo, coord_hi)
                ):
                    continue
                rebuilt_tokens.append(doc[i])
            rebuilt = "".join(t.text_with_ws for t in rebuilt_tokens)
            items.append(_clean(rebuilt))

    # 空文字列・前置詞で終わる断片（残骸）・重複を除去（順序は維持）。
    _DANGLING_PREP_END = re.compile(
        r"\b(to|of|in|on|at|from|for|with|by|as|than)\.$", re.IGNORECASE
    )
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if _DANGLING_PREP_END.search(item):
            continue
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def extract_stance_items_atomic(stance: str) -> list[str]:
    """stance文字列全体（複数行）から、機械的に細分化した項目リストを返す.

    evaluation_coverage.extract_stance_items と同じ入力形式（先頭2行がヘッダー・
    立場表明）を前提とし、以降の "You believe ..." 各行を decompose_stance_line で
    分解して連結する。
    """
    lines = [line.strip() for line in (stance or "").splitlines() if line.strip()]
    body_lines = lines[2:] if len(lines) > 2 else []
    items: list[str] = []
    for line in body_lines:
        items.extend(decompose_stance_line(line))
    return items


__all__ = ["decompose_stance_line", "extract_stance_items_atomic"]
