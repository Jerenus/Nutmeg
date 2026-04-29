from __future__ import annotations

from pathlib import Path

from nutmeg.services.psychology.inspiration import InspirationParser, InspirationStore
from nutmeg.services.psychology.llm import FakeLLMCompleter
from nutmeg.services.psychology.schemas import InspirationTags


def test_parser_uses_llm_when_available() -> None:
    parser = InspirationParser(
        llm=FakeLLMCompleter(
            responses=[
                '{"lean":"psychology","conviction":"high","focus":["tournament_stage"],"force_psychology":false,"force_data":false}'
            ]
        )
    )
    note = parser.parse("今晚反着来，欧冠淘汰赛感觉拜仁稳一些。", date="2026-04-29")
    assert note.parsed_tags.lean == "psychology"
    assert note.parsed_tags.conviction == "high"
    assert note.parsed_tags.focus == ["tournament_stage"]
    assert note.parse_method == "llm"


def test_parser_regex_fallback_when_llm_fails() -> None:
    note = InspirationParser(llm=FakeLLMCompleter(responses=["not json"])).parse(
        "反着来，淘汰赛风险大", date="2026-04-29"
    )
    assert note.parsed_tags.lean == "psychology"
    assert "tournament_stage" in note.parsed_tags.focus
    assert note.parse_method == "regex_fallback"


def test_regex_detects_force_flags() -> None:
    note = InspirationParser(llm=FakeLLMCompleter(responses=["bad"])).parse(
        "今天必须心理，强制心理层", date="2026-04-29"
    )
    assert note.parsed_tags.force_psychology is True


def test_default_neutral_when_unparseable_text() -> None:
    note = InspirationParser(llm=FakeLLMCompleter(responses=["bad"])).parse(
        "Nothing relevant.", date="2026-04-29"
    )
    assert note.parsed_tags.lean == "neutral"
    assert note.parsed_tags.conviction == "medium"


def test_store_round_trip(tmp_path: Path) -> None:
    store = InspirationStore(base_dir=tmp_path)
    tags = InspirationTags(
        lean="data", conviction="medium", focus=[], force_psychology=False, force_data=False
    )
    store.write_raw(date="2026-04-29", text="abc")
    store.write_parsed(
        date="2026-04-29",
        tags=tags,
        raw_text="abc",
        parse_method="llm",
        timestamp="2026-04-29T14:00:00Z",
    )
    note = store.read(date="2026-04-29")
    assert note is not None
    assert note.raw_text == "abc"
    assert note.parsed_tags == tags
