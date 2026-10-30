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
_ZUCAI_DIR_OPTION = _cli.typer.Option(
    Path(".nutmeg-data/zucai"), "--zucai-dir", help="zucai 源快照目录")
_AUDIT_DATA_DIR_OPTION = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_OPS_OPENCLAW_DB_OPTION = _cli.typer.Option(
    None, "--openclaw-db", help="OpenClaw sqlite；默认 ~/.openclaw/state/openclaw.sqlite")


@_cli.app.command("decision-read")
def decision_read(
    reads_file: Path = _READS_FILE_OPTION,
    output_dir: Path = _OUTPUT_DIR_OPTION,
) -> None:
    """决策本体 · 动词二:摄取 Claude 运行时产出的 Read(校验+提交内核)。"""
    from nutmeg.decision.ontology_adapter import run_decision_read_v2

    _cli.typer.echo(run_decision_read_v2(reads_file, output_dir))


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
    """
    from nutmeg.decision.ontology_adapter import run_decision_am_v2

    result = run_decision_am_v2(run_date, output_dir, issue=issue, zucai_dir=zucai_dir)
    _emit_result(result, format=format)
    if not getattr(result, "succeeded", True):
        raise _cli.typer.Exit(code=1)
    from nutmeg.decision.rsi_wiring import after_am

    after_am(day=run_date, data_dir=Path(output_dir).parent)


@_cli.app.command("decision-settle")
def decision_settle(
    run_date: str = _cli.typer.Option(..., "--run-date", help="YYYY-MM-DD"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    issue: str | None = _ISSUE_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    """决策本体 · 日循环结算段:内核 reconcile → calibrate → report(复盘)。"""
    from nutmeg.decision.ontology_adapter import run_decision_settle_v2

    result = run_decision_settle_v2(
        run_date, output_dir, dispatch=dispatch_telegram, dry_run=dry_run)
    _emit_result(result, format=format)
    if not dry_run:
        # RSI 接线（2026-09-18 spec §8.1 第 3 项）：结算落账 → 每条观察中的实验 grade
        # (+到期则 verdict)。失败只打印，不影响结算。dry-run 不碰本体。
        from nutmeg.decision import rsi_wiring

        rsi_wiring.after_settle(
            day=run_date,
            issue=issue,
            data_dir=Path(output_dir).parent,
        )
    if not getattr(result, "succeeded", True):
        raise _cli.typer.Exit(code=1)


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


def _warn_if_exposed(host: str, password: str = "") -> bool:
    """非 loopback 绑定 → 必须设 `NUTMEG_DECISION_WEB_PASSWORD`，否则拒绝启动（2026-10-30：
    校园网上谁都连得到，页面能写账本）；设了就打一行提示。返回是否对外。"""
    if host in ("127.0.0.1", "localhost", "::1"):
        return False
    import sys
    if not password:
        print(f"⛔ decision-web 绑定 {host} 需要 NUTMEG_DECISION_WEB_PASSWORD（未设，拒绝启动）。",
              file=sys.stderr)
        raise SystemExit(2)
    print(f"decision-web 绑定 {host}：非本机访问需密码登录。", file=sys.stderr)
    return True


@_cli.app.command("decision-web")
def decision_web(
    output_dir: Path = _OUTPUT_DIR_OPTION,
    host: str = _cli.typer.Option("127.0.0.1", "--host"),
    port: int = _cli.typer.Option(8787, "--port"),
) -> None:
    """Workshop 判读工作台:浏览器审草稿/追问共磨/确认出票(spec workshop-ui)。"""
    from datetime import UTC, datetime

    import uvicorn

    from nutmeg.config.settings import get_settings
    from nutmeg.interfaces.decision_web import create_decision_app
    from nutmeg.interfaces.decision_web_kernel import kernel_day_state, slips_for_date
    from nutmeg.ontology.wiring import build_ontology_kernel
    from nutmeg.product.repository import ProductReadRepository

    web_password = get_settings().decision_web_password
    _warn_if_exposed(host, web_password)
    # decision-read 写内核，工作台就读内核（不双写）。
    kernel = build_ontology_kernel(get_settings())
    kernel.initialize()
    repository = ProductReadRepository(kernel.engine)
    observe_repo = repository
    data_dir = Path(output_dir).parent          # .nutmeg-data/jczq → .nutmeg-data
    kernel_state = lambda date: kernel_day_state(  # noqa: E731
        repository, date, as_of=datetime.now(UTC),
        slips=slips_for_date(data_dir, data_dir / "zucai", date))
    app = create_decision_app(
        output_dir=Path(output_dir),
        kernel_state=kernel_state,
        observe_repo=observe_repo,
        data_dir=Path(output_dir).parent,
        web_password=web_password,
    )
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
    if result.status == "prepared" and result.issue:
        # RSI 接线（2026-09-18）：备料完成 → 排当天义务 + 列待办。失败只打印，不影响备料。
        from datetime import date as _date

        from nutmeg.decision.rsi_wiring import after_prep

        after_prep(issue=result.issue, day=(run_date or _date.today().isoformat()),
                   data_dir=Path(output_dir).parent)
    if not result.succeeded:
        raise _cli.typer.Exit(code=1)


@_cli.app.command("claude-auth-check")
def claude_auth_check() -> None:
    """定时任务用的 claude 无人值守认证自检：token 文件状态 + 真调一次（不打印 token）。

    2026-10-06 launchd 下钥匙串登录过期，深研/读者 B/解读句全挂；修法是
    `claude setup-token` 生成长期 token 放进私有文件（见 `claude_models`）。
    """
    from nutmeg.decision import claude_models

    r = claude_models.auth_check()
    source = {"token_file": "token 文件", "env": "环境变量",
              "inherited_login": "继承登录（钥匙串）"}[r["source"]]
    where = (f"{r['file']}，权限 {r['file_mode']}，写入 {r['file_age_days']} 天前"
             if r["file_exists"] else f"{r['file']} 不存在")
    if r["ok"]:
        _cli.typer.echo(f"claude 无人值守认证：ok｜来源 {source}｜{where}")
        if (r["file_age_days"] or 0) >= 330:
            _cli.typer.echo("⚠️ 长期 token 将满一年，提前用 `claude setup-token` 重新生成")
        return
    kind = "认证失败" if r["auth_failure"] else f"claude 退出码 {r['returncode']}"
    _cli.typer.echo(f"⚠️ claude {kind}｜来源 {source}｜{where}\n  {r['detail']}", err=True)
    _cli.typer.echo("  修法：普通终端运行 `claude setup-token`，把输出的 token 存进上面的文件"
                    "（chmod 600），再跑本命令", err=True)
    raise _cli.typer.Exit(code=1)


_OPS_RUN_LABEL_ARG = _cli.typer.Argument(..., help="作业名（com.nutmeg.<label>）")
_OPS_RUN_COMMANDS_ARG = _cli.typer.Argument(..., help="逐段执行的 shell 命令，每段一个参数")


@_cli.app.command("ops-run")
def ops_run(
    label: str = _OPS_RUN_LABEL_ARG,
    commands: list[str] = _OPS_RUN_COMMANDS_ARG,
    data_dir: Path = _AUDIT_DATA_DIR_OPTION,
) -> None:
    """launchd 作业包装：逐段跑、逐段记 `logs/runs.jsonl`、末行 NUTMEG_OK/FAILED 带时间戳。

    2026-10-12：plist 里 `;` 串联只让最后一段的退出码进 launchctl，`results` 段失败
    被 `settle` 段的 0 盖住。任一段失败仍跑完余段，最后退出 1。
    """
    from nutmeg.decision.ops_run import run_job

    code = run_job(label, list(commands), data_dir=Path(data_dir), cwd=Path.cwd())
    raise _cli.typer.Exit(code=code)


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
    import sqlite3
    from datetime import datetime as _datetime

    from nutmeg.decision.ops_status import (
        FAILED_MARK,
        CronStatus,
        PendingItem,
        agent_status,
        describe_schedule,
        format_status,
        iter_plists,
        launchctl_list,
        launchctl_running,
        parse_launchctl,
        stale_after_days,
    )

    def _read(path: Path) -> tuple[str, _datetime | None]:
        try:
            return path.read_text("utf-8", errors="replace")[-4000:], _datetime.fromtimestamp(
                path.stat().st_mtime
            )
        except OSError:
            return "", None

    listed = launchctl_list()
    loaded = parse_launchctl(listed)
    running = launchctl_running(listed)

    agents = []
    for plist, spec, error in iter_plists(Path.home() / "Library" / "LaunchAgents"):
        if spec is None:
            # 坏 plist 也要露面（2026-10-13：decision.web 的 `&&` 没转义，状态页静默少一行）
            agents.append(agent_status(
                plist.stem, f"plist 解析失败：{error!r}"[:40],
                loaded=plist.stem in loaded, last_exit=loaded.get(plist.stem, ""),
                err_text=f"{FAILED_MARK} plist 解析失败 {error!r}",
                err_at=_datetime.fromtimestamp(plist.stat().st_mtime),
            ))
            continue
        label = str(spec.get("Label") or plist.stem)
        out_text, out_at = _read(Path(str(spec.get("StandardOutPath") or "")))
        err_text, err_at = _read(Path(str(spec.get("StandardErrorPath") or "")))
        schedule = describe_schedule(spec, minute_word="分钟")
        agents.append(agent_status(
            label, schedule,
            loaded=label in loaded, last_exit=loaded.get(label, ""),
            running=label in running,
            out_text=out_text, out_at=out_at, err_text=err_text, err_at=err_at,
            # 常驻服务的日志只在有访问/重启时更新，不按「久未更新」报警
            stale_after=(10**6 if spec.get("KeepAlive")
                         else stale_after_days(spec.get("StartCalendarInterval"))),
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
    deadcode = Path(data_dir) / "analytics" / "deadcode" / "latest.json"
    if deadcode.exists():
        summary = _json.loads(deadcode.read_text("utf-8"))
        if summary.get("candidates"):
            pending.append(PendingItem(
                "死代码周报", str(summary.get("day")),
                f"{summary['candidates']} 个候选 / {summary['lines']} 行 → "
                f"analytics/deadcode/{summary.get('report')}（删前照 10-03 审计 §7 核对）",
            ))
    from nutmeg.decision.ops_run import failed_segments

    today = _datetime.now().date()
    _cli.typer.echo(format_status(
        agents, jobs, pending, today=today,
        segments=failed_segments(Path(data_dir), day=today.isoformat()),
    ))


@_cli.app.command("zucai-official")
def zucai_official(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26103"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
) -> None:
    """官方赛果/奖金(gameNo=90,90分钟口径)——结算与回填的唯一权威源。

    ⚠️AET 守卫:赛果只取官方 lotteryDrawResult 串,永不接触 API-Football 的 goals
    (含加时;2026-08-11 博德实测 90' 2-2 / goals 3-2)。未开奖 → 明确报"尚未开奖",退出码 1。
    """
    from nutmeg.decision.zucai_official import (
        fetch_official,
        format_draw,
        record_official_result,
    )

    draw = fetch_official(issue)
    if draw is None:
        _cli.typer.echo(f"⚠️ {issue} 尚未开奖(官方列表未出现)——不可当作赛果为空")
        raise _cli.typer.Exit(code=1)
    _cli.typer.echo(format_draw(draw))
    _cli.typer.echo(f"  赛果串 → {record_official_result(draw, zucai_dir)}")


@_cli.app.command("decision-alias-propose")
def decision_alias_propose(
    run_date: str | None = _cli.typer.Option(None, "--run-date", help="YYYY-MM-DD（竞彩板）"),
    issue: str | None = _cli.typer.Option(
        None, "--issue", help="足彩期号：截短队名 → 种子实体（经 zgzcw 全名/同联赛前缀）"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    apply: bool = _cli.typer.Option(False, "--apply", help="把'恰一个候选'的提案写入别名表"),
) -> None:
    """别名自愈提案器(Roadmap C1):audit 缺口 → 对手推断(确定性,零LLM) → 人一键确认。

    双边都未解析的场推断不了,如实报出;多候选/零候选只报告不写入。
    `--issue`(2026-10-08):足彩截短名(「埃因霍」「西班人」)写进种子实体 aliases——
    前提卡与深研 brief 靠它找到画像与 store id。
    """
    from nutmeg.decision.alias_propose import run_propose, run_propose_zucai

    if issue:
        _cli.typer.echo(run_propose_zucai(issue, zucai_dir, apply=apply))
        return
    if not run_date:
        raise _cli.typer.BadParameter("需要 --run-date 或 --issue")
    _cli.typer.echo(run_propose(run_date, output_dir, apply=apply))


@_cli.app.command("zucai-night-calibrate")
def zucai_night_calibrate(
    issue: str = _cli.typer.Option(..., "--issue", help="期号 如 26111"),
    date: str = _cli.typer.Option(
        ..., "--date",
        help="竞彩板面日 YYYY-MM-DD(jc-results 的键;北京凌晨场归前一天板面)"),
    zucai_dir: Path = _ZUCAI_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
):
    """夜间结果校准:板面日 jc-results→身份链→90'彩果→票面存活(不写 rx/scoreboard)。"""
    import hashlib

    report = run_night_calibrate(issue, date, zucai_dir)
    _cli.typer.echo(report)
    if not dispatch_telegram:
        return
    from nutmeg.notifications.notify import notify

    outcome = notify(
        "zucai.night-calibration", f"{issue}:{date}",
        hashlib.sha256(report.encode("utf-8")).hexdigest(), report, dry_run=dry_run,
    )
    _cli.typer.echo(f"notification: {outcome.status}")
    if not outcome.is_success:
        raise _cli.typer.Exit(code=1)


_EXPORT_OUT_OPTION = _cli.typer.Option(None, "--out", help="不给则打印到 stdout")


def _kernel_state_factory(output_dir: Path):
    """回放的内核读侧（与 decision-web 同一份）：判读与实票活在内核与登记簿里，不在 jsonl。"""
    from datetime import UTC, datetime

    from nutmeg.config.settings import get_settings
    from nutmeg.interfaces.decision_web_kernel import kernel_day_state, slips_for_date
    from nutmeg.ontology.wiring import build_ontology_kernel
    from nutmeg.product.repository import ProductReadRepository

    kernel = build_ontology_kernel(get_settings())
    kernel.initialize()
    repository = ProductReadRepository(kernel.engine)
    data_dir = Path(output_dir).parent          # .nutmeg-data/jczq → .nutmeg-data
    return lambda date: kernel_day_state(
        repository, date, as_of=datetime.now(UTC),
        slips=slips_for_date(data_dir, data_dir / "zucai", date))


@_cli.app.command("workbench-export")
def workbench_export(
    date: str = _cli.typer.Option(..., "--date"),
    output_dir: Path = _OUTPUT_DIR_OPTION,
    out: Path | None = _EXPORT_OUT_OPTION,
) -> None:
    """事件流 → Markdown 复盘底稿(只排版不总结)。

    走与网页回放同一份合并流（内核判读/实票在先，文件事件在后）；只读文件流会把判读与
    实票漏成「（无）」——day.settle 每天导出昨天，10-05 的 5 张实票就这样丢了。
    """
    from nutmeg.decision.workbench import read_events
    from nutmeg.decision.workbench_export import events_to_markdown

    try:
        kernel_events = _kernel_state_factory(Path(output_dir))(date)["events"]
        events = ([e for e in kernel_events if e.get("kind") != "attention"]
                  + read_events(Path(output_dir), date))
    except Exception as exc:  # noqa: BLE001 — 内核不可达时仍出文件流底稿，但要说出来
        _cli.typer.echo(f"⚠️ 内核读侧不可用，回放只含文件事件：{exc}", err=True)
        events = None
    md = events_to_markdown(Path(output_dir), date, events=events)
    if out:
        Path(out).write_text(md, encoding="utf-8")
        _cli.typer.echo(f"→ {out}")
    else:
        _cli.typer.echo(md)
