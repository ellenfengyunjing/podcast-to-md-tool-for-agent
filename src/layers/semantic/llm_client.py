import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()

# OpenRouter requires these headers for proper routing
OPENROUTER_EXTRA_HEADERS = {
    "HTTP-Referer": "https://github.com/podcast-knowledge-agent",
    "X-Title": "Podcast Knowledge Agent",
}


class LLMClient:
    """LLM client using OpenRouter via OpenAI-compatible SDK."""

    def __init__(self, model: str, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=OPENROUTER_EXTRA_HEADERS,
        )

    async def complete(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 4096) -> str:
        """Send a chat completion request and return the response text."""
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        logger.debug("llm_completion", model=self.model, tokens=response.usage.total_tokens if response.usage else 0)
        return content

    async def complete_json(self, messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096) -> str:
        """Send a completion request expecting JSON output."""
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        logger.debug("llm_json_completion", model=self.model, tokens=response.usage.total_tokens if response.usage else 0)
        return content
