# Nutmeg Tooling

## Primary Project Interface

```bash
cd /Users/jz71/Projects/Nutmeg
uv run nutmeg --help
```

优先使用 `AGENTS.md` 当前 SOP 指定的命令、项目 store、runbook 和：

```bash
python3 scripts/openclaw/nutmeg_command_router.py --help
```

先通过 `--help` 或当前文档确认参数，不根据旧会话猜测已退役命令。

## Codex Yolo Fallback

固定入口：

```bash
/Users/jz71/.nvm/versions/node/v22.22.1/bin/codex exec \
  -C /Users/jz71/Projects/Nutmeg \
  --dangerously-bypass-approvals-and-sandbox \
  "<完整任务；要求先读 AGENTS.md、使用当前框架、最小改动并验证>"
```

使用条件：跨文件深度审查、现有命令故障定位、阻塞当前用户任务的最小修复。
不要把普通查询、当天方案、票面分析或复盘自动转成开发任务。

## Permission Posture

- OpenClaw sandbox: `off`
- exec host: `gateway`
- exec security: `full`
- exec ask: `off`
- operational filesystem scope: stay within the Nutmeg workspace unless Jun explicitly supplies an external input path
- browser: enabled for证据核查

高权限用于完成项目任务，不改变真实投注、资金、公开推送和不可逆操作的确认边界。
