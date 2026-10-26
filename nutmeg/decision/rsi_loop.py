"""RSI 每日闭环运行器：把「人之前」的每一步串成一条可定时的链。

设计：`docs/superpowers/specs/2026-09-22-rsi-closed-loop-automation-design.md`。

每天一次（建议 10:45，在 09:30 赛果回填之后）：

    1. closing_backfill   补采 titan007 终盘（竞彩板 + 足彩期），幂等
    2. rubric_read        读者 B 两读（昨天、今天、最新足彩期）+ rubric report
    3. corpus_build       重建语料 v2
    4. grade_prospective  对每个有前瞻适配器的实验 `rsi grade --mode prospective`（系统身份）
    5. verdict_due        对每个实验尝试 `rsi verdict`；「未到期」是预期状态不是失败
    6. factor_propose     `rsi weights propose --all --log`（从不写权重）
    7. team_strength      客观实力指标重建（当日报告读它）
    8. scoreboard         记分牌散文 → 结构化计数
    9. commit_outputs     自动提交 experiments/ 下 loop 自己写的文件
    报告写 `.nutmeg-data/analytics/rsi-loop/<date>.json|.md` 与 `latest.md`

2026-10-04 删去三步：hyp（每天重测同一批 11 条假设、输入不变结果逐字相同）、factor_search
（输出无人读）、dream_compare（Dream 退役，规则 v3 对照改由 `gym run --policy jczq_rule_v3
--belief read` 回放）。

⛔运行器只编排、只追加：不写权重、不改 RULEBOOK / 码表 / 记分牌、不登记实验、不部署。
人类动作只出现在报告的「待人决定」清单里。每一步都是子进程，失败只影响该步并进报告；
退出码非零仅当有步骤失败（「未到期」「无提案」「n 不够」都是 0）。
同一天已有报告则跳过（`--force` 覆盖），保证 launchd 重复触发无副作用。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]

STEP_ORDER = (
    "closing_backfill",
    "rubric_read",
    "corpus_build",
    "grade_prospective",
    "verdict_due",
    "factor_propose",
    "team_strength",
    "scoreboard",
    "commit_outputs",
)
# loop 自己写的仓内文件（Jun 2026-10-01 定：每轮末尾自动提交，不再让它们长期脏着
# 把 pre-commit 的 stash 变成事故温床）。--no-verify：纯数据提交不跑测试钩子，也就不会
# 与正在编辑的会话抢 stash。rsi-samples.json 是结账步写的样本账（2026-10-05）。
LOOP_OUTPUT_PATHS = (
    "experiments/attempts.log",
    "experiments/rsi-samples.json",
    "experiments/scoreboard-tallies.json",
)
# experiments/corpus-v2.json 2026-10-19 起不进 git：每天重建的派生物（.gitignore），
# 判决的冻结证据是样本账
# 每个登记实验必须落在下面四处之一（tests/decision/test_rsi_loop.py 守卫；2026-10-19 起——
# F10/F11 09-27 登记后漏结账三天、F18 10-15 开窗后 n=0，都是「有适配器没进清单」）。
# 结账：有前瞻适配器、未退役、未结账（或是监测）的实验
GRADED_EXPERIMENTS = ("F9", "F10", "F14b", "F17", "F18", "F19", "K2", "N0")  # N0 2026-10-25
# 监测：v2 结账之后仍每天 grade（只看不判）——F9 只能测出「拨动有害」，留作有害监测
MONITORS = ("F9",)
# 不结账的登记实验与原因
UNGRADED = {
    "R0": "运维覆盖率指标（义务驱动每日深研，不判决；2026-10-19 Jun 裁）",
    "R1": "运维覆盖率指标（义务驱动每日深研，不判决；2026-10-19 Jun 裁）",
}
# 已关闭：v2 单次结账已判，或已退役（内核 rsi_verdicts / rsi_deployments 是事实源，这里是索引）
CLOSED = {
    "F1c": "退役 2026-10-02", "F2": "退役 2026-10-02", "F3": "退役 2026-10-04",
    "F4": "退役 2026-10-04",
    "F11": "v2 结账 2026-10-17 n=80 → falsified（C19 永久退休）",
    "F14": "v2 结账 2026-10-12 n=77 → falsified（由 F14b 接替）",
    "K1": "v2 结账 2026-10-08 → survived（合并 κ；由 K2 逐项接替）",
    "F5": "退役 2026-10-19（冻结窗口 26129–26140 已过、未达 n_min）",
    "F8": "退役 2026-10-19（无结账仪，被测规则 09-26 已退休）",
    "F13": "退役 2026-10-19（10-06 已定）", "F15": "退役 2026-10-19（并入 F10 分层）",
    "F16": "退役 2026-10-19（到期约 2 年）", "G1": "退役 2026-10-19（判据与主张不一致、约 430 天）",
}


def graded_experiments(root: Path) -> tuple[str, ...]:
    """固定清单 + 已签字的人群假说（experiments/registry/CR*.json，2026-10-07）
    + epoch 副本（`<exp>.v2.json`，2026-10-26 口径变更开新 epoch；沿用原实验的适配器）
    − 展示中（role=display_only：只做分析包列，不 grade）。"""
    from nutmeg.decision.rsi_prereg import base_exp_id, registry_role

    reg = Path(root) / "experiments" / "registry"
    crowd = sorted(p.stem for p in reg.glob("CR*.json"))
    epochs = sorted(p.stem for p in reg.glob("*.v[0-9]*.json")
                    if base_exp_id(p.stem) in GRADED_EXPERIMENTS)
    listed = GRADED_EXPERIMENTS + tuple(c for c in crowd if c not in CLOSED) + tuple(epochs)
    return tuple(e for e in listed if registry_role(reg, e) != "display_only")


def monitor_experiments(root: Path) -> tuple[str, ...]:
    """只 grade 不判决：固定的 F9 + 登记原件 role=monitor 的（K2，2026-10-26）。"""
    from nutmeg.decision.rsi_prereg import registry_role

    reg = Path(root) / "experiments" / "registry"
    return MONITORS + tuple(e for e in graded_experiments(root)
                            if e not in MONITORS and registry_role(reg, e) == "monitor")


# 步骤依赖（2026-10-19）：上游失败时这些步记 skipped，不拿旧语料结账、判决、出提案
DEPENDS_ON = {
    "grade_prospective": ("corpus_build",),
    "verdict_due": ("corpus_build", "grade_prospective"),
    "factor_propose": ("corpus_build",),
}

# 主指标（2026-10-01 评估换轴；2026-10-19 F14 v2 证伪后由 F14b 接替）：结构与决策——F10 热门带；
# F9（程度判断）等降为次指标：每天 8–15 场的 Brier 差在赛季内分不开噪声。
PRIMARY_EXPERIMENTS = ("F14b", "F10")
NOT_DUE_MARKERS = ("未到期", "没有 prospective 档", "重放结果进不了判决")
CONCLUDED_MARKERS = ("已结账",)


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
    quiet_factors: list[str] = field(default_factory=list)  # propose_zero 且现值已为 0：不需动作
    inbox: list[dict] = field(default_factory=list)   # 待人决定（固定 id、起始日、积压天数）
    notes: list[str] = field(default_factory=list)    # 自动生效的出口、观察型判决、只记账的提案

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


def _newest_issue_file(data_dir: Path) -> str | None:
    """最新一期（有 issue.json 的）——读者 B 要读在售期的研究，不是语料里最新结账的那期。"""
    try:
        from nutmeg.decision.day_brief import latest_issue

        zdir = Path(data_dir) / "zucai"
        return latest_issue(zdir) if zdir.exists() else None
    except Exception as exc:  # noqa: BLE001 —— 只少一条足彩补读，但要看得见
        print(f"⚠️rubric_read：最新期次解析失败，跳过足彩补读：{exc!r}", file=sys.stderr)
        return None


def _days_before(day: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) - timedelta(days=days)).isoformat()


def planned_commands(ctx: LoopContext) -> dict[str, list[list[str]]]:
    """每一步要跑的子进程命令；`rsi loop --dry-run` 打印这个。"""
    uv = ["uv", "run"]
    data = ["--data-dir", str(ctx.data_dir)]
    issue = _newest_issue_file(ctx.data_dir)
    return {
        "closing_backfill": [
            [*uv, "python", "scripts/titan007_closing_backfill.py", "--sleep", "0.3",
             "--data-dir", str(ctx.data_dir / "jczq")],
            [*uv, "python", "scripts/titan007_closing_backfill.py", "--zucai", "--sleep", "0.3",
             "--zucai-dir", str(ctx.data_dir / "zucai")],
        ],
        # 判断 rubric r1（2026-10-02）：读者 B 读当天竞彩研究 + 最新一期足彩研究，写侧车，
        # 再进语料（rubric_b 只在 at < kickoff 时入语料）。读者失败不挡后面的步。
        "rubric_read": [
            # 前一天 10:45 之后才落的研究（午后/晚场深研）在这里补读；已有侧车自动跳过
            [*uv, "nutmeg", "rubric", "read", "--day", _days_before(ctx.date, 1), *data],
            [*uv, "nutmeg", "rubric", "read", "--day", ctx.date, *data],
            *([[*uv, "nutmeg", "rubric", "read", "--issue", issue, *data]] if issue else []),
            [*uv, "nutmeg", "rubric", "report", "--day", ctx.date, *data],
        ],
        "corpus_build": [
            [*uv, "python", "experiments/corpus_build.py", "--out", str(ctx.corpus_path)],
        ],
        "grade_prospective": [
            [*uv, "nutmeg", "rsi", "grade", "--exp", exp, "--mode", "prospective", *data,
             *(["--registry-dir", str(ctx.root / "experiments" / "registry")]
               if exp.startswith("CR") else [])]
            for exp in graded_experiments(ctx.root)
        ],
        "verdict_due": [
            [*uv, "nutmeg", "rsi", "verdict", "--exp", exp, *data]
            for exp in graded_experiments(ctx.root)
            if exp not in monitor_experiments(ctx.root)      # 监测只 grade 不判决
        ],
        "factor_propose": [
            [*uv, "nutmeg", "rsi", "weights", "propose", "--all", "--log",
             "--corpus", str(ctx.corpus_path)],
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
        "commit_outputs": [
            ["bash", "-c", _commit_outputs_script(ctx)],
        ],
    }


def _commit_outputs_script(ctx: LoopContext) -> str:
    """没变化就静默退出 0；有变化只提交这几个路径（pathspec 提交，不碰别人暂存的东西）。"""
    paths = " ".join(LOOP_OUTPUT_PATHS)
    return (
        f"cd {ctx.root} && [ -z \"$(git status --porcelain -- {paths})\" ] || "
        f"git commit --no-verify -q -m 'chore(experiments): loop outputs {ctx.date}' -- {paths}"
    )


def _run_step(ctx: LoopContext, name: str, commands: list[list[str]]) -> StepResult:
    started = time.monotonic()
    outputs: list[dict] = []
    failed = False
    not_due = 0
    for cmd in commands:
        proc = ctx.runner(cmd)
        text = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        tail = _tail(text)
        exp = cmd[cmd.index("--exp") + 1] if "--exp" in cmd else ""
        if exp and not tail.startswith(exp):
            tail = f"{exp}: {tail}"           # 「rsi error: 未到期…」看不出是哪个实验（2026-10-19）
        item = {"cmd": " ".join(cmd[2:]), "exit": proc.returncode, "tail": tail}
        if name == "verdict_due" and proc.returncode != 0 and any(
            marker in text for marker in CONCLUDED_MARKERS
        ):
            item["status"] = "concluded"
            not_due += 1
        elif name == "verdict_due" and proc.returncode != 0 and any(
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


@dataclass
class Collected:
    proposals: list[dict]
    grades: list[dict]
    verdicts: list[dict]
    inbox: list[dict]       # 需要人动作的：{key, text, default, command}；update_inbox 定 id 与天数
    notes: list[str]        # 自动生效的出口、观察型判决、不可执行的提案——只记账
    quiet: list[str]        # 建议 0、现值 0：照着做什么都不会变（2026-09-30 降噪）


# 判决 → 登记出口（2026-10-19 Jun 裁 4）。跨线与到期都走 on_expired（没有结论）。
_VERDICT_EXIT = {"survived": "on_survived", "falsified": "on_falsified",
                 "inconclusive": "on_expired"}
# 要人动的出口：改规则 / 码表 / rubric 上限都走 RULEBOOK 治理；其余（展示、列标）自动生效
_HUMAN_EXITS = ("rule:", "retire_rule:", "rubric_cap:")
_RUBRIC_GOVERNANCE = "证据文档 → RUBRIC_CHANGELOG → 升版本（RULEBOOK「九」治理）"


def _registered_exits(root: Path | None, exp: str) -> dict | None:
    if root is None:
        return None
    path = Path(root) / "experiments" / "registry" / f"{exp}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("exits")
    except (OSError, ValueError):
        return None


def _route_verdict(exp: str, tail: str, root: Path | None, inbox: list[dict],
                   notes: list[str]) -> None:
    verdict = tail.split("→", 1)[-1].strip().split("（", 1)[0].strip()
    exits = _registered_exits(root, exp) or {}
    action = exits.get(_VERDICT_EXIT.get(verdict, ""), "none")
    if not exits or all(v == "none" for v in exits.values()):
        notes.append(f"判决已出（观察型，作为正样本）：{tail}")
    elif action.startswith(_HUMAN_EXITS):
        inbox.append({"key": f"exit:{exp}:{verdict}",
                      "text": f"{exp} 判 {verdict} → 登记出口 `{action}`",
                      "default": "按出口执行（改规则/码表走 RULEBOOK 治理：证据文档 + 变更记录）",
                      "command": ""})
    else:
        notes.append(f"判决已出：{tail} → 出口 `{action}` 自动生效（只改展示）")


def _route_proposal(p: dict, inbox: list[dict], notes: list[str], quiet: list[str]) -> None:
    from nutmeg.decision.rubric_items import ITEMS, cap_at

    fid, decision = p["factor_id"], p["decision"]
    proposed = float(p.get("proposed_weight_pp") or 0.0)
    if fid.startswith("rubric_") and fid[len("rubric_"):] in ITEMS:
        # rubric 逐项因子：「权重」就是该项的拨动上限（rubric_items.py），不是 factors.json 的 0
        item = fid[len("rubric_"):]
        cap = cap_at(ITEMS[item])
        lowers_to = 0.0 if decision == "propose_zero" or proposed <= 0 else proposed
        if decision not in ("propose_zero", "propose_change"):
            return
        if lowers_to < cap:
            inbox.append({"key": f"rubric_cap:{item}",
                          "text": f"rubric {item}：T13 {decision}（严格 n={p.get('strict_n')}）"
                                  f"→ 上限 {cap}pp → {lowers_to:g}",
                          "default": f"下一版 rubric 改上限（{_RUBRIC_GOVERNANCE}）",
                          "command": f"uv run nutmeg rsi weights propose --factor {fid}"})
        elif decision == "propose_zero":
            quiet.append(fid)
        else:
            notes.append(f"因子 {fid}：propose_change → {proposed:g}pp 高于现上限 {cap}pp，"
                         "不可执行（上限只许往下调）")
        return
    if decision == "propose_zero" and not p.get("current_weight_pp"):
        quiet.append(fid)
    elif decision in ("propose_change", "propose_zero"):
        notes.append(f"因子 {fid}：{decision} → {proposed:g}pp（严格 n={p.get('strict_n')}）"
                     "——因子权重无执行开关，只记账")


def _collect(steps: list[StepResult], *, root: Path | None = None) -> Collected:
    proposals: list[dict] = []
    grades: list[dict] = []
    verdicts: list[dict] = []
    inbox: list[dict] = []
    notes: list[str] = []
    quiet: list[str] = []
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
                    # 协议 v2：每个实验只判一次，判决行只会出现结账那一天
                    exp = item["cmd"].split("--exp", 1)[-1].split()[0]
                    _route_verdict(exp, item["tail"], root, inbox, notes)
    for p in proposals:
        _route_proposal(p, inbox, notes, quiet)
    return Collected(proposals, grades, verdicts, inbox, notes, quiet)


def update_inbox(out_dir: Path, date: str, items: list[dict]) -> list[dict]:
    """待人决定的收件箱（2026-10-19）：同一件事一个固定 id，记起始日与积压天数；
    当天没再出现＝已处理（记 closed_at），再出现重新起算。2026-10-19 前「待人决定」按位置编号、
    不记天数——10-06 定的修正案 13 天没人动也看不出来。"""
    from datetime import date as _date

    path = Path(out_dir) / "inbox.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    today = {item["key"] for item in items}
    out = []
    for item in items:
        entry = state.get(item["key"])
        if entry is None or entry.get("closed_at"):
            entry = {"id": "RSI-" + hashlib.sha1(item["key"].encode()).hexdigest()[:6],
                     "first_seen": date}
        entry["last_seen"] = date
        state[item["key"]] = entry
        age = (_date.fromisoformat(date) - _date.fromisoformat(entry["first_seen"])).days
        out.append({**item, "id": entry["id"], "first_seen": entry["first_seen"],
                    "age_days": age})
    for key, entry in state.items():
        if key not in today and not entry.get("closed_at"):
            entry["closed_at"] = date
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return out


def render_inbox_item(item: dict) -> str:
    line = (f"[{item['id']}·{item['age_days']}天] {item['text']} → 默认：{item['default']}")
    return line + (f"（`{item['command']}`）" if item.get("command") else "")


def run_loop(ctx: LoopContext, *, force: bool = False) -> LoopReport | None:
    """跑一整圈。同日报告已存在且未 force → 返回 None（幂等）。"""
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    marker = ctx.out_dir / f"{ctx.date}.json"
    if marker.exists() and not force and not _had_failures(marker):
        return None
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    plan = planned_commands(ctx)
    steps: list[StepResult] = []
    failed_so_far: set[str] = set()
    for name in STEP_ORDER:
        if name in ctx.skip:
            steps.append(StepResult(name, "skipped", 0.0, "skipped by --skip"))
            continue
        blocked = [dep for dep in DEPENDS_ON.get(name, ()) if dep in failed_so_far]
        if blocked:
            steps.append(StepResult(name, "skipped", 0.0,
                                    f"上游 {', '.join(blocked)} 失败，不拿旧语料跑"))
            failed_so_far.add(name)
            continue
        result = _run_step(ctx, name, plan[name])
        if result.status == "failed":
            failed_so_far.add(name)
        steps.append(result)
    collected = _collect(steps, root=ctx.root)
    inbox = update_inbox(ctx.out_dir, ctx.date, collected.inbox)
    actions = [render_inbox_item(item) for item in inbox]
    failed = [s.name for s in steps if s.status == "failed"]
    if failed:
        actions.append(f"步骤失败需人看：{', '.join(failed)}")
    report = LoopReport(
        date=ctx.date, started_at=started,
        finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        steps=steps, proposals=collected.proposals, grades=collected.grades,
        verdicts=collected.verdicts, human_actions=actions, failed_steps=failed,
        quiet_factors=collected.quiet, inbox=inbox, notes=collected.notes,
    )
    from nutmeg.decision.research_runner import research_telemetry_summary

    yesterday = (date.fromisoformat(report.date) - timedelta(days=1)).isoformat()
    write_report(report, ctx.out_dir, telemetry={
        d: research_telemetry_summary(ctx.data_dir, d) for d in (yesterday, report.date)})
    return report


def _had_failures(marker: Path) -> bool:
    """同日报告里有失败步骤 → 允许再触发重跑（2026-10-19 前同日一律跳过，失败要等明天）。"""
    try:
        return bool(json.loads(marker.read_text(encoding="utf-8")).get("failed_steps"))
    except (OSError, ValueError):
        return False


def _grade_exp(grade: dict) -> str:
    parts = str(grade.get("cmd") or "").split()
    return parts[parts.index("--exp") + 1] if "--exp" in parts else ""


def previous_quiet_factors(out_dir: Path, date: str) -> set[str] | None:
    """前一日报告里 propose_zero 且现值已为 0 的因子；没有前一日报告 → None（全列）。"""
    prev = out_dir / f"{(datetime.fromisoformat(date) - timedelta(days=1)).date()}.json"
    if not prev.exists():
        return None
    try:
        return set(json.loads(prev.read_text(encoding="utf-8")).get("quiet_factors") or [])
    except (OSError, ValueError):
        return None


def render_markdown(report: LoopReport, *, prev_quiet: set[str] | None = None,
                    telemetry: dict | None = None) -> str:
    """prev_quiet（2026-10-26）：与前一日相同的「propose_zero 且现值 0」因子折成一行，
    只有新进/退出这一类的因子才逐个列——21 个不变的零曾占日报七成篇幅。"""
    lines = [f"# RSI 闭环 · {report.date}", "",
             f"开始 {report.started_at} · 结束 {report.finished_at} · "
             f"失败步骤 {len(report.failed_steps)}", "", "## 待人决定", ""]
    lines += [f"- {a}" for a in report.human_actions] or [
        "- 无。所有提案为 hold / 只记录；判决未到期。"
    ]
    quiet = set(report.quiet_factors)
    unchanged = quiet & prev_quiet if prev_quiet is not None else set()
    if quiet:
        if prev_quiet is None:
            lines.append(
                f"- （另有 {len(quiet)} 个因子 propose_zero 且现值已为 0，不需动作："
                f"{', '.join(report.quiet_factors)}）"
            )
        else:
            parts = [f"{len(unchanged)} 个因子维持 propose_zero（现值 0），与昨日相同"]
            if quiet - unchanged:
                parts.append(f"新进 {', '.join(sorted(quiet - unchanged))}")
            if prev_quiet - quiet:
                parts.append(f"退出 {', '.join(sorted(prev_quiet - quiet))}")
            lines.append(f"- （{'；'.join(parts)}；不需动作）")
    if report.notes:
        lines += ["", "## 自动生效 / 只记账", ""] + [f"- {n}" for n in report.notes]
    lines += ["", "## 步骤", "", "| 步 | 状态 | 秒 | 摘要 |", "| --- | --- | --- | --- |"]
    lines += [f"| {s.name} | {s.status} | {s.seconds} | {s.summary[:160]} |" for s in report.steps]
    if telemetry:
        lines += ["", "## 研究成本（2026-10-26 起遥测）", ""]
        for day, t in sorted(telemetry.items()):
            if not t.get("matches"):
                lines.append(f"- {day}：无遥测行（研究在遥测接入前跑完，或当日无研究）")
                continue
            models = "/".join(f"{m} {b['matches']}" for m, b in t["by_model"].items())
            lines.append(f"- {day}：{t['matches']} 场 ${t['total_cost_usd']:.2f}，"
                         f"{t['total_duration_s']:.0f} s，{models}")
    if report.grades:
        primary = [g for g in report.grades if _grade_exp(g) in PRIMARY_EXPERIMENTS]
        secondary = [g for g in report.grades if _grade_exp(g) not in PRIMARY_EXPERIMENTS]
        lines += ["", "## 前瞻结账", "", "### 主指标（结构与决策）", ""]
        lines += [f"- {g['line']}" for g in primary] or ["- （F14b/F10 尚无结账）"]
        lines += ["", "### 次指标（程度判断）", ""] + [f"- {g['line']}" for g in secondary]
    if report.verdicts:
        lines += ["", "## 判决", ""] + [f"- [{v['status']}] {v['line']}" for v in report.verdicts]
    if report.proposals:
        lines += ["", "## 因子提案", "", "| 因子 | 层 | 严格 n | 地板判定 | 提案 | 建议 pp |",
                  "| --- | --- | --- | --- | --- | --- |"]
        lines += [
            f"| {p['factor_id']} | {p['layer']} | {p['strict_n']} | {p['verdict']} | "
            f"{p['decision']} | {p['proposed_weight_pp']} |"
            for p in report.proposals if p["factor_id"] not in unchanged
        ]
        folded = sum(p["factor_id"] in unchanged for p in report.proposals)
        if folded:
            lines.append(f"| （{folded} 个因子维持 propose_zero，现值 0，与昨日相同） | — | — | — "
                         "| propose_zero | 0.0 |")
    lines += ["", "⛔本报告只列事实与提案；改权重、改规则、登记实验、部署全部由人执行。", ""]
    return "\n".join(lines)


def write_report(report: LoopReport, out_dir: Path, *, telemetry: dict | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{report.date}.json"
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_markdown(report, prev_quiet=previous_quiet_factors(out_dir, report.date),
                         telemetry=telemetry)
    (out_dir / f"{report.date}.md").write_text(md, encoding="utf-8")
    (out_dir / "latest.md").write_text(md, encoding="utf-8")
    return path
