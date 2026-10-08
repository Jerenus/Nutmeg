"""`/runs/<日>` 的合成：定时作业的「计划 vs 实到」与当日产物，只读零写。

计划来自 ops/launchd 的 plist（单一来源）；实到只认**落盘证据**，按作业各取其证：

- ``day.*`` 作业写 ``daily/<日>/timeline.json``（每次一行，带 planned_at/exit）；
- 备料/研究/早刷新/RSI 闭环各有当日产物（mtime 或文件内时间戳）；
- 高频作业（播报/观察仪/巡检）数日志里带日期的行。

拿不到证据就如实说「无记录」，不从 launchctl 的最后退出码倒推历史日。
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nutmeg.decision.day_paths import BROADCASTS, RETRO, TIMELINE, day_dir, jczq_day_dir
from nutmeg.decision.files import read_json
from nutmeg.decision.ops_status import describe_calendar, iter_plists

LANES = {"jczq": "竞彩", "zucai": "足彩", "rsi": "RSI", "system": "系统"}
STATUS_TEXT = {
    "ok": "完成", "warn": "有警告", "fail": "失败", "skip": "无需运行",
    "missing": "没跑", "upcoming": "未到", "unknown": "无记录", "inactive": "未上线",
}
_FREQUENT_MIN_SLOTS = 12
_TIMELINE_JOB = {"day.settle": "settle", "day.brief": "brief", "day.broadcast": "broadcast"}


@dataclass(frozen=True)
class Run:
    at: str | None            # "HH:MM"；证据没有时刻时为 None
    status: str
    summary: str
    evidence: str | None = None
    slot: str | None = None   # 证据自带所属时刻（timeline 的 planned_at、备料的 slot）


@dataclass(frozen=True)
class JobSpec:
    name: str
    lane: str
    what: str                 # 这项作业做什么（给人看的一句话）
    evidence: Callable[[Path, str], list[Run]]
    rolling_log: bool = False  # 只有一份滚动日志：历史日拿不到证据是「无记录」不是「没跑」
    day_starts: str = "00:00"  # 按业务日记账的作业（sweep 07:00 前记前一天）
    since: Callable[[Path], str | None] | None = None  # 最早留下证据的那天 = 上线日


def _hm(iso: str | None) -> str | None:
    if not iso:
        return None
    match = re.search(r"[T ](\d{2}:\d{2})", iso)
    return match.group(1) if match else None


def _mtime(path: Path) -> datetime | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def _rel(path: Path, data_dir: Path) -> str:
    try:
        return str(path.relative_to(data_dir))
    except ValueError:
        return str(path)


# ── 各作业的证据 ─────────────────────────────────────────────────────────────

def _timeline_runs(job: str) -> Callable[[Path, str], list[Run]]:
    def read(data_dir: Path, day: str) -> list[Run]:
        rows = read_json(day_dir(data_dir, day) / TIMELINE, []) or []
        out = []
        for row in rows:
            if row.get("job") != job:
                continue
            code = row.get("exit")
            status = "ok" if code == 0 else "fail"
            evidence = row.get("evidence_path")
            out.append(Run(at=_hm(row.get("finished_at")), status=status,
                           summary=str(row.get("summary") or ""),
                           evidence=_rel(Path(evidence), data_dir) if evidence else None,
                           slot=_hm(row.get("planned_at"))))
        return out
    return read


def _am(data_dir: Path, day: str) -> list[Run]:
    """早刷新每跑一次在日志里写 ``NUTMEG_OK stage=am run_date=<日>``——带日期的唯一证据。

    ``scheduler-context.json`` 会被当天后续的补跑重写（2026-09-24 17:15），它的时间
    只作「最后更新」附注，不当作 08:00 那一次的完成时刻。
    """
    try:
        text = (data_dir / "logs" / "decision.am.out.log").read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    ctx = jczq_day_dir(data_dir, day) / "scheduler-context.json"
    doc = read_json(ctx) or {}
    succeeded = f"NUTMEG_OK stage=am run_date={day}" in text
    if not succeeded and not doc:
        return []
    legs = (read_json(jczq_day_dir(data_dir, day) / "jczq-legs-base.json", {}) or {}
            ).get("legs") or {}
    summary = f"竞彩板面 {len(legs)} 场，赔率快照已存"
    updated = _hm(str(doc.get("generated_at") or ""))
    if updated:
        summary += f"（快照最后更新 {updated}）"
    if not succeeded:
        summary = "日志里没有这天的早刷新成功记录，快照来自补跑。" + summary
    return [Run(at=None, status="ok" if succeeded else "warn", summary=summary,
                evidence=_rel(ctx, data_dir))]


def _research(data_dir: Path, day: str) -> list[Run]:
    folder = jczq_day_dir(data_dir, day)
    reads = folder / "reads.json"
    at = _mtime(reads)
    if at is None:
        return []
    n_reads = len(read_json(reads, []) or [])
    done = len(list(folder.glob("research-周*.json"))) - len(
        list(folder.glob("research-周*.rejected.json")))
    rejected = len(list(folder.glob("research-周*.rejected.json")))
    summary = f"判读草稿 {n_reads} 条，深研 {done} 场"
    status = "ok"
    if rejected:
        summary += f"，驳回 {rejected} 场"
        status = "warn"
    return [Run(at=at.strftime("%H:%M"), status=status, summary=summary,
                evidence=_rel(reads, data_dir))]


def _rsi_loop(data_dir: Path, day: str) -> list[Run]:
    path = data_dir / "analytics" / "rsi-loop" / f"{day}.json"
    doc = read_json(path)
    if not doc:
        return []
    failed = len(doc.get("failed_steps") or [])
    pending = len(doc.get("human_actions") or [])
    summary = f"{len(doc.get('steps') or [])} 步，待人决定 {pending} 条"
    if failed:
        summary += f"，失败步骤 {failed}"
    md = path.with_suffix(".md")
    return [Run(at=_hm(doc.get("finished_at")), status="fail" if failed else "ok",
                summary=summary, evidence=_rel(md if md.exists() else path, data_dir))]


def _prep(slot: str, log_name: str) -> Callable[[Path, str], list[Run]]:
    def read(data_dir: Path, day: str) -> list[Run]:
        zdir = data_dir / "zucai"
        for path in sorted(zdir.glob(f"*-prep-{slot}.json"), reverse=True):
            # 只认文件里的 run_date；按 mtime 预筛会让回看历史日（或测试）随今天日期漂移
            doc = read_json(path, {}) or {}
            if doc.get("run_date") != day:
                continue
            unmatched = len((doc.get("alignment") or {}).get("unmatched") or [])
            summary = f"{doc.get('issue')} 期 {doc.get('n_matches')} 场"
            summary += f"，体彩未对齐 {unmatched} 场" if unmatched else "，全部对齐"
            if doc.get("intl_status") != "available":
                summary += "，国际盘缺席"
            return [Run(at=_hm(doc.get("captured_at")), status="warn" if unmatched else "ok",
                        summary=summary, evidence=_rel(path.with_suffix(".md"), data_dir))]
        log = data_dir / "logs" / f"{log_name}.out.log"
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines():
            if f"足彩备料 {day}:今日无期" in line:
                rest = line.split("今日无期", 1)[1].lstrip("。 ")
                return [Run(at=None, status="skip", summary=f"今天没有足彩期。{rest}")]
        return []
    return read


def _log_tail_today(log_name: str, *, warn_markers: tuple[str, ...] = ()) -> Callable:
    """只有一份滚动日志、行里不带日期的作业：日志最后修改日 == 当天才算有证据。"""
    def read(data_dir: Path, day: str) -> list[Run]:
        log = data_dir / "logs" / f"{log_name}.out.log"
        at = _mtime(log)
        if at is None or at.date().isoformat() != day:
            return []
        lines = [ln.strip() for ln in log.read_text(encoding="utf-8", errors="replace")
                 .splitlines() if ln.strip()]
        tail = lines[-1] if lines else ""
        text = "\n".join(lines[-6:])
        status = "warn" if any(m in text for m in warn_markers) else "ok"
        return [Run(at=at.strftime("%H:%M"), status=status, summary=tail[:160],
                    evidence=_rel(log, data_dir))]
    return read


def _sweep(data_dir: Path, day: str) -> list[Run]:
    log = data_dir / "logs" / "rsi.sweep.out.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for match in re.finditer(rf"^{day} sweep: (.*)$", text, re.M):
        body = match.group(1)
        failed = re.search(r"failed=(\d+)", body)
        status = "warn" if failed and int(failed.group(1)) else "ok"
        out.append(Run(at=None, status=status, summary=body))
    return out


def _first_day(pattern: str) -> Callable[[Path], str | None]:
    """上线日：某类产物最早出现的那天。早于它的日子是「未上线」，不是「没跑」。"""
    def read(data_dir: Path) -> str | None:
        days = [m.group(0) for p in data_dir.glob(pattern)
                if (m := re.search(r"\d{4}-\d{2}-\d{2}", str(p.relative_to(data_dir))))]
        return min(days) if days else None
    return read


_TIMELINE_SINCE = _first_day("daily/*/timeline.json")


def _account_runs(data_dir: Path, day: str) -> list[Run]:
    """月初账房的证据：`analytics/account/<上月>.md` 在这一天写入。"""
    from datetime import date as _d
    from datetime import datetime as _dt

    from nutmeg.decision.account import previous_month

    report = data_dir / "analytics" / "account" / f"{previous_month(_d.fromisoformat(day))}.md"
    try:
        at = _dt.fromtimestamp(report.stat().st_mtime)
    except OSError:
        return []
    if at.date().isoformat() != day:
        return []
    head = next((ln for ln in report.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("**净值")), "")
    return [Run(at=at.strftime("%H:%M"), status="ok", summary=head[:120] or report.stem,
                evidence=_rel(report, data_dir))]


def _verdict_runs(data_dir: Path, day: str) -> list[Run]:
    log = data_dir / "jczq" / "daily" / day / "verdict-log.jsonl"
    try:
        lines = log.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        row = json.loads(line)
        out.append(Run(at=str(row.get("at", ""))[11:16], status="ok",
                       summary=f"{row.get('edition')}：{row.get('matches')} 场，改判 "
                               f"{row.get('overrides')}，打架 {row.get('disagreements')}",
                       evidence=_rel(log.with_name("verdict.html"), data_dir)))
    return out

JOBS: dict[str, JobSpec] = {
    "com.nutmeg.decision.am": JobSpec(
        "竞彩早刷新", "jczq", "抓当天竞彩板面和赔率快照", _am),
    "com.nutmeg.jczq.results-backfill": JobSpec(
        "赛果回填", "system", "把已完场的竞彩赛果写进结果库",
        _log_tail_today("jczq.results-backfill", warn_markers=("RESULTS_STALE",)),
        rolling_log=True),
    "com.nutmeg.day.settle": JobSpec(
        "结算与复盘", "system", "结算昨天的票，生成复盘底稿", _timeline_runs("settle"),
        since=_TIMELINE_SINCE),
    "com.nutmeg.jczq.research": JobSpec(
        "竞彩研究", "jczq", "逐场深研，写判读草稿", _research),
    "com.nutmeg.rsi.loop": JobSpec(
        "RSI 闭环", "rsi", "结账、提案、列出待你决定的事", _rsi_loop,
        since=_first_day("analytics/rsi-loop/*.json")),
    "com.nutmeg.zucai.prep-morning": JobSpec(
        "足彩备料·早", "zucai", "抓在售期、对齐体彩与国际盘",
        _prep("morning", "zucai.prep-morning")),
    "com.nutmeg.zucai.prep": JobSpec(
        "足彩备料·午", "zucai", "重抓一遍，和早间比位移", _prep("afternoon", "zucai.prep")),
    "com.nutmeg.zucai.prep-revision": JobSpec(
        "足彩复核", "zucai", "截止前最后一次位移复核",
        _prep("revision", "zucai.prep-revision")),
    "com.nutmeg.day.brief": JobSpec(
        "简报发布", "system", "汇总当日简报并发布页面", _timeline_runs("brief"),
        since=_TIMELINE_SINCE),
    "com.nutmeg.rsi.sweep": JobSpec(
        "义务巡检", "rsi", "补跑到期的 RSI 观察义务", _sweep, day_starts="07:00"),
    "com.nutmeg.day.verdict": JobSpec(
        "判决参考页", "system", "主版 12:30 / 晚版 18:45：刷新判断并生成当日判决参考页",
        lambda data_dir, day: _verdict_runs(data_dir, day),
        since=_first_day("jczq/daily/*/verdict-log.jsonl")),
    "com.nutmeg.day.broadcast": JobSpec(
        "截止播报", "system", "截止前 30 分、10 分提醒", _timeline_runs("broadcast"),
        since=_TIMELINE_SINCE),
    "com.nutmeg.account.month": JobSpec(
        "月初账房", "system", "每月 1 日出上个月的账：净值 vs 空仓、止损、偏离、判断力指标",
        lambda data_dir, day: _account_runs(data_dir, day),
        since=lambda _data_dir: "2026-10-02"),
}


# ── 计划时刻 ────────────────────────────────────────────────────────────────

def _runs_on(item: dict, day: str | None) -> bool:
    """排程项在这一天是否有计划：`Day`＝每月几号，`Weekday`＝launchd 星期（0/7=周日）。"""
    if day is None:
        return True
    from datetime import date as _d

    d = _d.fromisoformat(day)
    if "Day" in item and int(item["Day"]) != d.day:
        return False
    return not ("Weekday" in item and int(item["Weekday"]) % 7 != (d.weekday() + 1) % 7)


def planned_times(doc: dict, day: str | None = None) -> tuple[list[str], str]:
    """plist → (当天计划时刻 "HH:MM" 列表, 人读的频率)。给 `day` 时，月度/周度排程只在
    当月那天/当周那天有计划（2026-10-02：月初账房定时器在其余日子不该显示「漏跑」）。"""
    interval = doc.get("StartInterval")
    if isinstance(interval, int) and not isinstance(interval, bool):
        step = max(1, interval // 60)
        return [f"{m // 60:02d}:{m % 60:02d}" for m in range(0, 1440, step)], f"每 {step} 分"
    cal = doc.get("StartCalendarInterval")
    items = cal if isinstance(cal, list) else [cal] if isinstance(cal, dict) else []
    monthly = [i for i in items if isinstance(i, dict) and ("Day" in i or "Weekday" in i)]
    if monthly and len(monthly) == len(items):
        label = "、".join(describe_calendar(i) for i in monthly)
        times = sorted(f"{int(i.get('Hour', 0)):02d}:{int(i.get('Minute', 0)):02d}"
                       for i in monthly if _runs_on(i, day))
        return times, label
    times: set[str] = set()
    for item in items:
        minute = int(item.get("Minute", 0))
        if item.get("Hour") is None:
            times.update(f"{h:02d}:{minute:02d}" for h in range(24))
        else:
            times.add(f"{int(item['Hour']):02d}:{minute:02d}")
    ordered = sorted(times)
    if len(ordered) >= _FREQUENT_MIN_SLOTS:
        stamps = [int(t[:2]) * 60 + int(t[3:]) for t in ordered]
        gaps = {b - a for a, b in zip(stamps, stamps[1:], strict=False)}
        every = f"每 {gaps.pop()} 分" if len(gaps) == 1 else f"{len(ordered)} 次"
        if len(ordered) == 24 and every == "每 60 分":
            every = "每小时"
        return ordered, f"{every}（{ordered[0]}–{ordered[-1]}）"
    return ordered, "、".join(ordered) or "未声明"


def _slot_status(planned: str, *, day: str, today: str, now_hm: str) -> str:
    if day > today or (day == today and planned > now_hm):
        return "upcoming"
    return "missing"


def _timed_job(spec: JobSpec, times: list[str], runs: list[Run], *, day: str, today: str,
               now_hm: str, rolling_log: bool) -> list[dict]:
    """每个计划时刻配一次运行：先认证据自带的 slot，再按「计划时刻之后最早的一次」配。"""
    left = list(runs)
    slots = []
    for planned in times:
        run = next((r for r in left if r.slot == planned), None)
        if run is None:
            later = [r for r in left if r.slot is None and (r.at is None or r.at >= planned)]
            nxt = next((t for t in times if t > planned), None)
            later = [r for r in later if nxt is None or r.at is None or r.at < nxt]
            run = later[0] if later else None
        if run is not None:
            left.remove(run)
            slots.append({"planned": planned, "status": run.status, "at": run.at,
                          "summary": run.summary, "evidence": run.evidence})
            continue
        status = _slot_status(planned, day=day, today=today, now_hm=now_hm)
        if status == "missing" and rolling_log:
            status = "unknown"
        slots.append({"planned": planned, "status": status, "at": None,
                      "summary": "", "evidence": None})
    for run in left:                                   # 计划外的手动/补跑
        slots.append({"planned": None, "status": run.status, "at": run.at,
                      "summary": run.summary, "evidence": run.evidence, "extra": True})
    return slots


def _frequent_status(runs: list[Run], *, day: str, today: str) -> str:
    if not runs:
        return "upcoming" if day > today else ("unknown" if day < today else "missing")
    if any(r.status == "fail" for r in runs[-3:]):
        return "fail"
    if runs[-1].status == "warn":
        return "warn"
    return "ok"


# ── 当日产物 ────────────────────────────────────────────────────────────────

def _markers(data_dir: Path, day: str, brief: dict) -> list[dict]:
    out = []
    for match in ((brief.get("jczq") or {}).get("matches") or []):
        kickoff = str(match.get("kickoff_bj") or "")
        if kickoff[:10] == day and _hm(kickoff):
            out.append({"at": _hm(kickoff), "kind": "kickoff",
                        "label": f"{match.get('code')} {match.get('name') or ''}".strip()})
    zucai = brief.get("zucai") or {}
    deadline = str(zucai.get("sale_deadline") or "")
    if deadline[:10] == day and _hm(deadline):
        out.append({"at": _hm(deadline), "kind": "deadline",
                    "label": f"足彩 {zucai.get('issue')} 截止"})
    return sorted(out, key=lambda m: m["at"])


def _rsi_duties(data_dir: Path, day: str, now_iso: str) -> list[dict]:
    db = data_dir / "ontology" / "ontology.db"
    if not db.exists():
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT duty_id, COUNT(*), SUM(fulfilled_at IS NOT NULL), "
                "SUM(fulfilled_at IS NULL AND due_at <= ?) "
                "FROM rsi_duty_instances WHERE day=? GROUP BY duty_id ORDER BY duty_id",
                (now_iso, day),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [{"duty": duty, "total": total, "done": done or 0, "expired": expired or 0}
            for duty, total, done, expired in rows]


def _outputs(data_dir: Path, day: str, brief: dict, now_iso: str) -> dict:
    jczq = brief.get("jczq") or {}
    matches = jczq.get("matches") or []
    reads = [m.get("read") or {} for m in matches]
    zucai = brief.get("zucai") or {}
    issue = zucai.get("issue")
    zdir = data_dir / "zucai"
    tickets = read_json(zdir / f"{issue}-final-tickets.json") if issue else None
    rsi = brief.get("rsi") or {}
    broadcasts = []
    try:
        for line in (day_dir(data_dir, day) / BROADCASTS).read_text("utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                broadcasts.append({"at": _hm(row.get("at")), "key": row.get("key"),
                                   "minutes_left": row.get("minutes_left")})
    except (OSError, ValueError):
        pass
    retro = None
    try:
        retro = (day_dir(data_dir, day) / RETRO).read_text(encoding="utf-8")
    except OSError:
        pass
    return {
        "jczq": {
            "matches": len(matches),
            "deep": sum(1 for r in reads if r.get("judgment_tier") == "deep_research"),
            "moved": sum(1 for r in reads if abs(float(r.get("moved_pp") or 0)) > 0),
            "board": [{"code": m.get("code"), "name": m.get("name"),
                       "kickoff": _hm(m.get("kickoff_bj")),
                       "tier": (m.get("read") or {}).get("judgment_tier"),
                       "confidence": (m.get("read") or {}).get("confidence")}
                      for m in matches],
        },
        "zucai": {
            "issue": issue, "deadline": zucai.get("sale_deadline"),
            "planned": bool(zucai.get("plan")),
            "tickets": len(tickets) if isinstance(tickets, (list, dict)) else 0,
            "purchased": bool(issue and (zdir / f"{issue}-audit-purchased.txt").exists()),
        },
        "rsi": {
            "pending": [a.get("text") if isinstance(a, dict) else str(a)
                        for a in (rsi.get("human_actions") or [])],
            "duties": _rsi_duties(data_dir, day, now_iso),
        },
        "broadcasts": broadcasts,
        "retro": retro,
    }


def available_days(data_dir: Path, *, limit: int = 60) -> list[str]:
    found: set[str] = set()
    for folder in (data_dir / "daily", data_dir / "jczq" / "daily"):
        if folder.exists():
            found.update(p.name for p in folder.iterdir()
                         if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    return sorted(found, reverse=True)[:limit]


def day_runs(*, data_dir: Path, plists_dir: Path, day: str, now: datetime) -> dict:
    data_dir = Path(data_dir)
    today = now.date().isoformat()
    now_hm = now.strftime("%H:%M")
    errors: list[str] = []
    brief = read_json(day_dir(data_dir, day) / "brief.json", {}) or {}
    jobs = []
    for plist, doc, exc in iter_plists(plists_dir):
        if doc is None:  # 坏 plist 也要露面
            errors.append(f"{plist.name} 解析失败：{exc}")
            continue
        label = str(doc.get("Label") or plist.stem)
        spec = JOBS.get(label)
        if spec is None:
            errors.append(f"{label} 没有登记证据来源，页面上看不到它")
            continue
        times, every = planned_times(doc, day)
        live_from = spec.since(data_dir) if spec.since else None
        inactive = live_from is not None and day < live_from
        try:
            runs = spec.evidence(data_dir, day)
        except Exception as exc:  # noqa: BLE001 — 一项坏不塌整页
            runs = []
            errors.append(f"{spec.name} 证据读取失败：{exc}")
        base = {"id": label.removeprefix("com.nutmeg."), "name": spec.name, "lane": spec.lane,
                "what": spec.what, "schedule": every}
        if len(times) >= _FREQUENT_MIN_SLOTS:
            times = [t for t in times if t >= spec.day_starts]
            due = [t for t in times if day < today or (day == today and t <= now_hm)]
            status = _frequent_status(runs, day=day, today=today)
            if inactive and not runs:
                status = "inactive"
            jobs.append({**base, "kind": "frequent", "planned": len(times), "due": len(due),
                         "runs": [{"at": r.at, "status": r.status} for r in runs],
                         "run_count": len(runs),
                         "last": runs[-1].summary if runs else "",
                         "status": status,
                         "window": [times[0], times[-1]]})
        else:
            slots = _timed_job(spec, times, runs, day=day, today=today, now_hm=now_hm,
                               rolling_log=spec.rolling_log)
            if inactive:
                for slot in slots:
                    if slot["status"] == "missing":
                        slot["status"] = "inactive"
            jobs.append({**base, "kind": "timed", "slots": slots})
    order = {lane: i for i, lane in enumerate(LANES)}
    jobs.sort(key=lambda j: (order.get(j["lane"], 9),
                             (j.get("slots") or [{}])[0].get("planned") or "99",
                             j["name"]))
    counts = {status: 0 for status in STATUS_TEXT}
    for job in jobs:
        if job["kind"] == "frequent":
            counts[job["status"]] += 1
        else:
            for slot in job["slots"]:
                counts[slot["status"]] += 1
    return {
        "date": day, "today": today, "is_today": day == today,
        "now": now_hm if day == today else None,
        "days": available_days(data_dir),
        "lanes": LANES, "status_text": STATUS_TEXT,
        "jobs": jobs, "counts": counts,
        "markers": _markers(data_dir, day, brief),
        "outputs": _outputs(data_dir, day, brief, now.astimezone().isoformat(timespec="seconds")),
        "errors": errors,
    }
