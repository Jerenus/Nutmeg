"""实验室（2026-10-28 产品形态第 8 阶段 Task 8.1）：实证标签搬出 CLI 后五种结果不变、
`rsi columns` 与搬家前逐字一致、研究层消费量跨期相加。"""
import json
from pathlib import Path
from types import SimpleNamespace as NS

from typer.testing import CliRunner

from nutmeg.decision.bridge import BRIDGE_SUFFIX, cite_totals
from nutmeg.decision.lab import columns_line, evidence_label, lab_board
from nutmeg.interfaces.cli import app
from nutmeg.ontology.rsi.models import VERDICT_PROTOCOL

F = NS(n_min=60)
G = NS(n_cum=24)


def _v(verdict: str, **snap) -> NS:
    return NS(verdict=verdict, criterion_snapshot={"protocol": VERDICT_PROTOCOL, **snap})


def test_evidence_label_five_outcomes():
    assert evidence_label(None, _v("survived"), NS(decision="retire"), G, F) == "退役"
    assert evidence_label(None, _v("survived"), None, G, F) == "实证"
    assert evidence_label(None, _v("falsified"), NS(decision="deploy"), G, F) == "已证伪"
    assert evidence_label(None, _v("inconclusive"), None, G, F) == "测不出"
    assert evidence_label(None, _v("inconclusive", expired=True), None, G, F) == "测不出（到期）"
    # 旧协议的判决不算结账：照旧是「未证 n/n_min」
    old = NS(verdict="survived", criterion_snapshot={"protocol": "v1"})
    assert evidence_label(None, old, None, G, F) == "未证 24/60"
    assert evidence_label(None, None, None, None, F) == "未证 0/60"


DOC = {
    "claim": "c", "mechanism": "m", "tier": "observation", "layer": "judgment",
    "population": "zucai", "min_tier": "price_only",
    "window": {"issue_from": "26126", "issue_to": "26137"},
    "falsifier": {"metric": "home_resid_pp", "stratum": "zucai", "n_min": 140,
                  "bound": "ci_upper", "threshold_pp": 2.0, "direction": "lt_means_falsified"},
    "stop_rule": "n≥140", "quota_slot": False, "buckets": ["向主 ≥+0.5"], "rule_ids": [],
    "source_doc": "experiments/prereg-x.json", "registered_at": "2026-09-14", "duties": [],
}


def _exits(*cols: str) -> dict:
    keys = ("on_survived", "on_falsified", "on_expired")
    acts = [f"packet_column:{c}" for c in cols] + ["none"] * (3 - len(cols))
    return {"exits": dict(zip(keys, acts, strict=True))}


def _sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """沙盒库：四个登记实验（两个指向同一列、一个退役、一个无出口）+ 一份未登记的草稿。"""
    data, reg = tmp_path / "data", tmp_path / "registry"
    data.mkdir()
    reg.mkdir()
    docs = {"F18": _exits("许可证"), "F10": _exits("热门带", "许可证"),
            "F14b": _exits("表态面"), "F99": {}}
    for exp_id, extra in docs.items():
        path = reg / f"{exp_id}.json"
        path.write_text(json.dumps({**DOC, "exp_id": exp_id, **extra}), encoding="utf-8")
        r = CliRunner().invoke(app, ["rsi", "register", "--by", "Jun", str(path),
                                     "--data-dir", str(data)])
        assert r.exit_code == 0, r.output
    (reg / "_draft_F12.json").write_text(
        json.dumps({**DOC, "exp_id": "F12", **_exits("草稿列")}), encoding="utf-8")
    r = CliRunner().invoke(app, ["rsi", "deploy", "--exp", "F14b", "--retire", "--reason", "x",
                                 "--by", "Jun", "--data-dir", str(data)])
    assert r.exit_code == 0, r.output
    return data, reg


def _columns_before_move(data: Path, reg: Path) -> str:
    """搬家前 `rsi columns` 的命令体（2026-10-19 版）冻结在这里当参照：逐个 glob 原件 → 内核。"""
    from nutmeg.config.settings import AppSettings
    from nutmeg.decision.rsi_prereg import load_registry_doc
    from nutmeg.ontology import build_ontology_kernel
    from nutmeg.ontology.repository.unit_of_work import OntologyUnitOfWork
    from nutmeg.ontology.rsi.models import Falsifier

    by_column: dict[str, list[str]] = {}
    k = build_ontology_kernel(AppSettings(data_dir=data.resolve()))
    k.initialize()
    with OntologyUnitOfWork(k.engine) as uow:
        for path in sorted(reg.glob("*.json")):
            if path.name.startswith("_"):
                continue
            doc = load_registry_doc(path)
            cols = sorted({a.split(":", 1)[1] for a in (doc.get("exits") or {}).values()
                           if a.startswith("packet_column:")})
            e = uow.rsi.experiment(doc["exp_id"]) if cols else None
            if e is None:
                continue
            f = Falsifier.from_dict(e.falsifier)
            label = evidence_label(
                e, uow.rsi.latest_verdict(e.exp_id), uow.rsi.latest_deployment(e.exp_id),
                uow.rsi.latest_grade(e.exp_id, mode="prospective", stratum=f.stratum), f)
            for col in cols:
                by_column.setdefault(col, []).append(f"{e.exp_id} {label}")
    if not by_column:
        return "列实证：（没有登记出口指向分析包的实验）\n"
    return ("列实证：" + " ｜ ".join(f"{col} {'·'.join(v)}" for col, v in sorted(by_column.items()))
            + "（未证的列只是展示或纪律，不是有实证的判据）\n")


def test_rsi_columns_output_unchanged_by_the_move(tmp_path):
    data, reg = _sandbox(tmp_path)
    r = CliRunner().invoke(app, ["rsi", "columns", "--data-dir", str(data),
                                 "--registry-dir", str(reg)])
    assert r.exit_code == 0, r.output
    assert r.output == _columns_before_move(data, reg)
    # 同列两个实验按原件文件名排；退役照写；草稿与无出口的不出现
    assert "许可证 F10 未证 0/140·F18 未证 0/140" in r.output
    assert "表态面 F14b 退役" in r.output
    assert "草稿列" not in r.output and "F99" not in r.output


def test_lab_board_splits_live_and_settled(tmp_path):
    data, reg = _sandbox(tmp_path)
    board = lab_board(data, reg)
    assert board["errors"] == []
    assert sorted(r["exp_id"] for r in board["live"]) == ["F10", "F18", "F99"]
    assert [r["exp_id"] for r in board["settled"]] == ["F14b"]
    f10 = next(r for r in board["live"] if r["exp_id"] == "F10")
    assert f10["columns"] == ["热门带", "许可证"] and f10["label"] == "未证 0/140"
    assert f10["n_min"] == 140 and f10["claim"] == "c" and f10["source_doc"]
    assert columns_line(board) + "\n" == _columns_before_move(data, reg)
    empty = {"live": [], "settled": [], "errors": []}
    assert columns_line(empty) == "列实证：（没有登记出口指向分析包的实验）"


def test_lab_board_kernel_unreachable_goes_to_errors(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "ontology").write_text("不是目录", encoding="utf-8")
    board = lab_board(data, tmp_path / "no-registry")
    assert board["live"] == [] and board["settled"] == []
    assert board["errors"] and "内核读不出" in board["errors"][0]


def test_cite_totals_adds_across_issues(tmp_path):
    zucai = tmp_path / "zucai"
    zucai.mkdir()

    def bridge(issue: str, *recs: dict) -> None:
        (zucai / f"{issue}{BRIDGE_SUFFIX}").write_text(
            "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")

    bridge("26150", {"diffs": [{"reason": {"kind": "matrix"}}, {"reason": {"kind": "out"}},
                               {"reason": None}]},
           {"diffs": [{"reason": {"kind": "matrix"}}] * 5})   # 第二条不算：桥只走一次
    bridge("26151", {"diffs": [{"reason": {"kind": "matrix"}}, {}]})
    bridge("26152", {"diffs": []})
    assert cite_totals(tmp_path) == {"issues": 3, "diffs": 5, "matrix": 2, "outside": 1,
                                     "blank": 2}
    assert cite_totals(tmp_path / "nowhere") == {"issues": 0, "diffs": 0, "matrix": 0,
                                                 "outside": 0, "blank": 0}
