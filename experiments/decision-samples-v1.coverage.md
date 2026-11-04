# decision-samples-v1 覆盖报告（构建 2026-11-04T11:15；窗口 2026-05-18→2026-11-04）

总行数 2768（竞彩 2225 / 足彩 518 / 两者 372）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2308 | 2026-05-18 | 2026-11-04 |
| 终盘/开盘价 price_closing | 1842 | 2026-05-18 | 2026-11-05 |
| 读判时 15 家价 price_read_time | 1687 | 2026-05-19 | 2026-11-04 |
| 体彩 HAD 价 price_sporttery | 1957 | 2026-05-18 | 2026-11-04 |
| 队名 home/away | 2329 | 2026-05-18 | 2026-11-05 |
| belief.market | 2321 | 2026-05-18 | 2026-11-05 |
| belief.system ≠ market | 257 | 2026-07-07 | 2026-10-24 |
| research（任一 schema） | 782 | 2026-09-10 | 2026-11-05 |
| research.anchor_side | 705 | 2026-09-15 | 2026-11-04 |
| research.anchor_integrity | 772 | 2026-09-10 | 2026-11-05 |
| research.hole（v1 旧 schema） | 167 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 615 | 2026-09-20 | 2026-11-05 |
| research.verdict（强弱天平） | 571 | 2026-09-26 | 2026-11-05 |
| research.stance_face | 609 | 2026-09-23 | 2026-11-05 |
| research.license_questions | 736 | 2026-09-12 | 2026-11-05 |
| research.death_proofs | 698 | 2026-09-16 | 2026-11-04 |
| research.upset_label（原字段） | 571 | 2026-09-26 | 2026-11-05 |
| research.upset_label（q2_route 代理） | 131 | 2026-09-16 | 2026-10-24 |
| research.rubric r1 | 525 | 2026-10-05 | 2026-11-05 |
| research.prospective=True | 684 | 2026-09-16 | 2026-11-04 |
| reader_b.kappa | 514 | 2026-10-05 | 2026-11-04 |
| intl_drift（足彩国际盘位移） | 403 | 2026-09-16 | 2026-11-05 |
| polymarket | 301 | 2026-10-09 | 2026-11-04 |
| load（损耗台账） | 433 | 2026-10-09 | 2026-11-04 |
| overrides_n | 19 | 2026-09-26 | 2026-10-17 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 462
- 2026-11: 74

research schema 分布：{'v2': 668, 'v0': 14, 'v1': 100}
足彩 m 文件对齐：直接入表 131 ／ 经竞彩副本入表（zucai_twin）170

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
