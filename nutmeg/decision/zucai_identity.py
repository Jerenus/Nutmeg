"""足彩期次的身份映射 —— store-ids 不再手工重建。

**Why.** 26122 当天 store-ids 是手搓的：靠**把 fair 值挨个比对**反查 match_id/snapshot_id
（浮点相等匹配，换一次去水口径就会全错）。本体里其实有确定性的钥匙：`external_identifiers`
里 `provider='zucai-canonical'` 的 `M-<赛期日>-<主>-<客>` 就是 canonical 键，
`canonical_match_id()` 能确定性地算出来。

af-map（API-Football fixture id）2026-10-01 随夜账路径一起退役：跨渠道身份只走
`<issue>-channel-map(.auto).json` ↔ 内核 match_id ↔ `jczq-legs-base` 竞彩编号（RULEBOOK g-scope）。

本模块只做查表与落盘，不含判断。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.identity import canonical_match_id

CHANNEL_MAP_NAMES = ("{issue}-channel-map.json", "{issue}-channel-map.auto.json")
"""人工对号表优先，`.auto` 是备料按体彩板面自动对齐落的同一张表（`zucai_prep`）。"""


def load_channel_map(zucai_dir, issue: str) -> dict[str, int]:
    """跨渠道对号表 → {竞彩侧内核 match_id: 足彩场号}。

    人工表优先；某份缺失 / 损坏 / 为空就看下一份；都没有 → {}（下游逐场显式跳过）。
    唯一读取处（2026-10-08 B3）：此前约 10 处各读一遍，对「空 / 坏的人工表」各有各的处理，
    场号类型（26134 人工表写 "3"、`.auto` 写 3）也各自转换——10-05 修的两个缺口都出在这些副本里。
    """
    base = Path(zucai_dir)
    for pattern in CHANNEL_MAP_NAMES:
        try:
            data = json.loads((base / pattern.format(issue=issue)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data:
            return {str(mid): int(no) for mid, no in data.items()}
    return {}


def closing_issues(zucai_dir, day: str) -> list[tuple[str, dict]]:
    """当天截止（`sale_deadline` 的日期 = day）且已有 store-ids 的期次 → [(期号, 期次文档)]。

    并集池（足彩样本、刷新）与信号面板共用（2026-10-08 B3，此前三份副本）。"""
    base = Path(zucai_dir)
    out: list[tuple[str, dict]] = []
    for issue_path in sorted(base.glob("*-issue.json")):
        doc = json.loads(issue_path.read_text(encoding="utf-8"))
        issue = str(doc.get("issue_id") or issue_path.name.split("-")[0])
        if (str(doc.get("sale_deadline") or "")[:10] == day
                and (base / f"{issue}-store-ids.json").exists()):
            out.append((issue, doc))
    return out


def _prep_records(issue: str, zucai_dir) -> dict:
    """优先读 revision（18:30 位移复核后的盘），其次 afternoon，最后 morning（11:00 早刷新）。"""
    zdir = Path(zucai_dir)
    for slot in ("revision", "afternoon", "morning"):
        path = zdir / f"{issue}-prep-{slot}.json"
        if path.exists():
            return json.loads(path.read_text("utf-8")).get("records") or {}
    return {}


def build_store_ids(issue: str, zucai_dir, kernel) -> dict:
    """{场次: {match_no,name,match_id,snapshot_id,fair,canonical_id}}。

    按 canonical 键查 store；查不到的场次**显式留 `match_id=None`** 而不是跳过——
    静默跳过会让下游以为该场没判读，而真相是身份没对上。
    """
    from nutmeg.ontology.identity.models import EntityType
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork

    records = _prep_records(issue, zucai_dir)
    out: dict[str, dict] = {}
    with OntologyUnitOfWork(kernel.engine) as uow:
        for no, rec in records.items():
            name = rec.get("name", "")
            home, _, away = name.partition("-")
            canonical = canonical_match_id(home, away, rec.get("match_date", ""))
            match_id = uow.identity.entity_by_external_id(
                EntityType.MATCH, provider="zucai-canonical", external_id=canonical)
            snapshot_id = None
            if match_id:
                row = uow.connection.exec_driver_sql(
                    "SELECT market_snapshot_id FROM market_snapshots "
                    "WHERE match_id = ? ORDER BY as_of DESC LIMIT 1", (match_id,)
                ).fetchone()
                snapshot_id = row[0] if row else None
            out[str(no)] = {
                "match_no": int(no), "name": name, "canonical_id": canonical,
                "match_id": match_id, "snapshot_id": snapshot_id,
                "kind": "read_time", "fair": rec.get("fair_had"),
            }
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def write_store_ids(issue: str, zucai_dir, kernel) -> str:
    ids = build_store_ids(issue, zucai_dir, kernel)
    if not ids:
        # 无备料快照 = 该期还没备料，不是身份出错。编排步骤必须说话但不得中断 am。
        return f"store-ids {issue}: 无备料记录（先跑 zucai-prep）"
    path = Path(zucai_dir) / f"{issue}-store-ids.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids, ensure_ascii=False, indent=1), encoding="utf-8")
    missing = [no for no, v in ids.items() if not v["match_id"]]
    note = f"；⚠️{len(missing)} 场身份未对上: {','.join(missing)}" if missing else ""
    return f"store-ids {issue}: {len(ids)} 场 → {path.name}{note}"
