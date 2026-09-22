#!/usr/bin/env python
"""T13 因子注册表：加载、校验、按冻结规则出**提案**。⛔从不写权重。

    uv run python experiments/factor_registry.py validate
    uv run python experiments/factor_registry.py propose [--factor <id> | --all]
                                                         [--corpus <path>] [--log]

`propose` 对 `layer == "probability"` 的因子跑 `noise_floor`（严格档 = 只收
`provably_prospective is True` 的行，另附全量档参考），再按注册表里冻结的
`weight_change_rule` 给出三种结论之一：

    propose_change  n >= n_min ∧ above_floor ∧ 训练窗/测试窗同号 → 点估计截断进 weight_band
    propose_zero    n >= n_min ∧ indistinguishable                → 0.0（证伪路径，本身就是迭代）
    hold            其余（含 n 不够、insufficient）                 → 维持

`fact` 层因子只记录测量，永远输出 `record_only`。`expression` 不在因子表里。
提案是 stdout JSON；`--log` 追加一行到 attempts.log。`factors.json` 本身不被改写。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REGISTRY = ROOT / "experiments" / "factors.json"
LAYERS = {"fact", "probability"}
AUDIT_CODES = {
    "C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12",
    "C13", "C14", "C15", "C15b", "C17", "C18", "C18b",
}


def load_registry(path: Path = REGISTRY) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(registry: dict) -> list[str]:
    """Return a list of violations (empty = valid)."""
    problems: list[str] = []
    rule = registry.get("weight_change_rule") or {}
    for key in ("n_min", "requires_verdict", "split_window", "sample_mode"):
        if key not in rule:
            problems.append(f"weight_change_rule missing {key}")
    covered: set[str] = set()
    ids: set[str] = set()
    for factor in registry.get("factors", []):
        fid = factor.get("factor_id")
        if not fid or fid in ids:
            problems.append(f"duplicate or missing factor_id: {fid!r}")
        ids.add(fid)
        layer = factor.get("layer")
        if layer not in LAYERS:
            problems.append(f"{fid}: layer must be fact|probability, got {layer!r}")
        if layer == "fact" and not factor.get("measure_only"):
            problems.append(f"{fid}: fact-layer factor must be measure_only")
        if layer == "fact" and factor.get("weight_band") != [0.0, 0.0]:
            problems.append(f"{fid}: fact-layer weight_band must be [0.0, 0.0]")
        if layer == "probability":
            builder = factor.get("row_builder")
            if not builder or ":" not in builder:
                problems.append(f"{fid}: probability factor needs row_builder module:function")
            else:
                module, func = builder.split(":", 1)
                try:
                    mod = importlib.import_module(module)
                except ImportError as exc:
                    problems.append(f"{fid}: row_builder import failed: {exc}")
                else:
                    if not hasattr(mod, func):
                        problems.append(f"{fid}: {module} has no {func}")
                    elif fid not in getattr(mod, "_FACTORS", {}):
                        problems.append(f"{fid}: not registered in {module}._FACTORS")
        if float(factor.get("current_weight_pp", 0.0)) != 0.0:
            problems.append(f"{fid}: current_weight_pp must stay 0.0 (T13 does not move weights)")
        for code in factor.get("rule_codes", []):
            covered.add(code)
    for expr in registry.get("expression_rules", []):
        if not expr.get("reason"):
            problems.append(f"expression rule {expr.get('rule_codes')} lacks a reason")
        covered.update(expr.get("rule_codes", []))
    missing = sorted(AUDIT_CODES - covered)
    if missing:
        problems.append(f"audit codes without an owner: {missing}")
    return problems


def _split_window_signs(builder, rows: list[dict], n_perm: int, seed: int) -> dict:
    """Train/test halves by date; report each window's observed slope sign."""
    from experiments.noise_floor import permutation_floor

    dated = sorted((r for r in rows if r.get("date")), key=lambda r: r["date"])
    if len(dated) < 4:
        return {"train": None, "test": None, "agree": None}
    half = len(dated) // 2
    out = {}
    for name, part in (("train", dated[:half]), ("test", dated[half:])):
        built = builder(part)
        try:
            result = permutation_floor(built, "factor", "face_hit_rate_resid_pp", n_perm, seed)
            out[name] = {"n": result["n"], "observed_pp": result["observed_pp"]}
        except ValueError:
            out[name] = None
    signs = [
        (out[k]["observed_pp"] > 0) - (out[k]["observed_pp"] < 0)
        for k in ("train", "test")
        if out.get(k) and out[k]["observed_pp"] is not None
    ]
    out["agree"] = (len(signs) == 2 and signs[0] == signs[1] and signs[0] != 0)
    return out


def propose(
    registry: dict, factor_id: str, rows: list[dict], *, n_perm: int = 1000, seed: int = 20260920
) -> dict:
    from experiments.noise_floor import analyze

    factor = next(f for f in registry["factors"] if f["factor_id"] == factor_id)
    rule = registry["weight_change_rule"]
    band = factor.get("weight_band") or registry.get("default_weight_band_pp", [-15.0, 15.0])
    if factor["layer"] != "probability":
        strict = (
            analyze(rows, factor=factor_id, include_unproven=False, n_perm=n_perm, seed=seed)
            if factor.get("row_builder")
            else {"n": 0, "verdict": "not_measured", "observed_pp": None, "p_value": None}
        )
        return {
            "factor_id": factor_id,
            "layer": factor["layer"],
            "decision": "record_only",
            "current_weight_pp": factor["current_weight_pp"],
            "proposed_weight_pp": factor["current_weight_pp"],
            "strict": strict,
            "reason": "fact-layer factor: measurement is recorded, never drives a weight",
        }
    strict = analyze(rows, factor=factor_id, include_unproven=False, n_perm=n_perm, seed=seed)
    reference = analyze(rows, factor=factor_id, include_unproven=True, n_perm=n_perm, seed=seed)
    module, func = factor["row_builder"].split(":", 1)
    builder = getattr(importlib.import_module(module), func)
    provable = [r for r in rows if r.get("provably_prospective") is True]
    windows = _split_window_signs(builder, provable, n_perm, seed)
    n_ok = strict["n"] >= rule["n_min"]
    if n_ok and strict["verdict"] == rule["requires_verdict"] and windows.get("agree"):
        proposed = max(band[0], min(band[1], float(strict["observed_pp"])))
        decision = "propose_change"
        reason = "n >= n_min, above floor, train/test signs agree"
    elif n_ok and strict["verdict"] == "indistinguishable":
        proposed, decision = 0.0, "propose_zero"
        reason = "n >= n_min but indistinguishable from the permutation floor"
    else:
        proposed, decision = factor["current_weight_pp"], "hold"
        reason = (
            f"strict n={strict['n']} < n_min={rule['n_min']}"
            if not n_ok
            else f"verdict={strict['verdict']}, windows agree={windows.get('agree')}"
        )
    return {
        "factor_id": factor_id,
        "layer": factor["layer"],
        "rule_codes": factor.get("rule_codes"),
        "decision": decision,
        "reason": reason,
        "current_weight_pp": factor["current_weight_pp"],
        "proposed_weight_pp": proposed,
        "weight_band": band,
        "n_min": rule["n_min"],
        "strict": strict,
        "reference_all_rows": reference,
        "split_window": windows,
        "writes_weights": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("command", choices=["validate", "propose"])
    ap.add_argument("--registry", type=Path, default=REGISTRY)
    ap.add_argument(
        "--corpus", type=Path, default=ROOT / "experiments" / "corpus-v2.json"
    )
    ap.add_argument("--factor", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n-perm", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260920)
    ap.add_argument("--log", action="store_true")
    args = ap.parse_args()
    registry = load_registry(args.registry)
    problems = validate(registry)
    if args.command == "validate":
        print(json.dumps({"valid": not problems, "problems": problems}, ensure_ascii=False))
        return 1 if problems else 0
    if problems:
        print(json.dumps({"error": "registry invalid", "problems": problems}, ensure_ascii=False))
        return 1
    if not args.factor and not args.all:
        print("propose needs --factor <id> or --all")
        return 2
    from experiments.noise_floor import _load_corpus

    rows = _load_corpus(args.corpus)
    ids = [f["factor_id"] for f in registry["factors"]] if args.all else [args.factor]
    before = args.registry.read_bytes()
    outputs = [propose(registry, fid, rows, n_perm=args.n_perm, seed=args.seed) for fid in ids]
    assert args.registry.read_bytes() == before, "propose must never write the registry"
    for item in outputs:
        print(json.dumps(item, ensure_ascii=False, sort_keys=True))
    if args.log:
        from experiments.attempts import log_attempt

        for item in outputs:
            strict = item["strict"]
            log_attempt(
                f"factor propose {item['factor_id']}",
                f"strict n={strict['n']} n_min={item.get('n_min')} n_perm={args.n_perm}",
                f"obs={strict.get('observed_pp')}pp p={strict.get('p_value')} "
                f"verdict={strict.get('verdict')} "
                f"windows={(item.get('split_window') or {}).get('agree')}",
                f"{item['decision']} → proposed {item['proposed_weight_pp']}pp (not written)",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
