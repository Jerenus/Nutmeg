"""足彩期次的身份映射 —— store-ids 与 af-map 不再手工重建。

**Why.** 26122 当天这两份映射都是手搓的：store-ids 靠**把 fair 值挨个比对**反查
match_id/snapshot_id（浮点相等匹配，换一次去水口径就会全错），af-map 靠 curl
API-Football 再按队名模糊匹配。两者本体里其实都有确定性的钥匙：

- store-ids：`external_identifiers` 里 `provider='zucai-canonical'` 的
  `M-<赛期日>-<主>-<客>` 就是 canonical 键，`canonical_match_id()` 能确定性地算出来；
- af-map：fixture id 属于外部 provider，仍需采集，但**映射关系**应该按 canonical 键存，
  而不是每次重新猜队名。

本模块只做查表与落盘，不含判断。
"""
from __future__ import annotations

import json
from pathlib import Path

from nutmeg.decision.identity import canonical_match_id


def _prep_records(issue: str, zucai_dir) -> dict:
    """优先读 revision（18:30 位移复核后的盘），否则读 afternoon。"""
    zdir = Path(zucai_dir)
    for slot in ("revision", "afternoon"):
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


def build_af_map(issue: str, zucai_dir, fixtures: dict[str, int],
                 tickets: dict[str, dict] | None = None) -> dict:
    """af-map：{场次: fixture_id}。fixtures 由外部采集给定（provider 归属外部）。

    缺映射的场次**必须缺着**——`zucai-night-calibrate` 的既有纪律是"af-map 缺映射=显式
    跳过，禁按队名猜测补"，这里保持同一纪律。
    """
    records = _prep_records(issue, zucai_dir)
    return {
        "issue": issue,
        "fixtures": {str(no): int(fid) for no, fid in sorted(
            fixtures.items(), key=lambda kv: int(kv[0]))},
        "tickets": tickets or {},
        "unmapped": sorted((no for no in records if str(no) not in fixtures), key=int),
        "faces_semantics": "3=主胜 1=平 0=客胜",
    }
