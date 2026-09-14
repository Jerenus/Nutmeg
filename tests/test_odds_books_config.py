"""单测书目口径配置 —— 判断层输入口径必须可审计，且损坏时不得静默退化。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nutmeg.config.odds_books import (
    OddsBooksConfigError,
    load_odds_books_config,
)


def _write(tmp_path, body: str) -> str:
    path = tmp_path / "odds_books.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


_GOOD = """
titan007:
  excluded:
    - {id: "1129", name: Lottery Official}
  sharp:
    - {id: "177", name: Pinnacle}
    - {id: "545", name: Crown}
  thresholds:
    min_consensus_books: 3
    kickoff_tolerance_minutes: 30
    min_euro_books: 5
"""


def test_shipped_config_matches_what_the_code_expects():
    """仓内 config/odds_books.yaml 必须可加载——它是生产口径。"""
    cfg = load_odds_books_config()
    assert "1129" in cfg.excluded_ids      # 竞彩官方永远排除
    assert "177" in cfg.sharp_ids          # Pinnacle 永远在锐盘里
    assert not (cfg.excluded_ids & cfg.sharp_ids)
    assert cfg.min_consensus_books >= 1
    assert cfg.kickoff_tolerance > timedelta(0)


def test_loads_ids_names_and_thresholds(tmp_path):
    cfg = load_odds_books_config(_write(tmp_path, _GOOD))
    assert cfg.excluded_ids == frozenset({"1129"})
    assert cfg.sharp_ids == frozenset({"177", "545"})
    assert cfg.names_by_id["177"] == "Pinnacle"
    assert cfg.kickoff_tolerance == timedelta(minutes=30)


def test_missing_file_raises_rather_than_falling_back(tmp_path):
    """用沉默的内置默认值顶替读不到的口径文件 = 让判断层拿着没人审过的书目跑。"""
    with pytest.raises(OddsBooksConfigError):
        load_odds_books_config(str(tmp_path / "nope.yaml"))


def test_a_book_in_both_lists_is_a_contradiction(tmp_path):
    body = _GOOD.replace('- {id: "177", name: Pinnacle}',
                         '- {id: "1129", name: Lottery Official}')
    with pytest.raises(OddsBooksConfigError, match="自相矛盾"):
        load_odds_books_config(_write(tmp_path, body))


def test_empty_sharp_list_is_refused(tmp_path):
    body = """
titan007:
  excluded:
    - {id: "1129", name: Lottery Official}
  sharp: []
  thresholds:
    min_consensus_books: 3
    kickoff_tolerance_minutes: 30
    min_euro_books: 5
"""
    with pytest.raises(OddsBooksConfigError, match="为空"):
        load_odds_books_config(_write(tmp_path, body))


def test_missing_threshold_is_refused(tmp_path):
    body = _GOOD.replace("    min_euro_books: 5\n", "")
    with pytest.raises(OddsBooksConfigError, match="thresholds"):
        load_odds_books_config(_write(tmp_path, body))


def test_selection_built_from_config_excludes_the_lottery_line():
    from nutmeg.data.titan007 import Titan007BookQuote
    from nutmeg.services.jczq_titan007_odds import all_books, sharp_books

    def _q(cid: str) -> Titan007BookQuote:
        return Titan007BookQuote(
            company_id=cid, company_name="x",
            opening={"home": 2.0, "draw": 3.0, "away": 4.0},
            current={"home": 2.0, "draw": 3.0, "away": 4.0},
            updated_at=None,
        )

    for selection in (sharp_books(), all_books()):
        assert selection.accepts(_q("1129")) is False   # 竞彩官方
        assert selection.accepts(_q("432")) is False    # 香港马会(彩池)
        assert selection.accepts(_q("2")) is False      # Betfair(交易所)
    assert sharp_books().accepts(_q("177")) is True     # Pinnacle
    assert sharp_books().accepts(_q("9999")) is False   # 噪声盘不在白名单
    assert all_books().accepts(_q("9999")) is True      # all 口径收
