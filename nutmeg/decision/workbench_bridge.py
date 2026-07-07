"""把已落库的当日判读投影成 Workshop 协议事件(workbench_bridge)。

背景:decision-read CLI 落的 Read 直接进 store,不写 workbench.jsonl,故 Workshop
工作台的注意力流看不到它们(CLI↔Workshop 断链)。本桥接读当日 Match+非 shadow Read,
投影成 attention(左栏可点)+ judgment(只读判读,点议程→舞台显偏移读数器)事件;had 判读
挂上同场 ttg 进球轴读数器;并把 day-regime.json 投成 day_regime 事件(舞台默认态"今日盘面")。

**只投影、不改判断**:已裁决的判读投成只读展示,不产 read_draft/legs_proposal(那会误显
"批准/出票"按钮)。幂等:同一 obj 已投影则跳过,day_regime 已投则不重复。
"""
from __future__ import annotations

import json
from pathlib import Path


def bridge_day(store, output_dir, date: str) -> int:
    """当日 Match+非 shadow Read → attention+judgment(含 ttg)+day_regime。返回新写事件数。"""
    from nutmeg.decision.ontology import Match, Read
    from nutmeg.decision.workbench import append_event, read_events

    prefix = f"M-{date}-"
    matches = {m.match_id: m for m in store.load(Match)
               if m.match_id.startswith(prefix)}
    reads = [r for r in store.load(Read)
             if r.match_id.startswith(prefix) and not r.shadow]
    had = {r.match_id: r for r in reads if r.market == "had"}
    ttg = {r.match_id: r for r in reads if r.market == "ttg"}

    existing = read_events(output_dir, date)
    already = {e.get("obj_id") for e in existing if e.get("kind") == "judgment"}
    have_regime = any(e.get("kind") == "day_regime" for e in existing)

    n = 0
    for mid, r in sorted(had.items()):
        m = matches.get(mid)
        if m is None or mid in already:
            continue
        offset = bool(r.factors)
        label = f"{m.home} vs {m.away}"
        note = f"{r.market} · conf{r.confidence}"
        if offset:
            f0 = r.factors[0]
            note += f" · {f0.get('direction')} +{f0.get('weight_pp')}pp"
        append_event(output_dir, date, {
            "kind": "attention", "id": mid,
            "group": "偏移读数" if offset else "跟市场",
            "match": label, "note": note,
        })
        payload = {
            "match": label, "competition": m.competition,
            "market": r.market, "prior": r.prior, "belief": r.belief,
            "factors": r.factors, "note": r.note,
            "confidence": r.confidence, "committed": True,
        }
        tr = ttg.get(mid)
        if tr is not None:  # 同场进球轴读数器挂上(约束 h 判读)
            payload["ttg"] = {"belief": tr.belief, "note": tr.note,
                              "confidence": tr.confidence}
        append_event(output_dir, date, {
            "kind": "judgment", "id": f"J-{mid}", "obj_id": mid, "payload": payload,
        })
        n += 2

    if not have_regime:  # 日级盘面诊断(只攒样本,不进决策)→ 舞台默认态
        rp = Path(output_dir) / "daily" / date / "day-regime.json"
        if rp.exists():
            try:
                data = json.loads(rp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
            if data:
                append_event(output_dir, date,
                             {"kind": "day_regime", "id": "REGIME", "payload": data})
                n += 1
    return n
