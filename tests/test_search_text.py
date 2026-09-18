from rag.planner import parse_search_syntax
from rag.search_text import normalize_query_quotes


def test_normalize_common_double_quote_variants():
    assert normalize_query_quotes('“a” „b“ »c«') == '"a" "b" "c"'


def test_planner_accepts_german_typographic_phrase_quotes():
    parsed = parse_search_syntax('„38 M 8076/17“')
    assert parsed.phrases == ['38 M 8076/17']
    assert parsed.free_words == []
