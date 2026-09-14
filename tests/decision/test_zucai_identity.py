# tests/decision/test_zucai_identity.py
"""足彩身份映射：按 canonical 键查，不按 fair 值猜。"""
import json

import pytest

from nutmeg.decision.zucai_identity import build_af_map, build_store_ids, write_store_ids


class _FakeIdentity:
    def __init__(self, mapping):
        self._mapping = mapping

    def entity_by_external_id(self, _entity_type, *, provider, external_id):
        return self._mapping.get((provider, external_id))


class _FakeConn:
    def __init__(self, snapshots):
        self._snapshots = snapshots

    def exec_driver_sql(self, _sql, params):
        match_id = params[0]
        value = self._snapshots.get(match_id)
        return _FakeResult((value,) if value else None)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeUow:
    def __init__(self, mapping, snapshots):
        self.identity = _FakeIdentity(mapping)
        self.connection = _FakeConn(snapshots)

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeKernel:
    engine = object()


@pytest.fixture
def prep(tmp_path):
    (tmp_path / "26122-prep-afternoon.json").write_text(json.dumps({"records": {
        "1": {"name": "西汉姆联-雷克斯", "match_date": "2026-09-12",
              "fair_had": {"home": 0.6, "draw": 0.22, "away": 0.18}},
        "2": {"name": "柏林联-沙尔克", "match_date": "2026-09-12",
              "fair_had": {"home": 0.41, "draw": 0.27, "away": 0.32}},
    }}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _patch(monkeypatch, mapping, snapshots):
    monkeypatch.setattr(
        "nutmeg.ontology.repository.unit_of_work.OntologyUnitOfWork",
        lambda _engine: _FakeUow(mapping, snapshots))


def test_store_ids_use_canonical_key_not_fair_matching(prep, monkeypatch):
    """同一支队同一天出现在竞彩板与足彩板时，只有 canonical 键能选对 Match。

    出生事故 26122：store-ids 靠**逐场比对 fair 值**反查，场 2/6/7 因为同队也在竞彩板上，
    全部挂到了竞彩的 Match 对象——三条 Read 落在了错误的实体上，而且完全静默。
    """
    mapping = {
        ("zucai-canonical", "M-2026-09-12-西汉姆联-雷克斯"): "match-zucai-1",
        ("zucai-canonical", "M-2026-09-12-柏林联-沙尔克"): "match-zucai-2",
    }
    _patch(monkeypatch, mapping, {"match-zucai-1": "snap-1", "match-zucai-2": "snap-2"})
    ids = build_store_ids("26122", prep, _FakeKernel())
    assert ids["2"]["match_id"] == "match-zucai-2"     # 不是竞彩那一个
    assert ids["2"]["canonical_id"] == "M-2026-09-12-柏林联-沙尔克"
    assert ids["1"]["snapshot_id"] == "snap-1"


def test_unmapped_match_is_explicit_not_skipped(prep, monkeypatch):
    """身份没对上必须显式留 None——静默跳过会让下游以为"该场没判读"。"""
    _patch(monkeypatch, {}, {})
    ids = build_store_ids("26122", prep, _FakeKernel())
    assert set(ids) == {"1", "2"}
    assert all(v["match_id"] is None for v in ids.values())
    assert "身份未对上" in write_store_ids("26122", prep, _FakeKernel())


def test_revision_prep_wins_over_afternoon(prep, monkeypatch):
    """18:30 位移复核后的盘优先——读判冻结用的是 revision 那一份。"""
    (prep / "26122-prep-revision.json").write_text(json.dumps({"records": {
        "1": {"name": "改过-对阵", "match_date": "2026-09-12", "fair_had": {}}}},
        ensure_ascii=False), encoding="utf-8")
    _patch(monkeypatch, {}, {})
    ids = build_store_ids("26122", prep, _FakeKernel())
    assert set(ids) == {"1"} and ids["1"]["name"] == "改过-对阵"


def test_af_map_keeps_unmapped_visible(prep):
    """af-map 缺映射必须缺着——夜账校准的既有纪律是显式跳过、禁按队名猜测补。"""
    out = build_af_map("26122", prep, {"1": 1563166})
    assert out["fixtures"] == {"1": 1563166}
    assert out["unmapped"] == ["2"]


def test_morning_only_prep_still_yields_store_ids(tmp_path, monkeypatch):
    """26123 出生事故:只跑过 11:00 早刷新时 store-ids 报"无备料记录"。"""
    (tmp_path / "26123-prep-morning.json").write_text(json.dumps({"records": {
        "1": {"name": "维拉-诺丁汉", "match_date": "2026-09-12",
              "fair_had": {"home": 0.43, "draw": 0.28, "away": 0.29}}}},
        ensure_ascii=False), encoding="utf-8")
    _patch(monkeypatch, {}, {})
    ids = build_store_ids("26123", tmp_path, _FakeKernel())
    assert set(ids) == {"1"} and ids["1"]["name"] == "维拉-诺丁汉"
