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
OVERRIDE_REASONS = ("new_official_info", "evidence_tier_too_low", "priced_in",
                    "research_contradiction", "market_only", "legacy_tilt")
"""改判理由（2026-10-02 判断 rubric r1）：封闭枚举，改判账按理由分层结账——
新官宣信息 / 证据层级不够 / 已被价格吸收 / 研究自相矛盾 / 只回市场 /
旧式直接改 tilt（无 rubric 的研究）。"""


def _raw_items(norm_items: dict) -> dict:
    """norm 形态的项 → 可重新校验的原始答案形态。"""
    from nutmeg.decision.rubric_items import ITEMS

    raw = {}
    for item_id, row in (norm_items or {}).items():
        item = ITEMS.get(item_id)
        if item is None or not isinstance(row, dict):
            continue
        if row.get("abstain"):
            continue
        base = {"source": row.get("source") or "", "captured_at": row.get("captured_at"),
                "note": row.get("note") or ""}
        if item.type == "noul":
            raw[item_id] = {"p": row.get("p"), **base}
        else:
            raw[item_id] = {"answer": row.get("answer"), "p": row.get("p"), **base}
    return raw


def merged_rubric(rubric: dict, items: dict) -> dict:
    """研究的 rubric（norm）+ 改判的项（原始答案形态）→ 待校验的 rubric。"""
    raw = _raw_items((rubric or {}).get("items") or {})
    for item_id, answer in (items or {}).items():
        raw[item_id] = answer if isinstance(answer, dict) else {"p": answer}
    return {"version": (rubric or {}).get("version"), "items": raw,
            "belief": (rubric or {}).get("belief")}


def derive_override_tilt(rubric: dict, items: dict, *, prior: dict, kickoff: str | None,
                         at: str) -> tuple[dict | None, dict]:
    """→ (派生 tilt, 合并后的 rubric norm)。非法项抛 ValueError。"""
    from nutmeg.decision.rubric import rubric_to_tilt, validate_rubric

    norm, issues = validate_rubric(merged_rubric(rubric, items), kickoff=kickoff)
    errors = [i.message for i in issues if i.level == "ERROR"]
    if errors:
        raise ValueError("改判项: " + "; ".join(errors))
    tilt = rubric_to_tilt(norm, prior, captured_at=at)
    if tilt:
        tilt["derived_from"] = f"rubric:{norm['version']}+override"
    return tilt, norm


def _belief(prior: dict, tilt: dict | None) -> dict:
    if not tilt:
        return dict(prior)
    result = apply_tilt(prior, tilt)
    return dict(prior) if result.zeroed else dict(result.belief)


def record_override(research_path: Path, *, tilt: dict | None = None, note: str, at: str,
                    judge: str, prior: dict, source: str = "main_loop",
                    items: dict | None = None, reason: str | None = None,
                    to_market: bool = False, kickoff: str | None = None) -> dict:
    """追加一行改判。有 rubric 的研究：改判必须落到项（`items`）或回市场（`to_market`），
    tilt 由合并后的 rubric 派生；没有 rubric 的旧研究才允许直接给 `tilt`（reason=legacy_tilt）。"""
    research_path = Path(research_path)
    raw = research_path.read_bytes()
    doc = json.loads(raw)
    original = (doc.get("stance") or {}).get("tilt")
    rubric = doc.get("rubric") if isinstance(doc.get("rubric"), dict) else None
    if reason is not None and reason not in OVERRIDE_REASONS:
        raise ValueError(f"reason `{reason}` 不在 {OVERRIDE_REASONS}")
    if rubric:
        if to_market or (tilt is None and items is None):
            # 旧 API 的 `tilt=None` 就是「回市场」；rubric 研究上同义
            to_market, tilt, reason = True, None, reason or "market_only"
        elif items is not None:
            if not reason:
                raise ValueError("落到 rubric 项的改判必须给 reason")
            tilt, _norm = derive_override_tilt(rubric, items, prior=prior, kickoff=kickoff, at=at)
        else:
            raise ValueError("该研究有 rubric：改判须落到项（items）或回市场，不能直接写 tilt")
    else:
        reason = reason or ("market_only" if tilt is None else "legacy_tilt")
    row = {
        "research": research_path.name,
        "research_sha256": hashlib.sha256(raw).hexdigest()[:16],
        "match": doc.get("name"),
        "at": at,
        "judge": judge,
        "source": source,
        "reason": reason,
        "items": items,
        "to_market": bool(to_market),
        "rubric_version": rubric.get("version") if rubric else None,
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
    rubric = doc.get("rubric") if isinstance(doc.get("rubric"), dict) else None
    if rubric and latest.get("items") is not None and not latest.get("to_market"):
        # 判断 rubric r1：改判＝项的修订，tilt 从合并后的 rubric 重新派生（判断唯一事实）
        from nutmeg.decision.rubric import derive_stance, validate_rubric

        norm, _issues = validate_rubric(merged_rubric(rubric, latest["items"]))
        doc["research_original_rubric"] = rubric
        doc["rubric"] = norm
        stance = derive_stance(stance, norm, latest.get("prior"), captured_at=latest.get("at"))
        if stance.get("tilt"):
            stance["tilt"]["derived_from"] = f"rubric:{norm['version']}+override"
    else:
        stance["tilt"] = latest["tilt"]
        stance["why_not_market"] = "tilt_evidence" if latest["tilt"] else "none"
    doc["stance"] = stance
    doc["main_loop_rulings"] = {"judge": latest["judge"], "at": latest["at"],
                                "note": latest["note"], "reason": latest.get("reason")}
    doc["override_reason"] = latest.get("reason")
    if rubric:
        doc["rubric_overridden"] = True
    return doc
