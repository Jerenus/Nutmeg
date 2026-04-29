from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nutmeg.services.psychology.llm import LLMCompleter, LLMCompletionError
from nutmeg.services.psychology.schemas import InspirationNote, InspirationTags

LEAN_PSYCHOLOGY_KW = ("反着来", "反向", "心理", "直觉")
LEAN_DATA_KW = ("数据", "算法", "正常")
CONVICTION_HIGH_KW = ("必", "锁", "强")
CONVICTION_LOW_KW = ("微", "小", "或许")
FOCUS_TABLE = {
    "tournament_stage": ("淘汰", "决赛", "首回合", "次回合", "大赛"),
    "contrarian_narrative": ("舆论", "媒体", "热搜"),
    "personal_narrative": ("复仇", "首秀", "末战", "回归", "里程碑"),
    "reflexive_tactic": ("战术", "变招", "二阶", "压迫"),
}
FORCE_PSY_KW = ("今天必须", "强制心理", "心理强制")
FORCE_DATA_KW = ("强制数据", "数据强制")
SYSTEM_PROMPT = 'Extract inspiration JSON tags.'


@dataclass(slots=True)
class InspirationParser:
    llm: LLMCompleter

    def parse(self, text: str, *, date: str) -> InspirationNote:
        timestamp = datetime.now(tz=timezone.utc).isoformat()
        try:
            payload = json.loads(self.llm.complete(system=SYSTEM_PROMPT, user=text))
            tags = InspirationTags(str(payload.get("lean", "neutral")), str(payload.get("conviction", "medium")), list(payload.get("focus") or []), bool(payload.get("force_psychology", False)), bool(payload.get("force_data", False)))  # type: ignore[arg-type]
            return InspirationNote(date, text, tags, "llm", timestamp)
        except (LLMCompletionError, ValueError, TypeError, json.JSONDecodeError):
            return InspirationNote(date, text, self._regex_parse(text), "regex_fallback", timestamp)

    def _regex_parse(self, text: str) -> InspirationTags:
        lean = "neutral"
        if any(k in text for k in LEAN_PSYCHOLOGY_KW):
            lean = "psychology"
        elif any(k in text for k in LEAN_DATA_KW):
            lean = "data"
        conviction = "medium"
        if any(k in text for k in CONVICTION_HIGH_KW):
            conviction = "high"
        elif any(k in text for k in CONVICTION_LOW_KW):
            conviction = "low"
        focus = [provider for provider, kws in FOCUS_TABLE.items() if any(k in text for k in kws)]
        return InspirationTags(lean=lean, conviction=conviction, focus=focus, force_psychology=any(k in text for k in FORCE_PSY_KW), force_data=any(k in text for k in FORCE_DATA_KW))  # type: ignore[arg-type]


@dataclass(slots=True)
class InspirationStore:
    base_dir: Path

    def _dir(self, date: str) -> Path:
        return self.base_dir / date

    def write_raw(self, *, date: str, text: str) -> Path:
        path = self._dir(date) / "raw.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def write_parsed(self, *, date: str, tags: InspirationTags, raw_text: str, parse_method: str, timestamp: str) -> Path:
        path = self._dir(date) / "parsed.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": date, "raw_text": raw_text, "parsed_tags": {"lean": tags.lean, "conviction": tags.conviction, "focus": tags.focus, "force_psychology": tags.force_psychology, "force_data": tags.force_data}, "parse_method": parse_method, "timestamp": timestamp}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read(self, *, date: str) -> InspirationNote | None:
        path = self._dir(date) / "parsed.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        t = data["parsed_tags"]
        return InspirationNote(data["date"], data["raw_text"], InspirationTags(t["lean"], t["conviction"], list(t["focus"]), bool(t["force_psychology"]), bool(t["force_data"])), data["parse_method"], data["timestamp"])
