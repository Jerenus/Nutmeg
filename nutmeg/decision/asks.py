"""应答员（2026-11-02 产品形态第 10 阶段 Task 10.4，Jun 定走 `claude -p`）。

Jun 在决策页某一行（一期 / 一场 / 竞彩一场 / 账房一期）上提问；问题进当天讨论流，后台用 Claude
无头会话作答，答案写回同一线程并推 Telegram。此前追问只活在会话里（06-13→10-30 约 235 次），
答过的下次又问。

存储：复用 `daily/<日>/discussion.jsonl`（当日页照常显示），两种行：
- 问 `{"seq","who":"jun","obj","text","at","ask":true}`；
- 答 `{"seq","who":"应答员","obj","text","at","reply_to":<问的 seq>,"status":"answered"|"failed",
  "sources":[…],"corrections":[id…],"proposals":[id…],"duration_s","cost_usd","model"}`。
没有答行的问＝待答。答过的问不再自动重答（失败了就再问一次）。

只读：应答员的工具只有 Read / Grep / Glob（凭据文件拒读），没有写权限。会改表的回答只能产出
**纠正草稿**（corrections，Jun 在页上确认）或 **待签提案**（proposals，进 `/inbox`）——不假装已改。
"""
from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path

from nutmeg.decision.day_session import append_discussion, read_discussion

ASKER = "jun"
ANSWERER = "应答员"
QUICK = ("要防平吗", "钱往哪边", "和哪场死法像", "要补跑吗", "只能单选呢")
"""快捷问法（画布 AskPhone）。"""
PREFIXES = ("issue", "jczq", "ledger", "slip", "rule", "experiment")
"""`obj` 命名与纠正账同一套（见 corrections.py 文首）。"""
LOOKBACK_DAYS = 30
PENDING_DAYS = 2
"""只自动答最近两天的问：更早的没答上就是答不上了，别在重启时突然花钱。"""
TOOLS = "Read,Grep,Glob"
DENY_READ = ("Read(./.env*)", "Read(~/.config/nutmeg/**)", "Read(~/.ssh/**)")
MAX_TURNS = "24"
TIMEOUT_S = 600
EXCERPT_CHARS = 14000
REPO = Path(__file__).resolve().parents[2]

_lock = threading.Lock()   # 同进程里问与答都追加同一份讨论流；seq 按行数算，必须串行


def _now() -> datetime:
    from nutmeg.decision.bj_time import BJ

    return datetime.now(BJ)


def check_obj(obj: str) -> str:
    obj = (obj or "").strip()
    head, _, rest = obj.partition(":")
    if head not in PREFIXES or not rest or any(c.isspace() for c in obj):
        raise ValueError(f"obj 须为 {'/'.join(PREFIXES)}:<…>，不含空白（收到 {obj!r}）")
    return obj


def page_path(obj: str) -> str:
    """对象所在的页（推送链接与提示里用）；没有页的对象返回空。"""
    head, _, rest = obj.partition(":")
    top = rest.split("/", 1)[0]
    return {"issue": f"/issue/{top}", "jczq": f"/jczq/{top}",
            "ledger": f"/ledger/{top}"}.get(head, "")


def ask(data_dir: Path | str, *, obj: str, text: str, at: datetime | None = None) -> dict:
    """记一个问 → `{"date","seq"}`。"""
    obj = check_obj(obj)
    text = (text or "").strip()
    if not text:
        raise ValueError("问题为空")
    at = at or _now()
    day = at.date().isoformat()
    with _lock:
        append_discussion(data_dir, day, who=ASKER, text=text, obj=obj,
                          at=at.isoformat(timespec="seconds"), extra={"ask": True})
        seq = len(read_discussion(data_dir, day))
    return {"date": day, "seq": seq}


def _days(today: str, n: int) -> list[str]:
    end = _date.fromisoformat(today)
    return [(end - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _covers(obj: str, row_obj: str) -> bool:
    return row_obj == obj or row_obj.startswith(obj + "/")


def thread(data_dir: Path | str, obj: str, *, today: str,
           days: int = LOOKBACK_DAYS) -> list[dict]:
    """该对象（含下属对象）近 `days` 天的问，按时间排；每个问带 `answer`（无则 None）。"""
    out = []
    for day in _days(today, days):
        rows = read_discussion(data_dir, day)
        answers = {r["reply_to"]: r for r in rows if r.get("reply_to") is not None}
        for r in rows:
            if r.get("ask") and _covers(obj, r.get("obj") or ""):
                out.append({**r, "date": day, "answer": answers.get(r["seq"])})
    return out


def pending(data_dir: Path | str, *, today: str, days: int = PENDING_DAYS) -> list[dict]:
    out = []
    for day in _days(today, days):
        rows = read_discussion(data_dir, day)
        replied = {r["reply_to"] for r in rows if r.get("reply_to") is not None}
        out += [{**r, "date": day} for r in rows if r.get("ask") and r["seq"] not in replied]
    return out


# ---- 作答 ----------------------------------------------------------------

SYSTEM = """你是 Nutmeg 的应答员。Jun 在决策页的某一行上提了一个问题，你只回答这一个问题。

先读仓里 CLAUDE.md 指向的 SOP 三件套（docs/sop/CONSTITUTION.md、RUNBOOK.md、RULEBOOK.md）
里与问题相关的段落。
项目定位：机器＝风控官＋账房＋实验员，人下注；EV 不进决策层；赔率是噪声识别器。

纪律：
- 数字只照抄文件，写明出处（文件路径，或研究里的 URL＋原句）；
  文件里没有、算不出来就直说，不许心算凑数。
- 客观独立，不迎合：和 Jun 的判断或他的规则冲突，先说冲突；结论带样本量 n。
- 你没有写权限。若答案意味着表上某个数或判断该改，写进 corrections（草稿，Jun 在页上确认）；
  若需要 Jun 签字的新规则或口径，写进 proposals。不要说「已改」。
- 不读 .env 与任何凭据文件；回答里不出现密钥、密码、令牌。
- 先结论后理由，中文，400 字以内；用「几成」或百分比，不写 EV。

只回一个 JSON 对象，不要任何其他文字：
{"answer": "…", "sources": ["路径或 URL：原句"],
 "corrections": [{"obj": "issue:26153/m7/q4", "old": "…", "new": "…",
                  "kind": "data|transcription|premise|self", "evidence": "…"}],
 "proposals": [{"title": "…", "body": "…", "blocks": "拦住了什么"}]}
没有就给空数组。"""


def _hints(data_dir: Path, obj: str) -> list[str]:
    head, _, rest = obj.partition(":")
    top, _, sub = rest.partition("/")
    d = data_dir
    if head == "issue":
        out = [f"{d}/zucai/{top}-*（packet 旁车、draft 初稿、counter-matrix 反证矩阵、"
               "dead-align 死法对位、lineup-watch 首发、zgzcw/odds 市场、polymarket 人群、"
               "team-load 损耗、bridge §3 桥）"]
        m = re.match(r"m(\d+)", sub)
        if m:
            no = m.group(1)
            out.append(f"{d}/zucai/{top}-research-m{no}.json 与 -rubric-m{no}.json（研究原件；"
                       "没有＝这场没跑深研，竞彩重叠场见 channel-map 指向的 jczq 研究）")
        return out + [f"{d}/betslips.jsonl（登记簿）", f"{d}/scoreboard.json（记分牌）"]
    if head == "jczq":
        out = [f"{d}/jczq/daily/{top}/（板面 jczq-legs-base.json、判读、价带、人群）"]
        if sub:
            out.append(f"{d}/jczq/daily/{top}/research-{sub}.json（研究原件）")
        return out + [f"{d}/betslips.jsonl（登记簿）"]
    if head in ("ledger", "slip"):
        return [f"{d}/scoreboard.json（记分牌，账的唯一事实源）", f"{d}/betslips.jsonl（登记簿）"]
    return [f"{REPO}/docs/sop/RULEBOOK.md", f"{d}/analytics/rsi-loop/（实验闭环）"]


def build_prompt(data_dir: Path | str, q: dict, *, excerpt: str, history: list[dict]) -> str:
    lines = [f"对象：{q['obj']}", f"页面：{page_path(q['obj']) or '—'}",
             f"提问时刻：{q['at']}", f"问题：{q['text']}", ""]
    earlier = [h for h in history if h["seq"] != q["seq"] or h["date"] != q["date"]][-4:]
    if earlier:
        lines.append("这一行上之前的问答（新的在后）：")
        for h in earlier:
            ans = (h.get("answer") or {}).get("text") or "（未答）"
            lines += [f"- 问 {h['at'][:16]}：{h['text']}", f"  答：{ans[:600]}"]
        lines.append("")
    lines.append("可读的文件：")
    lines += [f"- {h}" for h in _hints(Path(data_dir), q["obj"])]
    lines += ["", "页面上这一行此刻显示的数据（JSON，可能截断）：", excerpt[:EXCERPT_CHARS]]
    return "\n".join(lines)


def parse_reply(text: str) -> dict:
    """应答员的输出 → {answer, sources, corrections, proposals}；不是 JSON 就整段当回答。"""
    doc = None
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            doc = json.loads(text[start:end + 1])
        except ValueError:
            doc = None
    if not isinstance(doc, dict) or not str(doc.get("answer") or "").strip():
        return {"answer": text.strip(), "sources": [], "corrections": [], "proposals": []}

    def _list(key):
        value = doc.get(key)
        return value if isinstance(value, list) else []

    return {"answer": str(doc["answer"]).strip(),
            "sources": [str(s) for s in _list("sources")],
            "corrections": [c for c in _list("corrections") if isinstance(c, dict)],
            "proposals": [p for p in _list("proposals") if isinstance(p, dict)]}


def _secrets() -> list[str]:
    from nutmeg.config.settings import get_settings

    out = []
    for name, value in get_settings().model_dump().items():
        if isinstance(value, str) and len(value) >= 8 and \
                any(k in name for k in ("token", "key", "password", "secret")):
            out.append(value)
    return out


def redact(text: str, secrets: list[str] | None = None) -> str:
    for secret in _secrets() if secrets is None else secrets:
        text = text.replace(secret, "＊＊＊")
    return text


def _drafts(data_dir: Path | str, q: dict, reply: dict, ref: str) -> tuple[list[str], list[str]]:
    """回答里的改表建议 → 纠正草稿 / 待签提案。字段不合法的一条丢掉、记进 errors。"""
    from nutmeg.decision import corrections, proposals

    cids, pids, errors = [], [], []
    for c in reply["corrections"]:
        try:
            obj = check_obj(str(c.get("obj") or q["obj"]))
            kind = c.get("kind") if c.get("kind") in corrections.KINDS else "self"
            cids.append(corrections.record(
                data_dir, obj=obj, old=str(c.get("old") or ""), new=str(c.get("new") or ""),
                kind=kind, found_by="machine", evidence=str(c.get("evidence") or ""),
                status="draft", note=f"应答员 · {ref}", source="asker"))
        except ValueError as exc:
            errors.append(f"纠正草稿丢弃：{exc}")
    for p in reply["proposals"]:
        try:
            pids.append(proposals.propose(
                data_dir, title=str(p.get("title") or ""), body=str(p.get("body") or ""),
                blocks=str(p.get("blocks") or ""), ref=ref, source="asker"))
        except ValueError as exc:
            errors.append(f"提案丢弃：{exc}")
    reply["errors"] = errors
    return cids, pids


Runner = Callable[..., tuple[int, str, dict]]


def _default_runner(system: str, stdin: str, *, data_dir: Path) -> tuple[int, str, dict]:
    from nutmeg.decision.claude_models import logic_model, run_claude_json

    extra = ("--disallowedTools", *DENY_READ, "--add-dir", str(data_dir))
    return run_claude_json(system, stdin, model=logic_model(), allowed_tools=TOOLS,
                           max_turns=MAX_TURNS, timeout=TIMEOUT_S, cwd=str(REPO),
                           extra_argv=extra)


def answer(data_dir: Path | str, q: dict, *, excerpt: str, runner: Runner | None = None,
           push: Callable[[dict, dict], None] | None = None) -> dict:
    """答一个问（`q` 来自 `pending` / `thread`）→ 写进讨论流的答行。"""
    from nutmeg.decision.claude_models import is_auth_failure

    history = thread(data_dir, q["obj"], today=q["date"], days=7)
    stdin = build_prompt(data_dir, q, excerpt=excerpt, history=history)
    started = _now()
    try:
        code, text, meta = (runner or _default_runner)(SYSTEM, stdin, data_dir=Path(data_dir))
    except Exception as exc:  # noqa: BLE001 — 超时、找不到 claude：都记成失败答行
        code, text, meta = 1, f"{type(exc).__name__}: {exc}", {}
    ref = f"问 {q['date']}#{q['seq']}"
    extra = {"reply_to": q["seq"], "sources": [], "corrections": [], "proposals": [],
             "duration_s": meta.get("duration_s")
             or round((_now() - started).total_seconds(), 1),
             "cost_usd": meta.get("cost_usd"), "model": meta.get("model")}
    if code != 0:
        why = "claude 登录过期，需要在终端重新 /login" if is_auth_failure(text) else \
            (text.strip()[:300] or f"退出码 {code}")
        body, extra["status"] = f"没答上：{redact(why)}。再问一次会重试。", "failed"
    else:
        reply = parse_reply(redact(text))
        extra["corrections"], extra["proposals"] = _drafts(data_dir, q, reply, ref)
        extra["sources"] = reply["sources"]
        if reply["errors"]:
            extra["errors"] = reply["errors"]
        body, extra["status"] = reply["answer"], "answered"
    with _lock:
        append_discussion(data_dir, q["date"], who=ANSWERER, text=body, obj=q["obj"],
                          at=_now().isoformat(timespec="seconds"), extra=extra)
    row = {**extra, "text": body, "obj": q["obj"]}
    if push:
        push(q, row)
    return row


def telegram_text(q: dict, row: dict, *, base_url: str) -> str:
    """推送正文：问一句、答（截断）、草稿数、页面链接。"""
    lines = [f"应答员 · {q['obj']}", f"问：{q['text']}", "", row["text"][:700]]
    drafts = []
    if row.get("corrections"):
        drafts.append(f"纠正草稿 {len(row['corrections'])} 条待你确认")
    if row.get("proposals"):
        drafts.append(f"待签提案 {len(row['proposals'])} 条")
    if drafts:
        lines += ["", "；".join(drafts)]
    path = page_path(q["obj"])
    if base_url and path:
        lines += ["", f"打开 {base_url}{path}"]
    return "\n".join(lines)


def telegram_push(q: dict, row: dict) -> None:
    from nutmeg.config.settings import decision_web_base_url
    from nutmeg.notifications.notify import notify

    notify("ask", f"{q['date']}#{q['seq']}", row.get("status") or "answered",
           telegram_text(q, row, base_url=decision_web_base_url()))


def work(data_dir: Path | str, *, today: str, excerpt_for: Callable[[str], str],
         runner: Runner | None = None, push: Callable[[dict, dict], None] | None = None,
         busy: set | None = None) -> list[dict]:
    """把最近两天的待答问一个个答掉（同一时刻只答一个，省钱也省乱）。
    `busy` 由网页传入：正在答的 (日, seq) 放进去，页面据此显示「在读」。"""
    done = []
    for q in pending(data_dir, today=today):
        key = (q["date"], q["seq"])
        if busy is not None:
            busy.add(key)
        try:
            try:
                excerpt = excerpt_for(q["obj"])
            except Exception as exc:  # noqa: BLE001 — 页面数据拼不出来也照样答，告诉它缺了
                excerpt = f"（页面数据取不到：{type(exc).__name__}: {exc}）"
            done.append(answer(data_dir, q, excerpt=excerpt, runner=runner, push=push))
        finally:
            if busy is not None:
                busy.discard(key)
    return done
