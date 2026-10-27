# decision-samples-v1 覆盖报告（构建 2026-10-27T12:06；窗口 2026-05-18→2026-10-27）

总行数 2622（竞彩 2096 / 足彩 420 / 两者 291）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2162 | 2026-05-18 | 2026-10-27 |
| 终盘/开盘价 price_closing | 1700 | 2026-05-18 | 2026-10-28 |
| 读判时 15 家价 price_read_time | 1560 | 2026-05-19 | 2026-10-26 |
| 体彩 HAD 价 price_sporttery | 1846 | 2026-05-18 | 2026-10-26 |
| 队名 home/away | 2183 | 2026-05-18 | 2026-10-28 |
| belief.market | 2175 | 2026-05-18 | 2026-10-28 |
| belief.system ≠ market | 257 | 2026-07-07 | 2026-10-24 |
| research（任一 schema） | 636 | 2026-09-10 | 2026-10-28 |
| research.anchor_side | 570 | 2026-09-15 | 2026-10-28 |
| research.anchor_integrity | 626 | 2026-09-10 | 2026-10-28 |
| research.hole（v1 旧 schema） | 167 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 469 | 2026-09-20 | 2026-10-28 |
| research.verdict（强弱天平） | 425 | 2026-09-26 | 2026-10-28 |
| research.stance_face | 463 | 2026-09-23 | 2026-10-28 |
| research.license_questions | 590 | 2026-09-12 | 2026-10-28 |
| research.death_proofs | 556 | 2026-09-16 | 2026-10-28 |
| research.upset_label（原字段） | 425 | 2026-09-26 | 2026-10-28 |
| research.upset_label（q2_route 代理） | 131 | 2026-09-16 | 2026-10-24 |
| research.rubric r1 | 379 | 2026-10-05 | 2026-10-28 |
| research.prospective=True | 549 | 2026-09-16 | 2026-10-28 |
| reader_b.kappa | 379 | 2026-10-05 | 2026-10-28 |
| intl_drift（足彩国际盘位移） | 310 | 2026-09-16 | 2026-10-28 |
| polymarket | 217 | 2026-10-09 | 2026-10-26 |
| load（损耗台账） | 304 | 2026-10-09 | 2026-10-26 |
| overrides_n | 19 | 2026-09-26 | 2026-10-17 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 390

research schema 分布：{'v2': 522, 'v0': 14, 'v1': 100}
足彩 m 文件对齐：直接入表 118 ／ 经竞彩副本入表（zucai_twin）151

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
