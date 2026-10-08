"""读 JSON 文件的唯一宽容实现（2026-10-08 第二轮瘦身 B5；此前十余个模块各写一个 `_read_json`）。"""
from __future__ import annotations

import json
from pathlib import Path


def read_json(path, default=None):
    """JSON 文件 → 对象；缺失 / 读不了 / 不是合法 JSON → `default`（不抛）。

    需要把缺失报出来的地方（当日报告的「缺席的输入」）自己判断，不用这个。"""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
