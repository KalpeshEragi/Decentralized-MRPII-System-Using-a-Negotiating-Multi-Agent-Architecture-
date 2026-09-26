from agents import (
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    set_tracing_disabled,
)


# Local Ollama client
ollama_client = AsyncOpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)


# Local Qwen model
ollama_model = OpenAIChatCompletionsModel(
    model="qwen3.5:4b",
    openai_client=ollama_client,
)


# We are using a local model, so disable OpenAI tracing.
set_tracing_disabled(True)


def create_agent(
    name: str,
    instructions: str,
    tools: list | None = None,
) -> Agent:
    """
    Create an MRPII domain agent using the local Ollama model.
    """

    return Agent(
        name=name,
        instructions=instructions,
        tools=tools or [],
        model=ollama_model,
    )