"""RUNBOOK 泳道 B 的确定性步骤登记表 + 进程内运行器。

出生事故 2026-09-18：26129 一期，B0→B9 的每一条命令都是我在终端手敲的，用户问
「不开聊天窗口能不能把一期跑完」——答案取决于这些命令能不能从页面上按出来。
本模块只做两件事：①把每一步描述成 (argv 构造器, 产物路径, 允许的退出码)，
②用 typer 的 CliRunner 在进程内调用**同一个** CLI，并把过程写进事件流。

⛔判断永不入脚本：这里没有 B3（深研，需要 agent）、没有 Jun 改票那一步、
   没有 B6b 的 ruling（只签发空裁决单，ruling 由人填）。
   2026-10-03：机器构票的 B4b 候选穷举 / B5c 定级 / B5 前沿 / B9 定案随命令一起删除。
2026-10-01 定位：B5 按钮＝`judgment brief --issue --write`（初判包 + 机器初稿，处方忠实），
   B5b＝把初稿票面送 `betslip preview` 审票，B6 审计门不给 legs_file 时默认吃初稿腿文件。
⛔审计门退出码 1 是「有 ERROR」这个**判决**，不是任务失败——`ok_exit_codes` 里显式列出。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from nutmeg.decision.workbench import append_event


@dataclass(frozen=True)
class SopParams:
    issue: str
    date: str                       # 业务日 YYYY-MM-DD（decision-am --run-date）
    zucai_dir: Path
    output_dir: Path                # .nutmeg-data/jczq
    legs_file: Path | None = None   # B6 / B6b 需要；其余步骤忽略
    made_at: str = field(default_factory=lambda: datetime.now().astimezone()
                         .isoformat(timespec="minutes"))


@dataclass(frozen=True)
class SopStep:
    step_id: str
    label: str
    argv: Callable[[SopParams], list[str]]
    artifacts: Callable[[SopParams], list[Path]]
    ok_exit_codes: tuple[int, ...] = (0,)
    needs_legs: bool = False


def _z(p: SopParams, name: str) -> Path:
    return p.zucai_dir / f"{p.issue}-{name}"


STEPS: tuple[SopStep, ...] = (
    SopStep("B0_prep_morning", "B0 早刷新",
            lambda p: ["zucai-prep", "--slot", "morning", "--issue", p.issue],
            lambda p: [_z(p, "prep-morning.json")]),
    SopStep("B1_prep_afternoon", "B1 14:00 备料",
            lambda p: ["zucai-prep", "--slot", "afternoon", "--issue", p.issue],
            lambda p: [_z(p, "prep-afternoon.json")]),
    SopStep("B2_canonical", "B2 入 canonical",
            lambda p: ["decision-am", "--run-date", p.date, "--issue", p.issue,
                       "--output-dir", str(p.output_dir)],
            lambda p: [_z(p, "store-ids.json")]),
    SopStep("B3a_premise_card", "B3a 前提卡",
            lambda p: ["zucai-premise-card", "--issue", p.issue,
                       "--out", str(_z(p, "premise-card.md"))],
            lambda p: [_z(p, "premise-card.md")]),
    SopStep("B4_build_reads", "B4 落 Read",
            lambda p: ["zucai-build-reads", "--judgment-file", str(_z(p, "judgment-v1.json")),
                       "--issue", p.issue, "--store-ids-file", str(_z(p, "store-ids.json")),
                       "--fair-file", str(_z(p, "fair.json")), "--made-at", p.made_at],
            lambda p: [_z(p, "reads.json"), _z(p, "legs-base.json")]),
    SopStep("B5_judgment_brief", "B5 初判+初稿",
            lambda p: ["judgment", "brief", "--issue", p.issue, "--write",
                       "--data-dir", str(p.output_dir / "..")],
            lambda p: [_z(p, "judgment-brief.md"), _z(p, "draft.json")]),
    SopStep("B5b_review_draft", "B5b 审初稿(任九)",
            lambda p: _review_draft_argv(p),
            lambda p: [], ok_exit_codes=(0, 1)),
    SopStep("B6_audit", "B6 审计门",
            lambda p: ["decision-audit-legs", "--legs-file",
                       str(p.legs_file or _z(p, "legs-draft-renjiu.json"))],
            lambda p: [], ok_exit_codes=(0, 1)),
    SopStep("B6b_adjudicate_issue", "B6b 签发裁决单",
            lambda p: ["decision-adjudicate", "--legs-file", str(p.legs_file),
                       "--out", str(_z(p, "adjudication.json"))],
            lambda p: [_z(p, "adjudication.json")], needs_legs=True),
)


def _review_draft_argv(p: SopParams) -> list[str]:
    """初稿票面（`<期>-draft.json` 的「初稿·任九」）→ `betslip preview`；没有初稿就先出初稿。"""
    import json

    try:
        doc = json.loads(_z(p, "draft.json").read_text(encoding="utf-8"))
        cand = next(c for c in doc.get("candidates") or []
                    if c.get("label") == "初稿" and c.get("channel") == "renjiu" and c.get("faces"))
    except (OSError, ValueError, StopIteration):
        return ["judgment", "draft", "--issue", p.issue, "--data-dir", str(p.output_dir / "..")]
    row = " ".join(f"{no}:{fs}" for no, fs in cand["faces"].items())
    return ["betslip", "preview", "--channel", "renjiu", "--placed-at", p.date,
            "--issue", p.issue, "--faces", row, "--data-dir", str(p.output_dir / "..")]


def step_by_id(step_id: str) -> SopStep:
    for s in STEPS:
        if s.step_id == step_id:
            return s
    raise KeyError(f"未登记的 SOP 步骤: {step_id}")


_TAIL_LINES = 12


def cli_invoke(argv: list[str]) -> tuple[int, str]:
    """生产 invoker：进程内跑同一个 typer app（不 subprocess，测试可替身）。"""
    from typer.testing import CliRunner

    from nutmeg.interfaces.cli import app

    result = CliRunner().invoke(app, argv)
    return result.exit_code, result.output


def run_step(step_id: str, params: SopParams, *, invoke=cli_invoke) -> dict:
    """跑一步；开始/结束各写一条事件（obj_id=task:<step_id>），返回结果摘要。"""
    step = step_by_id(step_id)
    obj = f"task:{step.step_id}"
    if step.needs_legs and params.legs_file is None:
        return {"ok": False, "step_id": step.step_id, "error": "该步骤需要 legs_file"}
    argv = step.argv(params)
    append_event(params.output_dir, params.date, {
        "kind": "task_started", "obj_id": obj, "step_id": step.step_id,
        "label": step.label, "argv": argv,
        "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    exit_code, output = invoke(argv)
    tail = "\n".join(output.strip().splitlines()[-_TAIL_LINES:])
    ok = exit_code in step.ok_exit_codes
    append_event(params.output_dir, params.date, {
        "kind": "task_done" if ok else "task_failed", "obj_id": obj,
        "step_id": step.step_id, "label": step.label, "exit_code": exit_code,
        "text": tail,
        "artifacts": [str(a) for a in step.artifacts(params) if a.exists()],
        "at": datetime.now().astimezone().isoformat(timespec="seconds")})
    return {"ok": ok, "step_id": step.step_id, "exit_code": exit_code, "tail": tail}
