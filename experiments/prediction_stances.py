#!/usr/bin/env python
"""预测账 → 单场结构表态（2026-10-06，一次性；F14 的窗前训练养料，永不进判决）。

内核 `predictions` 里 08-27 → 09-26 登记的 203 条可证伪预测（10-06 全部结账），有一部分
就是「某场 90' 开出哪个/哪两个面」的单场承诺——和 F14 的表态面集合同形，而且登记时间是
内核写下的、不可改的时间戳，早于开球即算 proven。

`TRANSCRIPTION` 是主循环 10-06 逐条读主张后的转录（判断在这里，脚本只搬运）：
  · 只收单场、90 分钟胜平负的面集主张：「X 胜」「X 不败 / 不胜」「不开出 Y」「开出 A/B」；
  · 进球轴（进球 / 净胜 / 总进球）、多场合取或计数、条件句、奖金、合取了进球轴的单场主张都不收；
  · 同一场有多条面集主张时只留最早登记的一条（同一时刻按 rx 里的先后）——26124 场2 先登记
    「莱比锡非主胜」、八小时后又登记「汉堡不赢」，只收前者；
  · 26131 的 14 条是 Jun 09-20 裁定「每场必须落单选或排除画像」下的**强制**表态，单独标出。
脚本做的事：按前缀对号内核预测、取登记时刻、取期次文件里的开球时刻、判 proven
（登记时刻 < 开球），写 `experiments/prediction-stances.json`。

用法：python experiments/prediction_stances.py [--db …] [--zucai-dir …] [--out …]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CST = timezone(timedelta(hours=8))
FORCED_ISSUES = {"26131"}

# 预测 id 前缀（prediction- 之后 6 位）→ (期, 场号, 面集)。面：3 主胜 / 1 平 / 0 客胜。
TRANSCRIPTION: dict[str, tuple[str, int, str]] = {
    # 26111
    "ec4520": ("26111", 12, "31"),   # 皇马不至于输球
    "d1b5de": ("26111", 14, "3"),    # 巴萨 90' 胜
    # 26113
    "eb8560": ("26113", 9, "3"),     # 多特胜
    "3c97fe": ("26113", 11, "3"),    # 尤文胜
    # 26114
    "f3ca11": ("26114", 7, "0"),     # 国米客胜
    "988ac9": ("26114", 9, "3"),     # 皇马胜
    "174e35": ("26114", 4, "31"),    # 弗赖堡不败
    "99020c": ("26114", 1, "30"),    # 利兹 主或客、不开平
    "7820c7": ("26114", 6, "31"),    # 那不勒斯-科莫 主或平
    # 26115
    "28faf1": ("26115", 2, "0"),     # 罗马客胜
    "916ed2": ("26115", 6, "3"),     # 本菲卡主胜
    "6f1387": ("26115", 7, "0"),     # 吉马良客胜（r3 全包所盖的面）
    "98e0e5": ("26115", 1, "10"),    # 维拉不胜
    # 26116
    "e768e7": ("26116", 6, "31"),    # 斯托克-诺维奇 客胜模态面不开出
    "ad7689": ("26116", 7, "3"),     # 西布罗模态面主胜开出
    # 26117
    "aa6475": ("26117", 11, "3"),    # 波尔图主胜
    "729b97": ("26117", 9, "1"),     # C12 带开平
    # 26118
    "d1ee65": ("26118", 10, "0"),    # 拜仁客胜
    "9c5dd2": ("26118", 12, "31"),   # 罗马 31 的被排客面不开
    # 26119
    "8061f2": ("26119", 9, "0"),     # 巴萨客胜
    # 26120
    "d37d3a": ("26120", 11, "31"),   # 雷克斯汉姆不败
    "d1dc8d": ("26120", 2, "31"),    # 布鲁日不败
    "20390b": ("26120", 9, "31"),    # 南安普顿不败
    "799d84": ("26120", 13, "10"),   # 桑德兰不胜
    "0f2d34": ("26120", 10, "31"),   # 普雷斯顿（客）不胜
    "7dc278": ("26120", 12, "10"),   # 西汉姆（客）不败
    "ff5c7b": ("26120", 6, "10"),    # 国米（客）拿分
    # 26121
    "ac65da": ("26121", 1, "3"),     # 巴萨胜
    "060c21": ("26121", 5, "3"),     # 巴黎胜
    "5dd3f7": ("26121", 8, "3"),     # 拜仁胜
    "21e6e9": ("26121", 13, "0"),    # 本菲卡（客）胜
    "ac1af4": ("26121", 2, "31"),    # 斯图加特不败
    "624230": ("26121", 10, "31"),   # 曼联不败
    "cc57a6": ("26121", 11, "1"),    # 斯拉维亚-朗斯 平
    "0adf59": ("26121", 12, "10"),   # 切尔西不胜
    "34f699": ("26121", 6, "1"),     # 竞技-加拉 平
    "b12a0d": ("26121", 14, "1"),    # 阿马多拉-布拉加 平
    "b45132": ("26121", 3, "10"),    # 利物浦不胜
    # 26122
    "3ece1a": ("26122", 13, "3"),    # AZ 胜
    "2f03aa": ("26122", 2, "10"),    # 柏林联不胜
    "874371": ("26122", 5, "31"),    # 佛罗伦萨（客）不胜
    "dc7454": ("26122", 12, "10"),   # 罗德兹不胜
    "d4f5dc": ("26122", 4, "31"),    # 汉诺威客胜（模态面）不开出
    # 26123
    "811247": ("26123", 14, "3"),    # 皇马胜
    "577c5c": ("26123", 9, "3"),     # 多特胜
    "253f4b": ("26123", 13, "1"),    # 拉齐奥-AC米兰 开平
    # 26124
    "e96a2c": ("26124", 7, "0"),     # 巴萨（客）胜
    "4f375c": ("26124", 3, "31"),    # 埃弗斯贝格取分
    "f84edc": ("26124", 2, "10"),    # 莱比锡非主胜
    "f15ee5": ("26124", 14, "10"),   # 葡体（客）不败
    "c6396d": ("26124", 10, "31"),   # 里尔不败
    "545334": ("26124", 5, "10"),    # 那不勒斯非主胜
    "3b9313": ("26124", 12, "10"),   # 巴黎（客）不败
    "57d0eb": ("26124", 6, "31"),    # 尤文（客）不赢
    "f8ee0c": ("26124", 11, "31"),   # 朗斯（客）不赢
    # 26126
    "fff7a3": ("26126", 4, "3"),     # 利雅得新月主胜
    "d8265b": ("26126", 13, "10"),   # 阿贾克斯不胜
    "479e5c": ("26126", 10, "10"),   # 巴列卡诺不胜
    "6a6155": ("26126", 12, "0"),    # 皇马（客）胜
    "52bf65": ("26126", 11, "3"),    # 阿拉维斯胜（竞彩渠道）
    "e303ca": ("26126", 3, "31"),    # 利雅得胜利（客）不赢（竞彩渠道）
    # 26131（强制表态）
    "691dea": ("26131", 1, "10"), "ebd8a3": ("26131", 2, "3"), "4804b2": ("26131", 3, "3"),
    "aa7f36": ("26131", 4, "10"), "7e4b6c": ("26131", 5, "31"), "e6b36a": ("26131", 6, "3"),
    "68eafe": ("26131", 7, "0"), "ca33d6": ("26131", 8, "1"), "ba723d": ("26131", 9, "1"),
    "f018bb": ("26131", 10, "3"), "a467e6": ("26131", 11, "31"), "729a4c": ("26131", 12, "0"),
    "9f5ab0": ("26131", 13, "1"), "0b9d1c": ("26131", 14, "0"),
    # 26132
    "ef6fb2": ("26132", 5, "3"),     # 葡萄牙主胜
    "f013e8": ("26132", 1, "31"),    # 中国 不开出客胜
    "023130": ("26132", 13, "10"),   # 土耳其-法国 不开出主胜
    "3c0467": ("26132", 12, "31"),   # 瑞典-罗马尼亚 不开出客胜
    "52110b": ("26132", 2, "0"),     # 巴西（客）胜
    "47dbf8": ("26132", 9, "3"),     # 格鲁吉亚胜
    "93a7c8": ("26132", 11, "3"),    # 波兰胜
    "1ed0eb": ("26132", 14, "3"),    # 黑山胜
    "5e46fc": ("26132", 6, "1"),     # 塞尔维亚-希腊 开平
    "8ef38a": ("26132", 8, "30"),    # 亚美尼亚-拉脱维亚 主/客
    # 26133（任九与胜负彩同一时刻登记，同场取 rx 里在先的任九表态）
    "068320": ("26133", 4, "3"), "f85c9c": ("26133", 8, "01"), "212947": ("26133", 9, "3"),
    "4624ea": ("26133", 10, "31"), "5a0b95": ("26133", 11, "01"), "936a7b": ("26133", 13, "3"),
    "4d7bb3": ("26133", 1, "30"), "ce3d1d": ("26133", 3, "31"), "cff84a": ("26133", 5, "31"),
    "1a92fc": ("26133", 6, "10"), "758c50": ("26133", 7, "30"), "802b12": ("26133", 12, "3"),
    "d84080": ("26133", 14, "30"),
}


def _kickoffs(zdir: str, issue: str) -> dict[int, str]:
    with open(os.path.join(zdir, f"{issue}-issue.json"), encoding="utf-8") as f:
        return {int(m["match_no"]): m["kickoff_bj"] for m in json.load(f)["matches"]}


def build(db: str, zdir: str) -> list[dict]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    preds = con.execute(
        "select prediction_id, subject_id, claim, registered_at from predictions").fetchall()
    out, seen = [], set()
    kickoffs: dict[str, dict[int, str]] = {}
    for prefix, (issue, match_no, faces) in TRANSCRIPTION.items():
        hits = [p for p in preds if p[0].startswith(f"prediction-{prefix}")]
        if len(hits) != 1 or hits[0][1] != issue:
            raise SystemExit(f"{prefix}: 对号失败 {hits}")
        if (issue, match_no) in seen:
            raise SystemExit(f"{issue}-{match_no}: 同场转录了两条")
        seen.add((issue, match_no))
        pid, _, claim, registered_at = hits[0]
        if issue not in kickoffs:
            kickoffs[issue] = _kickoffs(zdir, issue)
        kickoff = kickoffs[issue][match_no]
        reg = datetime.fromisoformat(registered_at)
        ko = datetime.strptime(kickoff, "%Y-%m-%d %H:%M").replace(tzinfo=CST)
        out.append({"prediction_id": pid, "key": f"{issue}-{match_no}", "issue": issue,
                    "match_no": match_no, "faces": faces,
                    "structure": "single" if len(faces) == 1 else "double",
                    "registered_at": registered_at, "kickoff_bj": kickoff,
                    "proven": reg < ko, "forced": issue in FORCED_ISSUES, "claim": claim})
    return sorted(out, key=lambda r: (r["issue"], r["match_no"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, ".nutmeg-data", "ontology", "ontology.db"))
    ap.add_argument("--zucai-dir", default=os.path.join(ROOT, ".nutmeg-data", "zucai"))
    ap.add_argument("--out", default=os.path.join(ROOT, "experiments", "prediction-stances.json"))
    args = ap.parse_args()
    rows = build(args.db, args.zucai_dir)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"source": "kernel predictions（2026-10-06 全部结账）× 主循环转录",
                   "n": len(rows), "rows": rows}, f, ensure_ascii=False, indent=1)
    proven = sum(r["proven"] for r in rows)
    print(f"{len(rows)} 条单场表态（proven {proven}，强制 {sum(r['forced'] for r in rows)}）"
          f" → {args.out}")


if __name__ == "__main__":
    main()
