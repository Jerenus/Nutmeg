"""JCZQ (竞彩足球) CLI commands.

Command functions live here and register on the shared
``nutmeg.interfaces.cli.app`` via ``@_cli.app.command()``. Every CLI-package
global (factories, helpers, options, re-exported imports) is reached through
``_cli`` so behaviour — including test monkeypatches on the ``cli`` package —
is identical to the pre-split single-module layout.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli

JCZQ_DAILY_BRIEF_WRITE_OPTION = _cli.typer.Option(
    None, "--write", help="写入文件（默认 stdout）"
)


@_cli.app.command("jczq-mixed-report")
def jczq_mixed_report(
    provider: str = _cli.JCZQ_PROVIDER_OPTION,
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    pdf: bool = _cli.typer.Option(False, "--pdf"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    if provider.strip().casefold() == "live":
        _cli.console.print(
            "jczq-mixed-report live mode is retired. Use "
            "`nutmeg jczq-daily-brief --write .nutmeg-data/jczq/daily/$(date +%F)/brief.md`, "
            "then `nutmeg jczq-debate-init` / `nutmeg jczq-debate-finalize` / "
            "`nutmeg jczq-final-plan-pdf` for the current daily workflow."
        )
        raise _cli.typer.Exit(code=2)
    try:
        service = _cli.build_jczq_mixed_report_service(provider=provider)
        report = service.build_report(
            output_dir=output_dir,
            render_pdf=pdf or dispatch_telegram,
            dispatch_telegram=dispatch_telegram,
            dry_run=dry_run,
        )
    except (_cli.JczqProviderError, _cli.JczqSelectionError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(
        f"jczq-mixed-report combos={len(report.combinations)} "
        f"official_update={report.official_last_update}"
    )
    _cli.console.print(f"markdown={report.artifacts.markdown_path}")
    if report.artifacts.pdf_path:
        _cli.console.print(f"pdf={report.artifacts.pdf_path}")
    _cli.console.print(f"dispatch={report.dispatch.status}")
    for combo in report.combinations:
        _cli.console.print(
            f" - {combo.name}: odds={combo.total_odds:.2f} 2元={combo.two_yuan_return:.2f}"
        )


_V1_DEPRECATION_BANNER = (
    "⚠️  v1 Poisson generator (jczq-daily-advisor / -brief / -mixed-report) is "
    "DEPRECATED.\n"
    "    每日决策唯一入口 = `nutmeg jczq-today`（spec §32，单一决策包 + 钉死指令）。\n"
    "    底层 live 引擎是 jczq-tiered；次晨复盘用 jczq-tiered-review。\n"
    "    本命令仅作历史参考，勿用于每日决策（背景见 docs/jczq-decision-chain-critique.md）。\n"
)


@_cli.app.command("jczq-daily-advisor")
def jczq_daily_advisor(
    provider: str = _cli.JCZQ_PROVIDER_OPTION,
    run_date: str = _cli.JCZQ_DAILY_DATE_OPTION,
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    revision_text: str | None = _cli.typer.Option(None, "--revision-text"),
    record_final: bool = _cli.typer.Option(True, "--record-final/--no-record-final"),
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _cli.console.print(_V1_DEPRECATION_BANNER)
    try:
        service = _cli.build_jczq_daily_advisor_service(provider=provider)
        if revision_text:
            report = service.revise(
                run_date=run_date,
                output_dir=output_dir,
                instruction=revision_text,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                record_final=record_final,
            )
        else:
            report = service.build_report(
                run_date=run_date,
                output_dir=output_dir,
                dispatch_telegram=dispatch_telegram,
                dry_run=dry_run,
                record_final=record_final,
            )
    except (_cli.JczqDailyAdvisorError, _cli.JczqProviderError, _cli.JczqSelectionError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    payload = report.to_dict()
    if format == "json":
        _cli.typer.echo(_cli.json.dumps(payload, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(service.render_message(report))


@_cli.app.command("jczq-daily-review")
def jczq_daily_review(
    run_date: str = _cli.typer.Option("yesterday", "--date"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(False, "--dispatch-telegram"),
    dry_run: bool = _cli.typer.Option(True, "--dry-run/--no-dry-run"),
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    _cli.console.print(_V1_DEPRECATION_BANNER)
    service = _cli.build_jczq_daily_review_service()
    report = service.build_review(
        run_date=run_date,
        output_dir=output_dir,
        dispatch_telegram=dispatch_telegram,
        dry_run=dry_run,
    )

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(report, indent=2, sort_keys=True, default=str))
        return

    _cli.console.print(str(report.get("message") or ""))


@_cli.app.command("jczq-debate-init")
def jczq_debate_init(
    run_date: str = _cli.typer.Option("today", "--date"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_jczq_debate_workspace_service()
    try:
        result = service.initialize_workspace(run_date=run_date, output_dir=output_dir)
    except _cli.JczqDebateWorkspaceError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"jczq-debate-init date={result['run_date']}")
    _cli.console.print(f"debate_dir={result['debate_dir']}")
    for path in result.get("artifacts", {}).values():
        _cli.console.print(f"- {path}")


@_cli.app.command("jczq-debate-compare")
def jczq_debate_compare(
    run_date: str = _cli.typer.Option("today", "--date"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_jczq_debate_workspace_service()
    result = service.compare_workspace(run_date=run_date, output_dir=output_dir)

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"jczq-debate-compare date={result['run_date']}")
    _cli.console.print(f"consensus={len(result['consensus_legs'])}")
    _cli.console.print(f"conflicts={', '.join(result['conflict_matches']) or '-'}")
    _cli.console.print(f"disagreements={result['artifacts']['disagreements_path']}")


@_cli.app.command("jczq-debate-finalize")
def jczq_debate_finalize(
    run_date: str = _cli.typer.Option("today", "--date"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    service = _cli.build_jczq_debate_workspace_service()
    result = service.finalize_workspace(run_date=run_date, output_dir=output_dir)

    if format == "json":
        _cli.typer.echo(_cli.json.dumps(result, indent=2, sort_keys=True, default=str))
        return
    _cli.console.print(f"jczq-debate-finalize date={result['run_date']}")
    _cli.console.print(f"final_plan={result['final_plan_path']}")
    if result.get("structured_plan"):
        _cli.console.print(
            f"final_plan_json={result['artifacts']['final_plan_json_path']} "
            "(PDF-ready · jczq-final-plan-pdf can render)"
        )
    else:
        _cli.console.print(
            "final_plan_json=thin metadata only — author "
            f"{result['artifacts']['final_plan_input_path']} "
            "(ticket skeleton) then re-run finalize for a PDF-ready plan"
        )


@_cli.app.command("jczq-daily-brief")
def jczq_daily_brief(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD，默认今天 live"
    ),
    replay_date: str | None = _cli.typer.Option(None, "--replay", help="从已存 context.json 回放"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    write: _cli.Path | None = JCZQ_DAILY_BRIEF_WRITE_OPTION,
) -> None:
    from nutmeg.services.jczq_brief import build_brief, today_iso, write_or_print_brief
    from nutmeg.services.jczq_conflict_bridge import record_conflict_signals

    # Wire the value/conflict engine: align the day's JCZQ matches to
    # API-Football, run ValueBoardService, render the real 赔率冲突点 section.
    # No key / API down / empty alignment → bridge is None → placeholder.
    brief_date = replay_date or run_date or today_iso()
    value_bridge = _cli._build_jczq_value_bridge_for_brief(brief_date)

    try:
        markdown = build_brief(
            run_date=run_date,
            replay_date=replay_date,
            output_dir=output_dir,
            service_builder=_cli.build_jczq_daily_advisor_service,
            value_bridge=value_bridge,
        )
    except FileNotFoundError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    # Self-validation loop: persist the day's conflict signals so next-day
    # jczq-daily-review grades them and the stake ladder accrues a track record.
    if value_bridge is not None:
        try:
            recorded = record_conflict_signals(
                value_bridge=value_bridge,
                run_date=brief_date,
                output_dir=output_dir,
            )
            if recorded:
                _cli.console.print(f"recorded {recorded} conflict signal(s)", style="dim")
        except Exception:  # noqa: BLE001 — store failure must not break the brief
            _cli.logger.warning("conflict-signal recording failed", exc_info=True)

    write_or_print_brief(markdown, write)


@_cli.app.command("jczq-second-leg")
def jczq_second_leg(
    run_date: str = _cli.typer.Option(..., "--date", help="目标日期 YYYY-MM-DD"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    solo: str | None = _cli.typer.Option(
        None,
        "--solo",
        help="单核腿 '<match_no> <pool> <pick>'，例如 '周三003 crs 0:0'",
    ),
    auto: bool = _cli.typer.Option(False, "--auto", help="从 final-plan.json 自动读取单核腿"),
    top: int = _cli.typer.Option(8, "--top", help="输出前 N 个候选"),
) -> None:
    from datetime import date as _date_cls

    from nutmeg.services.jczq_second_leg import parse_solo, suggest_second_legs

    if not auto and not solo:
        _cli.console.print("必须提供 --solo 或 --auto")
        raise _cli.typer.Exit(code=2)

    resolved_date = _date_cls.today().isoformat() if run_date == "today" else run_date
    try:
        solo_tuple = parse_solo(solo) if (solo and not auto) else None
        rendered = suggest_second_legs(
            run_date=resolved_date,
            output_dir=output_dir,
            solo=solo_tuple,
            auto=auto,
            top=top,
        )
    except (FileNotFoundError, ValueError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    _cli.typer.echo(rendered)


@_cli.app.command("jczq-final-plan-pdf")
def jczq_final_plan_pdf(
    run_date: str = _cli.typer.Option("today", "--date", help="目标日期 YYYY-MM-DD 或 today"),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    dispatch: bool = _cli.typer.Option(False, "--dispatch", help="渲染后通过 Telegram bot 推送"),
    telegram_token: str | None = _cli.typer.Option(
        None, "--telegram-token", help="覆盖 NUTMEG_TELEGRAM_BOT_TOKEN"
    ),
    telegram_chat_ids: str | None = _cli.typer.Option(
        None,
        "--telegram-chat-ids",
        help="覆盖 NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS，逗号分隔",
    ),
) -> None:
    from datetime import date as _date_cls

    from nutmeg.services.jczq_final_plan_pdf import render_and_dispatch

    resolved_date = _date_cls.today().isoformat() if run_date == "today" else run_date
    chat_ids = (
        [int(x.strip()) for x in telegram_chat_ids.split(",") if x.strip()]
        if telegram_chat_ids
        else None
    )

    try:
        result = render_and_dispatch(
            run_date=resolved_date,
            output_dir=output_dir,
            dispatch=dispatch,
            telegram_token=telegram_token,
            telegram_chat_ids=chat_ids,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    _cli.console.print(f"Wrote PDF: {result.pdf_path} ({result.pdf_bytes} bytes)")
    if result.skipped_dispatch_reason:
        _cli.console.print(f"(skipped dispatch: {result.skipped_dispatch_reason})")
        return
    for chat_id in result.dispatched_chat_ids:
        _cli.console.print(f"Dispatched PDF to chat_id={chat_id}")


@_cli.app.command("jczq-replay")
def jczq_replay(
    run_date: str = _cli.typer.Option("2026-05-03", "--date", help="回放的目标日期"),
    input_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    format: str = _cli.typer.Option("text", "--format", help="text or json"),
) -> None:
    from nutmeg.services.jczq_replay import replay_with_new_generator

    try:
        result = replay_with_new_generator(run_date=run_date, input_dir=input_dir)
    except FileNotFoundError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    if format == "json":
        _cli.typer.echo(
            _cli.json.dumps(
                {
                    "run_date": result.run_date,
                    "match_count": result.match_count,
                    "legs": [
                        {
                            "plan": r.plan,
                            "match_no": r.match_no,
                            "pool": r.pool,
                            "pick": r.pick,
                            "odds": r.odds,
                            "actual": r.actual,
                            "hit": r.hit,
                        }
                        for r in result.leg_rows
                    ],
                },
                indent=2,
                sort_keys=True,
                default=str,
            )
        )
        return

    _cli.typer.echo(result.rendered_text)


def _resolve_jczq_date(value: str | None) -> str:
    """Resolve a ``--date`` / ``--replay`` value to an ISO date.

    ``None`` / ``"today"`` → today, ``"yesterday"`` → yesterday (both in the
    JCZQ timezone, Asia/Shanghai — consistent with the review pipeline); an
    explicit ``YYYY-MM-DD`` passes through unchanged. Without this the literal
    string ``"today"`` reaches the engine as the run date and the Sporttery
    ``businessDate`` filter matches nothing (and the snapshot lands in a
    ``daily/today/`` directory)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if value is None or value == "today":
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return value


def _dispatch_jczq_telegram(rendered: str, *, dry_run: bool) -> str:
    """Push a rendered JCZQ message (bold plan or bold review) to the configured
    Telegram chats.

    Mirrors the advisor/review dispatch seam — dry-run by default, the welded
    🎲 honest label rides along untouched at the top of the message. Returns a
    short honest status string (never raises into the CLI)."""
    from nutmeg.services.jczq_review import _telegram_chunks

    settings = _cli.get_settings()
    chat_ids = sorted(
        _cli.parse_telegram_allowed_chat_ids(settings.telegram_allowed_chat_ids)
    )
    if dry_run:
        return f"dry_run · chat_ids={chat_ids}"
    if not settings.telegram_bot_token or not chat_ids:
        return "skipped · telegram 未配置"
    sender = _cli.TelegramBotClient(
        token=settings.telegram_bot_token,
        base_url=settings.telegram_api_base_url,
    )
    try:
        for chat_id in chat_ids:
            for chunk in _telegram_chunks(rendered):
                sender.send_message(chat_id=chat_id, text=chunk)
    except Exception as exc:  # noqa: BLE001 — network seam; report, never crash
        return f"failed · {exc}"
    return f"sent · chat_ids={chat_ids}"


@_cli.app.command("jczq-bold-combos")
def jczq_bold_combos(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD（live，默认今天）"
    ),
    replay_date: str | None = _cli.typer.Option(
        None, "--replay", help="从已存 context.json 回放"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    write: _cli.Path | None = JCZQ_DAILY_BRIEF_WRITE_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把方案推送到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不实际推送（默认开）"
    ),
) -> None:
    """娱乐性质的竞彩串关组合生成器 — 非 edge、长期负期望。

    从盘面冲突 / 反直觉 / 热度信号挑「大胆腿」，拼 3/4/5 串 1。每个输出顶部
    焊死 🎲 娱乐硬标签。不预测胜负、不号称优势。

    ``--dispatch-telegram --no-dry-run`` 把方案推到 Telegram —— 每日 launchd
    自动流走这条（com.nutmeg.jczq.daily-bold）。
    """
    from nutmeg.services.jczq_bold_combos import run_bold_combos_multimarket

    target_date = _resolve_jczq_date(replay_date or run_date)
    try:
        rendered = run_bold_combos_multimarket(
            target_date, output_dir, replay=replay_date is not None
        )
    except FileNotFoundError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(rendered, encoding="utf-8")
        _cli.console.print(f"Wrote bold-combo plan: {write}")

    if dispatch_telegram:
        status = _dispatch_jczq_telegram(rendered, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")

    if write is None and not dispatch_telegram:
        _cli.typer.echo(rendered)


@_cli.app.command("jczq-bold-review")
def jczq_bold_review(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="复盘日期 YYYY-MM-DD / today / yesterday（默认昨天）"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把复盘推送到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不实际推送（默认开）"
    ),
) -> None:
    """bold 大胆票的次日赛后复盘 — 用 §14 快照复现票面、对 okooo 赛果定级。

    赛后对照，只报命中 / 未中 + 累计趋势，不预测、不号称优势。每日 launchd
    自动流走这条（com.nutmeg.jczq.bold-review-8am）。
    """
    from nutmeg.services.jczq_bold_review import run_bold_review

    target_date = _resolve_jczq_date(run_date or "yesterday")
    review = run_bold_review(target_date, output_dir)

    if dispatch_telegram:
        status = _dispatch_jczq_telegram(review.message, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")
    else:
        _cli.typer.echo(review.message)


@_cli.app.command("jczq-tiered")
def jczq_tiered(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD（live，默认今天）"
    ),
    replay_date: str | None = _cli.typer.Option(
        None, "--replay", help="从已存快照回放"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    stake_multiplier: float = _cli.typer.Option(
        1.0, "--stake-multiplier", help="金额缩放（1.0=¥35/35/20/10）"
    ),
    write: _cli.Path | None = JCZQ_DAILY_BRIEF_WRITE_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把方案推到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不推送"
    ),
) -> None:
    """codex-style v2 — 4 档 A/B/D/E 风险分层方案（spec 2026-05-25）.

    替代 bold-combos v1。每日 launchd 自动流走这条
    (com.nutmeg.jczq.daily-tiered)。
    """
    import logging

    from nutmeg.services.jczq_bold_combos import (
        bold_matches_from_sporttery,
        fetch_sporttery_value_with_fallback,
        load_bold_odds_snapshot,
        load_sporttery_snapshot,
        persist_bold_odds_snapshot,
        persist_sporttery_snapshot,
    )
    from nutmeg.services.jczq_tiered import (
        compute_d_poisson_edge_index,
        render_tiered_plan,
        select_tiered_plan,
    )
    from nutmeg.services.jczq_tiered_review import (
        load_cross_version_history_dict,
    )

    logger = logging.getLogger(__name__)
    target_date = _resolve_jczq_date(replay_date or run_date)
    replay = replay_date is not None

    value: dict | None = None
    bold_odds: dict[str, dict] = {}
    if replay:
        value = load_sporttery_snapshot(target_date, output_dir)
        if value is None:
            _cli.console.print(f"no snapshot for {target_date}")
            raise _cli.typer.Exit(code=2)
        bold_odds = load_bold_odds_snapshot(target_date, output_dir)
    else:
        value, board_source = fetch_sporttery_value_with_fallback()
        if board_source != "sporttery":
            _cli.console.print(
                "⚠️ sporttery 主源不可用，已回退 500.com 备源（仅 had/hhad 池）"
            )
        persist_sporttery_snapshot(target_date, output_dir, value)
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001 — 国际 odds optional; degrade
            logger.warning(
                "jczq-tiered: 国际 odds enrichment failed", exc_info=True
            )
        if bold_odds:
            persist_bold_odds_snapshot(target_date, output_dir, bold_odds)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=target_date, bold_odds=bold_odds
    )
    history = load_cross_version_history_dict(output_dir)
    # spec §27.1 — compute direct Poisson edges once per day for D filtering.
    poisson_edge_index = compute_d_poisson_edge_index(matches)
    plan = select_tiered_plan(
        matches,
        history=history,
        multiplier=stake_multiplier,
        run_date=target_date,
        poisson_edge_index=poisson_edge_index,
    )
    rendered = render_tiered_plan(plan)

    daily_dir = output_dir / "daily" / target_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    # spec §26.4 — replay must never overwrite the originally dispatched plan;
    # next-day review depends on the saved markdown to grade exactly what
    # was shown to the operator, not what newer rules would produce.
    if not replay:
        (daily_dir / "tiered-plan.md").write_text(rendered, encoding="utf-8")

    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(rendered, encoding="utf-8")
        _cli.console.print(f"Wrote tiered plan: {write}")

    if dispatch_telegram:
        status = _dispatch_jczq_telegram(rendered, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")

    if write is None and not dispatch_telegram:
        _cli.typer.echo(rendered)


def _match_nos(value: dict | None) -> set[str]:
    """体彩快照里的场次编号集合。

    真实结构（对齐 ``bold_matches_from_sporttery`` 的解析口径）：
    ``matchInfoList``（按日分组）→ ``subMatchList`` → ``matchNumStr``。
    """
    if not value:
        return set()
    return {
        str(raw.get("matchNumStr", ""))
        for day in value.get("matchInfoList") or []
        for raw in day.get("subMatchList") or []
    } - {""}


def _board_changed(old: dict | None, new: dict | None) -> bool:
    """场次集合变化才算变(worldcup spec §6.1)— 赔率微动不触发重出包。

    旧快照缺失（``None``）一律视为有变化：当天首次刷新必须出包。
    """
    if old is None:
        return True
    return _match_nos(old) != _match_nos(new)


@_cli.app.command("jczq-today")
def jczq_today(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD（live，默认今天）"
    ),
    replay_date: str | None = _cli.typer.Option(
        None, "--replay", help="从已存快照回放"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    stake_multiplier: float = _cli.typer.Option(
        1.0, "--stake-multiplier", help="金额缩放（1.0=¥35/35/20/10）"
    ),
    write: _cli.Path | None = JCZQ_DAILY_BRIEF_WRITE_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把决策包推到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不推送"
    ),
    refresh_check: bool = _cli.typer.Option(
        False, "--refresh-check",
        help="盘面刷新检查:场次集合无变化则静默退出,变化才重出包(18:00 任务用)",
    ),
) -> None:
    """spec §32 — 单一决策入口：tiered 票面 + 盘面底座 + 有界裁量问题。

    这是 agent（GPT/Claude）跑每日 jczq 任务**唯一**该跑的命令——决策包内含钉死
    指令，把无界即兴压成有界提问。不重造票面（§A 复用 jczq-tiered 引擎）。
    """
    import logging

    from nutmeg.services.jczq_bold_combos import (
        bold_matches_from_sporttery,
        fetch_sporttery_value_with_fallback,
        load_bold_odds_snapshot,
        load_sporttery_snapshot,
        persist_bold_odds_snapshot,
        persist_sporttery_snapshot,
    )
    from nutmeg.services.jczq_tiered import (
        compute_d_poisson_edge_index,
        render_tiered_plan,
        select_tiered_plan,
    )
    from nutmeg.services.jczq_tiered_review import (
        load_cross_version_history_dict,
    )
    from nutmeg.services.jczq_today import render_today_packet

    logger = logging.getLogger(__name__)
    target_date = _resolve_jczq_date(replay_date or run_date)
    replay = replay_date is not None

    value: dict | None = None
    bold_odds: dict[str, dict] = {}
    if replay:
        value = load_sporttery_snapshot(target_date, output_dir)
        if value is None:
            _cli.console.print(f"no snapshot for {target_date}")
            raise _cli.typer.Exit(code=2)
        bold_odds = load_bold_odds_snapshot(target_date, output_dir)
    else:
        value, board_source = fetch_sporttery_value_with_fallback()
        if board_source != "sporttery":
            _cli.console.print(
                "⚠️ sporttery 主源不可用，已回退 500.com 备源（仅 had/hhad 池）"
            )
        # worldcup spec §6.1 — 18:00 盘面刷新检查：场次集合无变化 → 静默退出，
        # 不重出包、不覆盖当天已派发快照；有变化才继续走完整出包流程。
        # 放在 persist 之前：fetch 对空壳响应已 raise（绝不静默假空盘），到这里
        # value 必非空，与 persist_sporttery_snapshot 的防覆盖守卫互不冲突。
        if refresh_check:
            old_value = load_sporttery_snapshot(target_date, output_dir)
            if not _board_changed(old_value, value):
                _cli.console.print("refresh-check: 盘面无变化,静默退出")
                return
            _cli.console.print("refresh-check: 盘面有更新,重出决策包")
        persist_sporttery_snapshot(target_date, output_dir, value)
        # 国际 odds：API-Football 主源（12 家博彩、可靠），500.com 仅补 API-Football
        # 没盖到的场/盘口（友谊赛深夜场、它无大小球等）。只换数据源槽位，不动选腿。
        from nutmeg.services.jczq_apifootball_odds import (
            collect_bold_odds_apifootball_live,
            merge_bold_odds,
        )

        try:
            bold_odds = collect_bold_odds_apifootball_live(
                value, run_date=target_date
            )
        except Exception:  # noqa: BLE001 — 国际 odds optional; degrade
            logger.warning(
                "jczq-today: API-Football 国际 odds 失败", exc_info=True
            )
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                fcom_odds = collect_bold_odds(client)
            bold_odds = merge_bold_odds(bold_odds, fcom_odds)
        except Exception:  # noqa: BLE001 — 500.com 备源 optional; degrade
            logger.warning(
                "jczq-today: 500.com 备源 enrichment failed", exc_info=True
            )
        if bold_odds:
            persist_bold_odds_snapshot(target_date, output_dir, bold_odds)

    matches = bold_matches_from_sporttery(
        value or {}, run_date=target_date, bold_odds=bold_odds
    )
    history = load_cross_version_history_dict(output_dir)
    poisson_edge_index = compute_d_poisson_edge_index(matches)
    plan = select_tiered_plan(
        matches,
        history=history,
        multiplier=stake_multiplier,
        run_date=target_date,
        poisson_edge_index=poisson_edge_index,
    )
    # 世界杯专题层(worldcup spec §1):窗口外 layer=None,包与现状逐字节一致。
    wc_section: str | None = None
    wc_extra_questions: list = []
    try:
        from nutmeg.services.worldcup import run_worldcup_layer

        layer = run_worldcup_layer(
            run_date=target_date, matches=matches,
            output_dir=output_dir, replay=replay,
        )
        if layer is not None:
            wc_section = layer.section_md
            wc_extra_questions = layer.extra_questions
    except Exception:  # noqa: BLE001 — 专题层 optional; degrade
        logger.warning("jczq-today: 世界杯层失败,§E 缺席", exc_info=True)

    rendered = render_today_packet(
        plan, matches, poisson_edge_index,
        wc_section=wc_section, extra_questions=wc_extra_questions,
    )

    daily_dir = output_dir / "daily" / target_date
    daily_dir.mkdir(parents=True, exist_ok=True)
    # spec §26.4 / §32.1 — replay must never overwrite the dispatched packet.
    if not replay:
        (daily_dir / "today-packet.md").write_text(rendered, encoding="utf-8")
        # spec §32.1 — also persist tiered-plan.md so jczq-tiered-review grades
        # exactly the §A plan that was dispatched (§26.4). Lets jczq-today be the
        # sole daily launchd job while next-morning review keeps working unchanged.
        (daily_dir / "tiered-plan.md").write_text(
            render_tiered_plan(plan), encoding="utf-8"
        )

    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(rendered, encoding="utf-8")
        _cli.console.print(f"Wrote decision packet: {write}")

    if dispatch_telegram:
        payload = rendered
        if refresh_check:
            # worldcup spec §6.1 — 刷新出的包显式声明取代中午版本。
            payload = "⚠️ 盘面有更新(18:00 刷新)——以本包为准\n\n" + payload
        status = _dispatch_jczq_telegram(payload, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")

    if write is None and not dispatch_telegram:
        _cli.typer.echo(rendered)


@_cli.app.command("jczq-radar")
def jczq_radar(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD（live，默认今天）"
    ),
    replay_date: str | None = _cli.typer.Option(
        None, "--replay", help="从已存快照回放"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
) -> None:
    """spec §35 — 机会雷达：多视角透镜扫盘（反面/异动/大小球/平局/分歧）。

    挑出 tiered A 档"热门焊死"会撤退的机会：pick'em/灌水站反面、欧赔 steam、
    大小球错价、平局价值、高分歧软盘。非 edge、读盘视角。与 jczq-today 的 §D 同源。
    带欧赔（live 抓 fcom500）时信号最全；replay 老快照可能无欧赔。
    """
    from nutmeg.services.jczq_bold_combos import (
        bold_matches_from_sporttery,
        load_bold_odds_snapshot,
        load_sporttery_snapshot,
    )
    from nutmeg.services.jczq_opportunity import (
        render_opportunity_radar,
        scan_opportunities,
    )

    target_date = _resolve_jczq_date(replay_date or run_date)
    bold_odds: dict[str, dict] = {}
    if replay_date is not None:
        value = load_sporttery_snapshot(target_date, output_dir)
        if value is None:
            _cli.console.print(f"no snapshot for {target_date}")
            raise _cli.typer.Exit(code=2)
        bold_odds = load_bold_odds_snapshot(target_date, output_dir)
    else:
        from nutmeg.services.jczq import SportteryJczqCalculatorProvider

        fetched = SportteryJczqCalculatorProvider().fetch()
        value = fetched.get("value") if "value" in fetched else fetched
        try:
            from nutmeg.data.fcom500 import Fcom500Client, collect_bold_odds

            with Fcom500Client() as client:
                bold_odds = collect_bold_odds(client)
        except Exception:  # noqa: BLE001 — 欧赔可选；无则仅结构信号
            bold_odds = {}

    matches = bold_matches_from_sporttery(
        value or {}, run_date=target_date, bold_odds=bold_odds
    )
    _cli.typer.echo(render_opportunity_radar(scan_opportunities(matches)))


@_cli.app.command("jczq-tiered-review")
def jczq_tiered_review(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="复盘日期 YYYY-MM-DD / today / yesterday（默认昨天）"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把复盘推到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不推送"
    ),
) -> None:
    """v2 tiered-plan 次日复盘 — 4 档独立 grading + 累计趋势 + 跨版本 §24.

    每日 launchd 自动流走这条 (com.nutmeg.jczq.tiered-review-8am)。
    """
    from nutmeg.services.jczq_tiered_review import run_tiered_review

    target_date = _resolve_jczq_date(run_date or "yesterday")
    review = run_tiered_review(target_date, output_dir)

    if dispatch_telegram:
        status = _dispatch_jczq_telegram(review.message, dry_run=dry_run)
        _cli.console.print(f"Telegram dispatch: {status}")
    else:
        _cli.typer.echo(review.message)


@_cli.app.command("jczq-web")
def jczq_web(
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    host: str = _cli.typer.Option("127.0.0.1", "--host"),
    port: int = _cli.typer.Option(8765, "--port"),
) -> None:
    import uvicorn

    from nutmeg.interfaces.jczq_web import create_jczq_web_app
    from nutmeg.services.jczq_web import JczqWebCockpitService
    from nutmeg.storage.jczq_web_repository import JczqWebRepository

    repository = JczqWebRepository(_cli.Path(output_dir) / "jczq-web.sqlite3")
    repository.initialize()
    service = JczqWebCockpitService(output_dir=output_dir, repository=repository)
    uvicorn.run(create_jczq_web_app(service=service), host=host, port=port)


@_cli.app.command("jczq-report")
def jczq_report(
    run_date: str | None = _cli.typer.Option(
        None, "--date", help="目标日期 YYYY-MM-DD(默认今天)"
    ),
    output_dir: _cli.Path = _cli.JCZQ_OUTPUT_DIR_OPTION,
    if_missing: bool = _cli.typer.Option(
        False, "--if-missing", help="当日 PDF 已存在则跳过(20:00 兜底任务用)"
    ),
    review_pdf: bool = _cli.typer.Option(
        False, "--review-pdf", help="只渲染迷你战报(08:00 复盘任务用)"
    ),
    dispatch_telegram: bool = _cli.typer.Option(
        False, "--dispatch-telegram", help="把 PDF 推到 Telegram"
    ),
    dry_run: bool = _cli.typer.Option(
        True, "--dry-run/--no-dry-run", help="dry-run 时不推送"
    ),
) -> None:
    """worldcup spec §5 — 世界杯 PDF 日报:决策完成后的收尾渲染,绝不重新决策。

    全部从落盘文件合成(决策包/裁量答案/sim/复盘);缺哪节标注哪节。
    """
    import os

    from nutmeg.services.worldcup.report_data import build_daily_report
    from nutmeg.services.worldcup.report_pdf import (
        render_daily_pdf,
        render_review_pdf,
    )

    target_date = _resolve_jczq_date(run_date)
    daily_dir = output_dir / "daily" / target_date
    filename = "wc-review-report.pdf" if review_pdf else "wc-daily-report.pdf"
    pdf_path = daily_dir / filename
    if if_missing and pdf_path.exists():
        _cli.console.print(f"{filename} 已存在,跳过(--if-missing)")
        return

    # judge spec §2.1 — 渲染前对账最近 3 天判定(幂等,pending 自动补结)
    try:
        from nutmeg.services.worldcup.judge_ledger import reconcile_recent

        reconcile_recent(output_dir, today=target_date)
    except Exception:  # noqa: BLE001 — 记分失败不阻塞报告(spec §5)
        import logging

        logging.getLogger(__name__).warning("judge ledger 对账失败", exc_info=True)

    report = build_daily_report(target_date, output_dir)
    if review_pdf:
        render_review_pdf(report, pdf_path)
    else:
        render_daily_pdf(report, pdf_path)
    _cli.console.print(f"Wrote PDF: {pdf_path}")

    if dispatch_telegram and not dry_run:
        from nutmeg.interfaces.bot.telegram import TelegramBotClient

        token = os.environ.get("NUTMEG_TELEGRAM_BOT_TOKEN")
        chat_raw = os.environ.get("NUTMEG_TELEGRAM_ALLOWED_CHAT_IDS", "")
        if not token or not chat_raw:
            _cli.console.print("Telegram 凭据缺失,跳过推送")
            raise _cli.typer.Exit(code=1)
        caption = (
            f"🏆 世界杯日报 · {target_date} · {report.stage_label}"
            + ("(裁量未作答,兜底版)" if report.answers is None and not review_pdf
               else "")
        )
        client = TelegramBotClient(token=token)
        for chat_id in (int(c) for c in chat_raw.split(",") if c.strip()):
            client.send_document(chat_id=chat_id, document_path=pdf_path,
                                 caption=caption)
        _cli.console.print("Telegram dispatch: sent")
    elif dispatch_telegram:
        _cli.console.print("Telegram dispatch: dry-run skipped")
