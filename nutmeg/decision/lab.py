"""实验室（2026-10-28 产品形态第 8 阶段 Task 8.1）：每个登记实验走到哪一步了。只读内核与登记原件。

实证标签（实证 / 已证伪 / 测不出 / 未证 n/n_min / 退役）原本只写在 CLI `rsi columns` 里；搬到这里
成为唯一实现，`rsi columns` 与实验室页都调它，不再各写一份。

数字（n / n_min / metric / CI / verdict）照抄 `account.experiment_board`（已结账的显示判决所依的
结算 grade）；判决与退役按 `rsi columns` 的读法从内核读。分析包对应哪一列来自登记原件的
`exits` 里的 `packet_column:<列>`（内核不存出口）。
"""
from __future__ import annotations

from pathlib import Path

from nutmeg.decision.rsi_prereg import load_registry_doc

_PACKET_COLUMN = "packet_column:"


def evidence_label(e, v, d, g, f) -> str:
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

    if d is not None and d.decision == "retire":
        return "退役"
    if v is not None and v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL:
        if v.criterion_snapshot.get("expired"):
            return "测不出（到期）"
        return {"survived": "实证", "falsified": "已证伪",
                "inconclusive": "测不出"}.get(v.verdict, v.verdict)
    return f"未证 {g.n_cum if g else 0}/{f.n_min}"


def registry_docs(registry_dir: Path | str, errors: list[str] | None = None) -> dict[str, dict]:
    """{exp_id: 登记原件}，按文件名升序。`_` 开头的（`_draft_*` 草稿）不是登记原件，跳过。
    给了 `errors` 时坏原件只记一行、跳过；没给就照旧抛（CLI 遇坏原件直接报错）。"""
    out: dict[str, dict] = {}
    for path in sorted(Path(registry_dir).glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            doc = load_registry_doc(path)
        except (OSError, ValueError) as exc:
            if errors is None:
                raise
            errors.append(f"登记原件 {path.name} 读不出：{exc}"[:200])
            continue
        out[doc["exp_id"]] = doc
    return out


def _columns(doc: dict | None) -> list[str]:
    exits = (doc or {}).get("exits") or {}
    return sorted({a.split(":", 1)[1] for a in exits.values() if a.startswith(_PACKET_COLUMN)})


def lab_board(data_dir: Path | str, registry_dir: Path | str) -> dict:
    """{"live": [行], "settled": [行], "errors": [..]}，行＝{exp_id, claim, layer, tier, n, n_min,
    metric_pp, ci, label, verdict, columns, window, source_doc}，按内核登记顺序（同 `rsi status`）。

    settled＝已结账（协议 v2，含到期）或退役；其余 live。内核读不出 → 两表皆空，只进 errors。
    claim / window / source_doc 取内核冻结的登记文本（内核是唯一权威，原件只是登记时的文本）。"""
    from nutmeg.config.settings import AppSettings
    from nutmeg.decision.account import experiment_board
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL, Falsifier

    data_dir = Path(data_dir).expanduser().resolve()
    errors: list[str] = []
    docs = registry_docs(registry_dir, errors)
    nums = experiment_board(data_dir)
    if "_error" in nums:
        return {"live": [], "settled": [], "errors": [*errors, f"内核读不出：{nums['_error']}"]}
    live: list[dict] = []
    settled: list[dict] = []
    try:
        kernel = build_ontology_kernel(AppSettings(data_dir=data_dir))
        kernel.initialize()
        with OntologyUnitOfWork(kernel.engine) as uow:
            for e in uow.rsi.experiments():
                f = Falsifier.from_dict(e.falsifier)
                v = uow.rsi.latest_verdict(e.exp_id)
                d = uow.rsi.latest_deployment(e.exp_id)
                g = uow.rsi.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum)
                num = nums.get(e.exp_id) or {}
                row = {
                    "exp_id": e.exp_id, "claim": e.claim,
                    "layer": num.get("layer", e.layer), "tier": num.get("tier", e.tier),
                    "n": num.get("n", 0), "n_min": num.get("n_min", f.n_min),
                    "metric_pp": num.get("metric_pp"), "ci": num.get("ci"),
                    "label": evidence_label(e, v, d, g, f),
                    "verdict": v.verdict if v else None,
                    "columns": _columns(docs.get(e.exp_id)),
                    "window": e.window, "source_doc": e.source_doc,
                }
                done = ((v is not None and v.criterion_snapshot.get("protocol") == VERDICT_PROTOCOL)
                        or (d is not None and d.decision == "retire"))
                (settled if done else live).append(row)
    except Exception as exc:  # noqa: BLE001 —— 实验室页不能因内核故障整页空白
        return {"live": [], "settled": [], "errors": [*errors, f"内核读不出：{exc!r}"[:200]]}
    return {"live": live, "settled": settled, "errors": errors}


def columns_line(board: dict) -> str:
    """`rsi columns` 的那一行（分析包 §0 原样抄）：列 → 指向它的实验与实证标签。
    列内按登记原件文件名排（`<exp_id>.json`，与旧 CLI 逐个 glob 原件的顺序一致）。"""
    by_column: dict[str, list[str]] = {}
    rows = sorted([*board["live"], *board["settled"]], key=lambda r: f"{r['exp_id']}.json")
    for row in rows:
        for col in row["columns"]:
            by_column.setdefault(col, []).append(f"{row['exp_id']} {row['label']}")
    if not by_column:
        return "列实证：（没有登记出口指向分析包的实验）"
    return ("列实证：" + " ｜ ".join(f"{col} {'·'.join(v)}" for col, v in sorted(by_column.items()))
            + "（未证的列只是展示或纪律，不是有实证的判据）")
