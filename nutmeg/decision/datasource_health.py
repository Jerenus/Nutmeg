"""数据底座健康度 —— 换源后「健康可持续」的可执行判据。

换源把国际欧赔从有配额、覆盖 50% 的源换成无配额、覆盖 100% 的源。但「今天跑通了」
不等于「可持续」:端点会改版、板面会变大、共识会因书目流失而缩水、CLV 轴会因收盘那
一抓失手而重新饿回去。本模块把这些做成**能变红的检查**,而不是一段说它很好的散文。

每项检查只回答「是/否 + 证据」,绝不自动修复——静默自愈会把退化藏起来,而退化正是
需要被看见的东西。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "HealthCheck",
    "clv_fill_check",
    "coverage_check",
    "freshness_check",
    "render_health",
    "run_health",
    "verdict_of",
]

# 覆盖率地板:换源后 8 天回放 + 当日实测都是 100%,任何缺口都值得看一眼。
_COVERAGE_FLOOR = 1.0
# 读时快照与收盘快照的比值地板。换源前是 122/2264 = 5.4%,CLV 轴因此饿着:
# 970 条已结 Read 只有 69 条有 clv_pp,而因子生死是双轴判定——一个喂不饱的轴
# 让整条规则即使样本够了也判不准。
_CLV_FILL_FLOOR = 0.8

# CLV 填充率只看近窗口。全历史比值被换源前的存量主导,即使今后每天满格也要好几个月
# 才转绿——一个永远红的检查会被忽略,等于没有检查。近窗口才能立刻反映「收盘那一抓
# 今天是不是还在工作」。全历史数字仍作为上下文印出来,不参与判定。
_CLV_WINDOW_DAYS = 14


@dataclass(frozen=True, slots=True)
class HealthCheck:
    name: str
    ok: bool
    detail: str = ""
    value: str = ""


def verdict_of(checks: list[HealthCheck]) -> str:
    """整体结论。无检查 → ``unknown``(不是 healthy——没测过不等于没问题)。"""
    if not checks:
        return "unknown"
    return "healthy" if all(c.ok for c in checks) else "degraded"


def coverage_check(*, board: int, covered: int) -> HealthCheck:
    """国际欧赔覆盖率。空板面判 not ok——无法据此确认健康。"""
    if board <= 0:
        return HealthCheck(
            name="欧赔覆盖", ok=False, value="0/0",
            detail="板面为空,无法确认覆盖健康(可能是抓取失败而非真无赛事)",
        )
    ratio = covered / board
    return HealthCheck(
        name="欧赔覆盖", ok=ratio >= _COVERAGE_FLOOR,
        value=f"{covered}/{board} ({ratio:.0%})",
        detail="" if ratio >= _COVERAGE_FLOOR else f"低于地板 {_COVERAGE_FLOOR:.0%}",
    )


def freshness_check(*, age_minutes: float | None, limit_minutes: int) -> HealthCheck:
    """快照新鲜度。``None`` 判 not ok——没有快照比有一张旧的更糟。"""
    if age_minutes is None:
        return HealthCheck(
            name="快照新鲜度", ok=False, value="—", detail="当日无欧赔快照",
        )
    return HealthCheck(
        name="快照新鲜度", ok=age_minutes <= limit_minutes,
        value=f"{age_minutes:.0f} 分钟",
        detail="" if age_minutes <= limit_minutes else f"超过 {limit_minutes} 分钟",
    )


def clv_fill_check(
    *, read_time: int, closing: int, lifetime: tuple[int, int] | None = None
) -> HealthCheck:
    """收盘快照相对读时快照的填充率——CLV 轴是否吃得饱。

    ``read_time``/``closing`` 是**近 14 天窗口**内的计数,判定只看它。``lifetime``
    是 ``(全历史 read_time, 全历史 closing)``,仅作为上下文印出,不参与判定:全历史
    比值被换源前的存量主导,会让这项永远红。
    """
    context = ""
    if lifetime and lifetime[0] > 0:
        context = f"（全历史 {lifetime[1]}/{lifetime[0]} = {lifetime[1] / lifetime[0]:.0%}）"
    if read_time <= 0:
        return HealthCheck(
            name=f"CLV 填充率(近 {_CLV_WINDOW_DAYS} 天)", ok=False, value="0",
            detail=f"窗口内无读时快照,无从判断{context}",
        )
    ratio = closing / read_time
    return HealthCheck(
        name=f"CLV 填充率(近 {_CLV_WINDOW_DAYS} 天)", ok=ratio >= _CLV_FILL_FLOOR,
        value=f"{closing}/{read_time} ({ratio:.0%})",
        detail=context if ratio >= _CLV_FILL_FLOOR
        else (f"低于地板 {_CLV_FILL_FLOOR:.0%};因子生死是双轴判定,"
              f"CLV 饿着则判不准{context}"),
    )


def render_health(run_date: str, checks: list[HealthCheck]) -> str:
    verdict = verdict_of(checks)
    lines = [
        f"# 数据底座健康度 · {run_date}",
        "",
        f"**结论：{verdict}**（{sum(1 for c in checks if c.ok)}/{len(checks)} 项通过）",
        "",
        "| 检查 | 结果 | 实测 | 说明 |",
        "| --- | --- | --- | --- |",
    ]
    for check in checks:
        mark = "✅" if check.ok else "❌"
        lines.append(
            f"| {check.name} | {mark} | {check.value or '—'} | {check.detail or '—'} |"
        )
    return "\n".join(lines) + "\n"


def run_health(run_date: str, output_dir) -> tuple[str, str]:
    """跑全部检查,写报告。返回 ``(报告路径, 结论)``。

    检查项:
      1. titan007 板面可达且可解(端点改版/WAF 会在这里红)
      2. 欧赔覆盖率 = 板面场数(共识缩水会在这里红)
      3. 共识家数下限(书目流失会在这里红)
      4. 微结构可得性(初赔缺失会在这里红——drift 会悄悄退回恒 0)
      5. 当日欧赔快照新鲜度
      6. CLV 填充率(收盘那一抓失手会在这里红;只看近 14 天,见 clv_fill_check)
    """
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    from nutmeg.config.odds_books import load_odds_books_config
    from nutmeg.decision.market_data import (
        load_bold_odds_snapshot,
        load_sporttery_snapshot,
    )
    from nutmeg.decision.odds_shadow import _board_match_numbers
    from nutmeg.decision.ontology import MarketSnapshot
    from nutmeg.decision.store import DecisionStore

    checks: list[HealthCheck] = []
    base = Path(output_dir)

    # 1. 端点可达 + 可解
    try:
        from nutmeg.data.titan007 import Titan007Client

        with Titan007Client() as client:
            rows = client.fetch_board()
        checks.append(HealthCheck(
            name="titan007 板面", ok=bool(rows), value=f"{len(rows)} 场",
            detail="" if rows else "解出 0 场",
        ))
    except Exception as exc:  # noqa: BLE001 — 抓取失败正是本检查要报的红
        checks.append(HealthCheck(
            name="titan007 板面", ok=False, value="—", detail=f"{type(exc).__name__}: {exc}",
        ))

    # 2-4. 当日快照派生
    value = load_sporttery_snapshot(run_date, output_dir)
    board = _board_match_numbers(value, run_date) if value else []
    bold = load_bold_odds_snapshot(run_date, output_dir) or {}
    checks.append(coverage_check(board=len(board), covered=len(bold)))

    cfg = load_odds_books_config()
    book_counts = [
        int(getattr(m.get("match_winner"), "bookmaker_count", 0) or 0)
        for m in bold.values()
    ]
    thin = [n for n in book_counts if n < cfg.min_consensus_books]
    checks.append(HealthCheck(
        name="共识家数", ok=bool(book_counts) and not thin,
        value=f"最低 {min(book_counts)} 家" if book_counts else "—",
        detail="" if book_counts and not thin
        else (f"{len(thin)} 场低于 {cfg.min_consensus_books} 家" if thin else "当日无欧赔"),
    ))

    with_drift = sum(
        1 for m in bold.values()
        if getattr(m.get("match_winner"), "opening_odds", None)
    )
    checks.append(HealthCheck(
        name="初赔可得(drift 原料)", ok=bool(bold) and with_drift == len(bold),
        value=f"{with_drift}/{len(bold)}" if bold else "—",
        detail="" if bold and with_drift == len(bold)
        else "缺初赔的场 drift 会悄悄退回恒 0——那是旧源的老毛病",
    ))

    # 5-6. store 侧
    store = DecisionStore(base / "decision")
    snaps = list(store.load(MarketSnapshot))
    euro_today = [
        s for s in snaps
        if s.kind == "read_time" and s.source in ("titan007", "apifootball")
        and run_date in str(s.match_id)
    ]
    age = None
    if euro_today:
        stamps = []
        for s in euro_today:
            try:
                stamps.append(datetime.fromisoformat(s.taken_at))
            except (TypeError, ValueError):
                continue
        if stamps:
            newest = max(stamps)
            if newest.tzinfo:
                now = datetime.now(newest.tzinfo)
            else:
                now = datetime.now(UTC).replace(tzinfo=None)
            age = max((now - newest).total_seconds() / 60.0, 0.0)
    checks.append(freshness_check(age_minutes=age, limit_minutes=24 * 60))

    window_start = (
        datetime.fromisoformat(run_date) - timedelta(days=_CLV_WINDOW_DAYS)
    ).date().isoformat()

    def _in_window(snapshot) -> bool:
        stamp = str(snapshot.taken_at or "")[:10]
        return bool(stamp) and stamp >= window_start

    checks.append(clv_fill_check(
        read_time=sum(1 for s in snaps if s.kind == "read_time" and _in_window(s)),
        closing=sum(1 for s in snaps if s.kind == "closing" and _in_window(s)),
        lifetime=(
            sum(1 for s in snaps if s.kind == "read_time"),
            sum(1 for s in snaps if s.kind == "closing"),
        ),
    ))

    report = render_health(run_date, checks)
    path = base / "decision" / f"datasource-health-{run_date}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return str(path), verdict_of(checks)
