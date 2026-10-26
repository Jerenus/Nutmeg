"""定时 `claude -p` 的模型分档与无人值守认证。

读 settings（.env / NUTMEG_MODEL_*）；空串＝不传 --model，继承 Claude Code 默认。

认证：launchd 下的 `claude -p` 用钥匙串里的交互登录，过期后刷新失败（2026-10-06
12 场深研全挂）。`claude setup-token` 生成的长期 token 放在仓外私有文件里
（默认 `~/.config/nutmeg/claude-oauth-token`，`NUTMEG_CLAUDE_TOKEN_FILE` 可改），
`claude_env()` 把它注入 `CLAUDE_CODE_OAUTH_TOKEN`。token 不进 git、不打印。"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

INHERIT = "default"
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"
TOKEN_FILE_ENV = "NUTMEG_CLAUDE_TOKEN_FILE"
DEFAULT_TOKEN_FILE = Path("~/.config/nutmeg/claude-oauth-token")


# claude CLI 没登录/登录过期：环境问题，不是某场比赛的问题（2026-10-06）
AUTH_FAILURE_MARKERS = (
    "Failed to authenticate",
    "OAuth session expired",
    "Invalid API key",
    "Please run /login",
)


def is_auth_failure(text: str) -> bool:
    return any(marker in (text or "") for marker in AUTH_FAILURE_MARKERS)


def claude_bin() -> str:
    """`claude` 的绝对路径。launchd 的 PATH 不一定含 ~/.local/bin（rsi.loop 的 plist 没设，
    `launchctl submit` 也没有），按名字调会 FileNotFoundError（2026-10-06 12:37）。"""
    import shutil

    found = shutil.which("claude")
    if found:
        return found
    fallback = Path("~/.local/bin/claude").expanduser()
    return str(fallback) if fallback.is_file() else "claude"


def token_file() -> Path:
    return Path(os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE).expanduser()


def claude_env() -> dict[str, str]:
    """`claude -p` 子进程的环境：继承当前环境，缺 token 时从私有文件补上。

    已显式设置 `CLAUDE_CODE_OAUTH_TOKEN` 的不覆盖；文件不存在就原样继承（退回钥匙串登录）。
    文件对他人可读时收紧为 600（同 ssh 私钥的约定），不因权限放弃使用——
    放弃只会退回已过期的登录，让失败更难查。
    """
    env = dict(os.environ)
    if env.get(TOKEN_ENV):
        return env
    path = token_file()
    if not path.is_file():
        return env
    if path.stat().st_mode & 0o077:
        path.chmod(0o600)
    token = path.read_text(encoding="utf-8").strip()
    if token:
        env[TOKEN_ENV] = token
    return env


def run_claude(system_prompt: str, stdin: str, *, model: str | None, allowed_tools: str = "",
               max_turns: str = "1", timeout: int = 300) -> tuple[int, str]:
    """一次 `claude -p`（文本输出、在空的临时目录里跑、带无人值守认证）→ (退出码, stdout)。

    研究（`research_runner`）、读者 B（`rubric_reader`）、逻辑层（`brief_writer`）共用的唯一实现
    （2026-10-08 B5，此前三份）。"""
    proc = _run_claude_proc(system_prompt, stdin, model=model, allowed_tools=allowed_tools,
                            max_turns=max_turns, timeout=timeout, output_format="text")
    return proc.returncode, proc.stdout


def run_claude_json(system_prompt: str, stdin: str, *, model: str | None,
                    allowed_tools: str = "", max_turns: str = "1",
                    timeout: int = 300) -> tuple[int, str, dict]:
    """同 `run_claude`，但以 `--output-format json` 跑 → (退出码, 结果文本, 遥测)。

    遥测（2026-10-26 Tier 1 #4：研究层此前零遥测）：`model / duration_s / input_tokens /
    cache_read_input_tokens / cache_creation_input_tokens / output_tokens / cost_usd`。
    外层 JSON 解析不出来 → 结果文本退回原 stdout、遥测 {}，不影响调用方照旧处理。"""
    proc = _run_claude_proc(system_prompt, stdin, model=model, allowed_tools=allowed_tools,
                            max_turns=max_turns, timeout=timeout, output_format="json")
    text, meta = parse_claude_json_output(proc.stdout)
    return proc.returncode, text, meta


def parse_claude_json_output(stdout: str) -> tuple[str, dict]:
    """`claude -p --output-format json` 的 stdout → (result 文本, 遥测 dict)；
    解析失败 → (原文, {})。"""
    import json

    try:
        doc = json.loads(stdout)
    except (ValueError, TypeError):
        return stdout, {}
    if not isinstance(doc, dict) or "result" not in doc:
        return stdout, {}
    usage = doc.get("usage") if isinstance(doc.get("usage"), dict) else {}
    model_usage = doc.get("modelUsage") if isinstance(doc.get("modelUsage"), dict) else {}
    duration_ms = doc.get("duration_ms")
    meta = {
        "model": next(iter(model_usage), None),
        "duration_s": round(float(duration_ms) / 1000, 1) if duration_ms is not None else None,
        "input_tokens": usage.get("input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": doc.get("total_cost_usd"),
    }
    return str(doc.get("result") or ""), meta


def _run_claude_proc(system_prompt: str, stdin: str, *, model: str | None, allowed_tools: str,
                     max_turns: str, timeout: int, output_format: str):
    import subprocess

    argv = [claude_bin(), "-p", *model_argv(model), "--system-prompt", system_prompt,
            "--allowedTools", allowed_tools, "--max-turns", str(max_turns),
            "--output-format", output_format]
    return subprocess.run(argv, input=stdin, capture_output=True, text=True,
                          timeout=timeout, cwd=neutral_cwd(), env=claude_env(), check=False)


def neutral_cwd() -> str:
    """`claude -p` 的工作目录：**固定**的空目录（不是每次新建的临时目录）。

    空目录是为了不读仓里的 CLAUDE.md；固定是为了提示缓存——CLI 把 cwd 写进它自己的
    上下文前缀，每次换目录前缀就变，我方 ~1.85 万 token 的系统提示每场重建缓存
    （2026-10-26 对照：随机目录两次 cache_read 18.6k/创建 18.4k $0.15；固定目录第二次
    cache_read 37.1k/创建 0 $0.0075）。"""
    path = Path(tempfile.gettempdir()) / "nutmeg-claude-neutral"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def model_argv(name: str | None) -> list[str]:
    name = (name or "").strip()
    return ["--model", name] if name else []


def model_label(name: str | None) -> str:
    name = (name or "").strip()
    return name or INHERIT


def logic_model() -> str:
    from nutmeg.config.settings import get_settings

    return get_settings().model_logic


def research_model() -> str:
    from nutmeg.config.settings import get_settings

    return get_settings().model_research


def reader_model() -> str:
    """系统一读者（判断 rubric 两读 / 历史重打分）。"""
    from nutmeg.config.settings import get_settings

    return get_settings().model_reader


def auth_check(*, run=None) -> dict:
    """无人值守认证自检：token 文件状态 + 真调一次 `claude -p`。**报告里永远没有 token。**"""
    import subprocess
    import tempfile
    import time

    run = run or subprocess.run
    path = token_file()
    exists = path.is_file()
    env = claude_env()          # 顺带把过宽的文件权限收紧
    stat = path.stat() if exists else None
    with tempfile.TemporaryDirectory() as neutral:
        proc = run([claude_bin(), "-p", "--max-turns", "1", "--output-format", "text"],
                   input="reply with the single word ok", capture_output=True, text=True,
                   timeout=120, cwd=neutral, env=env, check=False)
    output = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    explicit = bool(os.environ.get(TOKEN_ENV))
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "auth_failure": is_auth_failure(output),
        "source": ("env" if explicit else
                   "token_file" if TOKEN_ENV in env else "inherited_login"),
        "file": str(path),
        "file_exists": exists,
        "file_mode": f"{stat.st_mode & 0o777:o}" if stat else None,
        "file_age_days": int((time.time() - stat.st_mtime) // 86400) if stat else None,
        "detail": "" if proc.returncode == 0 else output.strip()[:200],
    }
