# Daily Surface P4 · 逻辑层、审计列、/today 证据（2026-09-22）

计划：`docs/superpowers/plans/2026-09-22-daily-surface-p4-logic-layer-and-session.md`（Task 1–5 落地）。
提交：ec718ba（审计列）→ 28fc5ea（撰稿器）→ d606ea0（/today）→ 8c3793f（接线 + 页面 + 12:00 plist 加 `--with-logic`）。

## 审计列（真实四场，读数与当天下午的人工判读一致）

| 场 | 裸单 | 模态双选 | 全包 |
| --- | --- | --- | --- |
| 周二001 韩国亚-沙特亚 | 3 ✓（只有 WARN） | 31 ✓ | 310 ✓ |
| 周二004 维冈-布莱克浦 | 3 ✗ low_conf_single | 30 ✓ | 310 ✓ |
| 周二002 米尔顿-克劳利 | 3 ✗ flagged_naked_single + low_conf_single | 31 ✓ | 310 ✓ |
| 周二003 诺茨郡-格里姆 | 3 ✗ | 30 ✗ flag_face_uncovered | 310 ✓ |

`legs_audit.py:567` 的 C5 条件是 `single and anchor_integrity == "fail"`，无 confidence 门槛；`legs_from_dict` 直接吃卡片标签。

## 逻辑层真跑（`claude -p`，4 次调用，57 秒）

```
$ uv run nutmeg day run --job brief --with-logic --date 2026-09-22
day 2026-09-22 brief: brief 4 场 · 待人 6 · 缺席输入 0 (exit=0)
周二001 rejected  cites 不存在: <空>
周二004 ok
周二002 ok
周二003 ok
```

被拒的一场是模型返回空 `cites`——守则按设计拒收，该场 `logic.status=rejected` 并带原因。
三段生成文本全部只引用卡片里存在的字段（`labels.anchor_integrity`、`market.drift_pp`、`audit.naked.blocking`、`factors.8.decision`…），
且都以「因子在注册表里现在的状态」收尾，符合 §6.3 的字典序。

## 待收紧（下一版提示词）

- 三段都远超「3–6 句」，且字段名密度高（读起来像字段清单）。下一版在系统提示里加硬上限（≤ 120 字/句、≤ 6 句）并要求字段名只出现在 `cites`、正文用中文名。
- 空 `cites` 被拒是对的，但可以在提示里明确「至少 3 条 cites」减少无谓拒收。

## /today

`.claude/commands/today.md` 六条规则；`AGENTS.md` 加 Codex 同规一节；`CLAUDE.md` 触发短语加一行。测试 `tests/test_today_command.py` 通过。

## 测试

`test_day_audit`（4）、`test_brief_writer`（3）、`test_day_brief`（+1）、`test_day_runner`（+1）、`test_cli_day`（+1）、`test_today_command`（1）、`test_launchd_plists`（2）通过；ruff 干净。
