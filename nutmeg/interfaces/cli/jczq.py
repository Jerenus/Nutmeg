"""JCZQ (竞彩足球) CLI commands.

M2 cutover (2026-07-07): the v1/v2 daily analysis engine (jczq-tiered / -today /
-daily-* / -debate-* / -mixed-report / -radar / -web / -replay / -final-plan-pdf /
-judge-reconcile / -tiered-review) has been retired — the decision-* pipeline
(cli/decision.py) is the sole daily path. Only ``jczq-report`` remains here: it
renders the 世界杯 PDF 日报 from已落盘 files and is still driven by the launchd
``wc-report-20`` task until the world-cup handoff (plan Task 8).

Command functions register on the shared ``nutmeg.interfaces.cli.app`` via
``@_cli.app.command()``; every CLI-package global is reached through ``_cli``.
"""
from __future__ import annotations

import nutmeg.interfaces.cli as _cli


def _resolve_jczq_date(value: str | None) -> str:
    """Resolve a ``--date`` value to an ISO date.

    ``None`` / ``"today"`` → today, ``"yesterday"`` → yesterday (both in the
    JCZQ timezone, Asia/Shanghai); an explicit ``YYYY-MM-DD`` passes through.
    Without this the literal string ``"today"`` reaches the report as the run
    date and the daily directory resolves to ``daily/today/``."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if value is None or value == "today":
        return today.isoformat()
    if value == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    return value


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
