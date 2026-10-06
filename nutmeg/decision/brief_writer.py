"""逻辑层撰稿器：每场一次无联网 `claude -p`，输出 JSON，cites 逐一校验（设计 §6.3、§9）。"""
from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable

from nutmeg.decision.brief_prompt import LOGIC_SYSTEM_PROMPT, render_logic_input
from nutmeg.decision.claude_models import (
    claude_bin,
    claude_env,
    logic_model,
    model_argv,
    model_label,
)

Claude = Callable[[str, str], tuple[int, str]]
LOGIC_DAILY_BUDGET = 40
MIN_CITES = 2
MAX_SENTENCES = 8
"""提示要求 ≤6 句；超过 8 句视为没听话，拒收（宁缺毋滥，被拒的场页面照样显示原因）。"""


def _claude_cli(prompt: str, stdin: str) -> tuple[int, str]:
    argv = [claude_bin(), "-p", *model_argv(logic_model()), "--system-prompt", prompt,
            "--allowedTools", "", "--max-turns", "1", "--output-format", "text"]
    with tempfile.TemporaryDirectory() as neutral:
        proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=300,
                               cwd=neutral, env=claude_env(), check=False)
    return proc.returncode, proc.stdout


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def resolve_path(obj, path: str):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def validate_cites(cites: list, card: dict, factors: list[dict]) -> list[str]:
    scope = {**card, "factors": factors}
    bad = []
    for cite in cites:
        if not isinstance(cite, str):
            bad.append(str(cite))
        elif resolve_path(scope, cite) is None and not _exists(scope, cite):
            bad.append(str(cite))
    return bad


def _exists(scope, path: str) -> bool:
    """`resolve_path` 把值为 None/False 的字段也返回 None/False；存在性单独判。"""
    cur = scope
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False
    return True


def _one(card: dict, factors: list[dict], claude: Claude) -> dict:
    code, text = claude(LOGIC_SYSTEM_PROMPT, render_logic_input(card, factors))
    if code != 0:
        return {"status": "not_generated", "reason": f"claude exit {code}"}
    try:
        doc = json.loads(_strip_fence(text))
    except ValueError:
        return {"status": "rejected", "reason": "非法 JSON"}
    if not isinstance(doc, dict) or doc.get("code") != card.get("code"):
        return {"status": "rejected", "reason": "code 不匹配"}
    cites = doc.get("cites") or []
    bad = validate_cites(cites, card, factors)
    if bad or not cites:
        return {"status": "rejected", "reason": "cites 不存在: " + ", ".join(bad or ["<空>"])}
    if len(cites) < MIN_CITES:
        return {"status": "rejected", "reason": f"cites 少于 {MIN_CITES} 条"}
    logic = str(doc.get("logic") or "").strip()
    if not logic:
        return {"status": "rejected", "reason": "logic 为空"}
    sentences = [x for x in logic.replace("！", "。").replace("？", "。").split("。") if x.strip()]
    if len(sentences) > MAX_SENTENCES:
        return {"status": "rejected", "reason": f"超过 {MAX_SENTENCES} 句（{len(sentences)}）"}
    return {"status": "ok", "text": logic, "cites": list(cites), "author": "claude -p"}


def write_logic(
    brief: dict, *, claude: Claude = _claude_cli, budget: int = LOGIC_DAILY_BUDGET,
    model: str | None = None,
) -> dict:
    """返回带 `logic` 字段的 brief 副本。超预算的场 `not_generated/budget`。不改其它字段。

    `model` 只作标注（写进 `logic.model`），真正传给 claude 的模型由 `claude` 可调用对象决定；
    默认 `_claude_cli` 用 settings.model_logic。"""
    factors = brief.get("factors") or []
    label = model_label(model if model is not None else (
        logic_model() if claude is _claude_cli else None))
    matches = []
    for i, card in enumerate(brief.get("jczq", {}).get("matches", [])):
        card = dict(card)
        card["logic"] = (_one(card, factors, claude) if i < budget
                          else {"status": "not_generated", "reason": "budget"})
        card["logic"]["model"] = label
        matches.append(card)
    return {**brief, "jczq": {**brief["jczq"], "matches": matches}}


_LOGIC_INPUTS = ("stance", "read", "ladder", "labels", "market")


def carry_logic(brief: dict, previous: dict | None) -> dict:
    """不重算逻辑层的刷新：沿用上一版 `logic`，但只在解释所依据的输入没变时。

    14:20/18:35 的刷新不带 --with-logic，若整份重写会把 12:00 的解释丢掉（2026-09-23 实发）。
    表态 / Read / 阶梯 / 标签 / 市场任一变了，旧解释可能已失效——宁可丢，也不带着过期解释。"""
    if not previous:
        return brief
    old = {m.get("code"): m for m in previous.get("jczq", {}).get("matches", [])
           if isinstance(m, dict)}
    matches = []
    for card in brief.get("jczq", {}).get("matches", []):
        prev = old.get(card.get("code"))
        if (prev and isinstance(prev.get("logic"), dict) and "logic" not in card
                and all(prev.get(k) == card.get(k) for k in _LOGIC_INPUTS)):
            card = {**card, "logic": {**prev["logic"], "carried": True}}
        matches.append(card)
    return {**brief, "jczq": {**brief["jczq"], "matches": matches}}
