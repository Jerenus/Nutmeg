# decision-samples-v1 覆盖报告（构建 2026-11-14T09:02；窗口 2026-05-18→2026-11-16）

总行数 2918（竞彩 2346 / 足彩 602 / 两者 428）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2433 | 2026-05-18 | 2026-11-12 |
| 终盘/开盘价 price_closing | 1973 | 2026-05-18 | 2026-11-16 |
| 读判时 15 家价 price_read_time | 1804 | 2026-05-19 | 2026-11-14 |
| 体彩 HAD 价 price_sporttery | 2063 | 2026-05-18 | 2026-11-14 |
| 队名 home/away | 2478 | 2026-05-18 | 2026-11-16 |
| belief.market | 2469 | 2026-05-18 | 2026-11-16 |
| belief.system ≠ market | 258 | 2026-07-07 | 2026-11-07 |
| research（任一 schema） | 902 | 2026-09-10 | 2026-11-16 |
| research.anchor_side | 836 | 2026-09-15 | 2026-11-16 |
| research.anchor_integrity | 892 | 2026-09-10 | 2026-11-16 |
| research.hole（v1 旧 schema） | 167 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 735 | 2026-09-20 | 2026-11-16 |
| research.verdict（强弱天平） | 690 | 2026-09-26 | 2026-11-16 |
| research.stance_face | 729 | 2026-09-23 | 2026-11-16 |
| research.license_questions | 856 | 2026-09-12 | 2026-11-16 |
| research.death_proofs | 821 | 2026-09-16 | 2026-11-16 |
| research.upset_label（原字段） | 690 | 2026-09-26 | 2026-11-16 |
| research.upset_label（q2_route 代理） | 132 | 2026-09-16 | 2026-11-07 |
| research.rubric r1 | 644 | 2026-10-05 | 2026-11-16 |
| research.prospective=True | 815 | 2026-09-16 | 2026-11-16 |
| reader_b.kappa | 622 | 2026-10-05 | 2026-11-15 |
| intl_drift（足彩国际盘位移） | 484 | 2026-09-16 | 2026-11-16 |
| polymarket | 377 | 2026-10-09 | 2026-11-14 |
| load（损耗台账） | 552 | 2026-10-09 | 2026-11-14 |
| overrides_n | 20 | 2026-09-26 | 2026-11-11 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 462
- 2026-11: 224

research schema 分布：{'v2': 788, 'v0': 14, 'v1': 100}
足彩 m 文件对齐：直接入表 163 ／ 经竞彩副本入表（zucai_twin）191

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
