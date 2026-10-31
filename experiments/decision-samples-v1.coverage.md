# decision-samples-v1 覆盖报告（构建 2026-10-31T09:51；窗口 2026-05-18→2026-10-31）

总行数 2702（竞彩 2168 / 足彩 462 / 两者 325）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2218 | 2026-05-18 | 2026-10-30 |
| 终盘/开盘价 price_closing | 1748 | 2026-05-18 | 2026-11-01 |
| 读判时 15 家价 price_read_time | 1632 | 2026-05-19 | 2026-10-31 |
| 体彩 HAD 价 price_sporttery | 1913 | 2026-05-18 | 2026-10-31 |
| 队名 home/away | 2263 | 2026-05-18 | 2026-11-01 |
| belief.market | 2255 | 2026-05-18 | 2026-11-01 |
| belief.system ≠ market | 257 | 2026-07-07 | 2026-10-24 |
| research（任一 schema） | 716 | 2026-09-10 | 2026-11-01 |
| research.anchor_side | 648 | 2026-09-15 | 2026-10-31 |
| research.anchor_integrity | 706 | 2026-09-10 | 2026-11-01 |
| research.hole（v1 旧 schema） | 169 | 2026-09-10 | 2026-11-01 |
| research.hole（v2 side/unit/priced） | 547 | 2026-09-20 | 2026-10-31 |
| research.verdict（强弱天平） | 503 | 2026-09-26 | 2026-10-31 |
| research.stance_face | 541 | 2026-09-23 | 2026-10-31 |
| research.license_questions | 668 | 2026-09-12 | 2026-10-31 |
| research.death_proofs | 634 | 2026-09-16 | 2026-10-31 |
| research.upset_label（原字段） | 503 | 2026-09-26 | 2026-10-31 |
| research.upset_label（q2_route 代理） | 131 | 2026-09-16 | 2026-10-24 |
| research.rubric r1 | 457 | 2026-10-05 | 2026-10-31 |
| research.prospective=True | 627 | 2026-09-16 | 2026-10-31 |
| reader_b.kappa | 457 | 2026-10-05 | 2026-10-31 |
| intl_drift（足彩国际盘位移） | 349 | 2026-09-16 | 2026-11-01 |
| polymarket | 262 | 2026-10-09 | 2026-10-31 |
| load（损耗台账） | 376 | 2026-10-09 | 2026-10-31 |
| overrides_n | 19 | 2026-09-26 | 2026-10-17 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 468
- 2026-11: 2

research schema 分布：{'v2': 602, 'v0': 14, 'v1': 100}
足彩 m 文件对齐：直接入表 124 ／ 经竞彩副本入表（zucai_twin）161

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
