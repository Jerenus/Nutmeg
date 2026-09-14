# 已退役的 LaunchAgents（备份，可随时复装）

2026-09-14 清理。**备份在此的目的是让"删除"可逆**——复装只需
`cp <label>.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/<label>.plist`。

| Label | 卸载前最后一次运行 | 为什么退役 |
|---|---|---|
| `com.nutmeg.decision.close` | 2026-08-13 19:00 | 该次运行**失败**：`express: 'str' object has no attribute 'get'`（见下「未修的 bug」）。此后一直处于未加载状态一个月；RUNBOOK A6 早已把出票记为手动步骤 |
| `com.nutmeg.decision.settle` | 2026-07-21 08:10 | 自 2026-07-21 起未加载；RUNBOOK A7 结算记为手动步骤 |

## ✅已修的 bug（2026-09-14）

`decision.close` 最后一次失败的栈顶：

```
by_bucket.setdefault(str(leg.get("bucket") or ""), []).append(leg)
                         ^^^^^^^
AttributeError: 'str' object has no attribute 'get'
```

**根因**：`run_express` / `run_decision_express_v2` 都是 `json.loads(...)` 之后
**直接喂进 `compose_tickets`、零形状校验**。喂进一个 **dict**（票面结构
`{"issue":…,"legs":{场号:…}}`，即 `decision-audit-legs` 的输入）时，迭代 dict 得到的是
**字符串键** → `leg.get` 炸。`decision-audit-legs` 对反向错配（把扁平数组喂给它）
早有具名拒绝 `missing_audit_metadata`；**对称的那一半一直缺着**。

✅已在 `compose_tickets` 入口加形状闸（TDD，3 个测试）：dict 输入报「这是票面结构，
该走 decision-audit-legs」，数组里混入非 dict 报**第几条腿**。不再有深处的
AttributeError。

## 仍在跑的（勿动）

`com.nutmeg.decision.am`（08:00）· `com.nutmeg.zucai.prep-morning`（11:00）·
`com.nutmeg.zucai.prep`（14:00）· `com.nutmeg.zucai.prep-revision`（18:30）·
`com.nutmeg.zucai.f2-observe`（08:00-23:45 每 15 分，自算开球回推）

所有在跑 agent 的 plist 在 `docs/ops/` 下有仓内副本。

**复启 close/settle 的前提**：形状 bug 已修，但复启还需要确认
①`legs.json` 的产出方一直给扁平数组 ②close 会往 Telegram 推送真消息。
**未经用户确认不要自行 load。**
