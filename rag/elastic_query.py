"""Nextcloud Full Text Search expression parsing for the direct /elastic path."""

from __future__ import annotations

import re

from rag.search_text import normalize_query_quotes


def nextcloud_query_tokens(query: str) -> list[dict]:
    """Parse the Files full-text expression language like Nextcloud QueryContent.

    The important detail is the Elasticsearch match type chosen by the
    FullTextSearch_Elasticsearch ``QueryContent`` model used by the user's
    Nextcloud release:

    * bare / ``+`` / ``-`` terms -> ``match_phrase_prefix``
    * a quoted token without spaces (e.g. ``"22-07"``) -> ``match``
    * a quoted expression containing spaces -> ``match_phrase_prefix``

    ``+`` makes the clause required, ``-`` excluded, otherwise it is optional.
    Quotes are syntax only and are removed before the Elasticsearch query is
    built.
    """
    text = normalize_query_quotes(query).strip()
    if not text:
        return []

    # Optional + / - belongs to a quoted expression as a single token.
    raw_tokens = re.findall(r'[+-]?"(?:\\.|[^\\"])*"|\S+', text)
    parsed: list[dict] = []
    for raw in raw_tokens:
        token = raw.strip()
        if not token:
            continue

        occur = "should"
        if token.startswith("+"):
            occur = "must"
            token = token[1:].strip()
        elif token.startswith("-"):
            occur = "must_not"
            token = token[1:].strip()
        if not token:
            continue

        quoted = token.startswith('"')
        # Mirror QueryContent::init(): quoted single tokens use plain `match`;
        # quoted strings containing a space use `match_phrase_prefix`.
        match_type = "match_phrase_prefix"
        if quoted:
            match_type = "match"
            if " " in token:
                match_type = "match_phrase_prefix"

        token = token.replace('"', '')
        token = token.replace(r'\\', '\\').strip()
        if not token:
            continue

        parsed.append({
            "occur": occur,
            "text": token,
            "phrase": quoted,  # retained for diagnostics/backward compatibility
            "match": match_type,
        })
    return parsed
