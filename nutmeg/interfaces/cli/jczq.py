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
) -> None:
    """娱乐性质的竞彩串关组合生成器 — 非 edge、长期负期望。

    从盘面冲突 / 反直觉 / 热度信号挑「大胆腿」，拼 3/4/5 串 1。每个输出顶部
    焊死 🎲 娱乐硬标签。不预测胜负、不号称优势。
    """
    from datetime import date as _date_cls

    from nutmeg.services.jczq_bold_combos import replay_bold_combos

    target_date = replay_date or run_date or _date_cls.today().isoformat()
    try:
        rendered = replay_bold_combos(run_date=target_date, output_dir=output_dir)
    except FileNotFoundError as exc:
        _cli.console.print(str(exc))
        raise _cli.typer.Exit(code=2) from exc

    if write is not None:
        write.parent.mkdir(parents=True, exist_ok=True)
        write.write_text(rendered, encoding="utf-8")
        _cli.console.print(f"Wrote bold-combo plan: {write}")
        return
    _cli.typer.echo(rendered)


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
