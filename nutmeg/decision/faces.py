"""胜平负三面：键名 ↔ 竞彩码 ↔ 中文标签的唯一定义（2026-10-08 第二轮瘦身 B5）。

此前 22 个模块各写一份映射（28 份）。显示用的中文各处并不一样，**以现役显示为准**：
票面 / 审票写「主胜 / 平 / 客胜」（`RESULT_ZH`），信号面板写「主 / 平 / 客」（`SHORT_ZH`），
人群模型写「平局」（`crowd_model` 自留标签，冻结文件不动）。
"""
from __future__ import annotations

FACES = ("home", "draw", "away")
CODE_OF = {"home": "3", "draw": "1", "away": "0"}
"""面 → 竞彩胜平负码。"""
FACE_OF = {"3": "home", "1": "draw", "0": "away"}
"""竞彩胜平负码 → 面。"""
SHORT_ZH = {"home": "主", "draw": "平", "away": "客"}
RESULT_ZH = {"3": "主胜", "1": "平", "0": "客胜"}
