# Daily Surface P3 · 定时器、截止播报、赛果桥 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 P1 的作业在人之前自动发生：07:30 结算复盘、10:00 全板深研、12:00/14:20/18:30 日报、每 10 分钟检查截止并在 T-30/T-10 推 Telegram（只播报，不代决）；并把 `jc-results.json` 桥成 `betslip settle` 能吃的 `results-90.json`。

**Architecture:** 新作业 `broadcast` 与 `results` 加进 `day_runner.JOBS`；播报去重靠 `daily/<日>/broadcasts.jsonl`；发送函数注入（默认 `TelegramBotClient.send_message`，chat id 来自 `settings.telegram_allowed_chat_ids`）。定时器全部是 `ops/launchd/*.plist`，与 `rsi.loop` 同形；**装载是 Jun 的行权门**，计划只写文件。所有 plist 由一个测试统一校验。

**Tech Stack:** Python、`plistlib`、launchd、`TelegramBotClient`（`nutmeg/interfaces/bot/telegram.py`）。

**Spec:** 设计 §5 时间线（★ 项）、§9 播报只报时间与默认动作。**依赖 P1。**

---

## File structure

| 文件 | 职责 |
| --- | --- |
| Create `nutmeg/decision/day_broadcast.py` | `due_broadcasts`、`render_broadcast`、`send_all`、`read_sent` |
| Create `nutmeg/decision/day_results.py` | `bridge_results`：`jc-results.json[昨日]` → `daily/<日>/results-90.json` |
| Modify `nutmeg/decision/day_runner.py` | `JOBS += ("results", "broadcast")`；`run_job` 分派 |
| Modify `nutmeg/interfaces/cli/day.py` | `--job results|broadcast`；`broadcast --dry-run` 打印将发文本 |
| Create `ops/launchd/com.nutmeg.day.settle.plist`、`com.nutmeg.jczq.research.plist`、`com.nutmeg.day.brief.plist`、`com.nutmeg.day.broadcast.plist` | 定时器 |
| Modify `docs/ops/2026-09-20-scheduled-dataflows.md`、`docs/sop/RUNBOOK.md:3` | 文档 |
| Tests | `tests/decision/test_day_broadcast.py`、`tests/decision/test_day_results.py`、`tests/test_launchd_plists.py`；追加 `tests/decision/test_day_runner.py`、`tests/test_cli_day.py` |

---

### Task 1: 赛果桥 `day_results.bridge_results`

`jc-results.json` 形状（实测）：`{ "2026-09-21": { "周一001": {"match_id": "3088016", "ft_home": 5, "ft_away": 1, "ht_home": 2, "ht_away": 0, "line": "1.75"} } }`。
`betslip settle --results-file` 形状（`--help`）：`{腿key: {outcome_90, goals_h, goals_a}}`；竞彩腿 key 用板面代码。

**Files:**
- Create: `nutmeg/decision/day_results.py`
- Test: `tests/decision/test_day_results.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_results.py
import json
from pathlib import Path

from nutmeg.decision.day_results import bridge_results, outcome_90


def test_outcome_90_uses_sporttery_face_codes():
    assert outcome_90(2, 1) == "3" and outcome_90(1, 1) == "1" and outcome_90(0, 3) == "0"


def test_bridge_results_writes_results_90_for_yesterday(tmp_path: Path):
    data = tmp_path / "data"
    (data / "jczq").mkdir(parents=True)
    (data / "jczq" / "jc-results.json").write_text(json.dumps({
        "2026-09-22": {"周二001": {"match_id": "1", "ft_home": 2, "ft_away": 0},
                       "周二002": {"match_id": "2", "ft_home": None, "ft_away": None}},
    }), encoding="utf-8")
    report = bridge_results(data_dir=data, date="2026-09-23")
    doc = json.loads((data / "daily" / "2026-09-23" / "results-90.json").read_text(encoding="utf-8"))
    assert doc == {"周二001": {"outcome_90": "3", "goals_h": 2, "goals_a": 0}}
    assert report == {"source_day": "2026-09-22", "written": 1, "missing": ["周二002"]}


def test_bridge_results_without_source_day_writes_nothing(tmp_path: Path):
    data = tmp_path / "data"
    (data / "jczq").mkdir(parents=True)
    (data / "jczq" / "jc-results.json").write_text("{}", encoding="utf-8")
    assert bridge_results(data_dir=data, date="2026-09-23") == {"source_day": "2026-09-22", "written": 0, "missing": []}
    assert not (data / "daily" / "2026-09-23" / "results-90.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/decision/test_day_results.py -q`
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_results.py
"""昨日赛果桥：`jczq/jc-results.json`（09:30 回填）→ `daily/<日>/results-90.json`（betslip settle 的输入）。

只转格式；缺终场比分的场进 `missing`，不猜。源头过期时（回填脚本退出 2）这里自然写不出东西。
"""
from __future__ import annotations

import json
from datetime import date as _date
from datetime import timedelta
from pathlib import Path

from nutmeg.decision.day_paths import RESULTS_90, day_dir


def outcome_90(goals_h: int, goals_a: int) -> str:
    return "3" if goals_h > goals_a else ("1" if goals_h == goals_a else "0")


def bridge_results(*, data_dir: Path, date: str) -> dict:
    source_day = (_date.fromisoformat(date) - timedelta(days=1)).isoformat()
    path = Path(data_dir) / "jczq" / "jc-results.json"
    try:
        table = json.loads(path.read_text(encoding="utf-8")).get(source_day) or {}
    except (FileNotFoundError, ValueError):
        table = {}
    out: dict[str, dict] = {}
    missing: list[str] = []
    for code, row in sorted(table.items()):
        gh, ga = row.get("ft_home"), row.get("ft_away")
        if gh is None or ga is None:
            missing.append(code)
            continue
        out[code] = {"outcome_90": outcome_90(int(gh), int(ga)), "goals_h": int(gh), "goals_a": int(ga)}
    if out:
        target = day_dir(data_dir, date) / RESULTS_90
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"source_day": source_day, "written": len(out), "missing": missing}
```

- [ ] **Step 4: Run test to verify it passes** — `uv run pytest tests/decision/test_day_results.py -q` → `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_results.py tests/decision/test_day_results.py
git commit -m "feat(day): bridge yesterday's jc-results into results-90.json for betslip settle"
```

---

### Task 2: 播报 `day_broadcast`

**Files:**
- Create: `nutmeg/decision/day_broadcast.py`
- Test: `tests/decision/test_day_broadcast.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/decision/test_day_broadcast.py
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.day_broadcast import due_broadcasts, read_sent, render_broadcast, send_all

BJ = timezone(timedelta(hours=8))
DEC = [
    {"id": "read:周三001", "kind": "approve_read", "subject": "周三001 A vs B", "status": "open",
     "deadline": "2026-09-23T19:30:00+08:00", "default_action": "草稿不入库＝跟市场"},
    {"id": "plan:26132", "kind": "plan_choose_commit", "subject": "26132 定案", "status": "open",
     "deadline": "2026-09-23T21:00:00+08:00", "default_action": "空仓"},
    {"id": "rsi:0", "kind": "rsi", "subject": "C11", "status": "open", "deadline": None, "default_action": "hold"},
    {"id": "read:周三009", "kind": "approve_read", "subject": "done one", "status": "done",
     "deadline": "2026-09-23T19:30:00+08:00", "default_action": "x"},
]


def test_due_broadcasts_fire_t30_then_t10_once_each():
    at_19_05 = datetime(2026, 9, 23, 19, 5, tzinfo=BJ)
    due = due_broadcasts(DEC, now=at_19_05, sent=set())
    assert [(b.key, b.minutes_left) for b in due] == [("read:周三001@T30", 25)]
    assert due_broadcasts(DEC, now=at_19_05, sent={"read:周三001@T30"}) == []
    at_19_25 = datetime(2026, 9, 23, 19, 25, tzinfo=BJ)
    assert [b.key for b in due_broadcasts(DEC, now=at_19_25, sent={"read:周三001@T30"})] == ["read:周三001@T10"]
    at_20_45 = datetime(2026, 9, 23, 20, 45, tzinfo=BJ)
    assert [b.key for b in due_broadcasts(DEC, now=at_20_45, sent=set())] == ["plan:26132@T30"]


def test_render_broadcast_states_time_and_default_action():
    b = due_broadcasts(DEC, now=datetime(2026, 9, 23, 19, 5, tzinfo=BJ), sent=set())[0]
    text = render_broadcast(b)
    assert text.startswith("⏰ 剩 25 分（截止 19:30）")
    assert "周三001 A vs B" in text and "未定则默认：草稿不入库＝跟市场" in text
    assert "不代下单" in text


def test_send_all_records_sent_keys_and_survives_sender_errors(tmp_path: Path):
    calls: list[str] = []

    def sender(text: str) -> None:
        calls.append(text)
        if "26132" in text:
            raise RuntimeError("telegram down")

    now = datetime(2026, 9, 23, 20, 45, tzinfo=BJ)
    dec = DEC + [{"id": "read:周三010", "kind": "approve_read", "subject": "late", "status": "open",
                  "deadline": "2026-09-23T21:05:00+08:00", "default_action": "跟市场"}]
    report = send_all(dec, data_dir=tmp_path, date="2026-09-23", now=now, sender=sender)
    assert report["sent"] == ["read:周三010@T30"] and report["failed"] == ["plan:26132@T30"]
    assert read_sent(tmp_path, "2026-09-23") == {"read:周三010@T30"}
    rows = (tmp_path / "daily" / "2026-09-23" / "broadcasts.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(rows[0])["key"] == "read:周三010@T30"
```

- [ ] **Step 2: Run test to verify it fails** — `uv run pytest tests/decision/test_day_broadcast.py -q` → `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# nutmeg/decision/day_broadcast.py
"""截止播报（deadline_broadcast_discipline）：T-30 / T-10 各一次，明写默认动作；只报时间，不代决、不下单。"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
        left = int((deadline - now).total_seconds() // 60)
        for label, hi, lo in WINDOWS:
            key = f"{d['id']}@{label}"
            if lo < left <= hi and key not in sent:
                out.append(Broadcast(key=key, decision=d, minutes_left=left, window=label))
    return out


def render_broadcast(b: Broadcast) -> str:
    d = b.decision
    return (f"⏰ 剩 {b.minutes_left} 分（截止 {d['deadline'][11:16]}）\n"
            f"{d['subject']}\n未定则默认：{d['default_action']}\n"
            f"（Nutmeg 只播报时间，不代下单；回复或打开 /day 处理）")


def read_sent(data_dir: Path | str, date: str) -> set[str]:
    path = day_dir(data_dir, date) / BROADCASTS
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.add(json.loads(line)["key"])
    return keys


def send_all(decisions: list[dict], *, data_dir: Path | str, date: str, now: datetime, sender: Sender) -> dict:
    sent_keys = read_sent(data_dir, date)
    path = day_dir(data_dir, date) / BROADCASTS
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"sent": [], "failed": []}
    for b in due_broadcasts(decisions, now=now, sent=sent_keys):
        try:
            sender(render_broadcast(b))
        except Exception as exc:  # noqa: BLE001 — 发送失败下一轮再试
            report["failed"].append(b.key)
            continue
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"key": b.key, "at": now.isoformat(timespec="seconds"),
                                 "minutes_left": b.minutes_left}, ensure_ascii=False) + "\n")
        report["sent"].append(b.key)
    return report


def telegram_sender() -> Sender:
    """默认发送器：settings 里的 bot token + 允许的 chat id（逗号分隔）。"""
    from nutmeg.config.settings import get_settings
    from nutmeg.interfaces.bot.telegram import TelegramBotClient

    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_allowed_chat_ids:
        raise RuntimeError("telegram not configured (NUTMEG_TELEGRAM_BOT_TOKEN / _ALLOWED_CHAT_IDS)")
    client = TelegramBotClient(token=settings.telegram_bot_token, base_url=settings.telegram_api_base_url)
    chat_ids = [int(x) for x in settings.telegram_allowed_chat_ids.split(",") if x.strip()]

    def send(text: str) -> None:
        for chat_id in chat_ids:
            client.send_message(chat_id=chat_id, text=text)

    return send
```

- [ ] **Step 4: Run test to verify it passes** — `3 passed`

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_broadcast.py tests/decision/test_day_broadcast.py
git commit -m "feat(day): T-30/T-10 deadline broadcasts with default action, deduplicated per day"
```

---

### Task 3: 接进运行器与 CLI

**Files:**
- Modify: `nutmeg/decision/day_runner.py`（`JOBS`、`DayContext.sender`、`run_job` 两个分支）
- Modify: `nutmeg/interfaces/cli/day.py`（`--job` 说明；broadcast `--dry-run` 打印文本）
- Test: 追加 `tests/decision/test_day_runner.py`、`tests/test_cli_day.py`

- [ ] **Step 1: Write the failing tests**

```python
# 追加到 tests/decision/test_day_runner.py
from datetime import datetime as _dt


def test_results_job_writes_results_90_and_settle_then_picks_it_up(tmp_path: Path):
    log: list[list[str]] = []
    ctx = _ctx(tmp_path, log)
    (ctx.data_dir / "jczq" / "jc-results.json").write_text(
        json.dumps({"2026-09-22": {"周二001": {"match_id": "1", "ft_home": 1, "ft_away": 0}}}), encoding="utf-8")
    rec = run_job(ctx, "results")
    assert rec.exit == 0 and "written=1" in rec.summary
    assert any("betslip" in c for c in planned_commands(ctx, "settle"))


def test_broadcast_job_uses_injected_sender(tmp_path: Path):
    sent: list[str] = []
    ctx = _ctx(tmp_path, [])
    ctx.sender = sent.append
    ctx.now = lambda: _dt(2026, 9, 23, 19, 5, tzinfo=BJ)
    out = day_dir(ctx.data_dir, "2026-09-23"); out.mkdir(parents=True, exist_ok=True)
    (out / "decisions.json").write_text(json.dumps([{"id": "read:周三001", "kind": "approve_read", "subject": "A vs B",
        "status": "open", "deadline": "2026-09-23T19:30:00+08:00", "default_action": "跟市场"}]), encoding="utf-8")
    rec = run_job(ctx, "broadcast")
    assert rec.exit == 0 and sent and "剩 25 分" in sent[0] and "sent=1" in rec.summary
    assert run_job(ctx, "broadcast").summary.endswith("sent=0 failed=0")  # deduplicated
```

```python
# 追加到 tests/test_cli_day.py
def test_day_broadcast_dry_run_prints_text_without_sending(tmp_path: Path):
    data = _data(tmp_path)
    out = data / "daily" / "2026-09-23"; out.mkdir(parents=True)
    (out / "decisions.json").write_text(json.dumps([{"id": "plan:26132", "kind": "plan_choose_commit", "subject": "定案",
        "status": "open", "deadline": "2099-01-01T21:00:00+08:00", "default_action": "空仓"}]), encoding="utf-8")
    r = runner.invoke(app, ["day", "run", "--job", "broadcast", "--date", "2026-09-23", "--data-dir", str(data),
                            "--dry-run", "--now", "2099-01-01T20:45:00+08:00"])
    assert r.exit_code == 0 and "剩 15 分" in r.output and "空仓" in r.output
    assert not (out / "broadcasts.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify they fail** — `ValueError: unknown job 'results'` / `No such option: --now`

- [ ] **Step 3: Implement**

`day_runner.py`：

```python
JOBS = ("settle", "brief", "session", "results", "broadcast")
```

`DayContext` 加字段：

```python
    sender: Callable[[str], None] | None = None
```

`run_job` 在 `else:`（session）之前加两个分支：

```python
    elif job == "results":
        from nutmeg.decision.day_results import bridge_results

        report = bridge_results(data_dir=ctx.data_dir, date=ctx.date)
        summary = f"results 源 {report['source_day']} written={report['written']} missing={len(report['missing'])}"
        exit_code = 0
        evidence = str(ctx.out_dir / RESULTS_90) if report["written"] else None
    elif job == "broadcast":
        from nutmeg.decision.day_broadcast import send_all, telegram_sender

        dec_path = ctx.out_dir / DECISIONS
        decisions = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.exists() else []
        try:
            sender = ctx.sender or telegram_sender()
            report = send_all(decisions, data_dir=ctx.data_dir, date=ctx.date, now=ctx.now(), sender=sender)
            summary = f"broadcast sent={len(report['sent'])} failed={len(report['failed'])}"
            exit_code = 1 if report["failed"] else 0
        except RuntimeError as exc:  # telegram 未配置
            summary, exit_code = f"broadcast 未发：{exc}", 1
```

`cli/day.py`：`_JOB` help 改 `"settle | brief | session | results | broadcast"`；`run` 加 `now: str | None = typer.Option(None, "--now", help="测试用 ISO 时刻")`，`_ctx` 接 `now` 参数：`now=(lambda: datetime.fromisoformat(now)) if now else _now`；`--dry-run` 时若 `job == "broadcast"`：

```python
        if job == "broadcast":
            from nutmeg.decision.day_broadcast import due_broadcasts, read_sent, render_broadcast

            dec_path = ctx.out_dir / "decisions.json"
            decisions = json.loads(dec_path.read_text(encoding="utf-8")) if dec_path.exists() else []
            for b in due_broadcasts(decisions, now=ctx.now(), sent=read_sent(ctx.data_dir, ctx.date)):
                typer.echo(render_broadcast(b) + "\n---")
            return
```

- [ ] **Step 4: Run** `uv run pytest tests/decision/test_day_runner.py tests/test_cli_day.py -q` → 全部 passed

- [ ] **Step 5: Commit**

```bash
git add nutmeg/decision/day_runner.py nutmeg/interfaces/cli/day.py tests/decision/test_day_runner.py tests/test_cli_day.py
git commit -m "feat(day): results and broadcast jobs in the runner and CLI"
```

---

### Task 4: launchd plist ×4 + 统一 plist 测试

**Files:**
- Create: `ops/launchd/com.nutmeg.day.settle.plist`（07:30 `day run --job results && day run --job settle`）
- Create: `ops/launchd/com.nutmeg.jczq.research.plist`（10:00 `research run --day` → `research intake --write` → `jczq-build-reads`）
- Create: `ops/launchd/com.nutmeg.day.brief.plist`（12:00、14:20、18:35 三个 `StartCalendarInterval`；`day run --job brief`）
- Create: `ops/launchd/com.nutmeg.day.broadcast.plist`（`StartInterval` 600；`day run --job broadcast`）
- Test: `tests/test_launchd_plists.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_launchd_plists.py
import plistlib
from pathlib import Path

PLISTS = Path("ops/launchd")
EXPECTED = {
    "com.nutmeg.day.settle": ("07:30", "day run --job results", "day run --job settle"),
    "com.nutmeg.jczq.research": ("10:00", "research run --day", "research intake --day", "jczq-build-reads --day"),
    "com.nutmeg.day.brief": ("12:00,14:20,18:35", "day run --job brief"),
    "com.nutmeg.day.broadcast": ("every 600s", "day run --job broadcast"),
    "com.nutmeg.rsi.loop": ("10:45", "rsi loop"),
}


def _schedule(doc: dict) -> str:
    if "StartInterval" in doc:
        return f"every {doc['StartInterval']}s"
    cal = doc["StartCalendarInterval"]
    cal = cal if isinstance(cal, list) else [cal]
    return ",".join(f"{c['Hour']:02d}:{c.get('Minute', 0):02d}" for c in cal)


def test_every_plist_is_wellformed_and_self_consistent():
    for path in sorted(PLISTS.glob("com.nutmeg.*.plist")):
        doc = plistlib.loads(path.read_bytes())
        assert doc["Label"] == path.stem, path
        assert doc["ProgramArguments"], path
        assert "StartCalendarInterval" in doc or "StartInterval" in doc, path


def test_daily_surface_plists_call_expected_commands():
    for label, (schedule, *fragments) in EXPECTED.items():
        doc = plistlib.loads((PLISTS / f"{label}.plist").read_bytes())
        assert _schedule(doc) == schedule, label
        program = " ".join(doc["ProgramArguments"])
        for fragment in fragments:
            assert fragment in program, (label, fragment)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_launchd_plists.py -q` → FAIL `FileNotFoundError: ops/launchd/com.nutmeg.day.settle.plist`

- [ ] **Step 3: Write the plists**（模板同 `com.nutmeg.rsi.sweep.plist`，含 `EnvironmentVariables.PATH`）

`ops/launchd/com.nutmeg.day.settle.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/Users/jz71/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>Label</key><string>com.nutmeg.day.settle</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cd /Users/jz71/Projects/Nutmeg &amp;&amp; /opt/homebrew/bin/uv run nutmeg day run --job results --data-dir /Users/jz71/Projects/Nutmeg/.nutmeg-data; /opt/homebrew/bin/uv run nutmeg day run --job settle --data-dir /Users/jz71/Projects/Nutmeg/.nutmeg-data</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/jz71/Projects/Nutmeg/.nutmeg-data/logs/day.settle.out.log</string>
  <key>StandardErrorPath</key><string>/Users/jz71/Projects/Nutmeg/.nutmeg-data/logs/day.settle.err.log</string>
  <key>WorkingDirectory</key><string>/Users/jz71/Projects/Nutmeg</string>
</dict>
</plist>
```

`com.nutmeg.jczq.research.plist`（10:00）的命令串：

```
cd /Users/jz71/Projects/Nutmeg && D=$(date +%F) && /opt/homebrew/bin/uv run nutmeg research run --day $D --data-dir /Users/jz71/Projects/Nutmeg/.nutmeg-data; /opt/homebrew/bin/uv run nutmeg research intake --day $D --write; /opt/homebrew/bin/uv run nutmeg jczq-build-reads --day $D
```

`com.nutmeg.day.brief.plist` 的 `StartCalendarInterval` 用数组：

```xml
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>20</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>35</integer></dict>
  </array>
```

命令：`cd … && /opt/homebrew/bin/uv run nutmeg day run --job brief --data-dir …/.nutmeg-data`

`com.nutmeg.day.broadcast.plist`：`<key>StartInterval</key><integer>600</integer>`，命令 `… nutmeg day run --job broadcast --data-dir …`。

- [ ] **Step 4: Run** `uv run pytest tests/test_launchd_plists.py -q` → `2 passed`

- [ ] **Step 5: Commit**

```bash
git add ops/launchd/com.nutmeg.day.settle.plist ops/launchd/com.nutmeg.jczq.research.plist ops/launchd/com.nutmeg.day.brief.plist ops/launchd/com.nutmeg.day.broadcast.plist tests/test_launchd_plists.py
git commit -m "ops(launchd): day settle/brief/broadcast and jczq research timers (not loaded)"
```

---

### Task 5: 文档与装载说明（装载是 Jun 的门）

- [ ] `docs/ops/2026-09-20-scheduled-dataflows.md` 表加四行（07:30 day.settle、10:00 jczq.research、12:00/14:20/18:35 day.brief、每 10 分 day.broadcast），每行写「断流后果」：settle 断 → 昨日复盘草稿与实票结算缺；research 断 → 板上只剩 market-anchor 草稿；brief 断 → `/day` 与 `/today` 读到旧报告；broadcast 断 → 截止无人提醒（26130 复发）。
- [ ] `docs/sop/RUNBOOK.md:3` 那句「launchd 的 am/close/settle 仍禁用，全部手动」改为「launchd：am 08:00 自动；close 仍手动；settle 由 `com.nutmeg.day.settle` 07:30 承担（装载后）」。
- [ ] 在 evidence 文档末尾给装载命令（不执行）：

```bash
for p in day.settle jczq.research day.brief day.broadcast; do
  cp ops/launchd/com.nutmeg.$p.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.nutmeg.$p.plist; done
launchctl list | grep nutmeg
```

- [ ] `git add docs/ops/2026-09-20-scheduled-dataflows.md docs/sop/RUNBOOK.md docs/superpowers/evidence/2026-09-2X-daily-surface-p3.md && git commit -m "docs(ops): daily surface timers and their failure consequences"`

---

## Self-review

- §5 ★ 项：07:30 settle（含 results 桥）✓、10:00 深研定时 ✓、12:00/14:20/18:35 brief ✓（比 18:30 备料晚 5 分钟，让 revision 先落盘）、播报 ✓；`research board` 已由 `decision.am` 链上的 `after_am()` 负责，不重复。
- §9：播报文本明写「不代下单」✓；broadcast 只读 decisions.json ✓。
- results-backfill 退出 2：不在这里「修」——P2 的状态条把它亮出来，settle 的 results 桥在源过期时 `written=0`，两处都如实。
- 类型一致：`DayContext.sender` 可选；`send_all(decisions, *, data_dir, date, now, sender)`；`Broadcast(key, decision, minutes_left, window)`。
