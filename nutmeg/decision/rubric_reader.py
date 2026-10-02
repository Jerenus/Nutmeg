"""系统一读者（读者 B，2026-10-02 判断 rubric r1）——Jev 形状的任务。

输入 = 研究 JSON 里分析员写下的文本证据（state），不含 stance / rubric / 结论；
问题 = 固定问题表 r1；输出 = 只有 JSON 的 rubric 块：每题一个概率、不解释、不知道就弃权，
答"是"必须引用 state 里出现过的来源（否则校验器强制弃权）。

用途：①两读 kappa（分析员 vs 读者 B，逐项）；②历史重打分；③`--free` 模式只答整体概率
（不看问题表），与看表版本的分歧率是"分析员在写给表看"的监测指标。
产物是研究原件旁的侧车（原件只读）：竞彩 `rubric-<code>.json`，足彩 `<issue>-rubric-m<N>.json`。
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nutmeg.decision.claude_models import model_argv, model_label, reader_model
from nutmeg.decision.rubric import validate_rubric
from nutmeg.decision.rubric_items import ITEMS, RUBRIC_VERSION, question_table

Claude = Callable[[str, str], tuple[int, str]]
_BJ = timezone(timedelta(hours=8))
STATE_FIELDS = ("name", "summary", "anchor_side", "anchor_integrity", "anchor_integrity_detail",
                "hole_location", "license_questions", "crash_markers", "directional_flags",
                "nondirectional_flags", "precedents", "schedule", "anchor_absences",
                "opponent_absences", "expected_lineups", "predicted_lineups", "referee", "venue",
                "key_stats", "market_snapshot", "sources")
STRENGTH_FIELDS = ("verdict", "home_state", "away_state", "style_matchup", "tactical_scenarios",
                   "underdog_path", "events")
EXCLUDED = ("stance", "rubric", "confidence", "main_loop_rulings", "research_original_stance")

READER_PROMPT = f"""你是一个只做判断、不写文章的读者（系统一模型的形状）。
下面会给你一段 state（一位分析员对一场足球比赛写下的证据与结论之外的事实）和一张固定问题表。
对问题表**每一项**作答，只输出一个 JSON 对象，不要任何解释、前后缀或围栏：
{{"version": "{RUBRIC_VERSION}", "items": {{<id>: 答案, ...}},
 "belief": {{"3": p, "1": p, "0": p}}}}
答案格式：noul 项 → {{"p": 0到1 或 null}}；choice 项 → {{"answer": 选项, "p": 该选项的概率}}；
标"必须带来源"的项，答是/有效选项时加 "source"（必须是 state 里出现过的来源）
与 "captured_at"（state 里的时间，没有就用 state 的 captured_at）。
规则：①只根据 state 判断，不用你自己的记忆补事实；②state 里没写到的事实一律弃权
（p=null 或 answer=unknown），弃权永远正确，猜测永远错误；③不要把"可能""预计"当成已确认；
④belief 是你对 3/1/0 的整体概率，三个数之和为 1。
问题表：
{question_table()}
""".strip()

FREE_PROMPT = """你是一个只做判断的读者。读下面的 state，只输出一个 JSON 对象：
{"belief": {"3": p, "1": p, "0": p}}——你对主胜/平/客胜的整体概率，三数之和为 1。不要解释。"""


def state_text(research: dict) -> str:
    """分析员写下的证据层（去掉 stance/rubric/结论）→ 给读者 B 的 state。"""
    parts: list[str] = [f"captured_at: {research.get('captured_at')}"]
    for key in STATE_FIELDS:
        if key in research and research[key] not in (None, "", [], {}):
            parts.append(f"{key}: {json.dumps(research[key], ensure_ascii=False)}")
    sb = research.get("strength_balance") or {}
    for key in STRENGTH_FIELDS:
        if key in sb and sb[key] not in (None, "", [], {}):
            parts.append(f"strength_balance.{key}: {json.dumps(sb[key], ensure_ascii=False)}")
    text = "\n".join(parts)
    for key in EXCLUDED:
        assert f"\n{key}:" not in text
    return text


def _claude_cli(prompt: str, stdin: str) -> tuple[int, str]:
    argv = ["claude", "-p", *model_argv(reader_model()), "--system-prompt", prompt,
            "--allowedTools", "", "--max-turns", "1", "--output-format", "text"]
    with tempfile.TemporaryDirectory() as neutral:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=300,
                               cwd=neutral, check=False)
    return proc.returncode, proc.stdout


def _first_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ValueError("读者没有输出 JSON")
    doc, _ = json.JSONDecoder().raw_decode(text, start)
    if not isinstance(doc, dict):
        raise ValueError("读者输出不是 JSON 对象")
    return doc


def read_rubric(research: dict, *, kickoff: str | None, claude: Claude = _claude_cli,
                free: bool = False) -> dict:
    """→ 校验后的 rubric norm（free=True 只有 belief）；ERROR 抛 ValueError。"""
    code, out = claude(FREE_PROMPT if free else READER_PROMPT, state_text(research))
    if code != 0:
        raise ValueError(f"读者退出码 {code}")
    doc = _first_json(out)
    if free:
        doc = {"version": RUBRIC_VERSION, "items": {}, "belief": doc.get("belief")}
    doc.setdefault("version", RUBRIC_VERSION)
    doc["items"] = tolerate(doc.get("items"))
    doc["belief"] = tolerate_belief(doc.get("belief"))
    norm, issues = validate_rubric(doc, kickoff=kickoff)
    errors = [i.message for i in issues if i.level == "ERROR"]
    if errors:
        raise ValueError("rubric: " + "; ".join(errors))
    return norm


def tolerate(items) -> dict:
    """读者 B 是便宜的系统一：一个不合法的选项不该废掉整份作答——
    不在表里的项丢弃；choice 答案不在选项里 → unknown（弃权）；noul 的 p 不在 [0,1] → null。
    留痕在 `_tolerated`，报表可数。"""
    out: dict = {}
    if not isinstance(items, dict):
        return out
    for item_id, raw in items.items():
        item = ITEMS.get(str(item_id))
        if item is None:
            continue
        row = dict(raw) if isinstance(raw, dict) else (
            {"p": raw} if item.type == "noul" else {"answer": raw})
        if item.type == "choice":
            if str(row.get("answer")) not in item.options:
                fallback = "unknown" if "unknown" in item.options else item.options[-1]
                row["_tolerated"] = f"answer {row.get('answer')!r} → {fallback}"
                row["answer"] = fallback
        else:
            try:
                p = float(row["p"]) if row.get("p") is not None else None
            except (TypeError, ValueError):
                p = None
            if p is not None and not 0.0 <= p <= 1.0:
                row["_tolerated"] = f"p {row['p']!r} → null"
                p = None
            row["p"] = p
        out[str(item_id)] = row
    return out


def tolerate_belief(belief) -> dict | None:
    """整体概率不是合法的 3/1/0 分布（缺键、负数、和差太远）→ 丢掉，不废整份作答。"""
    if not isinstance(belief, dict):
        return None
    try:
        vals = {k: float(belief[k]) for k in ("3", "1", "0")}
    except (KeyError, TypeError, ValueError):
        return None
    total = sum(vals.values())
    if total <= 0 or any(v < 0 for v in vals.values()) or not 0.9 <= total <= 1.1:
        return None
    return {k: v / total for k, v in vals.items()}


def kappa(a: dict | None, b: dict | None) -> dict:
    """逐项一致性：两读都没弃权的项上 answer 是否相同；合并 Cohen's kappa（按选项边际）。"""
    a_items, b_items = (a or {}).get("items") or {}, (b or {}).get("items") or {}
    per_item: dict[str, bool | None] = {}
    pairs: list[tuple[str, str]] = []
    for item_id in ITEMS:
        ra, rb = a_items.get(item_id) or {}, b_items.get(item_id) or {}
        if ra.get("abstain", True) or rb.get("abstain", True):
            per_item[item_id] = None
            continue
        same = str(ra.get("answer")) == str(rb.get("answer"))
        per_item[item_id] = same
        pairs.append((str(ra.get("answer")), str(rb.get("answer"))))
    if not pairs:
        return {"n": 0, "agree": None, "kappa": None, "items": per_item}
    agree = sum(1 for x, y in pairs if x == y) / len(pairs)
    labels = {x for pair in pairs for x in pair}
    expected = sum((sum(1 for x, _ in pairs if x == lab) / len(pairs))
                   * (sum(1 for _, y in pairs if y == lab) / len(pairs)) for lab in labels)
    k = (agree - expected) / (1 - expected) if expected < 1 else 1.0
    return {"n": len(pairs), "agree": round(agree, 3), "kappa": round(k, 3), "items": per_item}


def sidecar_path(research_path: Path) -> Path:
    name = research_path.name
    if name.startswith("research-"):
        return research_path.with_name("rubric-" + name[len("research-"):])
    return research_path.with_name(name.replace("-research-m", "-rubric-m", 1))


def code_of(research_path: Path, research: dict | None = None) -> str | None:
    """场次标识：研究 JSON 的 code/match_no，否则从文件名推（旧文件没有 code 字段）。"""
    research = research or {}
    if research.get("code"):
        return str(research["code"])
    if research.get("match_no") is not None:
        return str(research["match_no"])
    name = research_path.name
    if name.startswith("research-"):
        return name[len("research-"):].removesuffix(".json")
    if "-research-m" in name:
        return name.split("-research-m", 1)[1].removesuffix(".json")
    return None


def _kickoff_of(research: dict) -> str | None:
    kick = research.get("kickoff_bj")
    return str(kick).replace(" ", "T") if kick else None


def read_file(research_path: Path, *, claude: Claude = _claude_cli, free: bool = False,
              force: bool = False, now: datetime | None = None) -> dict | None:
    """一份研究文件 → 侧车 {a, b, b_free?, kappa, model, at, prospective}；
    已有侧车且非 force → None。"""
    research_path = Path(research_path)
    target = sidecar_path(research_path)
    if target.exists() and not force:
        existing = json.loads(target.read_text(encoding="utf-8"))
        if not free or existing.get("b_free"):
            return None
    research = json.loads(research_path.read_text(encoding="utf-8"))
    if "rejected" in research_path.name:
        return None
    kickoff = _kickoff_of(research)
    at = (now or datetime.now(_BJ)).isoformat(timespec="seconds")
    existing = json.loads(target.read_text(encoding="utf-8")) if target.exists() else {}
    a_norm: dict = {}
    if research.get("rubric"):
        a_norm, _ = validate_rubric(research.get("rubric"), kickoff=kickoff)
    b = existing.get("b") if existing and not force else None
    if b is None:
        b = read_rubric(research, kickoff=kickoff, claude=claude)
    doc = {"code": code_of(research_path, research),
           "match_id": research.get("match_id"), "research": research_path.name,
           "a": a_norm or None, "b": b, "kappa": kappa(a_norm, b) if a_norm else None,
           "model": model_label(reader_model()), "at": at,
           "prospective": bool(kickoff) and at < kickoff}
    if free:
        doc["b_free"] = read_rubric(research, kickoff=kickoff, claude=claude, free=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


def is_research_file(path: Path) -> bool:
    """`research-<code>.json` 才是研究；`research-run-*` 是运行日志，`*.rejected*` 是拒收件。"""
    name = path.name
    return (name.startswith("research-") or "-research-m" in name) and "rejected" not in name \
        and not name.startswith("research-run-")


def research_files(data_dir: Path, *, day: str | None = None,
                   issue: str | None = None) -> list[Path]:
    data_dir = Path(data_dir)
    if day:
        base = data_dir / "jczq" / "daily" / day
        return sorted(p for p in base.glob("research-*.json") if is_research_file(p))
    if issue:
        return sorted(p for p in (data_dir / "zucai").glob(f"{issue}-research-m*.json")
                      if "rejected" not in p.name)
    return []


def read_many(paths: list[Path], *, claude: Claude = _claude_cli, free: bool = False,
              force: bool = False, limit: int | None = None) -> dict:
    done, skipped, failed = [], [], []
    for path in paths[: limit or None]:
        try:
            out = read_file(path, claude=claude, free=free, force=force)
        except (ValueError, OSError) as exc:
            failed.append({"path": path.name, "error": str(exc)[:200]})
            continue
        (done if out else skipped).append(path.name)
    return {"done": done, "skipped": skipped, "failed": failed}


def report(data_dir: Path, *, day: str | None = None, issue: str | None = None) -> dict:
    """侧车汇总 → analytics/rubric/<day|issue>.json|md：逐场 kappa、逐项一致率、
    分歧（free vs 表）。"""
    rows = []
    for path in research_files(data_dir, day=day, issue=issue):
        side = sidecar_path(path)
        if not side.exists():
            continue
        doc = json.loads(side.read_text(encoding="utf-8"))
        doc["code"] = doc.get("code") or code_of(path)
        rows.append(doc)
    per_item: dict[str, list[bool]] = {i: [] for i in ITEMS}
    for doc in rows:
        for item_id, same in ((doc.get("kappa") or {}).get("items") or {}).items():
            if same is not None:
                per_item.setdefault(item_id, []).append(bool(same))
    item_agree = {i: (round(sum(v) / len(v), 2), len(v)) for i, v in per_item.items() if v}
    kappas = [doc["kappa"]["kappa"] for doc in rows
              if doc.get("kappa") and doc["kappa"].get("kappa") is not None]
    out = {"key": day or issue, "n_sidecars": len(rows), "n_with_kappa": len(kappas),
           "kappa_mean": round(sum(kappas) / len(kappas), 3) if kappas else None,
           "item_agreement": item_agree,
           "rows": [{"code": d.get("code"), "kappa": (d.get("kappa") or {}).get("kappa"),
                     "n": (d.get("kappa") or {}).get("n"), "prospective": d.get("prospective"),
                     "b_belief": (d.get("b") or {}).get("belief"),
                     "b_free_belief": (d.get("b_free") or {}).get("belief")} for d in rows]}
    target = Path(data_dir) / "analytics" / "rubric" / f"{out['key']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    target.with_suffix(".md").write_text(render_report(out), encoding="utf-8")
    out["path"] = str(target)
    return out


def render_report(out: dict) -> str:
    lines = [f"# 判断 rubric 两读 · {out['key']}",
             f"侧车 {out['n_sidecars']} 份｜有 kappa {out['n_with_kappa']}｜平均 κ "
             f"{out['kappa_mean'] if out['kappa_mean'] is not None else '—'}", "",
             "| 项 | 一致率 | n |", "|---|---|---|"]
    for item_id, (rate, n) in sorted(out["item_agreement"].items()):
        lines.append(f"| {item_id} | {rate:.2f} | {n} |")
    lines += ["", "| 场 | κ | n | 前瞻 | B belief | B free |", "|---|---|---|---|---|---|"]
    for r in out["rows"]:
        k = r["kappa"] if r["kappa"] is not None else "—"
        lines.append(f"| {r['code']} | {k} | {r['n']} | {'是' if r['prospective'] else '否'} "
                     f"| {r['b_belief'] or '—'} | {r['b_free_belief'] or '—'} |")
    lines += ["", "> 读法：κ<0.4 的项要重写或删（行业阈值）；B free 与 B 表的分歧率上升＝"
                  "分析员在写给表看。读者 B 只读分析员写下的证据，它答对不等于判断对。"]
    return "\n".join(lines) + "\n"
