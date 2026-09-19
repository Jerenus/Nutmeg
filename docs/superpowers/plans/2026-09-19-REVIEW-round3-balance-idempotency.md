# 审查意见 · 第三轮：`rsi balance` 幂等键漏掉赛果（阻塞）

> 审查者：Claude Opus 5，2026-09-19 15:00。在 **26129 真实结算**中发现——这是 F9 的第一次真用。
> 前置：R2/R3/F8/F9 与阶段一二三已全部验收通过；本条是 F9 在真流程里暴露的唯一缺陷。

## 1. 现象（真库可复现）

```
$ uv run nutmeg rsi balance --issue 26129
IdempotencyConflictError: idempotency key rsi-ful:F9:balance-ledger:2026-09-19
was reused with a different request
```

## 2. 复现路径（就是真实的一天）

1. **开球前**跑 `rsi balance --issue 26129` → 此时 `official-results.json` 里没有 26129
   → 账为 `{n_moved:0, brier_vs_market_moved: null, direction_right_n: null}` → `rsi fulfill --exp F9` 成功。
2. **结算后**（赛果录入）再跑同一条命令 → 账变成带赛果的版本
   （`brier_vs_market_all: 0.0, direction_right_n: 0, direction_wrong_n: 0`）
   → `fulfill` 用**同一个** idempotency key 但**不同的 request** → `IdempotencyConflictError` 抛出，命令失败。

## 3. 后果（不是小事）

```
F9 observations: 1      ← 存的是「未开奖」版本
F9 gaps: ['2026-09-19']
```
**库里那条观察永远停在赛果到达之前**，`brier_vs_market_*` 与 `direction_*` 恒为 `None`。
F9 的 falsifier 挂的正是 `brier_delta_vs_market_moved_pp`——**这条实验按现状永远结不了账**。
账文件 `26129-balance.json` 本身写对了（带赛果），只有内核里的观察是旧的。

## 4. 根因

`nutmeg/interfaces/cli/rsi.py:297`
```python
idempotency_key=f"rsi-ful:F9:balance-ledger:{resolved_day}"
```
键只含日期，**不含账的内容**。而同一文件 `:346` 的 `grade` 命令做法是对的：
```python
idempotency_key=f"rsi-grade:{exp}:{mode}:{g.inputs_hash[:16]}"
```
两处口径不一致。

## 5. 改法

把账的内容哈希并入键，让「开奖前」与「开奖后」成为两次不同的合法登记：

```python
import hashlib, json
ledger_hash = hashlib.sha256(
    json.dumps(ledger, ensure_ascii=False, sort_keys=True).encode("utf-8")
).hexdigest()[:16]
...
idempotency_key=f"rsi-ful:F9:balance-ledger:{resolved_day}:{ledger_hash}"
```
同一天内容不变时重跑仍然幂等（键相同 → 重放已提交结果）；赛果到达后内容变了 → 新键 → 新观察入库。

⚠️`rsi fulfill` 的 `--artifact` 已经按文件内容算哈希，所以 observation 行本身能区分；
**只有幂等键这一层挡住了它**。

## 6. 补测试

`tests/test_cli_rsi.py`：
```python
def test_balance_can_be_rerun_after_results_arrive(tmp_path, monkeypatch):
    # 同一 issue：先无 official-results 跑一次 → 再写入赛果跑第二次
    # 断言两次都 exit_code == 0，且第二次的 observation 带非 None 的 brier/direction
```
`tests/decision/test_balance_ledger.py`：
```python
def test_ledger_hash_changes_when_outcomes_arrive():
    a = balance_ledger(reads, outcomes=None)
    b = balance_ledger(reads, outcomes={"1": "home"})
    assert a != b          # 内容必须可区分，否则幂等键分不开
```

## 7. 顺带修（非阻塞，同一提交即可）

`26129-rx.json` 暴露 **rx 登记器不去重**：43 条预测里只有 **11 条不同断言**，
S1–S4 各被复制 8–9 次成 P5–P36。结算时我按去重后的 11 条判（9 ✓ / 2 ✗），
但 `workflow grade-rx` 的统计会把重复条目当独立样本，**记分牌的 rx 命中率会被稀释/放大**。
请在 rx 登记（`workflow register-rx`）时按 `claim` 去重，重复的合并为一条并保留 alias id 列表。

## 8. 做完

```bash
uv run pytest tests/test_cli_rsi.py tests/decision/test_balance_ledger.py -q
uv run nutmeg rsi balance --issue 26129     # 必须成功，且账带赛果
uv run nutmeg rsi status                    # F9 的 observation 应更新为带赛果版本
```
把 `rsi balance --issue 26129` 的输出与 `rsi status` 里 F9 那行贴回来。
