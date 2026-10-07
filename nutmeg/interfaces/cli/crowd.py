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
        typer.echo(f"- {c['label_cn']}  γ={ev['gamma_pct']:+.1f}%  CI{ev['ci_pct']}  n={ev['n']}")
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
                 window_from=None)
    except typer.Exit:
        target.unlink(missing_ok=True)
        raise
