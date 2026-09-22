"""Single append point for `experiments/attempts.log` (multiple-comparison ledger).

Every replay-side experiment that reaches a conclusion goes through `log_attempt`
so the ledger keeps one line format::

    ts | experiment | params | result | conclusion

Pipes and newlines inside fields are flattened so a line stays one line. The file is
append-only; nothing here reads or rewrites earlier entries.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS = ROOT / "experiments" / "attempts.log"
HEADER = "# 闭环尝试记账（多重比较修正用）\n# ts | 实验 | 参数 | 样本外BSS | 结论\n"


def _flat(value: object) -> str:
    text = str(value if value is not None else "")
    return " ".join(text.replace("|", "/").split())


def format_attempt(
    experiment: str,
    params: object,
    result: object,
    conclusion: object,
    *,
    ts: _dt.datetime | None = None,
) -> str:
    stamp = (ts or _dt.datetime.now()).isoformat(timespec="minutes")
    fields = (stamp, _flat(experiment), _flat(params), _flat(result), _flat(conclusion))
    return " | ".join(fields) + "\n"


def log_attempt(
    experiment: str,
    params: object,
    result: object,
    conclusion: object,
    *,
    path: Path | str = ATTEMPTS,
    ts: _dt.datetime | None = None,
) -> str:
    """Append one line and return it. Creates the file with the header if absent."""
    target = Path(path)
    line = format_attempt(experiment, params, result, conclusion, ts=ts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size == 0:
        target.write_text(HEADER, encoding="utf-8")
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return line
