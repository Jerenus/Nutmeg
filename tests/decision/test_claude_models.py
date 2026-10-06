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
