from nutmeg.agents.router import QueryIntent, classify_intent


def test_classify_intent_detects_decisional_queries() -> None:
    assert classify_intent('Should I bet Arsenal -0.25?') == QueryIntent.DECISIONAL
    assert classify_intent('Give me the pre-match operator brief.') == QueryIntent.DECISIONAL
    assert classify_intent('这场比赛怎么看？') == QueryIntent.DECISIONAL


def test_classify_intent_defaults_to_informational() -> None:
    assert classify_intent('Show me Arsenal tactical trends') == QueryIntent.INFORMATIONAL
