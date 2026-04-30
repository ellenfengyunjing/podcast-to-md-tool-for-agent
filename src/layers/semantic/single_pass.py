"""Single-pass structured extraction - combines summary + memory in one LLM call.

For transcripts under ~8000 tokens, this replaces the multi-step
summarizer + memory compressor pipeline with a single LLM call,
reducing total LLM time from ~70s to ~15s.
"""
import json
import uuid

import structlog
import tiktoken

from src.api.v1.schemas.response import (
    AgentMemoryBlock,
    CompressedAgentMemory,
    Entity,
    StructuredSummary,
    TopicBlock,
    TranscriptSegment,
)
from src.layers.semantic.llm_client import LLMClient
from src.layers.memory.token_budget import TokenBudgetManager

logger = structlog.get_logger()

SINGLE_PASS_PROMPT = """You are an expert podcast analyst. Analyze the following transcript and produce a comprehensive structured extraction in ONE response.

Respond in the SAME LANGUAGE as the transcript. Output valid JSON with this exact structure:
{{
  "summary": {{
    "title": "A concise descriptive title for this content",
    "one_line_summary": "Single sentence summary",
    "executive_summary": "3-5 sentence comprehensive summary",
    "key_topics": [{{"topic": "...", "summary": "..."}}],
    "key_insights": ["Actionable insight 1", "Insight 2", "..."],
    "entities": [{{"name": "...", "type": "person|organization|product|concept", "context": "brief context"}}],
    "content_type": "interview|monologue|panel|narrative|discussion",
    "language": "detected language code (zh, en, ja, etc.)"
  }},
  "memory_blocks": [
    {{
      "content": "A concise, self-contained knowledge statement",
      "block_type": "fact|opinion|action_item|quote|topic_summary",
      "importance_score": 0.85,
      "tags": ["tag1", "tag2"],
      "embedding_text": "search-optimized version of content"
    }}
  ],
  "retrieval_summary": "A single paragraph telling an AI agent what this content covers and when it might be relevant"
}}

Rules for memory_blocks:
- Extract 15-30 discrete knowledge blocks
- Each block must be self-contained (understandable without context)
- Prioritize: novel facts > actionable insights > notable quotes > opinions
- importance_score: 0.9+ for unique/surprising facts, 0.7-0.9 for key points, 0.5-0.7 for supporting details

Original title: {title}
Total duration: {duration:.0f} seconds

Full transcript:
---
{text}
---"""

class SinglePassExtractor:
    """Extract summary + memory blocks in a single LLM call.

    For transcripts under max_input_tokens, this is much faster than
    the multi-step pipeline (1 call vs 8 calls).
    """

    def __init__(self, llm: LLMClient, token_budget: int = 2000, max_input_tokens: int = 12000):
        self.llm = llm
        self.token_budget = token_budget
        self.max_input_tokens = max_input_tokens
        self.budget_manager = TokenBudgetManager(target_tokens=token_budget)
        self._encoding = tiktoken.encoding_for_model("gpt-4o")

    def can_single_pass(self, full_text: str) -> bool:
        """Check if the transcript is short enough for single-pass extraction."""
        token_count = len(self._encoding.encode(full_text))
        return token_count <= self.max_input_tokens

    async def extract(
        self,
        full_text: str,
        title: str,
        duration: float,
        source_id: str,
        source_url: str,
    ) -> tuple[StructuredSummary, CompressedAgentMemory]:
        """Run single-pass extraction, returning both summary and memory."""
        logger.info("single_pass_start", text_tokens=len(self._encoding.encode(full_text)))

        prompt = SINGLE_PASS_PROMPT.format(
            title=title,
            duration=duration,
            text=full_text,
        )
        messages = [{"role": "user", "content": prompt}]

        response = await self.llm.complete_json(messages, max_tokens=8192)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            logger.error("single_pass_json_parse_failed")
            raise RuntimeError("Failed to parse single-pass LLM response as JSON")

        # Parse summary
        s = data.get("summary", {})
        summary = StructuredSummary(
            title=s.get("title", title or "Untitled"),
            one_line_summary=s.get("one_line_summary", ""),
            executive_summary=s.get("executive_summary", ""),
            key_topics=[
                TopicBlock(topic=t.get("topic", ""), summary=t.get("summary", ""))
                for t in s.get("key_topics", [])
            ],
            key_insights=s.get("key_insights", []),
            entities=[
                Entity(name=e.get("name", ""), type=e.get("type", "concept"), context=e.get("context", ""))
                for e in s.get("entities", [])
            ],
            content_type=s.get("content_type", "unknown"),
            language=s.get("language", "en"),
        )

        # Parse memory blocks
        all_blocks = []
        for item in data.get("memory_blocks", []):
            block = AgentMemoryBlock(
                block_id=str(uuid.uuid4())[:8],
                block_type=item.get("block_type", "fact"),
                content=item.get("content", ""),
                importance_score=float(item.get("importance_score", 0.5)),
                tags=item.get("tags", []),
                embedding_text=item.get("embedding_text", item.get("content", "")),
                tokens=0,
            )
            block.tokens = self.budget_manager.count_tokens(block.content)
            all_blocks.append(block)

        # Fit to token budget
        selected_blocks = self.budget_manager.fit_to_budget(all_blocks)

        # Build memory
        original_tokens = len(self._encoding.encode(full_text))
        total_tokens = sum(b.tokens for b in selected_blocks)
        compression_ratio = total_tokens / original_tokens if original_tokens > 0 else 0

        memory = CompressedAgentMemory(
            source_id=source_id,
            source_title=summary.title,
            source_url=source_url,
            total_duration_seconds=duration,
            language=summary.language,
            memory_blocks=selected_blocks,
            retrieval_summary=data.get("retrieval_summary", f"Podcast: {title}"),
            total_tokens=total_tokens,
            compression_ratio=round(compression_ratio, 4),
        )

        logger.info(
            "single_pass_complete",
            summary_title=summary.title,
            memory_blocks=len(selected_blocks),
            total_tokens=total_tokens,
        )
        return summary, memory
