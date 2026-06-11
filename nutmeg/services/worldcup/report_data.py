"""PDF 日报数据合成(spec §5)— 从落盘文件回放,不重新决策。

「今日主线」叙事:模板 + 当日信号确定性拼装,非 LLM 生成(spec §5.3)。
风格对齐「翻面读法」:不利信号翻面读成今晚盘面共识(jczq_advice_style)。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from nutmeg.services.jczq_judgment_answers import (
    JudgmentAnswers,
    load_judgment_answers,
)

from .sim import SimOutput, load_sim

logger = logging.getLogger(__name__)

# 信号 → 模板的优先级:淘汰赛 > 概率大迁移 > 满盘热门 > 冷门夜 > 薄盘 > 默认
NARRATIVE_TEMPLATES: dict[str, str] = {
    "knockout": (
        "今天是淘汰赛日:竞彩盘口只算 90 分钟,平局是真实可投结果——市场在生死战里"
        "天然低估僵局,这正是今晚盘面共识给出的落足点。引擎票面已按此口径出腿,"
        "{n_matches} 场在售,别用「必分胜负」的直觉去改它。"
    ),
    "prob_shift": (
        "昨夜赛果把夺冠版图挪动了 {max_delta_pp:.1f} 个百分点——这不是噪声,是淘汰"
        "概率在重新定价。今天 {n_matches} 场在售,翻面读:市场还没完全消化的方向,"
        "就是引擎 §E 变动榜里最大的那几行。"
    ),
    "hot_board": (
        "满盘热门日({hard_hot}/{n_matches} 场短赔):正路打出是市场共识,真正的"
        "信息在「热门用什么比分赢」。A 档稳健底仓今天结构最顺,B/D/E 继续纯娱乐"
        "定性,别给抽水盘套正 EV 叙事。"
    ),
    "cold_board": (
        "今晚无明显热门,{n_matches} 场里 coinflip 居多——市场自己也举棋不定。"
        "翻面读:这是方差的主场,空仓或最小注娱乐都是合法答案,引擎没出的票别手痒补。"
    ),
    "thin_board": (
        "薄盘日(仅 {n_matches} 场在售):样本越薄,单场权重越大,越要按引擎纪律走。"
        "世界杯赛程还长,§E 的概率榜比今天的薄盘更值得看。"
    ),
    "default": (
        "今天 {n_matches} 场在售,盘面没有压倒性主题。照 §A 票面执行,裁量只动 §C,"
        "夺冠概率变动见 §E——按纪律走完,明天复盘见。"
    ),
}


def pick_narrative(signals: dict) -> str:
    """确定性选模板填槽(spec §5.3)。signals 键:
    n_matches / hard_hot / stage(group|r32|r16|qf|sf|final)/ max_delta_pp。"""
    n = signals.get("n_matches", 0)
    key = "default"
    if signals.get("stage", "group") != "group":
        key = "knockout"
    elif signals.get("max_delta_pp", 0.0) >= 5.0:
        key = "prob_shift"
    elif n > 0 and signals.get("hard_hot", 0) / n >= 0.5:
        key = "hot_board"
    elif n >= 4 and signals.get("hard_hot", 0) == 0:
        key = "cold_board"
    elif 0 < n <= 2:
        key = "thin_board"
    return NARRATIVE_TEMPLATES[key].format(**{
        "n_matches": n,
        "hard_hot": signals.get("hard_hot", 0),
        "max_delta_pp": signals.get("max_delta_pp", 0.0),
    })


@dataclass(slots=True)
class DailyReport:
    run_date: str
    stage_label: str
    narrative: str
    packet_md: str | None          # today-packet.md 原文(票面/§C 从这里取段)
    answers: JudgmentAnswers | None
    sim: SimOutput | None
    sim_prev: SimOutput | None
    sim_history: list[SimOutput] = field(default_factory=list)
    review: dict | None = None     # 昨日 tiered-plan-review.json
    calibration_note: str | None = None


def build_daily_report(run_date: str, output_dir: Path) -> DailyReport:
    """全部从落盘文件合成 — 缺哪节哪节标注,绝不重新决策(spec §5.1)。"""
    daily = output_dir / "daily" / run_date
    wc_dir = output_dir / "wc2026"

    packet_md = None
    packet_path = daily / "today-packet.md"
    if packet_path.exists():
        packet_md = packet_path.read_text(encoding="utf-8")

    sim = load_sim(wc_dir / f"sim-{run_date}.json")
    prev_day = (date.fromisoformat(run_date) - timedelta(days=1)).isoformat()
    sim_prev = load_sim(wc_dir / f"sim-{prev_day}.json")
    history = sorted(
        (load_sim(p) for p in wc_dir.glob("sim-*.json")),
        key=lambda s: s.run_date,
    ) if wc_dir.exists() else []

    review = None
    review_path = output_dir / "daily" / prev_day / "tiered-plan-review.json"
    if review_path.exists():
        try:
            review = json.loads(review_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("昨日 review 损坏,战报节降级", exc_info=True)

    from .calibration import calibration_alert, load_entries

    note = calibration_alert(load_entries(wc_dir / "calibration-log.jsonl"))

    signals = _signals_from(packet_md, sim, sim_prev)
    stage = _stage_label_for(run_date)
    return DailyReport(
        run_date=run_date, stage_label=stage,
        narrative=pick_narrative(signals), packet_md=packet_md,
        answers=load_judgment_answers(daily), sim=sim, sim_prev=sim_prev,
        sim_history=[s for s in history if s], review=review,
        calibration_note=note,
    )


def _signals_from(packet_md, sim, sim_prev) -> dict:
    # B1 行形如「| 周四001 | 墨西哥 vs 南非 | 1.26 | 硬热(短赔) |」。
    # §D 雷达表的行同样以「| 周」开头 — 必须只数 B1 节内,否则重复计数。
    n = hard = 0
    if packet_md:
        in_b1 = False
        for line in packet_md.splitlines():
            if line.startswith("#"):
                in_b1 = line.startswith("### B1")
                continue
            if not in_b1:
                continue
            if line.startswith("| 周") or line.startswith("|周"):
                n += 1
                if "硬热" in line:
                    hard += 1
    max_delta = 0.0
    if sim and sim_prev:
        for t, p in sim.probs.items():
            if t in sim_prev.probs:
                max_delta = max(
                    max_delta,
                    abs(p["champion"] - sim_prev.probs[t]["champion"]) * 100,
                )
    return {"n_matches": n, "hard_hot": hard,
            "stage": _stage_key_for(sim.run_date if sim else "2026-06-12"),
            "max_delta_pp": max_delta}


def _stage_key_for(run_date: str) -> str:
    try:
        from .tournament import load_tournament

        t = load_tournament()
        todays = {m.stage for m in t.matches if m.date_utc == run_date}
        for s in ("final", "sf", "qf", "r16", "r32"):
            if s in todays:
                return s
    except Exception:  # noqa: BLE001
        pass
    return "group"


def _stage_label_for(run_date: str) -> str:
    key = _stage_key_for(run_date)
    return {"group": "小组赛", "r32": "32 强淘汰赛", "r16": "16 强淘汰赛",
            "qf": "1/4 决赛", "sf": "半决赛", "final": "决赛"}[key]
