from src.layers.memory.token_budget import TokenBudgetManager
from src.api.v1.schemas.response import AgentMemoryBlock


class TestTokenBudgetManager:
    def test_fit_to_budget_selects_by_importance(self):
        manager = TokenBudgetManager(target_tokens=100)

        blocks = [
            AgentMemoryBlock(
                block_id="1", block_type="fact", content="Low importance block",
                importance_score=0.3, tokens=40, tags=[], embedding_text=""
            ),
            AgentMemoryBlock(
                block_id="2", block_type="fact", content="High importance block",
                importance_score=0.9, tokens=40, tags=[], embedding_text=""
            ),
            AgentMemoryBlock(
                block_id="3", block_type="fact", content="Medium importance block",
                importance_score=0.6, tokens=40, tags=[], embedding_text=""
            ),
        ]

        selected = manager.fit_to_budget(blocks)

        # Budget is 100 tokens, each block is 40 tokens -> can fit 2
        assert len(selected) == 2
        # Should select highest importance first
        assert selected[0].block_id == "2"
        assert selected[1].block_id == "3"

    def test_fit_to_budget_respects_limit(self):
        manager = TokenBudgetManager(target_tokens=50)

        blocks = [
            AgentMemoryBlock(
                block_id="1", block_type="fact", content="A",
                importance_score=0.9, tokens=30, tags=[], embedding_text=""
            ),
            AgentMemoryBlock(
                block_id="2", block_type="fact", content="B",
                importance_score=0.8, tokens=30, tags=[], embedding_text=""
            ),
        ]

        selected = manager.fit_to_budget(blocks)

        # Only one fits within 50 tokens
        assert len(selected) == 1
        assert selected[0].block_id == "1"

    def test_count_tokens(self):
        manager = TokenBudgetManager(target_tokens=100)
        count = manager.count_tokens("Hello world")
        assert count > 0
        assert isinstance(count, int)
