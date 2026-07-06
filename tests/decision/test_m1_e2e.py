"""M1 端到端:一天走完 感知→判读→收盘→结算→校准,CLV 真实算出。"""
import json

from nutmeg.decision.calibrate import run_calibrate
from nutmeg.decision.closing import capture_closing
from nutmeg.decision.factors import load_seed_factors
from nutmeg.decision.read_ingest import backfill_shadows, ingest_reads
from nutmeg.decision.reconcile import settle_day
from nutmeg.decision.sense import sense_day
from nutmeg.decision.store import DecisionStore

_BOARD = {"matchInfoList": [{"businessDate": "2026-07-08", "subMatchList": [{
    "matchStatus": "Selling", "businessDate": "2026-07-08", "matchNumStr": "周日092",
    "homeTeamAbbName": "墨", "awayTeamAbbName": "英",
    "had": {"h": "2.03", "d": "3.30", "a": "3.55"}}]}]}


class _MO:
    def __init__(self, fair):
        self.fair_probability = fair
        self.line = None


def test_m1_full_clv_loop(tmp_path, monkeypatch):
    daily = tmp_path / "daily" / "2026-07-08"
    daily.mkdir(parents=True)
    (daily / "sporttery_markets.json").write_text(json.dumps(_BOARD), encoding="utf-8")
    store = DecisionStore(tmp_path / "decision")

    import nutmeg.decision.sense as sense_mod
    monkeypatch.setattr(
        sense_mod, "_load_euro_bold_odds",
        lambda rd, od: {"周日092": {"match_winner":
                                    _MO({"home": 0.42, "draw": 0.28, "away": 0.30})}},
    )
    assert sense_day("2026-07-08", output_dir=tmp_path,
                     taken_at="2026-07-08T15:00:00+08:00", store=store) == 1

    # 手造一个签位激励偏平的 Read(锚欧赔 fair)
    ingest_reads([{
        "read_id": "R-092", "match_id": "M-2026-07-08-墨-英", "snapshot_id": "S-x",
        "made_at": "2026-07-08T15:00:00+08:00", "judge": "claude", "market": "had",
        "prior": {"home": 0.42, "draw": 0.28, "away": 0.30},
        "belief": {"home": 0.36, "draw": 0.34, "away": 0.30},
        "factors": [{"factor_id": "seeding_incentive", "direction": "draw",
                     "weight_pp": 6, "evidence": [{"url": "u", "quote": "q", "at": "a"}]}],
        "confidence": 3, "shadow": False}], store=store, factors=load_seed_factors())

    backfill_shadows(store, run_date="2026-07-08", made_at="2026-07-08T15:30:00+08:00")

    # 收盘欧赔朝平移动(与 belief 同向)
    def _closing_live(v, *, run_date, settings=None):
        return {"周日092": {"match_winner":
                            _MO({"home": 0.36, "draw": 0.35, "away": 0.29})}}

    capture_closing("2026-07-08", output_dir=tmp_path,
                    taken_at="2026-07-08T20:00:00+08:00", store=store,
                    live_fetcher=_closing_live)

    settle_day(store, run_date="2026-07-08",
               results={"周日092": {"score": "1:1", "had": "平"}},
               settled_at="2026-07-09T08:00:00+08:00")

    s = store.settlement_for("read", "R-092")
    assert s.outcome_90 == "draw"
    assert s.brier is not None and s.clv_pp is not None
    assert s.clv_pp > 0            # belief 朝平偏、收盘也朝平 → CLV 正(信息含量)

    verdicts = run_calibrate(store, as_of="2026-07-08")
    assert any(v.factor_id == "seeding_incentive" for v in verdicts)
