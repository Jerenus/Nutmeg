from nutmeg.config.settings import AppSettings
from nutmeg.decision.claude_models import model_argv, model_label


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
