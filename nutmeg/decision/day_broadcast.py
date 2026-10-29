"""截止播报（deadline_broadcast_discipline）：T-30 / T-10 各一次，明写默认动作。

只报时间，不代决、不下单。
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nutmeg.decision.bj_time import BJ
from nutmeg.decision.day_decisions import decision_href
from nutmeg.decision.day_paths import BROADCASTS, day_dir

Sender = Callable[[str], None]
WINDOWS = (("T30", 30, 10), ("T10", 10, 0))
"""(标签, 上界含, 下界不含)：剩余分钟 ∈ (下界, 上界] 触发。"""


@dataclass(frozen=True)
class Broadcast:
    key: str
    decision: dict
    minutes_left: int
    window: str


def due_broadcasts(decisions: list[dict], *, now: datetime, sent: set[str]) -> list[Broadcast]:
    out: list[Broadcast] = []
    for d in decisions:
        if d.get("status") != "open" or not d.get("deadline"):
            continue
        try:
            deadline = datetime.fromisoformat(d["deadline"])
        except ValueError:
            continue
        if deadline.tzinfo is None:
            # 足彩 sale_deadline 是「2026-09-24 19:05」这种无时区的北京时间（2026-09-24 实发：
            # 与带时区的 now 相减抛 TypeError，整个广播作业退出 1，截止播报差点不发）
            deadline = deadline.replace(tzinfo=BJ)
        left = int((deadline - now).total_seconds() // 60)
        for label, hi, lo in WINDOWS:
            key = f"{d['id']}@{label}"
            if lo < left <= hi and key not in sent:
                out.append(Broadcast(key=key, decision=d, minutes_left=left, window=label))
    return out


def render_broadcast(b: Broadcast, *, base_url: str = "") -> str:
    return render_group([b], base_url=base_url)


def render_group(group: list[Broadcast], *, base_url: str = "") -> str:
    """同一截止、同一窗口的多条决定合成一条播报（2026-09-22 首跑三场 02:00 各发一条）。
    base_url 空＝末行逐字照旧；配了就把「/day」换成绝对链接：第一条有去处的决定
    （`decision_href`）、都没有则 `/day/<截止日>`。"""
    head = group[0]
    lines = [f"⏰ 剩 {head.minutes_left} 分（截止 {head.decision['deadline'][11:16]}）"]
    for b in group:
        lines.append(f"· {b.decision['subject']}\n  未定则默认：{b.decision['default_action']}")
    where = "/day"
    if base_url:
        href = next((h for h in (decision_href(b.decision) for b in group) if h),
                    f"/day/{head.decision['deadline'][:10]}")
        where = base_url.rstrip("/") + href
    lines.append(f"（Nutmeg 只播报时间，不代下单；回复或打开 {where} 处理）")
    return "\n".join(lines)


def group_due(due: list[Broadcast]) -> list[list[Broadcast]]:
    groups: dict[tuple[str, str], list[Broadcast]] = {}
    for b in due:
        groups.setdefault((str(b.decision.get("deadline")), b.window), []).append(b)
    return list(groups.values())


def read_sent(data_dir: Path | str, date: str) -> set[str]:
    path = day_dir(data_dir, date) / BROADCASTS
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.add(json.loads(line)["key"])
    return keys


def send_all(
    decisions: list[dict], *, data_dir: Path | str, date: str, now: datetime, sender: Sender,
    base_url: str | None = None,
) -> dict:
    """base_url 为 None 时读 settings（`NUTMEG_DECISION_WEB_URL`，默认空＝不加链接）。"""
    if base_url is None:
        from nutmeg.config.settings import get_settings

        base_url = get_settings().decision_web_url
    sent_keys = read_sent(data_dir, date)
    path = day_dir(data_dir, date) / BROADCASTS
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"sent": [], "failed": []}
    for group in group_due(due_broadcasts(decisions, now=now, sent=sent_keys)):
        try:
            sender(render_group(group, base_url=base_url))
        except Exception:  # noqa: BLE001 — 发送失败下一轮再试
            report["failed"].extend(b.key for b in group)
            continue
        with path.open("a", encoding="utf-8") as fh:
            for b in group:
                row = {
                    "key": b.key,
                    "at": now.isoformat(timespec="seconds"),
                    "minutes_left": b.minutes_left,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        report["sent"].extend(b.key for b in group)
    return report


def telegram_sender() -> Sender:
    """默认发送器：settings 里的 bot token + 允许的 chat id（逗号分隔）。"""
    from nutmeg.config.settings import get_settings
    from nutmeg.interfaces.bot.telegram import TelegramBotClient

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_allowed_chat_ids:
        raise RuntimeError(
            "telegram not configured (NUTMEG_TELEGRAM_BOT_TOKEN / _ALLOWED_CHAT_IDS)"
        )
    client = TelegramBotClient(
        token=settings.telegram_bot_token, base_url=settings.telegram_api_base_url
    )
    chat_ids = [int(x) for x in settings.telegram_allowed_chat_ids.split(",") if x.strip()]

    def send(text: str) -> None:
        for chat_id in chat_ids:
            client.send_message(chat_id=chat_id, text=text)

    return send
