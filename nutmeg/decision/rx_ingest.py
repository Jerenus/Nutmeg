"""rx JSON → workflow 请求的确定性映射。判断不入脚本:只做字段搬运与已决/未决分拣。"""
from __future__ import annotations

_RESOLVED_MARKS = ("已裁", "行权", "已复核", "终版", "已定")


def map_rx_predictions(rx: dict, issue: str) -> list[dict]:
    out_by_claim: dict[str, dict] = {}
    for p in rx.get("predictions") or []:
        claim = p["claim"]
        if claim in out_by_claim:
            out_by_claim[claim]["alias_ids"].append(p["id"])
            continue
        out_by_claim[claim] = {
            "match_id": None,
            "subject_type": "issue",
            "subject_id": issue,
            "claim": claim,
            "falsifier": p["falsifier"],
            "idempotency_key": f"rx:{issue}:{p['id']}",
            "alias_ids": [p["id"]],
        }
    return list(out_by_claim.values())


def map_rx_adjudications(rx: dict, issue: str) -> tuple[list[dict], list[str]]:
    out, skipped = [], []
    for a in rx.get("pending_adjudications") or []:
        status = a.get("status", "")
        if not any(m in status for m in _RESOLVED_MARKS):
            skipped.append(f"{a['id']}: 未决({status})")
            continue
        reason = "｜".join(x for x in (a.get("q"), a.get("reason")) if x)
        rejected = a.get("evidence_rejected")
        out.append({
            "subject_type": "issue",
            "subject_id": issue,
            "decision": "override" if "行权" in status else "approve",
            "reason": reason,
            "evidence_rejected": [{"type": "note", "id": rejected}] if rejected else [],
            "alternative": {"options": a["options"]} if a.get("options") else {},
            "idempotency_key": f"rx:{issue}:{a['id']}",
        })
    return out, skipped


def map_rx_gradings(rx: dict, issue: str) -> tuple[list[dict], list[str]]:
    """rx 里已判 outcome 的预测 → 批量判定请求；未判的跳过。

    **Why.** rx 用人读的 `P1..Pn`，本体存的是 `prediction-<hex>`；判定前要先去 sqlite 里
    按 claim 文本对号（26121 就是这么做的，13 条对了两轮）。两套 ID 之间唯一稳定的桥是
    注册时用的幂等键 `rx:<issue>:<P-id>`——本函数把桥显式化，判断仍留在主循环。
    """
    out, skipped = [], []
    for p in rx.get("predictions") or []:
        outcome = (p.get("outcome") or "").strip().lower()
        if outcome not in ("hit", "miss", "na"):
            skipped.append(f"{p['id']}: 未判定({p.get('outcome')!r})")
            continue
        out.append({
            "rx_id": p["id"],
            "idempotency_key": f"rx:{issue}:{p['id']}",
            "outcome": outcome,
            "reason": p.get("outcome_reason") or p.get("claim", ""),
        })
    return out, skipped
