"""票据收件（2026-11-02 产品形态第 10 阶段 Task 10.5）。

Jun 下完单发 500 截图，此前由会话肉眼抄进登记簿：抄错 ≥8 次（10-25 截图与抄录差一倍注数）、
开球后才登记 ≥5 次。这里把截图交给 `claude -p` 看图读格（与应答员同一条通道），结果只是**草稿**：
页面把读出的格填进决策表，看不清的格要 Jun 点选，截图底部的注数 / 金额必须和抄录卡（`slip500`，
与登记同源）算出来的一致才放行，最后仍走 `/action/issue/{期}/register` 登记。机器不替人登记。

落盘：`<data_dir>/intake/<期>/<id>.<ext>`（原图）与 `<id>.json`（读数或失败原因）——抄录有据可查。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

INTAKE_DIR = "intake"
EXTS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/heic": "heic"}
MAX_BYTES = 12 * 1024 * 1024
DAILY_CAP = 30
"""一天最多收 30 张截图（2026-11-02 加固）：每张一次 `claude -p`，防刷费用与塞满磁盘。"""
FACE_ORDER = "310"
CHANNELS = ("renjiu", "shengfucai")
TIMEOUT_S = 300

SYSTEM = """你是票据抄录员。用 Read 工具打开给你的截图（500 彩票网 / 体彩 app 的足彩任九或
胜负彩投注页、确认页或方案详情页），只抄录，不评论。

规则：
- 每场看哪几格被选中（深色 / 高亮 / 打勾），按 3＝胜(主胜)、1＝平、0＝负(客胜) 写成字符串，如 "31"。
  没选的场不列。截图上的场序号就是场号；没有场号时按给你的对阵表对上队名。
- 看不清、颜色介于选与不选之间、被遮挡的格：doubt=true，faces 写你最可能的读法，options 列出其他可能
  （如 ["3"]），why 用一句话说哪里看不清。不许猜成确定。
- 底部「共 N 注」「N 元」「N 倍」照抄成数字；看不到写 null。
- channel：选了 9 场且页面是任选九＝"renjiu"；14 场全选＝"shengfucai"；看不出写 null。
- status_text：截图上能看到的购买状态原文（如「已付款」「出票成功」「试玩」「投注确认」），
  没有写 ""。

只回一个 JSON 对象，不要任何其他文字：
{"channel": "renjiu", "issue_seen": "26153", "cells": [{"no": "1", "faces": "3", "doubt": false,
  "options": [], "why": ""}], "notes": 64, "multiplier": 1, "stake": 128, "status_text": "",
 "scheme_no": ""}"""


def intake_dir(data_dir: Path | str, issue: str) -> Path:
    return Path(data_dir) / INTAKE_DIR / str(issue)


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """`data:image/png;base64,…` → (字节, 扩展名)。类型不在 EXTS 或超过 12MB 抛 ValueError。"""
    m = re.match(r"data:([\w/+.-]+);base64,(.*)$", data_url or "", re.S)
    if not m:
        raise ValueError("要一张图片（data URL）")
    kind = m.group(1).lower()
    if kind not in EXTS:
        raise ValueError(f"不认这种图片：{kind}（只收 {' / '.join(EXTS)}）")
    raw = base64.b64decode(m.group(2), validate=False)
    if len(raw) > MAX_BYTES:
        raise ValueError(f"图片太大：{len(raw) // 1024 // 1024}MB > 12MB")
    return raw, EXTS[kind]


def save_image(data_dir: Path | str, issue: str, raw: bytes, ext: str, *,
               now: datetime | None = None) -> str:
    """存原图 → 收件 id（`HHMMSS-<sha1 前 6 位>`，同一张图同一秒再传不重写）。"""
    from nutmeg.decision.bj_time import BJ

    now = now or datetime.now(BJ)
    today = sum(1 for p in Path(data_dir, INTAKE_DIR).glob(f"*/{now:%m%d}-*")
                if p.suffix.lstrip(".") in EXTS.values())
    if today >= DAILY_CAP:
        raise ValueError(f"今天已收 {today} 张截图，到每日上限 {DAILY_CAP}，明天再传")
    iid = f"{now:%m%d-%H%M%S}-{hashlib.sha1(raw).hexdigest()[:6]}"
    out = intake_dir(data_dir, issue)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{iid}.{ext}").write_bytes(raw)
    return iid


def image_path(data_dir: Path | str, issue: str, iid: str) -> Path | None:
    if not re.fullmatch(r"[\w-]+", iid or ""):
        return None
    return next((p for p in intake_dir(data_dir, issue).glob(f"{iid}.*")
                 if p.suffix.lstrip(".") in EXTS.values()), None)


def result_path(data_dir: Path | str, issue: str, iid: str) -> Path:
    return intake_dir(data_dir, issue) / f"{iid}.json"


def _faces(text) -> str:
    got = {c for c in str(text or "") if c in FACE_ORDER}
    return "".join(c for c in FACE_ORDER if c in got)


def _int(value) -> int | None:
    try:
        return int(float(str(value).replace(",", "").replace("元", "").strip()))
    except (TypeError, ValueError):
        return None


def normalize(doc: dict) -> dict:
    """应答员原样输出 → 页面用的读数：场号 1–14、面按 3/1/0 排、去重；不合法的格丢进 dropped。"""
    cells, dropped = [], []
    for c in doc.get("cells") or []:
        if not isinstance(c, dict):
            continue
        no, faces = str(c.get("no") or "").strip(), _faces(c.get("faces"))
        if not (no.isdigit() and 1 <= int(no) <= 14 and faces) or \
                any(x["no"] == no for x in cells):
            dropped.append(c)
            continue
        options = [o for o in (_faces(x) for x in c.get("options") or []) if o and o != faces]
        doubt = bool(c.get("doubt")) or bool(options)
        cells.append({"no": no, "faces": faces, "doubt": doubt, "options": options,
                      "why": str(c.get("why") or "")})
    cells.sort(key=lambda x: int(x["no"]))
    channel = doc.get("channel") if doc.get("channel") in CHANNELS else None
    return {"channel": channel, "issue_seen": str(doc.get("issue_seen") or ""), "cells": cells,
            "notes": _int(doc.get("notes")), "multiplier": _int(doc.get("multiplier")),
            "stake": _int(doc.get("stake")), "status_text": str(doc.get("status_text") or ""),
            "scheme_no": str(doc.get("scheme_no") or ""), "dropped": dropped}


def build_prompt(path: Path, issue: str, names: dict[str, str]) -> str:
    table = "\n".join(f"{no}: {name or '—'}" for no, name in names.items())
    return f"截图：{path}\n本期 {issue} 的 14 场对阵（场号: 主-客）：\n{table}"


Runner = Callable[..., tuple[int, str, dict]]


def _default_runner(system: str, stdin: str, *, folder: Path) -> tuple[int, str, dict]:
    from nutmeg.decision.claude_models import logic_model, run_claude_json

    return run_claude_json(system, stdin, model=logic_model(), allowed_tools="Read",
                           max_turns="4", timeout=TIMEOUT_S, extra_argv=("--add-dir", str(folder)))


def read_ticket(data_dir: Path | str, issue: str, iid: str, *, names: dict[str, str],
                runner: Runner | None = None) -> dict:
    """看图读格 → 写 `<id>.json` 并返回 `{"state":"done","read":{…}}` 或
    `{"state":"failed","error":…}`。"""
    from nutmeg.decision.claude_models import is_auth_failure

    path = image_path(data_dir, issue, iid)
    if path is None:
        raise KeyError(iid)
    try:
        code, text, meta = (runner or _default_runner)(SYSTEM, build_prompt(path, issue, names),
                                                        folder=path.parent)
    except Exception as exc:  # noqa: BLE001 — 超时 / 找不到 claude 都记成失败
        code, text, meta = 1, f"{type(exc).__name__}: {exc}", {}
    out: dict = {"id": iid, "image": path.name, "model": meta.get("model"),
                 "duration_s": meta.get("duration_s"), "cost_usd": meta.get("cost_usd")}
    doc = None
    if code == 0:
        start, end = text.find("{"), text.rfind("}")
        try:
            doc = json.loads(text[start:end + 1]) if start != -1 and end > start else None
        except ValueError:
            doc = None
    read = normalize(doc) if isinstance(doc, dict) else None
    if read and read["cells"]:
        out |= {"state": "done", "read": read}
    elif read is not None:
        out |= {"state": "failed", "error": "没读出任何一场的选项——不是投注截图，或太糊"}
    else:
        why = "claude 登录过期，需要在终端重新 /login" if is_auth_failure(text) else \
            (text.strip()[:300] or f"退出码 {code}")
        out |= {"state": "failed", "error": f"没读出来：{why}"}
    result_path(data_dir, issue, iid).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                 encoding="utf-8")
    return out


def load_result(data_dir: Path | str, issue: str, iid: str) -> dict | None:
    path = result_path(data_dir, issue, iid)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def reconcile(read: dict, *, notes: int | None, stake: int | None) -> dict:
    """截图底部的注数 / 金额 对 抄录卡算出来的（与登记同源）。截图上读不到的项不算对上。"""
    pairs = [("注数", read.get("notes"), notes), ("金额", read.get("stake"), stake)]
    rows = [{"label": label, "seen": seen, "computed": comp,
             "ok": seen is not None and comp is not None and int(seen) == int(comp)}
            for label, seen, comp in pairs]
    return {"ok": all(r["ok"] for r in rows), "rows": rows}
