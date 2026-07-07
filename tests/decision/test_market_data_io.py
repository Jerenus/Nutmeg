"""market_data 盘口快照 I/O — 回退链 + 快照防覆盖守卫。

2026-07-07 kernel 下葬:这 8 个测试从 tests/test_fcom500_jczq_board.py 原样迁入
(断言一字不动,import 改指 nutmeg.decision.market_data)——被测符号
fetch_sporttery_value_with_fallback / persist_sporttery_snapshot 是活生产代码
(decision-am 抓取底座),不能随僵尸测试文件陪葬。
离线 fixture:tests/fixtures/fcom500/jczq-list-20260611.html。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from nutmeg.decision import market_data
from nutmeg.services.jczq import JczqProviderError

_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "fcom500"


def _board_html() -> str:
    return (_FIXTURE_DIR / "jczq-list-20260611.html").read_text(encoding="utf-8")


class _StubProvider:
    """SportteryJczqCalculatorProvider 替身：按构造参数返回/抛错。"""

    def __init__(self, *, value=None, error: Exception | None = None):
        self._value = value
        self._error = error

    def fetch(self) -> dict:
        if self._error is not None:
            raise self._error
        return self._value


class _StubFcomClient:
    """Fcom500Client 替身：get() 永远返回 2026-06-11 fixture HTML。"""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url: str) -> str:
        return _board_html()


def _patch_fallback_deps(monkeypatch, *, provider, fcom_client=_StubFcomClient):
    monkeypatch.setattr(
        "nutmeg.services.jczq.SportteryJczqCalculatorProvider",
        lambda: provider,
    )
    monkeypatch.setattr("nutmeg.data.fcom500.Fcom500Client", fcom_client)


# ---------------------------------------------------------------------------
# 回退 helper
# ---------------------------------------------------------------------------


def test_fallback_passthrough_when_primary_healthy(monkeypatch) -> None:
    healthy = {"matchInfoList": [{"businessDate": "2026-06-11", "subMatchList": []}]}
    _patch_fallback_deps(monkeypatch, provider=_StubProvider(value=healthy))
    value, source = market_data.fetch_sporttery_value_with_fallback()
    assert source == "sporttery"
    assert value == healthy


def test_fallback_on_provider_error(monkeypatch) -> None:
    _patch_fallback_deps(
        monkeypatch, provider=_StubProvider(error=JczqProviderError("403"))
    )
    value, source = market_data.fetch_sporttery_value_with_fallback()
    assert source == "fcom500-fallback"
    nums = [
        s["matchNumStr"]
        for day in value["matchInfoList"]
        for s in day["subMatchList"]
    ]
    assert nums == ["周四001", "周四002"]


def test_fallback_on_degraded_empty_value(monkeypatch) -> None:
    # 6/11 形态：errorCode=0 但只有 vtoolsConfig、无 matchInfoList
    _patch_fallback_deps(
        monkeypatch, provider=_StubProvider(value={"vtoolsConfig": {}})
    )
    value, source = market_data.fetch_sporttery_value_with_fallback()
    assert source == "fcom500-fallback"
    assert value["nutmegSource"] == "fcom500-fallback"


def test_fallback_failure_reraises_primary_error(monkeypatch) -> None:
    class _DeadFcomClient(_StubFcomClient):
        def get(self, url: str) -> str:
            raise RuntimeError("market degraded")

    _patch_fallback_deps(
        monkeypatch,
        provider=_StubProvider(error=JczqProviderError("403 primary")),
        fcom_client=_DeadFcomClient,
    )
    with pytest.raises(JczqProviderError, match="403 primary"):
        market_data.fetch_sporttery_value_with_fallback()


# ---------------------------------------------------------------------------
# 快照防覆盖守卫（6/11 数据丢失 bug）
# ---------------------------------------------------------------------------

_NONEMPTY = {
    "matchInfoList": [
        {"businessDate": "2026-06-11", "subMatchList": [{"matchNumStr": "周四001"}]}
    ]
}
_EMPTY = {"vtoolsConfig": {"offLineSaleStatus": 1}}


def _read_snapshot(tmp_path):
    import json

    path = tmp_path / "daily" / "2026-06-11" / "sporttery_markets.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_guard_refuses_empty_over_nonempty(tmp_path) -> None:
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _NONEMPTY)
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _NONEMPTY  # 完好快照未被降级响应冲掉


def test_guard_allows_first_write_even_empty(tmp_path) -> None:
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _EMPTY


def test_guard_allows_nonempty_over_anything(tmp_path) -> None:
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _NONEMPTY)
    assert _read_snapshot(tmp_path) == _NONEMPTY


def test_guard_survives_corrupt_existing_snapshot(tmp_path) -> None:
    path = tmp_path / "daily" / "2026-06-11" / "sporttery_markets.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    market_data.persist_sporttery_snapshot("2026-06-11", tmp_path, _EMPTY)
    assert _read_snapshot(tmp_path) == _EMPTY  # 坏快照可被覆盖、不崩
