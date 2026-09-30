"""RSI 每日闭环运行器：把「人之前」的每一步串成一条可定时的链。

设计：`docs/superpowers/specs/2026-09-22-rsi-closed-loop-automation-design.md`。

每天一次（建议 10:45，在 09:30 赛果回填之后）：

    1. closing_backfill   补采 titan007 终盘（竞彩板 + 足彩期），幂等
    2. corpus_build       重建语料 v2
    3. grade_prospective  对每个有前瞻适配器的实验 `rsi grade --mode prospective`（系统身份）
    4. verdict_due        对每个实验尝试 `rsi verdict`；「未到期」是预期状态不是失败
    5. factor_propose     `rsi weights propose --all --log`（从不写权重）
    6. hyp                `zucai_loop hyp --corpus v2 --log`（假设批次证伪）
    6b. factor_search     `zucai_loop search --corpus v2`（训练窗搜、测试窗验，自报噪音上限）
    7. team_strength      客观实力指标重建
    8. scoreboard         记分牌散文 → 结构化计数
    8b. dream_compare     前一业务日 Dream 世界对照记账（只报告；常设批准到期前 7 天报倒计时）
    9. report             写 `.nutmeg-data/analytics/rsi-loop/<date>.json|.md` 与 `latest.md`

⛔运行器只编排、只追加：不写权重、不改 RULEBOOK / 码表 / 记分牌、不登记实验、不部署。
人类动作只出现在报告的「待人决定」清单里。每一步都是子进程，失败只影响该步并进报告；
退出码非零仅当有步骤失败（「未到期」「无提案」「n 不够」都是 0）。
同一天已有报告则跳过（`--force` 覆盖），保证 launchd 重复触发无副作用。
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]

STEP_ORDER = (
    "closing_backfill",
    "corpus_build",
    "grade_prospective",
    "verdict_due",
    "factor_propose",
    "hyp",
    "factor_search",
    "team_strength",
    "scoreboard",
    "dream_compare",
)
GRADED_EXPERIMENTS = ("F2", "F3", "F4", "F5", "F9")
NOT_DUE_MARKERS = ("未到期", "没有 prospective 档", "重放结果进不了判决")


@dataclass
class StepResult:
    name: str
    status: str  # ok | failed | skipped | not_due
    seconds: float
    summary: str
    detail: dict = field(default_factory=dict)


@dataclass
class LoopReport:
    date: str
    started_at: str
    finished_at: str
    steps: list[StepResult]
    proposals: list[dict]
    grades: list[dict]
    verdicts: list[dict]
    human_actions: list[str]
    failed_steps: list[str]
    dream: dict = field(default_factory=dict)
    quiet_factors: list[str] = field(default_factory=list)  # propose_zero 且现值已为 0：不需动作

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "steps"},
            "steps": [asdict(s) for s in self.steps],
        }


@dataclass
class LoopContext:
    root: Path
    data_dir: Path
    date: str
    runner: Runner
    corpus: Path | None = None
    skip: frozenset[str] = frozenset()

    @property
    def corpus_path(self) -> Path:
        return self.corpus or self.root / "experiments" / "corpus-v2.json"

    @property
    def out_dir(self) -> Path:
        return self.data_dir / "analytics" / "rsi-loop"


def default_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


def _tail(text: str, lines: int = 3) -> str:
    chunks = [line for line in (text or "").strip().splitlines() if line.strip()]
    return " / ".join(chunks[-lines:])[:600]


def _json_lines(text: str) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _latest_issue(corpus_path: Path) -> str | None:
    try:
        rows = json.loads(corpus_path.read_text("utf-8"))["rows"]
    except (OSError, ValueError, KeyError):
        return None
    issues = sorted({str(r["issue"]) for r in rows if r.get("src") == "zucai" and r.get("issue")})
    return issues[-1] if issues else None


def _days_before(day: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


def planned_commands(ctx: LoopContext) -> dict[str, list[list[str]]]:
    """每一步要跑的子进程命令；`rsi loop --dry-run` 打印这个。"""
    uv = ["uv", "run"]
    data = ["--data-dir", str(ctx.data_dir)]
    cut = _latest_issue(ctx.corpus_path) or "26131"
    return {
        "closing_backfill": [
            [*uv, "python", "scripts/titan007_closing_backfill.py", "--sleep", "0.3",
             "--data-dir", str(ctx.data_dir / "jczq")],
            [*uv, "python", "scripts/titan007_closing_backfill.py", "--zucai", "--sleep", "0.3",
             "--zucai-dir", str(ctx.data_dir / "zucai")],
        ],
        "corpus_build": [
            [*uv, "python", "experiments/corpus_build.py", "--out", str(ctx.corpus_path)],
        ],
        "grade_prospective": [
            [*uv, "nutmeg", "rsi", "grade", "--exp", exp, "--mode", "prospective", *data]
            for exp in GRADED_EXPERIMENTS
        ],
        "verdict_due": [
            [*uv, "nutmeg", "rsi", "verdict", "--exp", exp, *data] for exp in GRADED_EXPERIMENTS
        ],
        "factor_propose": [
            [*uv, "nutmeg", "rsi", "weights", "propose", "--all", "--log",
             "--corpus", str(ctx.corpus_path)],
        ],
        "hyp": [
            [*uv, "python", "scripts/zucai_loop.py", "hyp", "--corpus", "v2",
             "--cut", cut, "--log"],
        ],
        "factor_search": [
            # 训练窗/测试窗按日期切：测试窗 = 最近 30 天；多重比较由脚本自报期望最大|z|
            [*uv, "python", "scripts/zucai_loop.py", "search", "--corpus", "v2",
             "--cut", _days_before(ctx.date, 30)],
        ],
        "team_strength": [
            [*uv, "python", "experiments/team_strength.py", "build",
             "--out", str(ctx.data_dir / "analytics" / "team_strength.json")],
        ],
        "scoreboard": [
            [*uv, "python", "experiments/scoreboard_parse.py",
             "--scoreboard", str(ctx.data_dir / "scoreboard.json"),
             "--out", str(ctx.root / "experiments" / "scoreboard-tallies.json")],
        ],
        "dream_compare": [
            [*uv, "nutmeg", "discovery", "compare", "--day", _days_before(ctx.date, 1), *data],
        ],
    }


def _run_step(ctx: LoopContext, name: str, commands: list[list[str]]) -> StepResult:
    started = time.monotonic()
    outputs: list[dict] = []
    failed = False
    not_due = 0
    for cmd in commands:
        proc = ctx.runner(cmd)
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        item = {"cmd": " ".join(cmd[2:]), "exit": proc.returncode, "tail": _tail(text)}
        if name == "verdict_due" and proc.returncode != 0 and any(
            marker in text for marker in NOT_DUE_MARKERS
        ):
            item["status"] = "not_due"
            not_due += 1
        elif proc.returncode != 0:
            item["status"] = "failed"
            failed = True
        else:
            item["status"] = "ok"
            item["json"] = _json_lines(proc.stdout or "")
        outputs.append(item)
    if failed:
        status = "failed"
    elif name == "verdict_due" and not_due == len(commands):
        status = "not_due"
    else:
        status = "ok"
    summary = "; ".join(f"{' '.join(o['cmd'].split(' ')[:5])}: {o['status']}" for o in outputs)
    return StepResult(
        name, status, round(time.monotonic() - started, 1), summary, {"commands": outputs}
    )


def _collect(
    steps: list[StepResult],
) -> tuple[list[dict], list[dict], list[dict], list[str], dict]:
    proposals: list[dict] = []
    grades: list[dict] = []
    verdicts: list[dict] = []
    actions: list[str] = []
    dream: dict = {}
    for step in steps:
        for item in step.detail.get("commands", []):
            if step.name == "factor_propose":
                for row in item.get("json", []):
                    proposals.append(
                        {k: row.get(k) for k in ("factor_id", "layer", "decision", "reason",
                                                  "proposed_weight_pp", "current_weight_pp")}
                        | {"strict_n": (row.get("strict") or {}).get("n"),
                           "verdict": (row.get("strict") or {}).get("verdict")}
                    )
            elif step.name == "grade_prospective":
                grades.append(
                    {"cmd": item["cmd"], "status": item["status"], "line": item["tail"]}
                )
            elif step.name == "verdict_due":
                verdicts.append(
                    {"cmd": item["cmd"], "status": item["status"], "line": item["tail"]}
                )
                if item["status"] == "ok":
                    actions.append(
                        f"判决已出：{item['tail']} → "
                        "若 survived 且 deploy_eligible，人决定 rsi deploy"
                    )
            elif step.name == "dream_compare":
                for row in item.get("json", []):
                    dream = row
                left = dream.get("standing_days_left")
                if left is not None and left <= 7:
                    actions.append(
                        f"Dream 常设批准还剩 {left} 天到期（2026-10-31）→ 续期/撤销/改窗口由 Jun 裁"
                    )
    quiet: list[str] = []
    for p in proposals:
        if p["decision"] == "propose_zero" and not p["current_weight_pp"]:
            quiet.append(p["factor_id"])  # 建议 0、现值 0：照着做什么都不会变（2026-09-30 降噪）
            continue
        if p["decision"] in ("propose_change", "propose_zero"):
            actions.append(
                f"因子 {p['factor_id']}：{p['decision']} → 建议 {p['proposed_weight_pp']}pp"
                f"（现 {p['current_weight_pp']}pp，严格 n={p['strict_n']}）；改权重只许 rsi deploy"
            )
    return proposals, grades, verdicts, actions, dream, quiet


def run_loop(ctx: LoopContext, *, force: bool = False) -> LoopReport | None:
    """跑一整圈。同日报告已存在且未 force → 返回 None（幂等）。"""
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    marker = ctx.out_dir / f"{ctx.date}.json"
    if marker.exists() and not force:
        return None
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    plan = planned_commands(ctx)
    steps: list[StepResult] = []
    for name in STEP_ORDER:
        if name in ctx.skip:
            steps.append(StepResult(name, "skipped", 0.0, "skipped by --skip"))
            continue
        steps.append(_run_step(ctx, name, plan[name]))
    proposals, grades, verdicts, actions, dream, quiet = _collect(steps)
    failed = [s.name for s in steps if s.status == "failed"]
    if failed:
        actions.append(f"步骤失败需人看：{', '.join(failed)}")
    report = LoopReport(
        date=ctx.date, started_at=started,
        finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        steps=steps, proposals=proposals, grades=grades, verdicts=verdicts,
        human_actions=actions, failed_steps=failed, dream=dream, quiet_factors=quiet,
    )
    write_report(report, ctx.out_dir)
    return report


def render_markdown(report: LoopReport) -> str:
    lines = [f"# RSI 闭环 · {report.date}", "",
             f"开始 {report.started_at} · 结束 {report.finished_at} · "
             f"失败步骤 {len(report.failed_steps)}", "", "## 待人决定", ""]
    lines += [f"- {a}" for a in report.human_actions] or [
        "- 无。所有提案为 hold / 只记录；判决未到期。"
    ]
    if report.quiet_factors:
        lines.append(
            f"- （另有 {len(report.quiet_factors)} 个因子 propose_zero 且现值已为 0，不需动作："
            f"{', '.join(report.quiet_factors)}）"
        )
    lines += ["", "## 步骤", "", "| 步 | 状态 | 秒 | 摘要 |", "| --- | --- | --- | --- |"]
    lines += [f"| {s.name} | {s.status} | {s.seconds} | {s.summary[:160]} |" for s in report.steps]
    if report.grades:
        lines += ["", "## 前瞻结账", ""] + [f"- {g['line']}" for g in report.grades]
    if report.verdicts:
        lines += ["", "## 判决", ""] + [f"- [{v['status']}] {v['line']}" for v in report.verdicts]
    if report.proposals:
        lines += ["", "## 因子提案", "", "| 因子 | 层 | 严格 n | 地板判定 | 提案 | 建议 pp |",
                  "| --- | --- | --- | --- | --- | --- |"]
        lines += [
            f"| {p['factor_id']} | {p['layer']} | {p['strict_n']} | {p['verdict']} | "
            f"{p['decision']} | {p['proposed_weight_pp']} |"
            for p in report.proposals
        ]
    if report.dream:
        lines += _dream_lines(report.dream)
    lines += ["", "⛔本报告只列事实与提案；改权重、改规则、登记实验、部署全部由人执行。", ""]
    return "\n".join(lines)


def _dream_lines(dream: dict) -> list[str]:
    reason = f"（{dream['reason']}）" if dream.get("reason") else ""
    lines = ["", "## Dream 对照", "", f"- {dream.get('day')}：{dream.get('status')}{reason}"]
    for row in dream.get("rows", []):
        lines.append(
            f"  - {row['kind']} {row.get('id') or ''} P={row.get('p_belief')} "
            f"中={row.get('hit')} 每元盈亏={row.get('pnl_per_yuan')}"
        )
    summary = dream.get("summary") or {}
    if summary:
        diff = summary.get("actual_minus_rule") or {}
        ci = diff.get("ci95") or f"n={diff.get('n')}<20，不给区间"
        mean = diff.get("mean")
        mean_text = "—" if mean is None else f"{mean:+.4f}".replace("-", "−")
        lines.append(
            f"- 累计 {summary.get('n_days')} 天；实际−规则最优 日均每元 {mean_text}（{ci}）"
        )
    return lines


def write_report(report: LoopReport, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report.date}.json"
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_markdown(report)
    (out_dir / f"{report.date}.md").write_text(md, encoding="utf-8")
    (out_dir / "latest.md").write_text(md, encoding="utf-8")
    return path
