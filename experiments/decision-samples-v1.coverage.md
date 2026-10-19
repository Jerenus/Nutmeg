# decision-samples-v1 覆盖报告（构建 2026-10-19T11:30；窗口 2026-05-18→2026-10-18）

总行数 2082（竞彩 1975 / 足彩 336 / 两者 229）

| 列 | 非空 n | 首日 | 末日 |
|---|---|---|---|
| 赛果 result | 1630 | 2026-05-18 | 2026-10-18 |
| 终盘/开盘价 price_closing | 1558 | 2026-05-18 | 2026-10-18 |
| 读判时 15 家价 price_read_time | 1443 | 2026-05-19 | 2026-10-18 |
| 体彩 HAD 价 price_sporttery | 1741 | 2026-05-18 | 2026-10-18 |
| 队名 home/away | 2040 | 2026-05-18 | 2026-10-18 |
| belief.market | 1637 | 2026-05-18 | 2026-10-18 |
| belief.system ≠ market | 218 | 2026-07-23 | 2026-10-18 |
| research（任一 schema） | 488 | 2026-09-10 | 2026-10-18 |
| research.anchor_side | 422 | 2026-09-15 | 2026-10-18 |
| research.anchor_integrity | 478 | 2026-09-10 | 2026-10-18 |
| research.hole（v1 旧 schema） | 165 | 2026-09-10 | 2026-09-20 |
| research.hole（v2 side/unit/priced） | 323 | 2026-09-20 | 2026-10-18 |
| research.verdict（强弱天平） | 285 | 2026-09-26 | 2026-10-18 |
| research.stance_face | 317 | 2026-09-23 | 2026-10-18 |
| research.license_questions | 442 | 2026-09-12 | 2026-10-18 |
| research.death_proofs | 417 | 2026-09-16 | 2026-10-18 |
| research.upset_label（原字段） | 285 | 2026-09-26 | 2026-10-18 |
| research.upset_label（q2_route 代理） | 123 | 2026-09-16 | 2026-09-27 |
| research.rubric r1 | 239 | 2026-10-05 | 2026-10-18 |
| research.prospective=True | 404 | 2026-09-16 | 2026-10-18 |
| reader_b.kappa | 239 | 2026-10-05 | 2026-10-18 |
| intl_drift（足彩国际盘位移） | 227 | 2026-09-16 | 2026-10-18 |
| polymarket | 132 | 2026-10-09 | 2026-10-18 |
| load（损耗台账） | 185 | 2026-10-09 | 2026-10-18 |
| overrides_n | 19 | 2026-09-26 | 2026-10-17 |

## 行数按月

- 2026-05: 261
- 2026-06: 423
- 2026-07: 235
- 2026-08: 417
- 2026-09: 501
- 2026-10: 245

research schema 分布：{'v2': 373, 'v0': 14, 'v1': 101}

## 纪律

- 每格来自当时落盘的文件；`research.prospective` 为 True 才是前瞻样本，None＝缺采集时刻或开球时刻。
- `upset_label_src` 以 `derived:` 开头的是 09-26 前旧研究的机械代理（牌照 q2_route）；`underdog_path.strength` 才是分析包「弱/真实」标签的原字段。
- 本表没有任何事后补写的研究；2026-09-19 之前的行只有价格、belief 与赛果。
