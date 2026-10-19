"""待人决定清单（设计 §4 `decisions.json`、§7「待人决定」块、§5 播报的输入）。

只列「系统做不了、只有人能做」的事，并给每条截止时间与默认动作（宪法：空仓是对着数字做的选择）。

2026-10-02 换内容（Jun 同意）：去掉「Read 草稿审批」——判断唯一事实 P2 后 Read
自动交本体，没有东西等人批，9 月下旬 74 条播报全是它；换成两类真正要人动作的截止：
- `register_zucai`：在售期停售前仍无已登记的实票（默认空仓）；
- `register_jczq`：当天有 `betslip preview` 预审过的竞彩方案、却没有登记实票，
  截止＝预审腿里最早开球。
这两类在每次播报时现算（`live_register_decisions`），不等 12:00/14:20/18:35 的报告。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nutmeg.decision.bj_time import BJ, parse_bj
from nutmeg.decision.day_paths import DECISIONS, day_dir, jczq_day_dir

DEFAULT_EMPTY = "空仓"


REGISTER_KINDS = ("register_zucai", "register_jczq")
OBSOLETE_KINDS = ("approve_read", "plan_choose_commit")
REGISTER_DEFAULT = "未登记＝空仓（不买）"


def log_preview(data_dir: Path | str, *, placed_at: str, channel: str, issue: str,
                keys: list[str], stake: int, vetoed: bool, now: datetime,
                faces: dict[str, str] | None = None, p: float | None = None) -> Path:
    """`betslip preview` 每审一张就记一行：播报据此知道「有在审方案」。
    足彩另记票面与当时的 P(全对)：复盘的选择账靠它还原开赛前审过哪几版（2026-10-10）。"""
    from nutmeg.decision.day_paths import PREVIEWS

    path = day_dir(data_dir, str(placed_at)[:10]) / PREVIEWS
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": now.isoformat(timespec="seconds"), "channel": channel, "issue": issue,
           "keys": list(keys), "stake": stake, "vetoed": vetoed}
    if faces:
        row |= {"faces": dict(faces), "p": p}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def _previews(data_dir: Path, date: str) -> list[dict]:
    from nutmeg.decision.day_paths import PREVIEWS

    path = day_dir(data_dir, date) / PREVIEWS
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def live_register_decisions(data_dir: Path | str, date: str, *, now: datetime) -> list[dict]:
    """两类「停售/开球前仍未登记」的截止，按当前文件现算。"""
    from nutmeg.decision.betslip import load_slips
    from nutmeg.decision.day_brief import current_issue

    data_dir = Path(data_dir)
    try:
        slips = load_slips(data_dir)
    except Exception:  # noqa: BLE001 —— 登记簿坏了也要发截止提醒
        slips = []
    rows: list[dict] = []
    zdir = data_dir / "zucai"
    issue = current_issue(zdir, now=now) if zdir.exists() else None
    if issue:
        meta = json.loads((zdir / f"{issue}-issue.json").read_text(encoding="utf-8"))
        deadline = meta.get("sale_deadline") or meta.get("sale_stop")
        purchased = any(s.purchased and s.issue == str(issue) for s in slips)
        draft_hint = ""
        draft = zdir / f"{issue}-draft.json"
        if draft.exists():
            try:
                cands = json.loads(draft.read_text(encoding="utf-8")).get("candidates") or []
                first = next((c for c in cands if c.get("label") == "初稿" and c.get("faces")),
                             None)
                if first:
                    verdict = "⛔否决" if (first.get("review") or {}).get("vetoed") else "可出"
                    draft_hint = f"；机器初稿 ¥{first['stake_yuan']}（审票 {verdict}）"
            except (OSError, ValueError):
                draft_hint = ""
        rows.append({
            "id": f"register:zucai:{issue}", "kind": "register_zucai",
            "subject": f"足彩 {issue} 停售前仍无已登记实票{draft_hint}",
            "deadline": deadline, "default_action": REGISTER_DEFAULT,
            "status": _status(deadline, purchased, now), "source": "betslips",
        })
    previews = [p for p in _previews(data_dir, date) if p.get("channel") == "jczq"]
    if previews:
        registered = any(s.purchased and s.channel == "jczq" and str(s.placed_at)[:10] == date
                         for s in slips)
        legs = {}
        try:
            board = json.loads((jczq_day_dir(data_dir, date) / "jczq-legs-base.json")
                               .read_text(encoding="utf-8"))
            legs = board.get("legs") or {}
        except (OSError, ValueError):
            legs = {}
        kicks = sorted(k for k in (parse_bj((legs.get(key) or {}).get("kickoff_bj"))
                                   for p in previews for key in p.get("keys") or [])
                       if k is not None and k > now)
        if not kicks:
            kicks = sorted(k for k in (parse_bj(leg.get("kickoff_bj")) for leg in legs.values())
                           if k is not None and k > now)
        if kicks:
            deadline = kicks[0].isoformat(timespec="seconds")
            rows.append({
                "id": f"register:jczq:{date}", "kind": "register_jczq",
                "subject": f"竞彩：今天预审过 {len(previews)} 次方案，还没有登记实票",
                "deadline": deadline, "default_action": REGISTER_DEFAULT,
                "status": _status(deadline, registered, now), "source": "previews",
            })
    return rows


def broadcast_decisions(data_dir: Path | str, date: str, *, now: datetime) -> list[dict]:
    """播报的输入：报告时写下的 decisions.json（去掉过时种类与旧的登记类）+ 现算的登记截止。"""
    path = day_dir(data_dir, date) / DECISIONS
    try:
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except ValueError:
        stored = []
    kept = [d for d in stored if d.get("kind") not in (*REGISTER_KINDS, *OBSOLETE_KINDS)]
    return kept + live_register_decisions(data_dir, date, now=now)


def _status(deadline: str | None, done: bool, now: datetime) -> str:
    if done:
        return "done"
    if deadline:
        try:
            parsed = datetime.fromisoformat(deadline)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=BJ)
            if parsed <= now:
                return "expired"
    return "open"


def build_decisions(
    brief: dict, timeline: list[dict], *, data_dir: Path | str, now: datetime
) -> list[dict]:
    rows: list[dict] = live_register_decisions(Path(data_dir), brief["date"], now=now)
    rsi = brief.get("rsi") or {}
    if rsi.get("inbox") is not None:
        # 2026-10-19 起闭环出收件箱：固定 id、积压天数、真实的默认动作
        # （不再按位置编号、一律「不动」）
        for item in rsi["inbox"]:
            rows.append({"id": f"rsi:{item['id']}", "kind": "rsi",
                         "subject": f"{item['text']}（积压 {item['age_days']} 天，自 "
                                    f"{item['first_seen']}）",
                         "deadline": None, "default_action": item["default"],
                         "status": "open", "source": "rsi-loop"})
    else:
        for i, action in enumerate(rsi.get("human_actions") or []):
            rows.append({"id": f"rsi:{i}", "kind": "rsi", "subject": action, "deadline": None,
                         "default_action": "不动（hold）", "status": "open",
                         "source": "rsi-loop"})
    for step in rsi.get("failed_steps") or []:
        rows.append({
            "id": f"loop:{step}", "kind": "failed_step",
            "subject": f"rsi loop 步骤 {step} 失败",
            "deadline": None, "default_action": "看 latest.md 后决定是否 --force 重跑",
            "status": "open", "source": "rsi-loop",
        })
    latest_per_job: dict[str, dict] = {}
    for job in timeline:  # 只看每个作业最近一次；早先失败、后来成功的不再列
        latest_per_job[str(job.get("job"))] = job
    for job in latest_per_job.values():
        if job.get("exit", 0) != 0:
            rows.append({"id": f"job:{job['job']}", "kind": "failed_job",
                         "subject": f"day 作业 {job['job']} 失败：{job.get('summary', '')[:120]}",
                         "deadline": None, "default_action": "看 timeline.json 的 commands 尾行",
                         "status": "open", "source": "timeline"})
    return rows


def write_decisions(data_dir: Path | str, date: str, rows: list[dict]) -> Path:
    out = day_dir(data_dir, date)
    out.mkdir(parents=True, exist_ok=True)
    path = out / DECISIONS
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
