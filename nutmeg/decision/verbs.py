"""五动词 CLI 实现(spec §3)。M0:sense 可跑(replay),余为骨架。

不动现有命令/launchd(M2 才切)。命令通过 cli/__init__ 的 @app.command 注册。
"""
from __future__ import annotations

from pathlib import Path


def run_sense(run_date: str, output_dir: Path, taken_at: str) -> str:
    # M1:用 sense_day(体彩+欧赔读时快照),欧赔是 CLV 先验锚——非 M0 的体彩-only。
    from nutmeg.decision.sense import sense_day
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = sense_day(run_date, output_dir=output_dir,
                  taken_at=taken_at, store=store)
    return f"decision-sense {run_date}: 入库 {n} 场 Match+体彩/欧赔 Snapshot"


def run_backfill(run_date: str, output_dir: Path, made_at: str) -> str:
    # 判读收尾:未判场补市场基线 shadow(belief=prior)。顺序纪律:须在 decision-read 之后。
    from nutmeg.decision.read_ingest import backfill_shadows
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = backfill_shadows(store, run_date=run_date, made_at=made_at)
    return f"decision-backfill {run_date}: 补 {n} 条市场基线 shadow"


def run_read_ingest(reads_file: Path, output_dir: Path) -> str:
    import json

    from nutmeg.decision.factors import load_seed_factors
    from nutmeg.decision.read_ingest import ingest_reads
    from nutmeg.decision.store import DecisionStore

    payloads = json.loads(Path(reads_file).read_text(encoding="utf-8"))
    store = DecisionStore(Path(output_dir) / "decision")
    # 词典：已落库 Factor 优先,否则种子
    factors = store.load(_factor_cls()) or load_seed_factors()
    errs = ingest_reads(payloads, store=store, factors=factors)
    ok = len(payloads) - len(errs)
    msg = f"decision-read: 摄取 {ok}/{len(payloads)} 条 Read"
    if errs:
        msg += " | 拒绝: " + "; ".join(errs)
    return msg


def _factor_cls():
    from nutmeg.decision.ontology import Factor
    return Factor


def run_capture_closing(run_date: str, output_dir: Path, taken_at: str) -> str:
    from nutmeg.decision.closing import capture_closing
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    n = capture_closing(run_date, output_dir=output_dir, taken_at=taken_at, store=store)
    return f"decision-capture-closing {run_date}: 收盘欧赔快照 {n} 条"


def run_reconcile(run_date: str, output_dir: Path, settled_at: str) -> str:
    from nutmeg.decision.reconcile import settle_day
    from nutmeg.decision.store import DecisionStore
    from nutmeg.services.jczq_results import OkoooJczqResultProvider

    store = DecisionStore(Path(output_dir) / "decision")
    try:
        results = OkoooJczqResultProvider().fetch_results(run_date)
    except Exception:  # noqa: BLE001 — 抓不到赛果 → 全 pending
        results = {}
    n = settle_day(store, run_date=run_date, results=results, settled_at=settled_at)
    return f"decision-reconcile {run_date}: 结算 {n} 条 Read"


def run_calibrate_panel(output_dir: Path, as_of: str) -> str:
    from nutmeg.decision.calibrate import (
        apply_verdicts,
        render_panel,
        run_calibrate,
    )
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    verdicts = run_calibrate(store, as_of=as_of)
    # 反积累免疫落地:把判决执行成 Factor 状态转换(转正/退休)+ 持久化。
    changes = apply_verdicts(store, verdicts)
    panel = render_panel(verdicts)
    out = Path(output_dir) / "decision" / f"calibration-panel-{as_of}.md"
    out.write_text(panel, encoding="utf-8")
    msg = f"decision-calibrate: {len(verdicts)} 因子判决 → {out}"
    if changes["promoted"] or changes["retired"]:
        msg += (f" | 转正 {changes['promoted']} 退休 {changes['retired']}")
    return msg
