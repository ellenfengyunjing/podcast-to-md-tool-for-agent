import tiktoken

from src.api.v1.schemas.response import AgentMemoryBlock


class TokenBudgetManager:
    """Manage token budget for agent memory blocks."""

    def __init__(self, target_tokens: int = 2000, model: str = "gpt-4o"):
        self.target_tokens = target_tokens
        self._encoding = tiktoken.encoding_for_model(model)

    def count_tokens(self, text: str) -> int:
        return len(self._encoding.encode(text))

    def fit_to_budget(self, blocks: list[AgentMemoryBlock]) -> list[AgentMemoryBlock]:
        """Select blocks by importance score until token budget is exhausted."""
        # Sort by importance descending
        sorted_blocks = sorted(blocks, key=lambda b: b.importance_score, reverse=True)

        selected = []
        total_tokens = 0

        for block in sorted_blocks:
            if total_tokens + block.tokens > self.target_tokens:
                continue
            selected.append(block)
            total_tokens += block.tokens

        return selected
