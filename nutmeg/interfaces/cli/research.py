"""CLI for the JCZQ board research bridge."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import typer

import nutmeg.interfaces.cli as _cli
from nutmeg.decision.research_runner import _claude_cli as _claude
from nutmeg.decision.research_runner import _cli_fulfill as _fulfill

research_app = typer.Typer(help="竞彩全板深研桥（headless）")
_cli.app.add_typer(research_app, name="research")
_DAY = typer.Option(..., "--day")
_JCZQ_DIR = typer.Option(Path(".nutmeg-data/jczq"), "--jczq-dir")
_DATA_DIR = typer.Option(Path(".nutmeg-data"), "--data-dir")


def _board_matches(day: str, data_dir: Path) -> list[dict]:
    from nutmeg.config.settings import AppSettings
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.ingest.sporttery import parse_sporttery_markets
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.product.repository import ProductReadRepository

    data_dir = Path(data_dir).resolve()
    kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
    kernel.initialize()
    market_path = data_dir / "jczq" / "daily" / day / "sporttery_markets.json"
    market_doc = json.loads(market_path.read_text(encoding="utf-8"))
    code_by_match: dict[str, str] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for parsed in parse_sporttery_markets(market_doc, business_date=day):
            match_id = uow.identity.entity_by_external_id(
                EntityType.MATCH,
                provider=parsed.provider,
                external_id=parsed.external_id,
            )
            if match_id:
                code_by_match[match_id] = parsed.match_no

    start = datetime.fromisoformat(f"{day}T00:00:00+08:00").astimezone(UTC)
    rows = ProductReadRepository(kernel.engine, kernel.paths.analytics).board_matches(
        start.isoformat(),
        (start + timedelta(days=2)).isoformat(),
        as_of=datetime.now(UTC).isoformat(),
    )
    return [
        {**row, "board_code": code_by_match[row["match_id"]]}
        for row in rows
        if row["match_id"] in code_by_match
    ]


def _profile_lookup(jczq_dir: Path, day: str):
    from nutmeg.decision.entities import profiles_for_board
    from nutmeg.decision.store import DecisionStore

    board_path = Path(jczq_dir) / "daily" / day / "jczq-legs-base.json"
    # 竞彩板缺（WAF 降级）时足彩并集池照样要研究：没有板就没有竞彩画像可查（2026-09-28）。
    board = (json.loads(board_path.read_text(encoding="utf-8"))
             if board_path.exists() else {"legs": {}})
    legs = list(board["legs"].values())
    teams = [team for leg in legs for team in (leg.get("home_team"), leg.get("away_team")) if team]
    profiles = profiles_for_board(
        DecisionStore(Path(jczq_dir) / "decision"),
        [str(leg.get("competition") or "") for leg in legs],
        teams,
    )
    notes_by_name = {
        item["board_name"]: "；".join(
            str(note.get("note") or "") for note in item.get("profile_notes") or []
        )
        for item in profiles["teams"]
    }
    by_match = {
        leg["match_id"]: {
            "home": notes_by_name.get(leg.get("home_team"), ""),
            "away": notes_by_name.get(leg.get("away_team"), ""),
        }
        for leg in legs
    }
    return lambda match_id: by_match.get(match_id, {})


@research_app.command("board")
def board(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    data_dir: Path = _DATA_DIR,
) -> None:
    from nutmeg.decision.jczq_board import build_board_legs

    doc = build_board_legs(day=day, matches=_board_matches(day, data_dir), jczq_dir=jczq_dir)
    typer.echo(f"{day} 板面 {len(doc['legs'])} 场 → jczq-legs-base.json（price_only）")


@research_app.command("run")
def run(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    data_dir: Path = _DATA_DIR,
    code: str | None = typer.Option(None, "--code"),
    budget: int | None = typer.Option(None, "--budget"),
    concurrency: int = typer.Option(2, "--concurrency", min=1),
) -> None:
    from nutmeg.decision.research_runner import RESEARCH_DAILY_BUDGET, run_day

    report = run_day(
        day=day,
        jczq_dir=jczq_dir,
        data_dir=data_dir,
        claude=_claude,
        fulfill=_fulfill,
        profile=_profile_lookup(jczq_dir, day),
        budget=budget if budget is not None else RESEARCH_DAILY_BUDGET,
        code=code,
        concurrency=concurrency,
    )
    for row in report["matches"]:
        suffix = f" {row['seconds']}s" if "seconds" in row else ""
        typer.echo(f"  {row['code']} {row['status']}{suffix}")
    typer.echo(
        f"used_attempts={report['used_attempts']} written={report['written']}"
    )
    if report["written"]:
        # 定时 sweep 只跑 `research run`：新研究落盘后若不重建 Read，F9 读不到该场、
        # 义务永远履约不了（2026-09-26 017–025 全漏）
        _refresh(day, data_dir)


def _refresh(day: str, data_dir: Path) -> None:
    from nutmeg.decision.judgment_projection import run_projection
    from nutmeg.decision.pool import refresh_day
    from nutmeg.decision.rsi_wiring import _cli_invoke

    summary = refresh_day(
        day=day,
        data_dir=Path(data_dir),
        made_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        submit=lambda path: _cli_invoke(["decision-read", "--reads-file", str(path)]),
        # 判断唯一事实 P0：每次刷新后落内核 vs 文件比对（judgment-projection.json）
        project=lambda **board: run_projection(Path(data_dir), **board),
    )
    jczq = summary["jczq"] or {"reads": 0, "submitted": 0}
    typer.echo(f"并集池刷新：竞彩 Read {jczq['reads']} 条（交本体 {jczq['submitted']}）")
    _echo_projection(jczq, indent="  ")
    for issue, row in summary["zucai"].items():
        typer.echo(f"  足彩 {issue}：Read {row['reads']} 条（交本体 {row['submitted']}）")
        _echo_projection(row, indent="    ")
    _read_pending(data_dir)


def _read_pending(data_dir: Path) -> None:
    """研究刚落盘：让读者 B 趁开球前读完（2026-10-05）。侧车已在的跳过；失败不挡刷新。"""
    from nutmeg.decision.rubric_reader import pending_research, read_many

    try:
        paths = pending_research(Path(data_dir))
        if not paths:
            return
        out = read_many(paths, workers=4)
    except Exception as exc:  # noqa: BLE001 读者 B 是旁路，不能拖垮刷新
        typer.echo(f"⚠️读者 B 开球前补读失败（不影响刷新）：{exc}", err=True)
        return
    typer.echo(f"读者 B 开球前补读：读 {len(out['done'])} · 失败 {len(out['failed'])}"
               f"（待读 {len(paths)} 份）")


def _echo_projection(row: dict, *, indent: str) -> None:
    if row.get("projection"):
        typer.echo(f"{indent}投影比对：{row['projection']}")
    if row.get("projection_error"):
        typer.echo(f"{indent}⚠️投影比对失败（不影响刷新）：{row['projection_error']}")


@research_app.command("refresh")
def refresh(day: str = _DAY, data_dir: Path = _DATA_DIR) -> None:
    """并集样本池刷新（Jun 2026-09-27）：两渠道重建 Read，未开球场次自动交本体。"""
    _refresh(day, data_dir)


@research_app.command("intake")
def intake(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    write: bool = typer.Option(False, "--write"),
) -> None:
    from nutmeg.decision.jczq_reads import intake_board

    if not (Path(jczq_dir) / "daily" / day / "jczq-legs-base.json").is_file():
        typer.echo(f"{day} 无竞彩板面（空盘）：入库跳过")
        return
    report = intake_board(day=day, jczq_dir=jczq_dir, write=write)
    suffix = "" if write else "（预演，未写）"
    typer.echo(f"入库 {len(report['ok'])} 场: {' '.join(report['ok'])}{suffix}")
    for code, messages in report["failed"].items():
        typer.echo(f"  ✗ {code}: {'; '.join(messages)}")


@_cli.app.command("jczq-build-reads")
def jczq_build_reads(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    made_at: str | None = typer.Option(None, "--made-at"),
) -> None:
    from nutmeg.decision.jczq_reads import build_jczq_reads

    if not (Path(jczq_dir) / "daily" / day / "jczq-legs-base.json").is_file():
        # 空盘日：竞彩没有 Read 可建；足彩并集池照常刷新（`research run` 已刷过一次，幂等）
        typer.echo(f"{day} 无竞彩板面（空盘）：竞彩 Read 跳过，只刷新并集池")
        _refresh(day, Path(jczq_dir).parent)
        return
    reads = build_jczq_reads(
        day=day,
        jczq_dir=jczq_dir,
        made_at=made_at or datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    typer.echo(f"{day} 草稿 Read {len(reads)} 条 → daily/{day}/reads.json")
    # 判断唯一事实 P2（2026-10-01）：建完就交本体、再从内核投影覆盖文件，
    # 不再有手工 decision-read 这一步
    _refresh(day, Path(jczq_dir).parent)


@_cli.app.command("jczq-combos")
def jczq_combos(
    day: str = _DAY,
    jczq_dir: Path = _JCZQ_DIR,
    max_legs: int = typer.Option(4, "--max-legs", min=2),
    max_notes: int = typer.Option(4, "--max-notes", min=1),
    top: int = typer.Option(10, "--top", min=1),
) -> None:
    """竞彩只放判断腿（Jun 2026-09-27）：深研过的未开球场次，按判断概率排序，不设赔率目标。"""
    from nutmeg.decision.jczq_combos import enumerate_combos, judgment_legs

    legs = judgment_legs(day=day, jczq_dir=jczq_dir,
                         now=datetime.now().astimezone().isoformat(timespec="seconds"))
    typer.echo(f"{day} 判断腿 {len(legs)} 条（仅深研且未开球；无总进球腿）")
    for leg in legs:
        b, p = leg["belief"], leg["prior"]
        moved = max(abs(b[k] - p[k]) for k in b) * 100
        typer.echo(f"  {leg['code']} {leg['name']} 判断 主{b['home']*100:.1f}/平{b['draw']*100:.1f}"
                   f"/客{b['away']*100:.1f}（偏离市场 {moved:.1f}pp）")
    for combo in enumerate_combos(legs, max_legs=max_legs, max_notes=max_notes, top=top):
        text = " + ".join(
            f"{leg['code']}{'让' + leg['line'] if leg['market'] == 'hhad' else ''}:{leg['faces']}"
            for leg in combo["legs"])
        typer.echo(f"P={combo['p']*100:5.1f}%  {combo['notes']}注  全中赔率≈{combo['odds']:.2f}"
                   f"  每元回报≈{combo['return_per_yuan']:.2f}  {text}")


@research_app.command("signals")
def signals(day: str = _DAY, data_dir: Path = _DATA_DIR) -> None:
    """信号面板（Jun 2026-09-27）：研究原判、主循环改判、两渠道研究分歧、未定价事件、改判得失。"""
    from nutmeg.decision.signals import write_signals

    path = write_signals(day=day, data_dir=Path(data_dir))
    typer.echo(path.read_text(encoding="utf-8"))
    typer.echo(f"→ {path}")


@research_app.command("override")
def override(
    day: str = _DAY,
    code: str = typer.Option(..., "--code", help="竞彩编号如 周日003，或足彩 26133-04"),
    note: str = typer.Option(..., "--note", help="改判理由（必填，自由文本）"),
    reason: str | None = typer.Option(
        None, "--reason", help="封闭理由：new_official_info | evidence_tier_too_low | priced_in "
                               "| research_contradiction | market_only"),
    market: bool = typer.Option(False, "--market", help="回到市场（不拨动）"),
    items_json: str | None = typer.Option(
        None, "--items-json", help="改判落到 rubric 项：{\"F_absence_home\": {\"p\": 0.9, "
                                   "\"source\": …, \"captured_at\": …}, …}"),
    tilt_json: str | None = typer.Option(None, "--tilt-json",
                                         help="旧式 tilt JSON（只给无 rubric 的研究）"),
    data_dir: Path = _DATA_DIR,
) -> None:
    """主循环改判：记进 overrides.jsonl，研究原件不动（2026-09-27）；记完立刻刷新，
    改判随即成为内核里一条 kind=override 的新 revision（判断唯一事实 P1，2026-10-01）。
    2026-10-02 判断 rubric r1：有 rubric 的研究，改判必须落到项（--items-json + --reason）
    或 --market。"""
    from nutmeg.decision.overrides import record_override

    given = sum(1 for x in (market, items_json is not None, tilt_json is not None) if x)
    if given != 1:
        raise typer.BadParameter("--market / --items-json / --tilt-json 三选一")
    refresh_for = day
    kickoff = None
    if "-" in code and code[:5].isdigit():
        issue, no = code.split("-", 1)
        zdir = Path(data_dir) / "zucai"
        path = zdir / f"{issue}-research-m{int(no)}.json"
        prior = json.loads((zdir / f"{issue}-store-ids.json").read_text("utf-8"))[
            str(int(no))]["fair"]
        issue_doc = json.loads((zdir / f"{issue}-issue.json").read_text("utf-8"))
        refresh_for = str(issue_doc.get("sale_deadline") or "")[:10] or day
        for m in issue_doc.get("matches") or []:
            if str(m.get("match_no")) == str(int(no)) and m.get("kickoff_bj"):
                kickoff = str(m["kickoff_bj"]).replace(" ", "T")
    else:
        day_dir = Path(data_dir) / "jczq" / "daily" / day
        path = day_dir / f"research-{code}.json"
        leg = json.loads((day_dir / "jczq-legs-base.json").read_text("utf-8"))["legs"][code]
        prior, kickoff = leg["fair"], leg.get("kickoff_bj")
    try:
        row = record_override(
            path, tilt=json.loads(tilt_json) if tilt_json else None,
            items=json.loads(items_json) if items_json else None, reason=reason,
            to_market=market, note=note, kickoff=kickoff,
            at=datetime.now().astimezone().isoformat(timespec="seconds"),
            judge="claude-main-loop", prior=prior)
    except ValueError as exc:
        typer.echo(f"override error: {exc}")
        raise typer.Exit(code=2) from exc
    typer.echo(f"已记改判 {code}［{row['reason']}］：研究原判 {row['research_belief']} → "
               f"终判 {row['final_belief']}")
    _refresh(refresh_for, data_dir)


@research_app.command("verdict")
def verdict(day: str = _DAY, data_dir: Path = _DATA_DIR) -> None:
    """当日判决参考页（Jun 2026-09-27）：主版 12:30 / 晚版 18:45 自动生成，供人工最终裁决。"""
    from nutmeg.decision.rsi_wiring import _cli_invoke
    from nutmeg.decision.verdict_page import write_verdict

    path = write_verdict(day=day, data_dir=Path(data_dir), invoke=_cli_invoke)
    typer.echo(f"判决参考页 → {path}")
