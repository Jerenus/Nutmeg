"""定时 `claude -p` 的模型分档。

读 settings（.env / NUTMEG_MODEL_*）；空串＝不传 --model，继承 Claude Code 默认。"""
from __future__ import annotations

INHERIT = "default"


def model_argv(name: str | None) -> list[str]:
    name = (name or "").strip()
    return ["--model", name] if name else []


def model_label(name: str | None) -> str:
    name = (name or "").strip()
    return name or INHERIT


def logic_model() -> str:
    from nutmeg.config.settings import get_settings

    return get_settings().model_logic


def research_model() -> str:
    from nutmeg.config.settings import get_settings

    return get_settings().model_research
