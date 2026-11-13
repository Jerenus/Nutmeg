"""足彩人群偏离笔记本：`nutmeg crowd fetch/backfill/scan/map/settle/nominate/sign`。

设计见 docs/superpowers/specs/2026-10-07-zucai-crowd-notebook-design.md。全部只追加、幂等；
判决不在这里——CR 假说的结账/判决/上线走 `nutmeg rsi grade|verdict|deploy`。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli

crowd_app = typer.Typer(help="足彩人群偏离笔记本：市场底座 / 线索 / 结算 / 提名 / 签字")
_cli.app.add_typer(crowd_app, name="crowd")

_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")
_ISSUE = typer.Option(..., "--issue")
_REGISTRY = typer.Option(Path("experiments/registry"), "--registry-dir")
_CANDIDATES = typer.Option(Path("experiments/candidates"), "--candidates-dir")
SPEC = "docs/superpowers/specs/2026-10-07-zucai-crowd-notebook-design.md"
FALSIFIER = {"metric": "crowd_prize_pct_per_face", "stratum": "zucai", "n_min": 30,
             "bound": "ci_lower", "threshold_pp": 0.0, "direction": "lt_means_falsified"}
STOP_RULE = "前瞻满 30 期判；60 期仍跨线则提 retire"


def _fetcher():
    return None            # None = crowd_source 默认联网抓取；测试替换


def _refresh_prizes(zdir: Path) -> None:
    from nutmeg.gym.prizes import build_prize_cache

    build_prize_cache(zdir)


def _zdir(data_dir: Path) -> Path:
    return Path(data_dir) / "zucai"


def _deployed(data_dir: Path, exp_ids: list[str]) -> set[str]:
    if not exp_ids:
        return set()
    from nutmeg.interfaces.cli.rsi import _kernel
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    with OntologyUnitOfWork(_kernel(data_dir).engine) as uow:
        return {e for e in exp_ids
                if (d := uow.rsi.latest_deployment(e)) is not None and d.decision == "deploy"}


def _readings(data_dir: Path, exp_ids: list[str]) -> dict[str, str]:
    if not exp_ids:
        return {}
    from nutmeg.interfaces.cli.rsi import _kernel
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    out = {}
    with OntologyUnitOfWork(_kernel(data_dir).engine) as uow:
        for exp in exp_ids:
            parts = []
            for mode in ("replay", "prospective"):
                g = uow.rsi.latest_grade(exp, mode=mode, stratum="zucai")
                parts.append(f"{mode} 未结账" if g is None else
                             f"{mode} n={g.n_cum} {g.metric_value_pp:+.2f}% "
                             f"CI[{g.ci_low_pp:+.2f}, {g.ci_high_pp:+.2f}]")
            out[exp] = "；".join(parts)
    return out


def crowd_map_text(data_dir: Path, issue: str, registry_dir: Path) -> str:
    """初稿复用：人群地图 markdown。"""
    from nutmeg.decision.crowd_clues import load_registry, read_rows, render_map
    from nutmeg.decision.crowd_source import load_board

    docs = load_registry(registry_dir)
    zdir = _zdir(data_dir)
    return render_map(issue, read_rows(zdir, issue), _readings(data_dir, sorted(docs)),
                      has_board=load_board(zdir, issue) is not None, n_registered=len(docs))


@crowd_app.command("fetch")
def fetch(issue: str = _ISSUE, data_dir: Path = _DATA_DIR) -> None:
    """拉 zgzcw 快照追加到 `<期>-zgzcw.json`。"""
    from nutmeg.decision.crowd_source import fetch_issue

    try:
        path = fetch_issue(_zdir(data_dir), issue, fetcher=_fetcher())
    except (OSError, ValueError) as exc:
        typer.echo(f"crowd fetch {issue} 失败：{exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(f"{issue} 市场底座 → {path}")


@crowd_app.command("backfill")
def backfill_cmd(issue_from: str = typer.Option(..., "--from"),
                 issue_to: str = typer.Option(..., "--to"), data_dir: Path = _DATA_DIR) -> None:
    """官方奖金有记录的期逐期回取（已有快照跳过，间隔 1 秒）。"""
    from nutmeg.decision.crowd_source import backfill
    from nutmeg.gym.prizes import load_prizes

    zdir = _zdir(data_dir)
    issues = sorted(i for i in load_prizes(zdir) if issue_from <= i <= issue_to)
    out = backfill(zdir, issues, fetcher=_fetcher())
    counts = {k: sum(1 for v in out.values() if v.startswith(k)) for k in ("ok", "skip", "fail")}
    typer.echo(f"回填 {len(issues)} 期：新取 {counts['ok']} / 已有 {counts['skip']} / "
               f"失败 {counts['fail']}")
    for issue, status in out.items():
        if status.startswith("fail"):
            typer.echo(f"  {issue} {status}")


def _pm_summary(label: str, path) -> str:
    from nutmeg.decision.crowd_polymarket import SHOW_MIN_VOLUME
    from nutmeg.decision.files import read_json

    if path is None:
        return f"{label}: 无场次（未写）"
    snaps = (read_json(path, {}) or {}).get("snapshots") or []
    rows = (snaps[-1].get("rows") if snaps else None) or {}
    liquid = sum(1 for r in rows.values() if (r.get("volume") or 0) >= SHOW_MIN_VOLUME)
    text = f"{label}: 对上 {len(rows)} 场（有量 ≥$20k {liquid} 场）→ {path}"
    cn = dict(home="主", draw="平", away="客")
    for key in sorted(rows, key=lambda k: rows[k].get("rank") or 99):
        money = rows[key].get("money_to") or {}
        if not money and not rows[key].get("lopsided"):
            continue
        bits = []
        if money.get("face"):
            bits.append(f"钱→{cn[money['face']]} ${money['usd'] / 1000:.1f}k")
        if money.get("against"):
            bits.append(f"反{cn[money['against']]} ${-money['against_usd'] / 1000:.1f}k")
        if rows[key].get("lopsided"):
            bits.append("⚑单向价不动（富勒姆型形状）")
        text += f"\n   场{key}: " + "，".join(bits)
    return text


@crowd_app.command("polymarket")
def polymarket_cmd(issue: str | None = typer.Option(None, "--issue"),
                   day: str | None = typer.Option(None, "--day",
                                                  help="竞彩当日板 + 当天截止的足彩期次"),
                   flow: bool = typer.Option(False, "--flow",
                                             help="有量的场另取三个市场的逐笔成交：钱去了哪一面"
                                                  "（每场 3 次 data-api 请求，出包时用）"),
                   data_dir: Path = _DATA_DIR) -> None:
    """Polymarket 关注度快照（2026-10-09，只读公开接口）：成交量 / 三向归一价 / 与市场基线差 /
    本板名次，追加到 `<期>-polymarket.json` / `daily/<日>/polymarket.json`。只展示不拨动。
    `--flow`（2026-10-18）：分市场量 + 逐笔方向 → 行上 `flow` / `money_to` / `lopsided`。"""
    from datetime import datetime

    from nutmeg.data import polymarket as pm
    from nutmeg.decision.bj_time import BJ
    from nutmeg.decision.crowd_polymarket import snapshot_day, snapshot_issue

    if not issue and not day:
        raise typer.BadParameter("需要 --issue 或 --day")
    now = datetime.now(BJ).isoformat(timespec="seconds")
    try:
        if issue:
            labelled = [(f"足彩 {issue}", snapshot_issue(Path(data_dir), issue,
                                                       fetch=pm.default_fetch, now=now,
                                                       with_flow=flow))]
        else:
            out = snapshot_day(Path(data_dir), day, fetch=pm.default_fetch, now=now,
                               with_flow=flow)
            labelled = [(f"竞彩 {day}", out["jczq"]),
                        *((f"足彩 {k}", v) for k, v in out["zucai"].items())]
    except Exception as exc:  # noqa: BLE001 —— 网络/接口变化：失败要看得见，不当成空结果
        typer.echo(f"crowd polymarket 失败：{exc!r}"[:300])
        raise typer.Exit(code=1) from exc
    for label, path in labelled:
        typer.echo(_pm_summary(label, path))


@crowd_app.command("polymarket-backfill")
def polymarket_backfill_cmd(issue_from: str = typer.Option(..., "--from"),
                            issue_to: str = typer.Option(..., "--to"),
                            data_dir: Path = _DATA_DIR) -> None:
    """历史期次的 Polymarket 关注度（已结束对阵的终场总成交，写 `source=closed_backfill` 快照）。

    供人群假说回放用：终场成交与赛前成交口径不同，所以触发条件用期内名次 `pm_rank`。"""
    from datetime import datetime

    from nutmeg.data import polymarket as pm
    from nutmeg.decision.bj_time import BJ
    from nutmeg.decision.crowd_polymarket import backfill

    zdir = _zdir(data_dir)
    # 期次文件 26070 起才有；更早的期用 zgzcw 快照对号（人群回放块 26035–26089）
    stems = {p.name.split("-")[0] for pattern in ("*-issue.json", "*-zgzcw.json")
             for p in zdir.glob(pattern)}
    issues = sorted(i for i in stems if i.isdigit() and issue_from <= i <= issue_to)
    now = datetime.now(BJ).isoformat(timespec="seconds")
    out = backfill(Path(data_dir), issues, fetch=pm.default_fetch, now=now)
    matched = sum(out.values())
    typer.echo(f"回补 {len(out)} 期，对上 {matched} 场（平均每期 "
               f"{matched / max(len(out), 1):.1f} / 14）")


@crowd_app.command("scan")
def scan_cmd(issue: str = _ISSUE, registry_dir: Path = _REGISTRY,
             data_dir: Path = _DATA_DIR) -> None:
    """已登记 CR 假说的 trigger 跑过最后一张快照 → 线索。"""
    from nutmeg.decision.crowd_clues import load_registry, scan

    docs = load_registry(registry_dir)
    new = scan(_zdir(data_dir), issue, docs=docs, deployed=_deployed(data_dir, sorted(docs)))
    typer.echo(f"{issue} 新线索 {len(new)} 条（已登记 CR {len(docs)} 条）")


@crowd_app.command("map")
def map_cmd(issue: str = _ISSUE, registry_dir: Path = _REGISTRY,
            data_dir: Path = _DATA_DIR) -> None:
    """人群地图 markdown（初稿同款）。"""
    typer.echo(crowd_map_text(data_dir, issue, registry_dir))


@crowd_app.command("settle")
def settle_cmd(issue: str | None = typer.Option(None, "--issue"),
               pending: bool = typer.Option(False, "--pending",
                                            help="结算所有有线索、赛果已出、尚未结算的期"),
               data_dir: Path = _DATA_DIR) -> None:
    """赛后：刷官方奖金缓存，给线索写 outcome 与 acted。"""
    from nutmeg.decision.betslip import registry_path
    from nutmeg.decision.crowd_clues import read_rows, settle, ticket_faces
    from nutmeg.gym.prizes import load_prizes

    zdir = _zdir(data_dir)
    if issue is None and not pending:
        typer.echo("给 --issue 或 --pending")
        raise typer.Exit(code=2)
    try:
        _refresh_prizes(zdir)
    except Exception as exc:  # noqa: BLE001 —— 刷不到就用已有缓存
        typer.echo(f"⚠️官方奖金缓存未刷新：{exc!r}"[:200])
    prizes = load_prizes(zdir)
    targets = [issue] if issue else sorted(
        p.name.split("-")[0] for p in zdir.glob("*-clues.jsonl")
        if not any(r.get("kind") == "settle" for r in read_rows(zdir, p.name.split("-")[0])))
    if not targets:
        typer.echo("无待结算的期")
    for target in targets:
        results = str((prizes.get(target) or {}).get("results") or "").split()
        rows = settle(zdir, target, results=results if len(results) == 14 else None,
                      tickets=ticket_faces(registry_path(data_dir), target))
        typer.echo(f"{target} 结算 {len(rows)} 条" if rows else f"{target} 赛果未出或已结")


@crowd_app.command("nominate")
def nominate_cmd(issue_from: str = typer.Option(..., "--from"),
                 issue_to: str = typer.Option(..., "--to"),
                 write: bool = typer.Option(False, "--write", help="写候选文件；不给只打印"),
                 registry_dir: Path = _REGISTRY, candidates_dir: Path = _CANDIDATES,
                 data_dir: Path = _DATA_DIR) -> None:
    """扫 48 桶找奖金残差显著的人群偏离 → 候选（只提名，不登记）。"""
    from nutmeg.decision.crowd_clues import load_registry
    from nutmeg.decision.crowd_model import load_observations, nominate

    obs = load_observations(_zdir(data_dir),
                            window={"issue_from": issue_from, "issue_to": issue_to})
    existing = {k: d["trigger"] for k, d in load_registry(registry_dir).items()}
    cands = nominate(obs, existing=existing)
    typer.echo(f"窗口 {issue_from}–{issue_to} 有效 {len(obs)} 期；扫 48 桶，"
               f"候选 {len(cands)} 条（48 桶在 5% 水平期望约 2.4 个假阳性）")
    candidates_dir = Path(candidates_dir)
    taken = {p.stem for p in candidates_dir.glob("CR-cand-*.json")}
    k = 1
    for c in cands:
        ev = c["evidence"]
        typer.echo(f"- {c['label_cn']}  z={ev['z']:.2f}  γ={ev['gamma_pct']:+.1f}%  "
                   f"CI{ev['ci_pct']}  n={ev['n']} 期  实开 {ev['hits']} 次")
        if not write:
            continue
        while f"CR-cand-{k}" in taken:
            k += 1
        candidates_dir.mkdir(parents=True, exist_ok=True)
        under = c["crowd_bias"] == "under"
        doc = {"exp_id": None, "tier": "deploy_eligible", "layer": "structural",
               "population": "zucai", "min_tier": "price_only", "label_cn": c["label_cn"],
               "claim": f"{c['label_cn']}：触发面开出时任九奖金{'高' if under else '低'}于"
                        f"市场意外度预期（γ{'>' if under else '<'}0）",
               "mechanism": "", "psychology": "", "trigger": c["trigger"],
               "crowd_bias": c["crowd_bias"], "falsifier": FALSIFIER,
               "window": {"issue_from": None, "issue_to": "26999"}, "replay_window": None,
               "stop_rule": STOP_RULE, "quota_slot": False, "buckets": [], "rule_ids": [],
               "examples": {"pos": [], "neg": []}, "source_doc": SPEC, "registered_at": None,
               "evidence": ev}
        path = candidates_dir / f"CR-cand-{k}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        taken.add(path.stem)
        typer.echo(f"  → {path}")


@crowd_app.command("sign")
def sign(candidate: Path, as_: str = typer.Option(..., "--as", help="CR<k>"),
         by: str = typer.Option(..., "--by"),
         from_issue: str = typer.Option(..., "--from-issue", help="前瞻窗口起点（下一期）"),
         replay_from: str = typer.Option(..., "--replay-from"),
         replay_to: str = typer.Option(..., "--replay-to"),
         registry_dir: Path = _REGISTRY, data_dir: Path = _DATA_DIR) -> None:
    """人签字：候选 → `experiments/registry/CR<k>.json` → `rsi register`。mechanism 必须先写。"""
    from nutmeg.interfaces.cli.rsi import register

    if not as_.startswith("CR"):
        typer.echo("--as 必须是 CR<k>")
        raise typer.Exit(code=1)
    doc = json.loads(Path(candidate).read_text("utf-8"))
    if not str(doc.get("mechanism") or "").strip():
        typer.echo("签字前先在候选里写 mechanism（为什么全国人群会这么偏）")
        raise typer.Exit(code=1)
    target = Path(registry_dir) / f"{as_}.json"
    if target.exists():
        typer.echo(f"{target} 已存在")
        raise typer.Exit(code=1)
    doc.update({"exp_id": as_, "registered_at": date.today().isoformat(),
                "window": {"issue_from": from_issue, "issue_to": "26999"},
                "replay_window": {"issue_from": replay_from, "issue_to": replay_to}})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        register(doc_path=target, by=by, data_dir=data_dir, fork_from=None, population=None,
                 window_from=None, prescreen=None, n_min=None, dry_run=False)
    except typer.Exit:
        target.unlink(missing_ok=True)
        raise
