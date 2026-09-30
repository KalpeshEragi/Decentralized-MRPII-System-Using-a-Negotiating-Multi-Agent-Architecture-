"""OpenAI Agents SDK + Ollama compatibility spike (Phase 2, D13). Not one of the real agents (Phase 3).

It shows that an Agents SDK `Agent` can be pointed at the configured Ollama model through its OpenAI-compatible
endpoint, with the project's no-reasoning setting (`reasoning.effort = "none"`) passed in the model settings, and that the
model's text stays a *proposal*: it is parsed and validated by `parse_structured` before anything can use it.

`build_proposer_agent` performs no network call. `propose_with_agent` calls Ollama, so it needs a running Ollama and has
not been run by the tests.
"""

from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
from openai import AsyncOpenAI
from openai.types.shared import Reasoning

from app.core.config import get_settings
from app.llm.prompts import PROPOSAL_SYSTEM_PROMPT
from app.llm.reasoning import NegotiationProposal, parse_structured

NO_REASONING = "none"  # "Normal negotiation calls use fast/no-reasoning mode" (DECISIONS.md)


def build_model_settings() -> ModelSettings:
    return ModelSettings(temperature=0.0, reasoning=Reasoning(effort=NO_REASONING))


def build_proposer_agent(base_url: str | None = None, model: str | None = None) -> Agent:
    """An Agents SDK agent on the configured Ollama model. Base URL and model name come from settings unless given."""
    settings = get_settings()
    set_tracing_disabled(True)  # no calls to OpenAI's tracing service
    client = AsyncOpenAI(base_url=base_url or settings.ollama_base_url, api_key="ollama")  # Ollama ignores the key
    return Agent(
        name="proposer-spike",
        instructions=PROPOSAL_SYSTEM_PROMPT,
        model=OpenAIChatCompletionsModel(model=model or settings.ollama_model, openai_client=client),
        model_settings=build_model_settings(),
    )


async def propose_with_agent(agent: Agent, prompt: str) -> NegotiationProposal:
    """Run the agent and return its reply only if it validates as a NegotiationProposal (else StructuredOutputError)."""
    result = await Runner.run(agent, prompt)
    return parse_structured(str(result.final_output), NegotiationProposal)
