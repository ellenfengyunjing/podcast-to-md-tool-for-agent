import json
import uuid

import structlog
import tiktoken

from src.api.v1.schemas.response import (
    AgentMemoryBlock,
    CompressedAgentMemory,
    TranscriptSegment,
)
from src.layers.semantic.llm_client import LLMClient
from src.layers.memory.token_budget import TokenBudgetManager

logger = structlog.get_logger()

EXTRACTION_PROMPT = """You are a knowledge extraction engine. Extract discrete knowledge blocks from this transcript segment.

Each block should be ONE of these types:
- "fact": A concrete, verifiable piece of information
- "opinion": A viewpoint or perspective expressed by a speaker
- "action_item": Something suggested to be done
- "quote": A notable or memorable statement
- "topic_summary": A brief summary of a discussed topic

For each block, provide:
- content: The knowledge in a concise, self-contained sentence
- block_type: One of the types above
- importance_score: 0.0-1.0 based on novelty, actionability, and specificity
- tags: 2-4 semantic tags for retrieval
- embedding_text: A search-optimized version of the content

Respond in the SAME LANGUAGE as the transcript. Output valid JSON:
{{
  "blocks": [
    {{
      "content": "...",
      "block_type": "fact",
      "importance_score": 0.8,
      "tags": ["tag1", "tag2"],
      "embedding_text": "..."
    }}
  ]
}}

Transcript segment (timestamps {start:.0f}s - {end:.0f}s):
---
{text}
---"""

RETRIEVAL_SUMMARY_PROMPT = """Write a single paragraph (under 150 words) that tells an AI agent what this podcast is about and whether it might be relevant to a given task. Be specific about topics, people, and conclusions discussed.

Respond in the SAME LANGUAGE as the content.

Title: {title}
Summary: {summary}"""


class MemoryCompressor:
    """Extract and compress knowledge into agent-consumable memory blocks."""

    def __init__(self, llm: LLMClient, token_budget: int = 2000):
        self.llm = llm
        self.budget_manager = TokenBudgetManager(target_tokens=token_budget)
        self._encoding = tiktoken.encoding_for_model("gpt-4o")

    async def compress(
        self,
        segments: list[TranscriptSegment],
        source_id: str,
        source_title: str,
        source_url: str,
        total_duration: float,
        language: str,
        summary_text: str = "",
    ) -> CompressedAgentMemory:
        """Run the full compression pipeline."""
        # Group segments into ~3000-token blocks for extraction
        text_blocks = self._group_segments(segments)
        logger.info("memory_compression_start", blocks=len(text_blocks))

        # Extract knowledge blocks from each text block
        all_blocks: list[AgentMemoryBlock] = []
        for block_text, start_ts, end_ts in text_blocks:
            extracted = await self._extract_blocks(block_text, start_ts, end_ts)
            all_blocks.extend(extracted)

        logger.info("blocks_extracted", count=len(all_blocks))

        # Count tokens for each block
        for block in all_blocks:
            block.tokens = self.budget_manager.count_tokens(block.content)

        # Fit to budget
        selected_blocks = self.budget_manager.fit_to_budget(all_blocks)

        # Generate retrieval summary
        retrieval_summary = await self._generate_retrieval_summary(source_title, summary_text)

        # Calculate stats
        original_text = " ".join(s.text for s in segments)
        original_tokens = len(self._encoding.encode(original_text))
        total_tokens = sum(b.tokens for b in selected_blocks)
        compression_ratio = total_tokens / original_tokens if original_tokens > 0 else 0

        return CompressedAgentMemory(
            source_id=source_id,
            source_title=source_title,
            source_url=source_url,
            total_duration_seconds=total_duration,
            language=language,
            memory_blocks=selected_blocks,
            retrieval_summary=retrieval_summary,
            total_tokens=total_tokens,
            compression_ratio=round(compression_ratio, 4),
        )

    def _group_segments(
        self, segments: list[TranscriptSegment], max_tokens: int = 3000
    ) -> list[tuple[str, float, float]]:
        """Group consecutive segments into blocks of ~max_tokens."""
        groups = []
        current_texts = []
        current_tokens = 0
        start_ts = segments[0].start if segments else 0.0

        for seg in segments:
            seg_tokens = len(self._encoding.encode(seg.text))
            if current_tokens + seg_tokens > max_tokens and current_texts:
                groups.append((" ".join(current_texts), start_ts, seg.start))
                current_texts = [seg.text]
                current_tokens = seg_tokens
                start_ts = seg.start
            else:
                current_texts.append(seg.text)
                current_tokens += seg_tokens

        if current_texts:
            end_ts = segments[-1].end if segments else 0.0
            groups.append((" ".join(current_texts), start_ts, end_ts))

        return groups

    async def _extract_blocks(
        self, text: str, start: float, end: float
    ) -> list[AgentMemoryBlock]:
        """Extract knowledge blocks from a text segment using LLM."""
        prompt = EXTRACTION_PROMPT.format(text=text, start=start, end=end)
        messages = [{"role": "user", "content": prompt}]

        response = await self.llm.complete_json(messages)
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            logger.warning("extraction_json_parse_failed")
            return []

        blocks = []
        for item in data.get("blocks", []):
            blocks.append(AgentMemoryBlock(
                block_id=str(uuid.uuid4())[:8],
                block_type=item.get("block_type", "fact"),
                content=item.get("content", ""),
                source_timestamp=[start, end],
                importance_score=float(item.get("importance_score", 0.5)),
                tags=item.get("tags", []),
                embedding_text=item.get("embedding_text", item.get("content", "")),
            ))

        return blocks

    async def _generate_retrieval_summary(self, title: str, summary: str) -> str:
        """Generate a short retrieval summary for agent planning."""
        if not summary:
            return f"Podcast: {title}"

        prompt = RETRIEVAL_SUMMARY_PROMPT.format(title=title, summary=summary)
        messages = [{"role": "user", "content": prompt}]
        return await self.llm.complete(messages, max_tokens=200)
