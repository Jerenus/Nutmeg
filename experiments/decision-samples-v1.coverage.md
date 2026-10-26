# decision-samples-v1 覆盖报告（构建 2026-10-25T13:16；窗口 2026-05-18→2026-10-24）

总行数 2574（竞彩 2061 / 足彩 392 / 两者 275）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 2089 | 2026-05-18 | 2026-10-24 |
| 终盘/开盘价 price_closing | 1635 | 2026-05-18 | 2026-10-25 |
| 读判时 15 家价 price_read_time | 1527 | 2026-05-19 | 2026-10-24 |
| 体彩 HAD 价 price_sporttery | 1816 | 2026-05-18 | 2026-10-24 |
| 队名 home/away | 2136 | 2026-05-18 | 2026-10-25 |
| belief.market | 2129 | 2026-05-18 | 2026-10-25 |
| belief.system ≠ market | 256 | 2026-07-07 | 2026-10-20 |
| research（任一 schema） | 590 | 2026-09-10 | 2026-10-25 |
| research.anchor_side | 524 | 2026-09-15 | 2026-10-25 |
| research.anchor_integrity | 580 | 2026-09-10 | 2026-10-25 |
| research.hole（v1 旧 schema） | 167 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 423 | 2026-09-20 | 2026-10-25 |
| research.verdict（强弱天平） | 380 | 2026-09-26 | 2026-10-25 |
| research.stance_face | 417 | 2026-09-23 | 2026-10-25 |
| research.license_questions | 544 | 2026-09-12 | 2026-10-25 |
| research.death_proofs | 511 | 2026-09-16 | 2026-10-25 |
| research.upset_label（原字段） | 380 | 2026-09-26 | 2026-10-25 |
| research.upset_label（q2_route 代理） | 130 | 2026-09-16 | 2026-09-27 |
| research.rubric r1 | 334 | 2026-10-05 | 2026-10-25 |
| research.prospective=True | 504 | 2026-09-16 | 2026-10-25 |
| reader_b.kappa | 334 | 2026-10-05 | 2026-10-25 |
| intl_drift（足彩国际盘位移） | 283 | 2026-09-16 | 2026-10-25 |
| polymarket | 193 | 2026-10-09 | 2026-10-24 |
| load（损耗台账） | 271 | 2026-10-09 | 2026-10-24 |
| overrides_n | 19 | 2026-09-26 | 2026-10-17 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 347
- 2026-08: 621
- 2026-09: 580
- 2026-10: 342

research schema 分布：{'v2': 476, 'v0': 14, 'v1': 100}

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
