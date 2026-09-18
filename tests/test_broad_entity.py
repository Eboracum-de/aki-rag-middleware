from rag.query_specificity import is_broad_entity_query


def ctx(mention="Frank Muster"):
    return {"entities": [{"status": "resolved", "entity_id": "p1", "mention": mention, "display_name": mention}]}


def test_bare_entity_is_broad():
    assert is_broad_entity_query('"Frank Muster"', ctx()) is True


def test_generic_information_request_is_broad():
    assert is_broad_entity_query("Informationen zu Frank Muster", ctx()) is True


def test_year_narrows_entity_query():
    assert is_broad_entity_query("Frank Muster 2010", ctx()) is False


def test_subject_term_narrows_entity_query():
    assert is_broad_entity_query("Frank Muster Musterhof", ctx()) is False


def test_search_channel_words_do_not_narrow_entity_query():
    from rag.query_specificity import is_broad_entity_query
    ctx = {"entities": [{"status": "resolved", "entity_id": "e1", "mention": "Erika Muster"}]}
    assert is_broad_entity_query("Suche intern und im Netz nach Erika Muster", ctx) is True
