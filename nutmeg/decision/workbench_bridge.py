"""把已落库的当日判读投影成 Workshop 协议事件(workbench_bridge)。

背景:decision-read CLI 落的 Read 直接进 store,不写 workbench.jsonl,故 Workshop
工作台的注意力流看不到它们(CLI↔Workshop 断链)。本桥接读当日 Match+非 shadow had
Read,投影成 attention(左栏可点)+ judgment(只读判读,点议程→舞台显偏移读数器)事件。

**只投影、不改判断**:已裁决的判读投成只读展示,不产 read_draft/legs_proposal(那会误显
"批准/出票"按钮)。幂等:同一 obj 已投影则跳过。
"""
from __future__ import annotations


def bridge_day(store, output_dir, date: str) -> int:
    """当日 Match+非 shadow had Read → attention+judgment 事件。返回新写事件数。"""
    from nutmeg.decision.ontology import Match, Read
    from nutmeg.decision.workbench import append_event, read_events

    prefix = f"M-{date}-"
    matches = {m.match_id: m for m in store.load(Match)
               if m.match_id.startswith(prefix)}
    reads = [r for r in store.load(Read)
             if r.match_id.startswith(prefix) and not r.shadow and r.market == "had"]
    already = {e.get("obj_id") for e in read_events(output_dir, date)
               if e.get("kind") == "judgment"}
    n = 0
    for r in sorted(reads, key=lambda x: x.match_id):
        m = matches.get(r.match_id)
        if m is None or r.match_id in already:
            continue
        offset = bool(r.factors)
        label = f"{m.home} vs {m.away}"
        note = f"{r.market} · conf{r.confidence}"
        if offset:
            f0 = r.factors[0]
            note += f" · {f0.get('direction')} +{f0.get('weight_pp')}pp"
        append_event(output_dir, date, {
            "kind": "attention", "id": r.match_id,
            "group": "偏移读数" if offset else "跟市场",
            "match": label, "note": note,
        })
        append_event(output_dir, date, {
            "kind": "judgment", "id": f"J-{r.match_id}", "obj_id": r.match_id,
            "payload": {
                "match": label, "competition": m.competition,
                "market": r.market, "prior": r.prior, "belief": r.belief,
                "factors": r.factors, "note": r.note,
                "confidence": r.confidence, "committed": True,
            },
        })
        n += 2
    return n
