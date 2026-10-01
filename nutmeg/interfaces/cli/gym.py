"""历史回放环境（假期迭代 #1）：`nutmeg gym prizes-cache / verify / run`。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import nutmeg.interfaces.cli as _cli

gym_app = _cli.typer.Typer(help="历史回放环境：决策规则在 134 个板面日 / 42 期上的精确账")
_cli.app.add_typer(gym_app, name="gym")
_DATA_DIR = _cli.typer.Option(Path(".nutmeg-data"), "--data-dir")
_PAGE_SIZE = _cli.typer.Option(130, "--page-size", help="官方历史页一次取几期")
_POLICY = _cli.typer.Option(..., "--policy", help="逗号分隔的策略名")
_FROM = _cli.typer.Option(None, "--from", help="起始板面日 YYYY-MM-DD")
_TO = _cli.typer.Option(None, "--to", help="截止板面日 YYYY-MM-DD")
_BELIEF = _cli.typer.Option("market", "--belief", help="market | closing | read")
_CAP_JCZQ = _cli.typer.Option(400, "--cap-jczq")
_CAP_ZUCAI = _cli.typer.Option(400, "--cap-zucai")
_OUT = _cli.typer.Option(None, "--out", help="输出目录（ledger.jsonl / summary.json / report.md）")


@gym_app.command("prizes-cache")
def gym_prizes_cache(
    data_dir: Path = _DATA_DIR,
    page_size: int = _PAGE_SIZE,
) -> None:
    """抓官方任九/胜负彩奖金与赛果串，缓存到 zucai/official-prizes.json（增量合并）。"""
    from nutmeg.gym.prizes import build_prize_cache, load_prizes

    path = build_prize_cache(Path(data_dir) / "zucai", page_size=page_size)
    issues = sorted(load_prizes(Path(data_dir) / "zucai"))
    _cli.typer.echo(f"缓存 {len(issues)} 期（{issues[0] if issues else '-'} → "
                    f"{issues[-1] if issues else '-'}）→ {path}")


@gym_app.command("verify")
def gym_verify(data_dir: Path = _DATA_DIR) -> None:
    """验收门：真票回放净额 vs 记分牌。可比键总差 > ¥1 → 退出码 1。"""
    from nutmeg.gym.verify import render_verify, verify_real

    out = verify_real(Path(data_dir))
    _cli.typer.echo(render_verify(out))
    if abs(out["total_diff_on_compared"]) > 1:
        raise _cli.typer.Exit(code=1)


@gym_app.command("run")
def gym_run(
    policy: str = _POLICY,
    date_from: str | None = _FROM,
    date_to: str | None = _TO,
    belief: str = _BELIEF,
    cap_jczq: int = _CAP_JCZQ,
    cap_zucai: int = _CAP_ZUCAI,
    out: Path | None = _OUT,
    data_dir: Path = _DATA_DIR,
) -> None:
    """在历史板面/期次上回放策略，打印账表。"""
    from nutmeg.gym.board import list_days, list_issues, load_zucai_issue
    from nutmeg.gym.policy import Ctx, names
    from nutmeg.gym.report import render
    from nutmeg.gym.run import run_gym

    policies = [p.strip() for p in policy.split(",") if p.strip()]
    unknown = [p for p in policies if p not in names()]
    if unknown:
        _cli.typer.echo(f"gym error: 未登记的策略 {unknown}；已登记：{names()}")
        raise _cli.typer.Exit(code=2)
    data_dir = Path(data_dir)
    days = [d for d in list_days(data_dir)
            if (not date_from or d >= date_from) and (not date_to or d <= date_to)]
    issues = []
    for issue in list_issues(data_dir):
        key = (load_zucai_issue(data_dir, issue).sale_deadline or "")[:10]
        if (not date_from or key >= date_from) and (not date_to or key <= date_to):
            issues.append(issue)
    run_id = out.name if out else datetime.now().strftime("gym-%Y%m%d-%H%M")
    ctx = Ctx(cap_jczq_day=cap_jczq, cap_zucai_slip=cap_zucai, belief_source=belief)
    result = run_gym(data_dir=data_dir, policies=policies, days=days, issues=issues, ctx=ctx,
                     out_dir=out, run_id=run_id)
    text = render(result)
    _cli.typer.echo(text)
    if out:
        (Path(out) / "report.md").write_text(text, encoding="utf-8")
        _cli.typer.echo(f"→ {Path(out) / 'report.md'}")
