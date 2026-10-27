"""The offline eval judge must default to a model OpenAI still serves."""

from app.config import DEFAULT_OPENAI_EVAL_MODEL, env_or_default, responses_reasoning_controls


def test_eval_model_default_is_the_supported_successor():
    # gpt-4.1-mini shuts down 2027-01-14 (replacement gpt-6-luna).
    # gpt-5-mini shuts down 2026-12-11.
    assert DEFAULT_OPENAI_EVAL_MODEL == "gpt-6-luna"
    assert "4.1" not in DEFAULT_OPENAI_EVAL_MODEL
    assert DEFAULT_OPENAI_EVAL_MODEL != "gpt-5-mini"


def test_blank_model_env_uses_the_default(monkeypatch):
    monkeypatch.setenv("OPENAI_EVAL_MODEL", "  ")
    assert env_or_default("OPENAI_EVAL_MODEL", DEFAULT_OPENAI_EVAL_MODEL) == "gpt-6-luna"


def test_model_env_override_is_honored(monkeypatch):
    monkeypatch.setenv("OPENAI_EVAL_MODEL", "gpt-5.6-terra")
    assert env_or_default("OPENAI_EVAL_MODEL", DEFAULT_OPENAI_EVAL_MODEL) == "gpt-5.6-terra"


def test_reasoning_controls_follow_the_model_family():
    assert responses_reasoning_controls("gpt-6-luna")
    assert responses_reasoning_controls("gpt-5.6-terra")
    assert not responses_reasoning_controls("gpt-4.1-mini")
    assert not responses_reasoning_controls("  ")
