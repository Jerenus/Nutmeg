"""登记原件（experiments/registry/<exp_id>.json）的加载与校验。

原件由人手写，`nutmeg rsi register` 摄入一次；之后内核是唯一权威，原件只是登记时的
文本。这里只做结构校验——判据的语义（CI 怎么判）在 nutmeg.ontology.rsi.models。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from nutmeg.ontology.rsi.models import Falsifier, JudgmentTier, Layer, Population, Tier

_REQUIRED = ("exp_id", "claim", "mechanism", "tier", "layer", "population", "min_tier",
             "window", "falsifier", "stop_rule", "quota_slot", "source_doc", "registered_at")
_DUTY_REQUIRED = ("name", "scope", "deadline_rule", "instrument", "artifact_glob")
_DEADLINE_RULES = ("earliest_kickoff", "match_kickoff")
_SCOPES = ("day", "match")
_DUTY_STATUSES = ("active", "pending_instrument", "manual")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CR_REQUIRED = ("label_cn", "trigger", "crowd_bias", "replay_window")
EXIT_KEYS = ("on_survived", "on_falsified", "on_expired")
_EXIT_ACTION = re.compile(r"^((rubric_cap|rule|retire_rule|packet_column):\S+|display_only|none)$")
# 指标两段式（2026-10-26 RULEBOOK「〇」）：登记原件顶层可选 `role`
#   display_only：过了回溯预筛但 |效应| <10pp → 只做分析包展示列，不 grade / 不 verdict
#   monitor     ：只 grade 不 verdict（K2 n_min 1,500；F9 有害监测另在 rsi_loop.MONITORS）
ROLES = ("display_only", "monitor")
PRESCREEN_N_MIN = 60


EXTERNAL_FIRST_FROM = "2026-11-13"
EXTERNAL_N_MIN = 5000
_EXTERNAL_REQUIRED = ("source", "n", "effect_pp", "ci_low_pp", "ci_high_pp", "script")


def require_external_first(doc: dict) -> None:
    """判断类新实验先过外部样本（2026-11-13 Jun 签 P-574c4d0b ⑤）。

    24 个实验里没有一条判断类主张变成拦截或拨动规则，五轮因子挖掘在同一张内部样本表上
    没有可复现信号；外部 6–8 万场回测两次改写了内部小样本的读数（平局排序、损耗格）。
    所以 `registered_at` 在 `EXTERNAL_FIRST_FROM` 之后的 judgment 层登记，原件里必须带
    `external_prescreen`：{source, n ≥ EXTERNAL_N_MIN, effect_pp, ci_low_pp, ci_high_pp,
    script}，且 CI 不含 0。内部样本只用来确认，不用来发现。
    不在此列：结构类实验、规矩之前登记的原件、口径变更的续登记（`epoch_of`）。"""
    if (doc.get("layer") != Layer.JUDGMENT.value or doc.get("epoch_of")
            or str(doc.get("registered_at") or "") < EXTERNAL_FIRST_FROM):
        return
    ext = doc.get("external_prescreen")
    if not isinstance(ext, dict):
        raise ValueError(
            f"{doc.get('exp_id')} 是判断类新实验：先过外部样本再登记（原件缺 "
            "external_prescreen；2026-11-13 Jun 签 P-574c4d0b ⑤）")
    missing = [k for k in _EXTERNAL_REQUIRED if ext.get(k) in (None, "")]
    if missing:
        raise ValueError(f"external_prescreen 缺字段: {missing}")
    if int(ext["n"]) < EXTERNAL_N_MIN:
        raise ValueError(f"external_prescreen.n={ext['n']} 不够：外部样本至少 {EXTERNAL_N_MIN} 场")
    if float(ext["ci_low_pp"]) <= 0 <= float(ext["ci_high_pp"]):
        raise ValueError(
            f"外部样本 CI [{ext['ci_low_pp']}, {ext['ci_high_pp']}] 含 0：没有信号，不登记")


def load_registry_doc(path: Path) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in _REQUIRED if k not in doc]
    if missing:
        raise ValueError(f"登记原件缺字段: {missing}")
    Tier(doc["tier"])
    Layer(doc["layer"])
    Population(doc["population"])
    JudgmentTier(doc["min_tier"])
    Falsifier.from_dict(doc["falsifier"])
    w = doc["window"]
    if not isinstance(w, dict) or not (
        {"issue_from", "issue_to"} <= set(w) or {"date_from", "n_min"} <= set(w)
    ):
        raise ValueError("window 必须是 {issue_from, issue_to} 或 {date_from, n_min[, date_to]}")
    if not _DATE.match(str(doc["registered_at"])):
        raise ValueError("registered_at 必须是 YYYY-MM-DD（原登记日，不是摄入日）")
    for d in doc.get("duties") or []:
        for k in _DUTY_REQUIRED:
            if k not in d:
                raise ValueError(f"duty 缺字段 {k}")
        if d["deadline_rule"] not in _DEADLINE_RULES:
            raise ValueError(f"deadline_rule 必须是 {_DEADLINE_RULES}")
        if d["scope"] not in _SCOPES:
            raise ValueError(f"duty.scope 必须是 {_SCOPES}")
        status = d.get("status", "active")
        if status not in _DUTY_STATUSES:
            raise ValueError(f"duty.status 必须是 {_DUTY_STATUSES}")
        if status == "pending_instrument" and d["instrument"] and d["instrument"][0] == "TODO":
            continue
        if not d["instrument"] or not any("{issue}" in a or "{day}" in a for a in d["instrument"]):
            raise ValueError("instrument 必须含 {issue} 或 {day} 占位，否则每天跑的是同一条命令")
    if str(doc["exp_id"]).startswith("CR"):
        _validate_crowd(doc)
    validate_exits(doc.get("exits"))
    if doc.get("role") is not None and doc["role"] not in ROLES:
        raise ValueError(f"role 只许 {ROLES}")
    return doc


def apply_prescreen(doc: dict, prescreen: dict, *, n_min: int | None = None) -> dict:
    """两段式第二段的入口（`rsi register --prescreen`）：按 `structure_align.py --indicator`
    的输出改写登记原件——不过地板拒登记；过地板但 suggested_n_min 为空 → role=display_only
    （n_min 不动，只展示）；否则 window/falsifier 的 n_min 取 60（--n-min 可覆盖但 ≥60）。
    预筛原件整份存进 doc["prescreen"]，进冻结指纹。"""
    for key in ("id", "n", "residual_pp", "passes_floor", "suggested_n_min"):
        if key not in prescreen:
            raise ValueError(f"预筛结果缺字段 {key}（要 structure_align.py --indicator 的输出）")
    if not prescreen["passes_floor"]:
        raise ValueError(
            f"预筛不过地板：{prescreen['id']} n={prescreen['n']} 残差 "
            f"{prescreen['residual_pp']:+.1f}pp 落在选择置换地板 "
            f"[{prescreen.get('floor_low_pp')},{prescreen.get('floor_pp')}] 内——不登记")
    out = json.loads(json.dumps(doc, ensure_ascii=False))
    out["prescreen"] = prescreen
    if prescreen["suggested_n_min"] is None:
        out["role"] = "display_only"
        return out
    chosen = PRESCREEN_N_MIN if n_min is None else int(n_min)
    if chosen < PRESCREEN_N_MIN:
        raise ValueError(f"--n-min 必须 ≥{PRESCREEN_N_MIN}（两段式前瞻确认的下限）")
    out["window"] = {**out["window"], "n_min": chosen}
    out["falsifier"] = {**out["falsifier"], "n_min": chosen}
    out.pop("role", None)
    return out


def registry_role(registry_dir: Path, exp_id: str) -> str | None:
    """登记原件顶层 `role`（内核不存它；原件是登记时的文本，这里只读不写）。"""
    path = Path(registry_dir) / f"{exp_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("role")
    except (OSError, ValueError):
        return None


def base_exp_id(exp_id: str) -> str:
    """`F19.v2` → `F19`：epoch 副本沿用原实验的结账适配器与清单位置。"""
    return re.sub(r"\.v\d+$", "", str(exp_id))


def next_epoch_id(exp_id: str) -> str:
    m = re.search(r"\.v(\d+)$", str(exp_id))
    return f"{base_exp_id(exp_id)}.v{int(m.group(1)) + 1 if m else 2}"


def validate_exits(exits) -> None:
    """登记出口（2026-10-19 Jun 裁 4）：判决之后改哪个开关。可缺——缺出口的实验照样登记，
    记作「观察型」正样本；写了就必须是封闭动作：`rubric_cap:<项>` / `rule:<码>` /
    `retire_rule:<码>` / `packet_column:<列>` / `display_only` / `none`。"""
    if exits is None:
        return
    if not isinstance(exits, dict) or set(exits) - set(EXIT_KEYS):
        raise ValueError(f"exits 只许 {EXIT_KEYS}")
    for key, action in exits.items():
        if not isinstance(action, str) or not _EXIT_ACTION.match(action):
            raise ValueError(f"exits.{key} `{action}` 不是封闭动作")


def is_observation_only(doc: dict) -> bool:
    """没写出口、或三个出口全是 none ＝ 观察型（只积累样本，判决不改任何开关）。"""
    exits = doc.get("exits") or {}
    return all(exits.get(k, "none") == "none" for k in EXIT_KEYS)


def _validate_crowd(doc: dict) -> None:
    """人群假说（CR，2026-10-07）：结构层、带触发谓词与方向、带回放窗。"""
    from nutmeg.decision.crowd_trigger import validate

    missing = [k for k in _CR_REQUIRED if k not in doc]
    if missing:
        raise ValueError(f"CR 原件缺字段: {missing}")
    if doc["crowd_bias"] not in ("under", "over"):
        raise ValueError("crowd_bias 必须是 under/over")
    if doc["layer"] != Layer.STRUCTURAL.value:
        raise ValueError("CR 实验必须是 structural 层（结账靠官方奖金回放，可上线）")
    rw = doc["replay_window"]
    if not isinstance(rw, dict) or not {"issue_from", "issue_to"} <= set(rw):
        raise ValueError("replay_window 必须是 {issue_from, issue_to}")
    validate(doc["trigger"])


def render_instrument(argv: list[str], *, issue: str | None, day: str) -> list[str]:
    out: list[str] = []
    for a in argv:
        if "{issue}" in a:
            if issue is None:
                raise ValueError("该 instrument 需要 issue，但当天没有足彩期")
            a = a.replace("{issue}", issue)
        out.append(a.replace("{day}", day))
    return out
