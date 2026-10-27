import os

import pytest

from nutmeg.config.settings import AppSettings
from nutmeg.decision.claude_models import TOKEN_ENV, claude_env, model_argv, model_label


def test_model_argv_and_label_treat_empty_as_inherit():
    assert model_argv("") == [] and model_argv(None) == [] and model_argv(" ") == []
    assert model_argv("haiku") == ["--model", "haiku"]
    assert model_label("") == "default" and model_label("opus") == "opus"


def test_settings_default_to_cheap_logic_and_inherited_research(monkeypatch):
    monkeypatch.delenv("NUTMEG_MODEL_LOGIC", raising=False)
    monkeypatch.delenv("NUTMEG_MODEL_RESEARCH", raising=False)
    settings = AppSettings(_env_file=None)
    assert settings.model_logic == "sonnet" and settings.model_research == ""
    monkeypatch.setenv("NUTMEG_MODEL_RESEARCH", "sonnet")
    assert AppSettings(_env_file=None).model_research == "sonnet"


# —— 无人值守认证：长期 token（2026-10-06 launchd 下 OAuth 过期，12 场深研全挂）————
@pytest.fixture
def token_file(tmp_path, monkeypatch):
    path = tmp_path / "claude-oauth-token"
    monkeypatch.setenv("NUTMEG_CLAUDE_TOKEN_FILE", str(path))
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    return path


def test_claude_env_injects_the_long_lived_token_from_the_private_file(token_file):
    token_file.write_text("sk-ant-oat01-test\n", encoding="utf-8")
    token_file.chmod(0o600)
    env = claude_env()
    assert env[TOKEN_ENV] == "sk-ant-oat01-test"
    assert env["PATH"] == os.environ["PATH"]          # 其余环境原样继承


def test_claude_env_inherits_unchanged_without_a_token_file(token_file):
    assert TOKEN_ENV not in claude_env()


def test_claude_env_keeps_an_explicitly_set_token(token_file, monkeypatch):
    token_file.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv(TOKEN_ENV, "explicit")
    assert claude_env()[TOKEN_ENV] == "explicit"


def test_claude_env_tightens_a_token_file_others_can_read(token_file):
    token_file.write_text("sk-ant-oat01-test", encoding="utf-8")
    token_file.chmod(0o644)
    assert claude_env()[TOKEN_ENV] == "sk-ant-oat01-test"
    assert token_file.stat().st_mode & 0o077 == 0


def test_every_scheduled_claude_call_passes_the_token_env(token_file, monkeypatch):
    """深研、读者 B、brief 解读句三处 `claude -p` 都要带上 token 环境。"""
    import subprocess

    from nutmeg.decision import brief_writer, research_runner, rubric_reader

    token_file.write_text("sk-ant-oat01-test", encoding="utf-8")
    token_file.chmod(0o600)
    seen = []

    def fake_run(argv, **kwargs):
        seen.append((kwargs.get("env") or {}).get(TOKEN_ENV))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    research_runner._claude_cli("sys", "brief")
    rubric_reader._claude_cli("sys", "in")
    brief_writer._claude_cli("sys", "in")
    assert seen == ["sk-ant-oat01-test"] * 3


def _proc(code, out="", err=""):
    import subprocess
    return lambda argv, **kw: subprocess.CompletedProcess(argv, code, stdout=out, stderr=err)


def test_auth_check_reports_ok_and_the_token_source_without_leaking_it(token_file):
    from nutmeg.decision.claude_models import auth_check

    token_file.write_text("sk-ant-oat01-secret", encoding="utf-8")
    token_file.chmod(0o600)
    report = auth_check(run=_proc(0, "ok"))
    assert report["ok"] is True and report["source"] == "token_file"
    assert report["file_mode"] == "600" and report["file_age_days"] == 0
    assert "sk-ant-oat01-secret" not in repr(report)


def test_auth_check_names_an_expired_login(token_file):
    from nutmeg.decision.claude_models import auth_check

    report = auth_check(run=_proc(
        1, "Failed to authenticate: OAuth session expired and could not be refreshed\n"))
    assert report["ok"] is False and report["auth_failure"] is True
    assert report["source"] == "inherited_login" and report["file_exists"] is False


def test_cli_auth_check_exits_nonzero_and_tells_how_to_fix(monkeypatch):
    from typer.testing import CliRunner

    import nutmeg.decision.claude_models as cm
    from nutmeg.interfaces.cli import app

    monkeypatch.setattr(cm, "auth_check", lambda **kw: {
        "ok": False, "returncode": 1, "auth_failure": True, "source": "inherited_login",
        "file": "/x/claude-oauth-token", "file_exists": False, "file_mode": None,
        "file_age_days": None, "detail": "Failed to authenticate"})
    bad = CliRunner().invoke(app, ["claude-auth-check"])
    assert bad.exit_code == 1 and "认证失败" in bad.output and "setup-token" in bad.output

    monkeypatch.setattr(cm, "auth_check", lambda **kw: {
        "ok": True, "returncode": 0, "auth_failure": False, "source": "token_file",
        "file": "/x/claude-oauth-token", "file_exists": True, "file_mode": "600",
        "file_age_days": 340, "detail": ""})
    good = CliRunner().invoke(app, ["claude-auth-check"])
    assert good.exit_code == 0 and "ok" in good.output and "满一年" in good.output


def test_claude_bin_falls_back_to_the_user_install_when_path_lacks_it(tmp_path, monkeypatch):
    """launchd 的 PATH 不一定含 ~/.local/bin（rsi.loop 的 plist 没设，launchctl submit 也没有）：
    10-06 12:37 复验时 `claude` 直接 FileNotFoundError。"""
    from nutmeg.decision.claude_models import claude_bin

    home = tmp_path / "home"
    exe = home / ".local" / "bin" / "claude"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert claude_bin() == str(exe)


def test_every_scheduled_claude_call_uses_the_resolved_binary(token_file, tmp_path, monkeypatch):
    import subprocess

    import nutmeg.decision.claude_models as cm
    from nutmeg.decision import brief_writer, research_runner, rubric_reader

    exe = tmp_path / "home" / ".local" / "bin" / "claude"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    seen = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (
        seen.append(argv[0]) or subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")))
    research_runner._claude_cli("sys", "brief")
    rubric_reader._claude_cli("sys", "in")
    brief_writer._claude_cli("sys", "in")
    cm.auth_check()
    assert seen == [str(exe)] * 4


def test_research_first_attempt_gets_the_turn_budget_that_actually_finishes(monkeypatch):
    """10-06 起 18/18 场第一次都撞 12 轮上限、24 轮重试才成：白烧一次尝试，40 次/日预算
    实际只够 20 场。首轮给 24 轮，带标记的重试再放宽到 36。"""
    import subprocess

    from nutmeg.decision import research_runner

    seen = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (
        seen.append(argv[argv.index("--max-turns") + 1])
        or subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")))
    research_runner._claude_cli("sys", "brief")
    research_runner._claude_cli("sys", "brief " + research_runner.RETRY_MARKER)
    assert seen == ["24", "36"]


def test_claude_runs_in_one_fixed_neutral_directory(token_file, monkeypatch, tmp_path):
    """2026-10-26：cwd 进了 CLI 的缓存前缀，每次新建临时目录＝每场重建 ~1.85 万 token 系统提示
    缓存（$0.15 → 固定目录第二次 $0.0075）。目录固定、为空、存在。"""
    import subprocess

    import nutmeg.decision.claude_models as cm

    monkeypatch.setattr(cm.tempfile, "gettempdir", lambda: str(tmp_path))
    seen = []

    def fake_run(argv, **kw):
        seen.append(kw["cwd"])
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cm.run_claude("sys", "in", model=None)
    cm.run_claude("sys", "in", model=None)
    assert seen[0] == seen[1] == str(tmp_path / "nutmeg-claude-neutral")
    assert list((tmp_path / "nutmeg-claude-neutral").iterdir()) == []


def test_json_output_parser_keeps_num_turns_as_the_search_count_proxy():
    """2026-10-27 P1：json 输出没有工具调用明细，num_turns 是「搜了几次」的最近代理。"""
    import json

    from nutmeg.decision.claude_models import parse_claude_json_output

    text, meta = parse_claude_json_output(json.dumps(
        {"result": "{}", "num_turns": 17, "duration_ms": 1500, "total_cost_usd": 0.02,
         "usage": {"input_tokens": 1}, "modelUsage": {"claude-opus-5-5": {}}}))
    assert text == "{}" and meta["num_turns"] == 17 and meta["model"] == "claude-opus-5-5"
    assert parse_claude_json_output("not json")[1] == {}
