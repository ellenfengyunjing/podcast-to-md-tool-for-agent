import json

import structlog
import tiktoken

from src.api.v1.schemas.response import StructuredSummary, TopicBlock, Entity
from src.layers.semantic.llm_client import LLMClient

logger = structlog.get_logger()

CHUNK_SUMMARY_PROMPT = """You are an expert content analyst. Analyze the following transcript segment and extract structured information.

Respond in the SAME LANGUAGE as the transcript. Output valid JSON with this structure:
{{
  "topics": [{{"topic": "...", "summary": "...", "quotes": ["..."]}}],
  "insights": ["..."],
  "entities": [{{"name": "...", "type": "person|organization|product|concept", "context": "..."}}]
}}

Transcript segment:
---
{text}
---"""

META_SUMMARY_PROMPT = """You are an expert content analyst. Given the following per-segment analyses of a podcast/audio, produce a final structured summary.

Respond in the SAME LANGUAGE as the content. Output valid JSON:
{{
  "title": "A concise descriptive title",
  "one_line_summary": "Single sentence summary",
  "executive_summary": "3-5 sentence comprehensive summary",
  "key_topics": [{{"topic": "...", "summary": "...", "related_quotes": ["..."]}}],
  "key_insights": ["Actionable insight 1", "..."],
  "entities": [{{"name": "...", "type": "person|organization|product|concept", "context": "..."}}],
  "content_type": "interview|monologue|panel|narrative|discussion",
  "language": "detected language code (zh, en, etc.)"
}}

Original title: {title}

Per-segment analyses:
---
{analyses}
---"""


class Summarizer:
    """Hierarchical summarization: chunk → per-chunk analysis → meta-summary."""

    def __init__(self, llm: LLMClient, max_chunk_tokens: int = 4000):
        self.llm = llm
        self.max_chunk_tokens = max_chunk_tokens
        self._encoding = tiktoken.encoding_for_model("gpt-4o")

    async def summarize(self, full_text: str, title: str = "") -> StructuredSummary:
        """Generate a structured summary from the full transcript text."""
        chunks = self._split_into_chunks(full_text)
        logger.info("summarizer_chunks", count=len(chunks))

        # Phase 1: Per-chunk analysis
        chunk_analyses = []
        for i, chunk in enumerate(chunks):
            analysis = await self._analyze_chunk(chunk)
            chunk_analyses.append(analysis)
            logger.debug("chunk_analyzed", index=i)

        # Phase 2: Meta-summary
        summary = await self._meta_summarize(chunk_analyses, title)
        return summary

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split text into chunks of approximately max_chunk_tokens tokens."""
        tokens = self._encoding.encode(text)
        if len(tokens) <= self.max_chunk_tokens:
            return [text]

        chunks = []
        # Split by sentences to avoid cutting mid-sentence
        sentences = text.replace("\n", " ").split("。")  # Chinese period
        if len(sentences) <= 1:
            sentences = text.split(". ")  # English period

        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sentence_tokens = len(self._encoding.encode(sentence))
            if current_tokens + sentence_tokens > self.max_chunk_tokens and current_chunk:
                chunks.append("。".join(current_chunk))
                current_chunk = [sentence]
                current_tokens = sentence_tokens
            else:
                current_chunk.append(sentence)
                current_tokens += sentence_tokens

        if current_chunk:
            chunks.append("。".join(current_chunk))

        return chunks

    async def _analyze_chunk(self, text: str) -> dict:
        """Analyze a single chunk of transcript."""
        prompt = CHUNK_SUMMARY_PROMPT.format(text=text)
        messages = [{"role": "user", "content": prompt}]

        response = await self.llm.complete_json(messages)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            logger.warning("chunk_analysis_json_parse_failed")
            return {"topics": [], "insights": [], "entities": []}

    async def _meta_summarize(self, analyses: list[dict], title: str) -> StructuredSummary:
        """Combine per-chunk analyses into a final structured summary."""
        analyses_text = json.dumps(analyses, ensure_ascii=False, indent=1)

        # If analyses text is too long, truncate
        analyses_tokens = len(self._encoding.encode(analyses_text))
        if analyses_tokens > 12000:
            # Recursive reduction: summarize the analyses themselves
            analyses_text = analyses_text[:40000]  # Rough character limit

        prompt = META_SUMMARY_PROMPT.format(title=title, analyses=analyses_text)
        messages = [{"role": "user", "content": prompt}]

        response = await self.llm.complete_json(messages, max_tokens=4096)
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            logger.warning("meta_summary_json_parse_failed")
            data = {}

        return StructuredSummary(
            title=data.get("title", title or "Untitled"),
            one_line_summary=data.get("one_line_summary", ""),
            executive_summary=data.get("executive_summary", ""),
            key_topics=[
                TopicBlock(
                    topic=t.get("topic", ""),
                    summary=t.get("summary", ""),
                    related_quotes=t.get("related_quotes", []),
                )
                for t in data.get("key_topics", [])
            ],
            key_insights=data.get("key_insights", []),
            entities=[
                Entity(
                    name=e.get("name", ""),
                    type=e.get("type", "concept"),
                    context=e.get("context", ""),
                )
                for e in data.get("entities", [])
            ],
            content_type=data.get("content_type", "unknown"),
            language=data.get("language", "en"),
        )
