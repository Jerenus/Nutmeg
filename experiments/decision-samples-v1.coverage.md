# decision-samples-v1 覆盖报告（构建 2026-11-13T22:16；窗口 2026-05-18→2026-11-16）

总行数 2909（竞彩 2340 / 足彩 599 / 两者 428）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2433 | 2026-05-18 | 2026-11-12 |
| 终盘/开盘价 price_closing | 1968 | 2026-05-18 | 2026-11-16 |
| 读判时 15 家价 price_read_time | 1798 | 2026-05-19 | 2026-11-13 |
| 体彩 HAD 价 price_sporttery | 2057 | 2026-05-18 | 2026-11-13 |
| 队名 home/away | 2469 | 2026-05-18 | 2026-11-16 |
| belief.market | 2460 | 2026-05-18 | 2026-11-16 |
| belief.system ≠ market | 258 | 2026-07-07 | 2026-11-07 |
| research（任一 schema） | 899 | 2026-09-10 | 2026-11-16 |
| research.anchor_side | 833 | 2026-09-15 | 2026-11-16 |
| research.anchor_integrity | 889 | 2026-09-10 | 2026-11-16 |
| research.hole（v1 旧 schema） | 167 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 732 | 2026-09-20 | 2026-11-16 |
| research.verdict（强弱天平） | 687 | 2026-09-26 | 2026-11-16 |
| research.stance_face | 726 | 2026-09-23 | 2026-11-16 |
| research.license_questions | 853 | 2026-09-12 | 2026-11-16 |
| research.death_proofs | 818 | 2026-09-16 | 2026-11-16 |
| research.upset_label（原字段） | 687 | 2026-09-26 | 2026-11-16 |
| research.upset_label（q2_route 代理） | 132 | 2026-09-16 | 2026-11-07 |
| research.rubric r1 | 641 | 2026-10-05 | 2026-11-16 |
| research.prospective=True | 812 | 2026-09-16 | 2026-11-16 |
| reader_b.kappa | 621 | 2026-10-05 | 2026-11-15 |
| intl_drift（足彩国际盘位移） | 479 | 2026-09-16 | 2026-11-16 |
| polymarket | 373 | 2026-10-09 | 2026-11-13 |
| load（损耗台账） | 546 | 2026-10-09 | 2026-11-13 |
| overrides_n | 20 | 2026-09-26 | 2026-11-11 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 462
- 2026-11: 215

research schema 分布：{'v2': 785, 'v0': 14, 'v1': 100}
足彩 m 文件对齐：直接入表 160 ／ 经竞彩副本入表（zucai_twin）191

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
