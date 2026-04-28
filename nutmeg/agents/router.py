from __future__ import annotations

from enum import StrEnum


class QueryIntent(StrEnum):
    INFORMATIONAL = 'informational'
    DECISIONAL = 'decisional'


DECISION_KEYWORDS = (
    'bet',
    'value',
    'pick',
    'should i',
    'recommend',
    'odds',
    'win',
    'lose',
    'over',
    'under',
    'brief',
    'pre-match',
    '盘口',
    '下注',
    '推荐',
    '怎么看',
    '看好',
    '判断',
    '赛前',
    '方向',
    '胜负',
)


def classify_intent(query: str) -> QueryIntent:
    lowered = query.strip().lower()
    if any(keyword in lowered for keyword in DECISION_KEYWORDS):
        return QueryIntent.DECISIONAL
    return QueryIntent.INFORMATIONAL
