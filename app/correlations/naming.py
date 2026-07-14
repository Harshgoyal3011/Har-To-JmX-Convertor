from __future__ import annotations

import functools

from app.patterns import (
    GENERIC_ID_FIELD_NAMES,
    NOUN_STOPWORDS,
    TRANSACTION_VERB_STOPWORDS,
    WRAPPER_KEY_STOPWORDS,
    _NON_ALNUM_RE,
    _PATH_SEGMENT_ID_RE,
    _TRANSACTION_WORD_RE,
)


@functools.lru_cache(maxsize=4096)
def _singularize(word: str) -> str:
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("ses"):
        return word[:-2]
    if len(word) > 2 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@functools.lru_cache(maxsize=4096)
def _noun_from_path(path: str) -> str | None:
    segments = [
        s for s in path.split("/")
        if s
        and not _PATH_SEGMENT_ID_RE.match(s)
        and not s.isdigit()
        and s.lower() not in NOUN_STOPWORDS
    ]
    if not segments:
        return None
    return _singularize(segments[-1].lower())


@functools.lru_cache(maxsize=4096)
def _noun_from_transaction(transaction: str) -> str | None:
    words = _TRANSACTION_WORD_RE.findall(transaction or "")
    meaningful = [w for w in words if w.lower() not in TRANSACTION_VERB_STOPWORDS and not w.isdigit()]
    if not meaningful:
        return None
    return _singularize(meaningful[-1].lower())


def derive_contextual_field_key(field_name: str, ancestry: list[str], sampler_path: str, transaction: str = "") -> str:
    if field_name.lower() not in GENERIC_ID_FIELD_NAMES:
        return field_name

    context_noun = None
    for ancestor in reversed(ancestry):
        singular = _singularize(ancestor.lower())
        if singular and singular not in WRAPPER_KEY_STOPWORDS:
            context_noun = singular
            break
    if not context_noun:
        context_noun = _noun_from_path(sampler_path)
    if not context_noun:
        context_noun = _noun_from_transaction(transaction)
    if not context_noun:
        return field_name

    context_noun = _NON_ALNUM_RE.sub("", context_noun)
    if not context_noun:
        return field_name
    return f"{context_noun[0].lower()}{context_noun[1:]}{field_name[0].upper()}{field_name[1:]}"
