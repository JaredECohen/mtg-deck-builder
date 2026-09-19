"""Skill prompts must resolve from the repo root, not the process cwd.

The API is served from `api/` (per the README), where a cwd-relative
`.claude/skills/...` path does not exist — so before this fix the critic
builder and reviewer sent an empty system prompt and the goldfish coach
silently returned None in production.
"""
from __future__ import annotations

from pathlib import Path

from app.config import SKILLS_DIR
from app.critic.clients import AnthropicBuilder, OpenAICritic, _skill_prompt
from app.services.deck_rationale import goldfish_skill_prompt


def _skill_text(name: str) -> str:
    return (SKILLS_DIR / name / "SKILL.md").read_text()


def test_skill_prompts_load_from_the_repo_regardless_of_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-test-key")

    builder = AnthropicBuilder()
    critic = OpenAICritic(client_factory=lambda: object())

    assert builder.system_prompt == _skill_text("builder-responder")
    assert critic.system_prompt == _skill_text("deck-critic")
    assert goldfish_skill_prompt() == _skill_text("goldfish-coach")
    for prompt in (builder.system_prompt, critic.system_prompt, goldfish_skill_prompt()):
        assert prompt.strip(), "a Skill prompt resolved to empty text"


def test_explicit_skill_paths_are_still_honoured(tmp_path: Path) -> None:
    custom = tmp_path / "my-skill"
    custom.mkdir()
    (custom / "SKILL.md").write_text("custom prompt")
    assert _skill_prompt(str(custom)) == "custom prompt"
    assert _skill_prompt(str(tmp_path / "missing")) == ""
