"""决策本体系统五动词 CLI(spec §3)。M0:sense 可 replay,余为骨架。

仿 cli/jczq.py 模式:@_cli.app.command 注册,由 cli/__init__ 底部 import 触发。
"""
from __future__ import annotations

from pathlib import Path

import nutmeg.interfaces.cli as _cli
from nutmeg.decision.zucai_night import run_night_calibrate

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
_LEGS_AUDIT_FILE_OPTION = _cli.typer.Option(..., "--legs-file", help="票面结构 JSON")
_EXPLAIN_MATCH_OPTION = _cli.typer.Option(
    None, "--match", help="只展开这些场号；不给＝全部")
_EXPLAIN_OUT_OPTION = _cli.typer.Option(
    None, "--out", help="落盘路径；不给＝打到 stdout")
_WITH_LEGS_FILE_OPTION = _cli.typer.Option(
    [], "--with-legs-file",
    help="同期其它票面文件；用于 C15 多票共享被排面检查（可重复）")
_AUDIT_DATA_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_AUDIT_ZUCAI_LEGS_OPTION = _cli.typer.Option(
    None, "--zucai-legs-file",
    help="同日足彩票面；与 --channel-map 一起给才触发 C18 跨渠道立场一致性")
_AUDIT_CHANNEL_MAP_OPTION = _cli.typer.Option(
    None, "--channel-map",
    help="{竞彩 match_id: 足彩场号} 显式映射；身份不许猜（26122）")
_OPS_OPENCLAW_DB_OPTION = _cli.typer.Option(
    None, "--openclaw-db", help="OpenClaw sqlite；默认 ~/.openclaw/state/openclaw.sqlite")
_ADJUDICATE_APPLY_OPTION = _cli.typer.Option(
    None, "--apply", help="填好的裁决单；不给＝签发一张留空的新单")
_ADJUDICATE_OUT_OPTION = _cli.typer.Option(
    None, "--out", help="裁决单落盘路径；不给＝打到 stdout")
_ADJUDICATE_RX_OPTION = _cli.typer.Option(
    None, "--rx-file", help="驳回预测并入的 rx 文件；默认 .nutmeg-data/zucai/<期>-rx.json")
_DEPLOYMENT_GATE_FILE_OPTION = _cli.typer.Option(
    ..., "--gate-file", help="部署门候选、注金帽与历史窗口 JSON"
)
_OFFICIAL_HISTORY_FILE_OPTION = _cli.typer.Option(
    None,
    "--official-history-file",
    help="离线 sporttery gameNo=90 历史响应 JSON；省略则抓官方接口",
)
_ZUCAI_OPTIMIZER_INPUT_OPTION = _cli.typer.Option(
    ..., "--input-file", help="候选版本与 fair JSON"
)


@_cli.app.command("decision-fetch")
def decision_fetch(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 数据自取:体彩盘口 + API-Football 国际欧赔 → 当日快照。"""
    from nutmeg.decision.fetch import fetch_day
    _cli.typer.echo(fetch_day(run_date, output_dir))


@_cli.app.command("decision-odds-shadow")
def decision_odds_shadow(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 影子期:API-Football vs titan007 国际欧赔对照报告(judgment 不动)。"""
    from nutmeg.decision.odds_shadow import run_shadow
    _cli.typer.echo(run_shadow(run_date, output_dir))


@_cli.app.command("decision-datasource-health")
def decision_datasource_health(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    issue: str | None = _cli.typer.Option(None, "--issue", help="给了才查足彩链"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
) -> None:
    """决策本体 · 数据底座健康度:端点/覆盖/共识家数/初赔/新鲜度/CLV 填充率(+足彩对齐)。

    结论为 degraded 时退出码 1——供无人值守链路把数据退化变成可见失败。
    """
    from nutmeg.decision.datasource_health import run_health
    path, verdict = run_health(run_date, output_dir, issue=issue, zucai_dir=zucai_dir)
    _cli.typer.echo(f"{path} → {verdict}")
    if verdict != "healthy":
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-fetch-zucai")
def decision_fetch_zucai(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26091"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    slot: str = _cli.typer.Option("afternoon", "--slot", help="morning | afternoon | revision"),
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


@_cli.app.command("decision-fetch-zucai-intl")
def decision_fetch_zucai_intl(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26125"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
) -> None:
    """决策本体 · 足彩国际欧赔(titan007):→ <issue>-odds-intl.json。

    **只补充不替换**:500.com 基线 <issue>-odds.json 原样保留。对不上 titan007
    板面的场次直接缺席(足彩含竞彩不卖的场),不猜、不回填。
    """
    import json

    from nutmeg.services.zucai_titan007_odds import (
        collect_zucai_euro_titan007_live,
    )
    issue_path = Path(zucai_dir) / f"{issue}-issue.json"
    if not issue_path.exists():
        _cli.typer.echo(f"缺 {issue_path}——先跑 decision-fetch-zucai")
        raise _cli.typer.Exit(code=1)
    doc = json.loads(issue_path.read_text(encoding="utf-8"))
    priced = collect_zucai_euro_titan007_live(doc)
    total = len(doc.get("matches") or [])
    if not priced:
        _cli.typer.echo(f"decision-fetch-zucai-intl {issue}: 0/{total} 场——不落盘")
        raise _cli.typer.Exit(code=1)
    out = Path(zucai_dir) / f"{issue}-odds-intl.json"
    out.write_text(json.dumps({
        "issue_id": issue,
        "source": "titan007",
        "sources": [{"label": "titan007 逐家国际欧赔(锐盘共识,含初赔)",
                     "url": "http://1x2d.titan007.com/{match_id}.js"}],
        "matches": [priced[k] for k in sorted(priced)],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    _cli.typer.echo(f"decision-fetch-zucai-intl {issue}: {len(priced)}/{total} 场 → {out}")


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


@_cli.app.command("decision-alias-audit")
def decision_alias_audit(
    run_date: str | None = _cli.typer.Option(None, "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    history: bool = _cli.typer.Option(
        False, "--history", help="改跑全部历史板面的覆盖率(加完别名后的验收口径)"),
) -> None:
    """决策本体 · 别名覆盖审计:未命中 = 丢国际欧赔锚(decision-am 已内嵌当日审计)。"""
    if history:
        from nutmeg.decision.alias_audit import audit_history, format_history
        _cli.typer.echo(format_history(audit_history(output_dir)))
        return
    if not run_date:
        _cli.typer.echo("❌ 需要 --run-date 或 --history", err=True)
        raise _cli.typer.Exit(code=1)
    from nutmeg.decision.verbs import run_alias_audit
    _cli.typer.echo(run_alias_audit(run_date, output_dir))


@_cli.app.command("decision-entities-sync")
def decision_entities_sync(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    write_seed: bool = _cli.typer.Option(
        False, "--write-seed", help="反向:把 store 里领先的实体/笔记回灌种子文件"),
) -> None:
    """决策本体 · 实体同步:种子 → store 幂等 upsert(画像笔记按 key 合并)。"""
    from nutmeg.decision.entities import export_entities_to_seed, sync_entities
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    if write_seed:
        written = export_entities_to_seed(store)
        _cli.typer.echo(
            f"decision-entities-sync --write-seed: 回灌种子 "
            f"{written['leagues']} 联赛 / {written['teams']} 球队")
        return
    stats = sync_entities(store)
    _cli.typer.echo(
        f"decision-entities-sync: 新增 {stats['added']} / 更新 {stats['updated']} / "
        f"未变 {stats['unchanged']}")


@_cli.app.command("decision-profile")
def decision_profile(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    league: str | None = _cli.typer.Option(None, "--league", help="league_id"),
    team: str | None = _cli.typer.Option(None, "--team", help="team_id"),
    run_date: str | None = _cli.typer.Option(
        None, "--run-date", help="按当日板面列出相关联赛/球队画像"),
    add_note: bool = _cli.typer.Option(False, "--add-note", help="写模式"),
    key: str = _cli.typer.Option("", "--key"),
    note: str = _cli.typer.Option("", "--note"),
    evidence: str = _cli.typer.Option("", "--evidence", help="必填:URL 或数据出处"),
    at: str = _cli.typer.Option("", "--at", help="YYYY-MM-DD"),
) -> None:
    """决策本体 · 联赛/球队画像读写(证据式笔记,evidence 必填)。"""
    import json as _json

    from nutmeg.decision.entities import add_profile_note, profiles_for_board
    from nutmeg.decision.ontology import League, Team
    from nutmeg.decision.store import DecisionStore

    store = DecisionStore(Path(output_dir) / "decision")
    if add_note:
        try:
            _cli.typer.echo(add_profile_note(
                store, league_id=league, team_id=team,
                key=key, note=note, evidence=evidence, at=at))
        except ValueError as exc:
            _cli.typer.echo(f"❌ {exc}", err=True)
            raise _cli.typer.Exit(code=1) from exc
        return
    if run_date:
        from nutmeg.decision.alias_audit import board_matches
        from nutmeg.decision.market_data import load_sporttery_snapshot

        value = load_sporttery_snapshot(run_date, output_dir) or {}
        rows = board_matches(value)
        payload = profiles_for_board(
            store,
            [str(r.get("leagueAbbName") or "") for r in rows],
            [str(r.get(k) or "") for r in rows
             for k in ("homeTeamAbbName", "awayTeamAbbName")],
        )
        _cli.typer.echo(_json.dumps(payload, ensure_ascii=False, indent=1))
        return
    entities = (
        [store.get(League, league)] if league
        else [store.get(Team, team)] if team
        else [*store.load(League), *store.load(Team)]
    )
    for entity in entities:
        if entity is None:
            _cli.typer.echo("❌ 实体不在 store(先建种子再 decision-entities-sync)", err=True)
            raise _cli.typer.Exit(code=1)
        _cli.typer.echo(f"== {entity.id} {entity.name_zh} ({len(entity.profile_notes)} 条)")
        for row in entity.profile_notes:
            _cli.typer.echo(
                f"   [{row.get('key')}] {row.get('note')}"
                f"\n      证据 {row.get('evidence')} · {row.get('at')}")


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
        result = run_decision_am_v2(run_date, output_dir, issue=issue, zucai_dir=zucai_dir)
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
    kernel_state = None
    from nutmeg.config.settings import get_settings
    if get_settings().ontology_v2:
        # 读侧与写侧同一个开关：decision-read 写内核，工作台就读内核（不双写）。
        from datetime import UTC, datetime

        from nutmeg.interfaces.decision_web_kernel import kernel_day_state, slips_for_date
        from nutmeg.ontology.wiring import build_ontology_kernel
        from nutmeg.product.repository import ProductReadRepository

        kernel = build_ontology_kernel(get_settings())
        kernel.initialize()
        repository = ProductReadRepository(kernel.engine, kernel.paths.analytics)
        data_dir = Path(output_dir).parent          # .nutmeg-data/jczq → .nutmeg-data
        kernel_state = lambda date: kernel_day_state(  # noqa: E731
            repository, date, as_of=datetime.now(UTC),
            slips=slips_for_date(data_dir, data_dir / "zucai", date))
        _cli.typer.echo("decision-web: 读侧=内核(ontology v2)")
    app = create_decision_app(store=store, output_dir=Path(output_dir), kernel_state=kernel_state)
    uvicorn.run(app, host=host, port=port)


@_cli.app.command("zucai-prep")
def zucai_prep(
    run_date: str | None = _cli.typer.Option(None, "--run-date", help="YYYY-MM-DD,默认今天"),
    slot: str = _cli.typer.Option(
        "afternoon", "--slot",
        help="morning(11:00 早刷新) | afternoon(14:00 备料) | revision(18:30 复核)"),
    issue: str | None = _cli.typer.Option(
        None, "--issue", help="强制期号(手动补跑;省略则自动探测在售期)"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    output_dir: Path = _OUTPUT_DIR_OPTION,
    no_fetch: bool = _cli.typer.Option(False, "--no-fetch", help="不抓取,只用已落盘快照重算"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
) -> None:
    """传统足彩备料底座(有期才干活,无期发心跳)。**只出事实与确定性算术,不含判读。**

    旗 / 共振级 / 动作阶梯 / 票面一律留空——判断由主循环 Claude 产出,永不入脚本
    (26102 复盘:预生成的"初稿"会锚定后续判读)。
    """
    from nutmeg.decision.zucai_prep import run_zucai_prep

    result = run_zucai_prep(
        run_date=run_date, slot=slot, issue=issue,
        zucai_dir=zucai_dir, output_dir=output_dir,
        live_fetch=not no_fetch, dispatch=dispatch_telegram,
    )
    _cli.typer.echo(result.summary)
    for label, path in (("备料", result.prep_path), ("brief", result.brief_path),
                        ("位移", result.diff_path)):
        if path:
            _cli.typer.echo(f"  {label} → {path}")
    if not result.succeeded:
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-audit-legs")
def decision_audit_legs(
    legs_file: Path = _LEGS_AUDIT_FILE_OPTION,
    user_override: bool = _cli.typer.Option(
        False,
        "--user-override",
        help="Jun 显式知情行权：保留 ERROR 并写 evidence_rejected Adjudication",
    ),
    ticket_batch_token: str | None = _cli.typer.Option(
        None,
        "--ticket-batch-token",
        help="Web 工位签发的当前票批次 token；ERROR override 必填",
    ),
    with_legs_file: list[Path] = _WITH_LEGS_FILE_OPTION,
    zucai_legs_file: Path | None = _AUDIT_ZUCAI_LEGS_OPTION,
    channel_map_file: Path | None = _AUDIT_CHANNEL_MAP_OPTION,
    data_dir: Path = _AUDIT_DATA_DIR_OPTION,
) -> None:
    """出票前结构校验:把「用新理由撤掉结构保险」变成非零退出码。

    只看「这条腿有没有方向性旗」和「面集合有几个面」,**不听任何论证**——
    同一个动作已杀死四张票(26098/26101/26102/26103),每次的理由都不同且一次比一次讲究,
    这说明散文规则挡不住它。有 ERROR 即退出码 1。
    """
    import json as _json
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from nutmeg.config.settings import AppSettings
    from nutmeg.decision.audit_override import AuditOverrideError, record_user_overrides
    from nutmeg.decision.legs_audit import format_findings, has_blocking

    payload = _json.loads(Path(legs_file).read_text("utf-8"))
    # JCZQ close consumes a flat legs array; an empty array is the canonical
    # abstain shape and has no structure to audit.
    if isinstance(payload, list):
        if payload:
            # C18 —— 竞彩腿本身没有 fair/旗/完整度可查，但**同日足彩票面的立场**可查。
            cross = []
            if zucai_legs_file and channel_map_file:
                from nutmeg.decision.legs_audit import audit_cross_channel

                cross = audit_cross_channel(
                    _json.loads(Path(zucai_legs_file).read_text("utf-8")),
                    payload,
                    channel_map=_json.loads(
                        Path(channel_map_file).read_text("utf-8")
                    ),
                )
            _cli.typer.echo(
                "出票前结构校验：1 个 ERROR\n\n"
                "❌ [missing_audit_metadata] JCZQ 投注腿数组不含 fair/旗/锚方完整度，"
                "无法执行结构纪律校验。"
                + ("\n\n" + format_findings(cross) if cross else "")
            )
            raise _cli.typer.Exit(code=1)
        _cli.typer.echo(format_findings([]))
        return
    # 腿级 + 处方偏离 + 全包分配（按被排面 fair 降序，2026-09-13 入码）
    # + C17 票面级读判一致性 + C15 多票共享死点 —— 与 `decision-adjudicate` 同源，
    # 两个命令看到的 ERROR 集必须逐字一致，否则裁决单的指纹永远对不上。
    findings = _ticket_findings(payload, Path(legs_file), with_legs_file)
    _cli.typer.echo(format_findings(findings, issue=str(payload.get("issue", ""))))
    if has_blocking(findings):
        if user_override:
            try:
                if ticket_batch_token is None or not ticket_batch_token.strip():
                    raise AuditOverrideError(
                        "--user-override requires --ticket-batch-token"
                    )
                kernel = _cli.build_ontology_kernel(
                    AppSettings(data_dir=Path(data_dir).expanduser().resolve())
                )
                status = kernel.status()
                if (
                    not status.initialized
                    or status.integrity_check != "ok"
                    or status.pending_migrations
                ):
                    raise AuditOverrideError(
                        "ontology must be initialized, healthy, and current"
                    )
                result = record_user_overrides(
                    payload,
                    findings,
                    decision_actions=kernel.decision_actions,
                    ticket_batch_token=ticket_batch_token,
                    requested_at=_datetime.now(_UTC),
                )
                _cli.typer.echo(
                    f"user override 已入账：{result.error_count} 个 ERROR -> "
                    f"{result.adjudication_count} 条 Adjudication"
                )
                return
            except (AuditOverrideError, ValueError) as error:
                _cli.typer.echo(f"❌ user override blocked: {error}")
        raise _cli.typer.Exit(code=1)


@_cli.app.command("decision-explain-faces")
def decision_explain_faces(
    legs_file: Path = _LEGS_AUDIT_FILE_OPTION,
    match_no: list[int] = _EXPLAIN_MATCH_OPTION,
    output: Path | None = _EXPLAIN_OUT_OPTION,
) -> None:
    """面集展开：每场七个面集 × 各自触发哪些码。**不是出票门**，退出码恒 0。

    出生事故：2026-09-15 构 26125 票时把 C14 的「**被排面** fair>20%」口算成
    「任一面 fair>20%」，两场灰带排除被误锁全包，帽内零 ERROR 解 1,890→0，
    并支撑了当时的空仓建议。宪法「判据必须入代码」此前只用在判据上，没用在
    **判据的应用**上——本命令补这一刀。

    ⛔它只摊算术。死亡三证够不够、洞能不能被对手吃掉、旗的证据等级到没到，
    一律留空给判断（表末「判断栏」）。它**不排序、不推荐、不裁合法性**。
    出票门仍然只有 `decision-audit-legs`。
    """
    import json as _json

    from nutmeg.decision.legs_audit import format_face_options, legs_from_dict

    payload = _json.loads(Path(legs_file).read_text("utf-8"))
    if isinstance(payload, list):
        _cli.typer.echo("❌ 扁平 legs 数组不含 fair/旗/完整度，无法展开面集。", err=True)
        raise _cli.typer.Exit(code=2)
    legs = legs_from_dict(payload)
    if match_no:
        wanted = set(match_no)
        legs = [lg for lg in legs if lg.match_no in wanted]
    if not legs:
        _cli.typer.echo("没有可展开的场次。", err=True)
        raise _cli.typer.Exit(code=2)
    text = format_face_options(legs, issue=str(payload.get("issue", "")))
    if output:
        Path(output).write_text(text + "\n", "utf-8")
        _cli.typer.echo(f"面集展开 → {output}")
    else:
        _cli.typer.echo(text)


def _ticket_findings(payload: dict, legs_file: Path, with_legs_file: list[Path]) -> list:
    """读文件 → `legs_audit.audit_ticket`（门/裁决单/候选穷举共用的单一事实源）。"""
    import json as _json

    from nutmeg.decision.legs_audit import audit_ticket, legs_from_dict

    others = {}
    for extra in with_legs_file:
        other = _json.loads(Path(extra).read_text("utf-8"))
        others[str(other.get("version") or Path(extra).stem)] = legs_from_dict(other)
    payload = {**payload, "version": payload.get("version") or legs_file.stem}
    return audit_ticket(payload, others=others or None)


@_cli.app.command("decision-adjudicate")
def decision_adjudicate(
    legs_file: Path = _LEGS_AUDIT_FILE_OPTION,
    apply_sheet_file: Path | None = _ADJUDICATE_APPLY_OPTION,
    output: Path | None = _ADJUDICATE_OUT_OPTION,
    rx_file: Path | None = _ADJUDICATE_RX_OPTION,
    with_legs_file: list[Path] = _WITH_LEGS_FILE_OPTION,
) -> None:
    """裁决单：把「行权」从一行 reason 升格成可结账的判断。**它不是门，也不放宽门。**

    两段式（同 B4c 面集展开：机器出单、判断留空）：

      1. `--legs-file 票面.json --out 裁决单.json` —— 摊开当前每条 ERROR，
         `ruling` 一律留空。**机器绝不预填裁决。**
      2. 人填完后 `--legs-file 票面.json --apply 裁决单.json` —— 校验完整性，
         把驳回写回 `deviation_registry`，把预测并入 rx 文件。

    出生事故：热板四连（26125-26128）严格裁决全部空仓，而同期行权形状
    8/9、8/9、9/9。门的判断是对的，但「洞已定价≠翻车」没有出口：每个 ERROR
    手写登记、rx 另立文件、记分牌复盘时手补 —— 守门与行权**两条路都没有账**。

    ⛔驳回必须附可证伪预测。26098-26103 四次撤保险，理由一次比一次讲究且全亏：
    理由的质量不可自证，能自证的只有事后可判真假的断言。
    ⛔真正的门仍然只有 `decision-audit-legs --user-override`（Jun 本人 + Web token）。
    本命令只落文书，落完还得去按那道门。
    """
    import json as _json
    from datetime import UTC as _UTC
    from datetime import datetime as _datetime

    from nutmeg.decision.adjudication_sheet import (
        AdjudicationSheetError,
        accepted_slots,
        format_sheet_summary,
        issue_sheet,
        merge_deviation_registry,
        merge_rx_predictions,
        prediction_records,
        rejected_slots,
        validate_sheet,
    )

    payload = _json.loads(Path(legs_file).read_text("utf-8"))
    if isinstance(payload, list):
        _cli.typer.echo("❌ 扁平 legs 数组不含 fair/旗/完整度，无法裁决。", err=True)
        raise _cli.typer.Exit(code=2)
    findings = _ticket_findings(payload, Path(legs_file), with_legs_file)
    now = _datetime.now(_UTC).astimezone()

    if apply_sheet_file is None:
        try:
            sheet = issue_sheet(
                payload, findings, legs_file=Path(legs_file), issued_at=now
            )
        except AdjudicationSheetError as error:
            _cli.typer.echo(f"✅ {error}")
            return
        text = _json.dumps(sheet, ensure_ascii=False, indent=1)
        if output:
            Path(output).write_text(text + "\n", "utf-8")
            _cli.typer.echo(
                f"裁决单（{len(sheet['rulings'])} 条 ERROR，ruling 全部留空）→ {output}\n"
                "填 ruling=accept|reject；驳回须附 rule_ids + reason + predictions，"
                "然后 --apply 本文件。"
            )
        else:
            _cli.typer.echo(text)
        return

    sheet = _json.loads(Path(apply_sheet_file).read_text("utf-8"))
    try:
        slots = validate_sheet(sheet, findings)
    except AdjudicationSheetError as error:
        _cli.typer.echo(f"❌ 裁决单不完整：{error}", err=True)
        raise _cli.typer.Exit(code=2) from error
    _cli.typer.echo(format_sheet_summary(slots))
    accepted = accepted_slots(slots)
    if accepted:
        marks = "、".join(slot.signature for slot in accepted)
        _cli.typer.echo(
            f"\n⛔ 接受门的 ERROR 未落文书：{marks}\n"
            "   接受门 = 这张票不出。8/08 铁律：预算压缩唯一合法动作是**丢整场**，"
            "不是降双选。改票后重新签发裁决单。"
        )
        raise _cli.typer.Exit(code=1)
    rejected = rejected_slots(slots)
    updated = merge_deviation_registry(payload, slots)
    Path(legs_file).write_text(
        _json.dumps(updated, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )
    _cli.typer.echo(f"\n偏离登记 → {legs_file}（{len(rejected)} 条 user_override）")
    records = prediction_records(slots)
    if records:
        issue = str(payload.get("issue", "") or "")
        target = rx_file or (
            Path(".nutmeg-data/zucai") / f"{issue}-rx.json" if issue else None
        )
        if target is None:
            _cli.typer.echo("⚠️ 无 issue 也未给 --rx-file，预测未落盘：")
            for record in records:
                _cli.typer.echo(f"   {record['id']} {record['claim']}")
        else:
            document = merge_rx_predictions(
                Path(target), records, issue=issue, registered_at=now
            )
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_text(
                _json.dumps(document, ensure_ascii=False, indent=1) + "\n", "utf-8"
            )
            _cli.typer.echo(f"驳回预测 → {target}（{len(records)} 条）")
    _cli.typer.echo(
        "\n文书已落。门还没按 —— 出票仍需："
        f"\n  uv run nutmeg decision-audit-legs --legs-file {legs_file} "
        "--user-override --ticket-batch-token <Web 工位签发>"
    )


@_cli.app.command("ops-status")
def ops_status(
    data_dir: Path = _AUDIT_DATA_DIR_OPTION,
    openclaw_db: Path | None = _OPS_OPENCLAW_DB_OPTION,
) -> None:
    """今日状态页：launchd + OpenClaw + 不会自己消失的待办，一屏看全。**只读。**

    出生事故 2026-09-17（我自己踩的）：为判断链路健康，我 `tail` 了
    `decision.am.err.log`，看见一条 WAF 降级失败就报告「今天 08:00 成功、
    17:15 又跑出降级」。**两句都错**——那条错误是 9/15 的（文件 mtime 为证），
    17:15 只是当日数据文件的 mtime。根因是结构不是马虎：`NUTMEG_OK`/
    `NUTMEG_FAILED` 两行**不带时间戳**，out 与 err 各自追加，launchd 与
    OpenClaw 又各管一半链路。

    所以本页第一纪律：**每条结局都与它的时间证据并排打印**；拿不到时间
    就显示「无时间证据」，而不是默认它是今天的。
    """
    import json as _json
    import plistlib
    import sqlite3
    import subprocess
    from datetime import datetime as _datetime

    from nutmeg.decision.ops_status import (
        CronStatus,
        PendingItem,
        agent_status,
        describe_calendar,
        format_status,
    )

    def _read(path: Path) -> tuple[str, _datetime | None]:
        try:
            return path.read_text("utf-8", errors="replace")[-4000:], _datetime.fromtimestamp(
                path.stat().st_mtime
            )
        except OSError:
            return "", None

    loaded: dict[str, str] = {}
    try:
        listing = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=10
        ).stdout
        for line in listing.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].startswith("com.nutmeg."):
                loaded[parts[2]] = parts[1]
    except (OSError, subprocess.SubprocessError):
        pass

    agents = []
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    for plist in sorted(plist_dir.glob("com.nutmeg.*.plist")):
        try:
            spec = plistlib.loads(plist.read_bytes())
        except (OSError, ValueError):
            continue
        label = str(spec.get("Label") or plist.stem)
        out_text, out_at = _read(Path(str(spec.get("StandardOutPath") or "")))
        err_text, err_at = _read(Path(str(spec.get("StandardErrorPath") or "")))
        schedule = describe_calendar(
            spec.get("StartCalendarInterval")
            or (f"每 {int(spec['StartInterval']) // 60} 分钟"
                if spec.get("StartInterval") else None)
        )
        agents.append(agent_status(
            label, schedule,
            loaded=label in loaded, last_exit=loaded.get(label, ""),
            out_text=out_text, out_at=out_at, err_text=err_text, err_at=err_at,
        ))

    jobs = []
    db_path = openclaw_db or (Path.home() / ".openclaw" / "state" / "openclaw.sqlite")
    if db_path.exists():
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                for row in conn.execute(
                    "SELECT name, enabled, schedule_expr, last_run_status, "
                    "consecutive_errors, last_error FROM cron_jobs "
                    "WHERE lower(name) LIKE '%nutmeg%' ORDER BY schedule_expr"
                ):
                    jobs.append(CronStatus(
                        name=str(row[0]), enabled=bool(row[1]),
                        schedule=str(row[2] or ""), last_status=str(row[3] or ""),
                        consecutive_errors=int(row[4] or 0),
                        last_error=str(row[5] or ""),
                    ))
        except sqlite3.Error as error:
            jobs = []
            _cli.typer.echo(f"（OpenClaw 库读不出：{error}）")

    pending = []
    zucai = Path(data_dir) / "zucai"
    results_path = zucai / "official-results.json"
    results = {}
    if results_path.exists():
        results = _json.loads(results_path.read_text("utf-8"))
    ledger = Path(data_dir) / "betslips.jsonl"
    if ledger.exists():
        seen = set()
        for line in ledger.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            slip = _json.loads(line)
            issue = str(slip.get("issue") or "")
            if not issue or issue in seen or slip.get("channel") == "jczq":
                continue
            seen.add(issue)
            if issue not in results:
                pending.append(PendingItem(
                    "待官方开奖", f"{issue}",
                    f"票 {slip.get('slip_id')} 已登记，official-results 无该期 —— "
                    "重跑 `nutmeg zucai-official --issue " + issue + "`",
                ))
    _cli.typer.echo(format_status(
        agents, jobs, pending, today=_datetime.now().date()
    ))


@_cli.app.command("zucai-optimize")
def zucai_optimize(
    input_file: Path = _ZUCAI_OPTIMIZER_INPUT_OPTION,
    json_output: bool = _cli.typer.Option(False, "--json", help="输出稳定 JSON"),
) -> None:
    """比较人工给定的足彩候选版本，只做确定性算术，不生成或裁决票面。"""
    import json

    from nutmeg.decision.zucai_optimizer import (
        OptimizerInputError,
        format_report,
        optimize,
    )

    try:
        payload = json.loads(input_file.read_text("utf-8"))
        result = optimize(payload)
    except (OSError, json.JSONDecodeError, OptimizerInputError) as exc:
        _cli.typer.echo(f"输入错误：{exc}", err=True)
        raise _cli.typer.Exit(code=2) from exc
    if json_output:
        _cli.typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _cli.typer.echo(format_report(result))


@_cli.app.command("zucai-official")
def zucai_official(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26103"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    write_outcomes: bool = _cli.typer.Option(
        False, "--write-outcomes", help="落 {issue}-outcomes.json(喂 decision-reconcile-zucai)"),
    settle_ledger: bool = _cli.typer.Option(
        False, "--settle-ledger", help="按 rx.final_ticket 计命中并回填 ledger(幂等,已结不重结)"),
) -> None:
    """官方赛果/奖金(gameNo=90,90分钟口径)——结算与回填的唯一权威源。

    ⚠️AET 守卫:赛果只取官方 lotteryDrawResult 串,永不接触 API-Football 的 goals
    (含加时;2026-08-11 博德实测 90' 2-2 / goals 3-2)。未开奖 → 明确报"尚未开奖",退出码 1。
    """
    from datetime import date as _date

    from nutmeg.decision.zucai_official import (
        fetch_official,
        format_draw,
    )
    from nutmeg.decision.zucai_official import (
        settle_ledger as _settle,
    )
    from nutmeg.decision.zucai_official import (
        write_outcomes as _write,
    )

    draw = fetch_official(issue)
    if draw is None:
        _cli.typer.echo(f"⚠️ {issue} 尚未开奖(官方列表未出现)——不可当作赛果为空")
        raise _cli.typer.Exit(code=1)
    _cli.typer.echo(format_draw(draw))
    if write_outcomes:
        _cli.typer.echo(f"  outcomes → {_write(draw, zucai_dir)}")
    if settle_ledger:
        for line in _settle(issue, zucai_dir, draw, settled_at=_date.today().isoformat()):
            _cli.typer.echo(f"  ledger: {line}")


@_cli.app.command("zucai-deployment-gate")
def zucai_deployment_gate(
    gate_file: Path = _DEPLOYMENT_GATE_FILE_OPTION,
    official_history_file: Path | None = _OFFICIAL_HISTORY_FILE_OPTION,
    json_output: bool = _cli.typer.Option(False, "--json", help="输出机器可读 JSON"),
) -> None:
    """足彩出票前部署门：确定性资金/回本算术，只报告不改票。"""
    import json as _json

    from nutmeg.decision.zucai_deployment import (
        evaluate_deployment_gate,
        format_deployment_gate,
    )
    from nutmeg.decision.zucai_official import (
        fetch_renjiu_history,
        parse_renjiu_history_payload,
    )

    try:
        payload = _json.loads(Path(gate_file).read_text("utf-8"))
        if official_history_file is None:
            history = fetch_renjiu_history()
        else:
            raw_history = _json.loads(Path(official_history_file).read_text("utf-8"))
            history = parse_renjiu_history_payload(raw_history)
        result = evaluate_deployment_gate(payload, history)
    except Exception as error:
        _cli.typer.echo(f"deployment gate error: {error}")
        raise _cli.typer.Exit(code=1) from error

    if json_output:
        _cli.typer.echo(_json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _cli.typer.echo(format_deployment_gate(result))
    if result.exit_code:
        raise _cli.typer.Exit(code=result.exit_code)


@_cli.app.command("decision-rules")
def decision_rules(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    verify_issue: str | None = _cli.typer.Option(
        None, "--verify-issue", help="用官方赛果核验该期全部 pending falsifier(幂等)"),
) -> None:
    """规则/证伪登记表(Roadmap A1):预登记的证伪条件由机器核验,不再依赖"记得去核"。

    check 是封闭谓词词典(outcome_eq/outcome_count/margin),只判赛果与比分——判断进不来。
    """
    from datetime import date as _date

    from nutmeg.decision.rules_registry import format_rules, load_rules
    from nutmeg.decision.rules_registry import verify_issue as _verify

    store = Path(output_dir) / "decision"
    if verify_issue:
        from nutmeg.decision.zucai_official import fetch_official

        draw = fetch_official(verify_issue)
        if draw is None:
            _cli.typer.echo(f"⚠️ {verify_issue} 尚未开奖,falsifier 保持 pending")
            raise _cli.typer.Exit(code=1)
        for line in _verify(store, verify_issue, draw.results, draw.scores,
                            verified_at=_date.today().isoformat()):
            _cli.typer.echo(line)
        return
    _cli.typer.echo(format_rules(load_rules(store)))


@_cli.app.command("decision-alias-propose")
def decision_alias_propose(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    apply: bool = _cli.typer.Option(False, "--apply", help="把'恰一个候选'的提案写入别名表"),
) -> None:
    """别名自愈提案器(Roadmap C1):audit 缺口 → 对手推断(确定性,零LLM) → 人一键确认。

    双边都未解析的场推断不了,如实报出;多候选/零候选只报告不写入。
    """
    from nutmeg.decision.alias_propose import run_propose

    _cli.typer.echo(run_propose(run_date, output_dir, apply=apply))


@_cli.app.command("zucai-ticket")
def zucai_ticket(
    legs_file: Path = _LEGS_AUDIT_FILE_OPTION,
    sales: float = _cli.typer.Option(13_000_000, "--sales", help="当期任九销量估计(¥)"),
    skip_audit: bool = _cli.typer.Option(False, "--skip-audit", help="跳过结构校验(不建议)"),
) -> None:
    """票面算术(Roadmap D1,确定性,零判断):注数/P/回本门槛/需中奖注数,并自动过结构校验。

    输入与 decision-audit-legs 同一 JSON。该买哪面不归它管。
    """
    import json as _json

    from nutmeg.decision.legs_audit import audit_legs, format_findings, has_blocking, legs_from_dict
    from nutmeg.decision.zucai_ticket import format_stats, ticket_stats

    payload = _json.loads(Path(legs_file).read_text("utf-8"))
    stats = ticket_stats(payload.get("legs") or {}, sales=sales)
    _cli.typer.echo(format_stats(stats, issue=str(payload.get("issue", ""))))
    if not skip_audit:
        findings = audit_legs(legs_from_dict(payload))
        _cli.typer.echo("")
        _cli.typer.echo(format_findings(findings, issue=str(payload.get("issue", ""))))
        if has_blocking(findings):
            raise _cli.typer.Exit(code=1)


@_cli.app.command("zucai-ledger")
def zucai_ledger(
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    issue: str | None = _cli.typer.Option(None, "--issue", help="按期号过滤(list)"),
    add: bool = _cli.typer.Option(False, "--add", help="追加一行入账(配 --kind/--stake/...)"),
    kind: str | None = _cli.typer.Option(None, "--kind", help="任九|胜负彩"),
    stake: int | None = _cli.typer.Option(None, "--stake", help="stake_yuan"),
    tickets: int | None = _cli.typer.Option(None, "--tickets", help="注数"),
    code: str | None = _cli.typer.Option(None, "--code", help="票面串"),
    note: str | None = _cli.typer.Option(None, "--note", help="备注"),
) -> None:
    """账本操作(Roadmap D2):没入账 = 没打。结算/派奖由 zucai-official --settle-ledger 填。"""
    from nutmeg.decision.zucai_ticket import ledger_add, ledger_summary

    if add:
        _cli.typer.echo(ledger_add(zucai_dir, {
            "issue": issue, "kind": kind, "stake_yuan": stake,
            "tickets": tickets, "code": code, "note": note}))
        return
    _cli.typer.echo(ledger_summary(zucai_dir, issue=issue))


@_cli.app.command("zucai-night-calibrate")
def zucai_night_calibrate(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26111"),
    date: str = _cli.typer.Option(
        ..., "--date",
        help="欧洲比赛日 YYYY-MM-DD(API-Football date 口径,北京凌晨场取前一天)"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
):
    """夜间结果校准:抓当日完赛→90'彩果→票面存活报告(不写 rx/scoreboard)。"""
    import hashlib

    from nutmeg.notifications.models import NotificationRequest

    report = run_night_calibrate(issue, date, zucai_dir)
    _cli.typer.echo(report)
    if not dispatch_telegram:
        return
    service = _cli.build_notification_service(settings=_cli.get_settings())
    outcome = service.publish(
        NotificationRequest.text(
            kind="zucai.night-calibration",
            business_key=issue,
            stage=date,
            semantic_fingerprint=hashlib.sha256(report.encode("utf-8")).hexdigest(),
            subject=f"{issue} 夜间校准 {date}",
            text=report,
        ),
        dry_run=dry_run,
    )
    _cli.typer.echo(f"notification: {outcome.status.value}")
    if not outcome.is_success:
        raise _cli.typer.Exit(code=1)
