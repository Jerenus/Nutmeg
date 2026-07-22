"""决策本体系统五动词 CLI(spec §3)。M0:sense 可 replay,余为骨架。

仿 cli/jczq.py 模式:@_cli.app.command 注册,由 cli/__init__ 底部 import 触发。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli

# 含嵌套 Path() 构造的 Option 提到模块级单例(避 B008,仿 jczq.py 的
# JCZQ_OUTPUT_DIR_OPTION 惯例);行为与内联默认完全一致。
_OUTPUT_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data/jczq"), "--output-dir")
_READS_FILE_OPTION = _cli.typer.Option(..., "--reads-file", help="Read JSON 数组文件")
_LEGS_FILE_OPTION = _cli.typer.Option(..., "--legs-file", help="投注腿 JSON 数组文件")
_ZUCAI_DIR_OPTION = _cli.typer.Option(
    Path(".nutmeg-data/zucai"), "--zucai-dir", help="zucai 源快照目录")
_ZUCAI_SCHEDULE_SOURCE_FILE_OPTION = _cli.typer.Option(
    None, "--schedule-source-file", help="赛程源文件(离线;省略则需 --live-fetch)")
_ZUCAI_ODDS_SOURCE_FILE_OPTION = _cli.typer.Option(
    None, "--odds-source-file", help="赔率源文件(离线;省略则需 --live-fetch)")


@_cli.app.command("decision-fetch")
def decision_fetch(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 数据自取:体彩盘口 + API-Football 国际欧赔 → 当日快照。"""
    from nutmeg.decision.fetch import fetch_day
    _cli.typer.echo(fetch_day(run_date, output_dir))


@_cli.app.command("decision-fetch-zucai")
def decision_fetch_zucai(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26091"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    slot: str = _cli.typer.Option("afternoon", "--slot", help="afternoon 或 revision"),
    live_fetch: bool = _cli.typer.Option(False, "--live-fetch"),
    schedule_source_url: str | None = _cli.typer.Option(None, "--schedule-source-url"),
    schedule_source_file: Path | None = _ZUCAI_SCHEDULE_SOURCE_FILE_OPTION,
    odds_source_url: str | None = _cli.typer.Option(None, "--odds-source-url"),
    odds_source_file: Path | None = _ZUCAI_ODDS_SOURCE_FILE_OPTION,
    run_date: str | None = _cli.typer.Option(None, "--run-date"),
    captured_at: str | None = _cli.typer.Option(None, "--captured-at"),
) -> None:
    """决策本体 · 传统足彩数据自取:赛程 + 赔率 → <issue>-issue.json + <issue>-odds*.json。"""
    from nutmeg.decision.fetch import fetch_zucai
    _cli.typer.echo(fetch_zucai(
        issue, zucai_dir, slot=slot, live_fetch=live_fetch,
        schedule_source_url=schedule_source_url,
        schedule_source_file=schedule_source_file,
        odds_source_url=odds_source_url, odds_source_file=odds_source_file,
        run_date=run_date, captured_at=captured_at,
    ))


@_cli.app.command("decision-sense")
def decision_sense(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 动词一:盘口快照 → Match+Snapshot 入库(replay)。"""
    from nutmeg.decision.verbs import run_sense
    _cli.typer.echo(run_sense(run_date, output_dir, taken_at))


@_cli.app.command("decision-read")
def decision_read(
    reads_file: Path = _READS_FILE_OPTION,
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 动词二:摄取 Claude 运行时产出的 Read(校验+落库)。

    NUTMEG_ONTOLOGY_V2=1 时提交到 kernel(ontology_adapter);否则旧 JSONL 路径不变。
    """
    from nutmeg.config.settings import get_settings

    if get_settings().ontology_v2:
        from nutmeg.decision.ontology_adapter import run_decision_read_v2
        _cli.typer.echo(run_decision_read_v2(reads_file, output_dir))
    else:
        from nutmeg.decision.verbs import run_read_ingest
        _cli.typer.echo(run_read_ingest(reads_file, output_dir))


@_cli.app.command("decision-backfill")
def decision_backfill(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    made_at: str = _cli.typer.Option(..., "--made-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 判读收尾:未判场补市场基线 shadow(须在 decision-read 之后)。"""
    from nutmeg.decision.verbs import run_backfill
    _cli.typer.echo(run_backfill(run_date, output_dir, made_at))


@_cli.app.command("decision-day-regime")
def decision_day_regime(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 日级盘面热度诊断:确定性算术攒样本,不进决策(decision-am 已内嵌)。"""
    from nutmeg.decision.verbs import run_day_regime
    _cli.typer.echo(run_day_regime(run_date, output_dir))


@_cli.app.command("decision-capture-closing")
def decision_capture_closing(
    run_date: str = _cli.typer.Option(..., "--run-date"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at"),
) -> None:
    """决策本体 · 收盘捕获:近开赛欧赔 → CLV 参照快照。"""
    from nutmeg.decision.verbs import run_capture_closing
    _cli.typer.echo(run_capture_closing(run_date, output_dir, taken_at))


@_cli.app.command("decision-express")
def decision_express(
    legs_file: Path = _LEGS_FILE_OPTION,
    channel: str = _cli.typer.Option("jczq", "--channel", help="jczq | shengfucai | renjiu"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    made_at: str = _cli.typer.Option(..., "--made-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 动词三:已声明投注腿 → Ticket(¥400 框架预算/串关算术)。

    legs = 主循环 Claude 判读产物(结构化 JSON 数组);express 只做确定性算术,不判玩法。
    """
    from nutmeg.decision.express import run_express
    _cli.typer.echo(run_express(legs_file, channel, output_dir, made_at))


@_cli.app.command("decision-report")
def decision_report(
    date: str = _cli.typer.Option(..., "--date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram",
                                                help="渲染后通过 Telegram 推送 PDF"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run",
                                      help="dry-run 时不真推送"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    """决策本体 · 清洁版 PDF 日报(判读/偏移/CLV + Ticket + 双轴校准)+ Telegram 推送。"""
    from nutmeg.decision.report import run_report
    result = run_report(
        date,
        output_dir,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
        stage="manual",
    )
    _emit_result(result, format=format)
    if not result.succeeded:
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-reconcile")
def decision_reconcile(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    settled_at: str = _cli.typer.Option(..., "--settled-at", help="ISO 结算时刻"),
) -> None:
    """决策本体 · 动词四:赛果+收盘 → Settlement(Brier+CLV)落库。"""
    from nutmeg.decision.verbs import run_reconcile
    _cli.typer.echo(run_reconcile(run_date, output_dir, settled_at))


@_cli.app.command("decision-sense-zucai")
def decision_sense_zucai(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26091"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    taken_at: str = _cli.typer.Option(..., "--taken-at", help="ISO 时刻"),
) -> None:
    """决策本体 · 传统足彩感知:zucai 14场+赔率 → 同一信念层 Match+Snapshot。"""
    from nutmeg.decision.verbs import run_sense_zucai
    _cli.typer.echo(run_sense_zucai(issue, output_dir, taken_at, zucai_dir))


@_cli.app.command("decision-reconcile-zucai")
def decision_reconcile_zucai(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26091"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    settled_at: str = _cli.typer.Option(..., "--settled-at", help="ISO 结算时刻"),
) -> None:
    """决策本体 · 传统足彩结算:zucai 1X2 赛果 → Settlement(canonical 通用)。"""
    from nutmeg.decision.verbs import run_reconcile_zucai
    _cli.typer.echo(run_reconcile_zucai(issue, output_dir, settled_at, zucai_dir))


_ISSUE_OPTION = _cli.typer.Option(None, "--issue", help="传统足彩期号(带则纳入 zucai)")


@_cli.app.command("decision-am")
def decision_am(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    issue: str | None = _ISSUE_OPTION,
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    """决策本体 · 日循环早段:fetch(+可选 zucai)→ sense(+可选 zucai)→ backfill。

    编排不含判读——只数据入库+市场基线;主循环 Claude 在 am 与 close 之间人工插 decision-read。

    NUTMEG_ONTOLOGY_V2=1 时改走 kernel-backed am(ontology_adapter);否则旧 JSONL 路径不变。
    """
    from nutmeg.config.settings import get_settings

    if get_settings().ontology_v2:
        from nutmeg.decision.ontology_adapter import run_decision_am_v2
        result = run_decision_am_v2(run_date, output_dir)
    else:
        from nutmeg.decision.verbs import run_decision_am
        result = run_decision_am(run_date, output_dir, zucai_dir=zucai_dir, issue=issue)
    _emit_result(result, format=format)
    if not getattr(result, "succeeded", True):
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-close")
def decision_close(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    """决策本体 · 日循环收盘段:capture-closing → express → report。

    express legs 来自主循环 Claude 判读(daily/<date>/legs.json,无则空票)。

    NUTMEG_ONTOLOGY_V2=1 时改走 kernel-backed close(ontology_adapter);否则旧路径不变。
    """
    from nutmeg.config.settings import get_settings

    if get_settings().ontology_v2:
        from nutmeg.decision.ontology_adapter import run_decision_close_v2
        result = run_decision_close_v2(
            run_date, output_dir, dispatch=dispatch_telegram, dry_run=dry_run)
    else:
        from nutmeg.decision.verbs import run_decision_close
        result = run_decision_close(
            run_date, output_dir, dispatch=dispatch_telegram, dry_run=dry_run
        )
    _emit_result(result, format=format)
    if not getattr(result, "succeeded", True):
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-settle")
def decision_settle(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    issue: str | None = _ISSUE_OPTION,
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    """决策本体 · 日循环结算段:reconcile(+可选 zucai)→ calibrate → report(复盘)。

    NUTMEG_ONTOLOGY_V2=1 时改走 kernel-backed settle(ontology_adapter);否则旧路径不变。
    """
    from nutmeg.config.settings import get_settings

    if get_settings().ontology_v2:
        from nutmeg.decision.ontology_adapter import run_decision_settle_v2
        result = run_decision_settle_v2(
            run_date, output_dir, dispatch=dispatch_telegram, dry_run=dry_run)
    else:
        from nutmeg.decision.verbs import run_decision_settle
        result = run_decision_settle(
            run_date,
            output_dir,
            dispatch=dispatch_telegram,
            dry_run=dry_run,
            issue=issue,
            zucai_dir=zucai_dir,
        )
    _emit_result(result, format=format)
    if not getattr(result, "succeeded", True):
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-calibrate")
def decision_calibrate(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    as_of: str = _cli.typer.Option(..., "--as-of", help="YYYY-MM-DD"),
) -> None:
    """决策本体 · 动词五:聚合 Settlement → FactorVerdict + 校准面板。"""
    from nutmeg.decision.verbs import run_calibrate_panel
    _cli.typer.echo(run_calibrate_panel(output_dir, as_of))


def _emit_result(result, *, format: str) -> None:
    if format == "json":
        if not hasattr(result, "to_dict"):
            payload = {"status": "succeeded", "message": str(result)}
        else:
            payload = result.to_dict()
        _cli.typer.echo(_cli.json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if format != "text":
        raise _cli.typer.BadParameter("format must be text or json", param_hint="--format")
    _cli.typer.echo(str(result))


def _warn_if_exposed(host: str) -> bool:
    """非 loopback 绑定 → stderr 警告(单人无鉴权假设)。返回是否警告。"""
    if host not in ("127.0.0.1", "localhost", "::1"):
        import sys
        print(f"⚠️ decision-web 绑定 {host}:无鉴权,仅限可信局域网。", file=sys.stderr)
        return True
    return False


@_cli.app.command("decision-web")
def decision_web(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    host: str = _cli.typer.Option("127.0.0.1", "--host"),
    port: int = _cli.typer.Option(8787, "--port"),
) -> None:
    """Workshop 判读工作台:浏览器审草稿/追问共磨/确认出票(spec workshop-ui)。"""
    import uvicorn

    from nutmeg.decision.store import DecisionStore
    from nutmeg.interfaces.decision_web import create_decision_app

    _warn_if_exposed(host)
    store = DecisionStore(Path(output_dir) / "decision")
    app = create_decision_app(store=store, output_dir=Path(output_dir))
    uvicorn.run(app, host=host, port=port)
