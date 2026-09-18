from rag.planner import create_plan


def test_one_word_query_prepares_lexical_and_semantic_signals():
    plan = create_plan("Kontoauszug")
    assert plan.search_mode == "hybrid"
    assert plan.semantic_query == "Kontoauszug"
    assert plan.should == ["Kontoauszug"]
    assert "Kurzquery-Fast-Path" in plan.notes


def test_two_word_query_keeps_combined_lexical_boost_and_semantic_query():
    plan = create_plan("Max Mustermann")
    assert plan.search_mode == "hybrid"
    assert plan.semantic_query == "Max Mustermann"
    assert "Max" in plan.should
    assert "Mustermann" in plan.should
    assert "Max Mustermann" in plan.should
