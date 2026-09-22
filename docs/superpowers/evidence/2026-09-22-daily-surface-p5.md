# Daily Surface P5 · 对外发布与历史三页证据（2026-09-22）

计划：`docs/superpowers/plans/2026-09-22-daily-surface-p5-publish-and-observe-history.md`（Task 1–5 落地）。
提交：ba6204f（历史数据函数）→ 195fb08（发布器）→ 215fe3a（三页路由）→ 111f3be（`day publish` CLI + brief 定时器末尾发布）。

## 真跑（只读，输出到会话 scratch 目录，不进仓）

```
$ uv run nutmeg day publish --date 2026-09-22 --out <scratch>/site
published 2026-09-22 pages=4 matches=4 → <scratch>/site
   2026-09-22/index.html  7.9K   index.html 1.4K   method.html 4.7K   record.html 5.7K
```

当日页：四张卡各带 阶梯 / 深研档 / 研究状态 / 三种默认表达 ✓✗ / fair / 位移 / judge+conf / 逻辑层正文；足彩块「风向 mixed（T1×1 T2×4 T3×6 T4×3）· 未定案＝空仓」；页脚固定声明「不构成购买建议；亏损与空仓如实显示」。
战绩页：记分牌 40 条判据链照登（含证伪）。方法页：字典序 + 阶梯 + 九步闭环 SVG。

## 守则命中过一次（已修）

首次真跑 `record.html` 被拦：禁用词 `override` 命中记分牌里的真实链名 `strict_ruling_vs_override`。禁用词改为 `user-override`（要拦的是内部行权旗，不是链名）。其余三个禁用词零命中。

## 观察台三页（真实数据）

```
/observe/rules           200  24 条变更（RULEBOOK / factors.json / CONSTITUTION 的 git log）
/observe/factors         200  14 因子，44 条提案记录已对上，153 条其它尝试
/observe/trace/2026-09-22 200  昨日追溯：今日尚无 results-90.json，summary 全零（如实）
```

## 顺手修的两处呈现

对外卡片 `competition` 为空时不再显示 `None`；风向不再渲染成 Python dict 原文。

## 测试

`test_observe_history`（3）、`test_day_publish`（3）、`test_decision_web_observe_history`（2）、`test_cli_day`（+1）、`test_launchd_plists`（2）通过；ruff 干净。

## 分享（Jun 的门）

- 小圈子：在会话里用 Artifact 工具把 `site/<日>/index.html` 发成私有页再决定分享。
- 静态托管：`site/` 整目录推到任一静态主机；`com.nutmeg.day.brief` 装载后每次日报末尾自动重生成。
- 未做：成员账号与访问控制（按 spec §10 不在本包）。
