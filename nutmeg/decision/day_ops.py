"""状态条的 launchd 半边：每个 com.nutmeg.* 标签一行，
结局与时间证据并排（沿用 ops_status 纪律；launchctl / plist / 排程解析都在 ops_status）。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from nutmeg.decision.ops_status import (
    describe_schedule,
    iter_plists,
    parse_launchctl,
    stale_after_days,
)


def _log_evidence(logs_dir: Path, label: str) -> tuple[str, datetime | None]:
    short = label.removeprefix("com.nutmeg.")
    best: tuple[str, datetime | None] = ("", None)
    for suffix in ("out", "err"):
        path = logs_dir / f"{short}.{suffix}.log"
        if not path.exists():
            continue
        at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        raw = path.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in raw.splitlines() if ln.strip()]
        tail = lines[-1][:200] if lines else ""
        if best[1] is None or at > best[1]:
            best = (tail, at)
    return best


def launchd_rows(
    *, plists_dir: Path, logs_dir: Path, launchctl_text: str, today: date,
) -> list[dict]:
    exits = parse_launchctl(launchctl_text)
    rows = []
    for plist, doc, exc in iter_plists(plists_dir):
        if doc is None:  # 坏 plist 也要出现在状态条上
            rows.append({"label": plist.stem, "schedule": "?", "loaded": False, "last_exit": "-",
                         "tail": f"plist 解析失败: {exc}", "log_at": None, "alarm": True})
            continue
        label = str(doc.get("Label") or plist.stem)
        tail, at = _log_evidence(logs_dir, label)
        loaded = label in exits
        last_exit = exits.get(label, "-")
        schedule_src = doc.get("StartCalendarInterval") or doc.get("StartInterval")
        stale = at is not None and (today - at.date()).days > stale_after_days(schedule_src)
        rows.append({
            "label": label,
            "schedule": describe_schedule(doc),
            "loaded": loaded,
            "last_exit": last_exit,
            "tail": tail,
            "log_at": at.isoformat(timespec="minutes") if at else None,
            "alarm": (loaded and last_exit not in ("0", "-")) or stale or "RESULTS_STALE" in tail
                     or "NUTMEG_FAILED" in tail,
        })
    return sorted(rows, key=lambda r: r["label"])
