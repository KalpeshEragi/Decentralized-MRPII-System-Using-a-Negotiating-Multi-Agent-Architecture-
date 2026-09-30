"""Agents SDK + Ollama spike, offline: configuration only. No Ollama, no network."""

import asyncio

import pytest

from app.llm.agents_spike import NO_REASONING, build_model_settings, build_proposer_agent, propose_with_agent
from app.llm.reasoning import StructuredOutputError


def test_no_reasoning_setting_is_passed_to_the_agent():
    agent = build_proposer_agent(base_url="http://ollama.test:11434/v1", model="qwen3.5:4b")
    assert NO_REASONING == "none"
    assert agent.model_settings.reasoning.effort == "none"
    assert build_model_settings().reasoning.effort == "none"


def test_base_url_and_model_are_configurable():
    agent = build_proposer_agent(base_url="http://ollama.test:11434/v1", model="some-model")
    assert agent.model.model == "some-model"
    assert str(agent.model._client.base_url).startswith("http://ollama.test:11434/v1")


def test_unvalidated_reply_never_becomes_a_proposal(monkeypatch):
    class Result:
        final_output = "sure, buy 500 units"  # not JSON

    async def fake_run(agent, prompt):
        return Result()

    monkeypatch.setattr("app.llm.agents_spike.Runner.run", fake_run)
    with pytest.raises(StructuredOutputError):
        asyncio.run(propose_with_agent(build_proposer_agent(), "propose"))
