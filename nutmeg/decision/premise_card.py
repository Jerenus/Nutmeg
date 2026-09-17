"""前提卡 —— 派研究之前，把「我记得的」换成「store 里有的」。

**出生事故 26128（一期六条）。** 我给 14 个深研 agent 的任务提示里塞了自己的前提，
其中六条是错的：曼城主帅写成瓜迪奥拉（实为 Maresca）、伯恩茅斯写成 Iraola
（实为 Marco Rose）、贝西克塔斯写成 van Bronckhorst（实为 Italiano）、
桑德兰"刚升班"、考文垂"在英冠"、格拉茨"卫冕冠军"。agent 逐条纠正了我，
**但纠正只活在那一次对话里**——store 的 `profile_notes` 一个字都没变，
下一期我还会给出同样的错前提。

同时另一个方向也漏：我照着记忆写前提，等于给 agent 一个**带锚的起点**，
而反偏置约束要求它们独立取证。写错的前提比不给前提更贵。

本模块两件事，**都不产生判断**：

1. `build_card` —— 从 issue + store 画像生成每场的前提卡。
   ⛔**只写 store 里有的**；store 没有的字段一律写「本卡未提供」而不是让我填空。
   卡上每一条都带 `tier` 与 `as_of`，agent 的任务因此从「从零查」变成
   「**核实并纠正这张卡**」。
2. `collect_corrections` —— 把 agent 在研究 JSON 里写的 `premise_corrections`
   收上来，交给 `decision-profile --add-note` 回写 store。纠正不回写＝白纠正。
"""
from __future__ import annotations

from dataclasses import dataclass

UNKNOWN = "本卡未提供（store 无记录）——请独立取证，不要替我补全"
"""⛔这句话是本模块的要害。上一版的等价物是我凭记忆填的一句话，六条里错了六条。"""

CARD_FIELDS = (
    ("coach", "主帅"),
    ("league_position", "联赛位次"),
    ("european_path", "欧战路径"),
    ("squad_change", "阵容变动"),
    ("recent_form", "近况"),
)


@dataclass(frozen=True)
class PremiseLine:
    field: str
    label: str
    value: str
    tier: str
    as_of: str

    @property
    def known(self) -> bool:
        return self.value != UNKNOWN

    def render(self) -> str:
        if not self.known:
            return f"  - {self.label}：{UNKNOWN}"
        return f"  - {self.label}：{self.value}  ［{self.tier}｜{self.as_of}］"


@dataclass(frozen=True)
class PremiseCard:
    match_no: int
    name: str
    competition: str
    kickoff: str
    fair: dict[str, float]
    home_lines: list[PremiseLine]
    away_lines: list[PremiseLine]

    @property
    def unknown_count(self) -> int:
        return sum(
            1 for line in (*self.home_lines, *self.away_lines) if not line.known
        )

    def render(self) -> str:
        fair = "／".join(
            f"{k}{self.fair.get(k, 0) * 100:.1f}" for k in ("home", "draw", "away")
        )
        out = [
            f"## 场{self.match_no} {self.name}",
            f"  赛事 {self.competition or '未提供'}｜开球 {self.kickoff or '未提供'}"
            f"｜去水 {fair}",
            "  主队：",
            *[line.render() for line in self.home_lines],
            "  客队：",
            *[line.render() for line in self.away_lines],
        ]
        return "\n".join(out)


def _lines_from_notes(notes: list[dict] | None) -> list[PremiseLine]:
    """store 的 `profile_notes` → 前提行。**没有的就是没有**，不推断、不补默认值。"""
    by_key: dict[str, dict] = {}
    for note in notes or []:
        if not isinstance(note, dict):
            continue
        key = str(note.get("key", "") or "")
        current = by_key.get(key)
        if current is None or str(note.get("at", "")) >= str(current.get("at", "")):
            by_key[key] = note
    lines: list[PremiseLine] = []
    for field, label in CARD_FIELDS:
        note = by_key.get(field)
        if note is None:
            lines.append(PremiseLine(field, label, UNKNOWN, "", ""))
            continue
        lines.append(
            PremiseLine(
                field,
                label,
                str(note.get("note", "") or "").strip() or UNKNOWN,
                str(note.get("evidence", "") or "无出处"),
                str(note.get("at", "") or "无日期"),
            )
        )
    return lines


def build_card(
    match: dict,
    *,
    match_no: int,
    fair: dict[str, float],
    profiles: dict[str, list[dict]],
) -> PremiseCard:
    """一场的前提卡。`profiles` = {队名: profile_notes}。"""
    home = str(match.get("home") or match.get("home_team") or "")
    away = str(match.get("away") or match.get("away_team") or "")
    return PremiseCard(
        match_no=match_no,
        name=f"{home}-{away}",
        competition=str(match.get("competition") or match.get("league") or ""),
        kickoff=str(match.get("kickoff") or match.get("match_time") or ""),
        fair=fair,
        home_lines=_lines_from_notes(profiles.get(home)),
        away_lines=_lines_from_notes(profiles.get(away)),
    )


def format_cards(cards: list[PremiseCard], *, issue: str) -> str:
    known = sum(
        1
        for card in cards
        for line in (*card.home_lines, *card.away_lines)
        if line.known
    )
    total = sum(
        len(card.home_lines) + len(card.away_lines) for card in cards
    )
    return "\n\n".join([
        f"# 前提卡（{issue}） —— {len(cards)} 场，store 覆盖 {known}/{total} 条",
        "> 派研究时把对应场次的卡原样贴进任务提示。**卡上没有的，我不许替 agent 补。**\n"
        "> agent 的任务是**核实并纠正这张卡**，纠正写进研究 JSON 的 "
        "`premise_corrections`（字段见 RUNBOOK B3b），\n"
        "> 再由 `zucai-premise-corrections --apply` 回写 store —— 纠正不回写＝白纠正。\n"
        "> 出生事故 26128：我凭记忆给的前提一期错六条（主帅错三个），"
        "agent 逐条纠正而 store 一个字没变。",
        *[card.render() for card in cards],
    ])


@dataclass(frozen=True)
class PremiseCorrection:
    match_no: int
    subject: str
    subject_type: str      # team | league
    field: str
    given: str
    correct: str
    evidence: str
    as_of: str

    def render(self) -> str:
        given = f"我给的「{self.given}」→ " if self.given else ""
        return (
            f"  场{self.match_no} {self.subject}［{self.field}］"
            f"{given}实为「{self.correct}」  ［{self.evidence}｜{self.as_of}］"
        )


def collect_corrections(research: dict) -> list[PremiseCorrection]:
    """读研究 JSON 的 `premise_corrections`。缺 evidence 的纠正**不收**——
    纠正也是证据，无出处的纠正只是换一个人的记忆。"""
    raw = research.get("premise_corrections") or []
    if not isinstance(raw, list):
        return []
    match_no = int(research.get("match_no") or 0)
    out: list[PremiseCorrection] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        correct = str(item.get("correct", "") or "").strip()
        evidence = str(item.get("evidence", "") or "").strip()
        subject = str(item.get("subject", "") or "").strip()
        if not (correct and evidence and subject):
            continue
        out.append(
            PremiseCorrection(
                match_no=match_no,
                subject=subject,
                subject_type=str(item.get("subject_type", "team") or "team"),
                field=str(item.get("field", "") or "note"),
                given=str(item.get("given", "") or "").strip(),
                correct=correct,
                evidence=evidence,
                as_of=str(item.get("as_of", "") or "").strip(),
            )
        )
    return out
