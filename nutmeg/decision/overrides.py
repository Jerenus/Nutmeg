"""主循环改判账（Jun 2026-09-27）：研究原判只读，改判另记，赛后两者分别计分。

出生事故：26133 场4 冰岛。竞彩深研 08:19 给出平局 +7pp（官宣门将 4 + 结构 3），
主循环 14:15 以「已定价」砍到 +2，并**覆盖了研究文件里的拨动**；10:00 的 Read 没进本体、
reads.json 被重建覆盖——原判只剩一份手工备份。Jun：「方向上的改动只能通过捕捉到的
信号来帮助我做决策」，所以信号必须原样留存、可以被人看见、可以被计分。

- `record_override`：往研究文件同目录的 `overrides.jsonl` 追加一行（原拨动、新拨动、
  两个判断分布、理由、时间），**不改研究文件**；
- `effective_research`：入库时读「研究原件 + 最新改判」，原表态留在 `research_original_stance`。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nutmeg.decision.stance import apply_tilt

LEDGER = "overrides.jsonl"


def _belief(prior: dict, tilt: dict | None) -> dict:
    if not tilt:
        return dict(prior)
    result = apply_tilt(prior, tilt)
    return dict(prior) if result.zeroed else dict(result.belief)


def record_override(research_path: Path, *, tilt: dict | None, note: str, at: str,
                    judge: str, prior: dict, source: str = "main_loop") -> dict:
    research_path = Path(research_path)
    raw = research_path.read_bytes()
    doc = json.loads(raw)
    original = (doc.get("stance") or {}).get("tilt")
    row = {
        "research": research_path.name,
        "research_sha256": hashlib.sha256(raw).hexdigest()[:16],
        "match": doc.get("name"),
        "at": at,
        "judge": judge,
        "source": source,
        "original_tilt": original,
        "tilt": tilt,
        "prior": prior,
        "research_belief": _belief(prior, original),
        "final_belief": _belief(prior, tilt),
        "note": note,
    }
    with (research_path.parent / LEDGER).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def load_overrides(directory: Path) -> list[dict]:
    path = Path(directory) / LEDGER
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def effective_research(research_path: Path) -> dict:
    research_path = Path(research_path)
    doc = json.loads(research_path.read_text(encoding="utf-8"))
    rows = [r for r in load_overrides(research_path.parent) if r["research"] == research_path.name]
    if not rows:
        return doc
    latest = rows[-1]
    stance = dict(doc.get("stance") or {})
    doc["research_original_stance"] = dict(stance)
    stance["tilt"] = latest["tilt"]
    stance["why_not_market"] = "tilt_evidence" if latest["tilt"] else "none"
    doc["stance"] = stance
    doc["main_loop_rulings"] = {"judge": latest["judge"], "at": latest["at"],
                                "note": latest["note"]}
    if doc.get("rubric"):
        # 判断 rubric r1：改判直接替换派生 tilt；留痕以便逐项结账知道这场 belief 不是 rubric 算的
        doc["rubric_overridden"] = True
    return doc
