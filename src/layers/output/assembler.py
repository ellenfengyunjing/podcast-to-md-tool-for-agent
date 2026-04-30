import json
import re
from pathlib import Path

import structlog

from src.api.v1.schemas.response import (
    AudioMetadata,
    CompressedAgentMemory,
    FullTranscript,
    PodcastKnowledge,
    ProcessingInfo,
    StructuredSummary,
    TimedParagraph,
    TranscriptSegment,
)
from src.layers.resolver.factory import ResolvedPodcast

logger = structlog.get_logger()


def _count_words(text: str) -> int:
    """Count words for mixed CJK/Latin text.

    For CJK characters, each character counts as one word.
    For Latin text, split by whitespace.
    """
    cjk_chars = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
    # Remove CJK chars, count remaining Latin words
    latin_text = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', ' ', text)
    latin_words = len(latin_text.split())
    return cjk_chars + latin_words


class OutputAssembler:
    """Assemble all layer outputs into the final PodcastKnowledge JSON."""

    def assemble(
        self,
        resolved: ResolvedPodcast,
        segments: list[TranscriptSegment],
        summary: StructuredSummary,
        agent_memory: CompressedAgentMemory,
        processing_info: ProcessingInfo,
    ) -> PodcastKnowledge:
        # Build metadata
        metadata = AudioMetadata(
            source_url=resolved.original_url,
            platform=resolved.platform.value,
            title=resolved.title,
            author=resolved.author,
            description=resolved.description,
            duration_seconds=resolved.duration_seconds or 0.0,
            published_at=resolved.published_at,
            language=summary.language,
            thumbnail_url=resolved.thumbnail_url,
        )

        # Build transcript
        full_text = " ".join(seg.text for seg in segments)
        speakers = list(set(seg.speaker for seg in segments))
        paragraphs = self._build_paragraphs(segments, block_seconds=60)
        transcript = FullTranscript(
            segments=segments,
            paragraphs=paragraphs,
            full_text=full_text,
            word_count=_count_words(full_text),
            speaker_count=len(speakers),
            speakers=speakers,
        )

        return PodcastKnowledge(
            metadata=metadata,
            transcript=transcript,
            summary=summary,
            agent_memory=agent_memory,
            processing=processing_info,
        )

    def save_to_file(self, knowledge: PodcastKnowledge, output_path: Path) -> Path:
        """Serialize and save to JSON file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        json_str = knowledge.model_dump_json(indent=2)
        # Ensure Chinese characters are preserved
        data = json.loads(json_str)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info("output_saved", path=str(output_path))
        return output_path

    @staticmethod
    def _build_paragraphs(
        segments: list[TranscriptSegment], block_seconds: int = 60
    ) -> list[TimedParagraph]:
        """Group segments into time-based paragraphs with speaker labels.

        When multiple speakers exist, text is formatted with speaker prefixes.
        """
        if not segments:
            return []

        # Detect if multiple speakers exist
        speakers = set(seg.speaker for seg in segments)
        multi_speaker = len(speakers) > 1

        paragraphs = []
        current_block_idx = 0
        current_texts: list[str] = []

        for seg in segments:
            block_idx = int(seg.start // block_seconds)

            if block_idx != current_block_idx and current_texts:
                # Flush previous block
                block_start = current_block_idx * block_seconds
                block_end = block_start + block_seconds
                m1, s1 = divmod(int(block_start), 60)
                m2, s2 = divmod(int(block_end), 60)
                paragraphs.append(TimedParagraph(
                    time_start=block_start,
                    time_end=block_end,
                    time_label=f"{m1:02d}:{s1:02d} - {m2:02d}:{s2:02d}",
                    text="".join(current_texts),
                ))
                current_texts = []
                current_block_idx = block_idx

            if multi_speaker:
                # Prefix with speaker label for multi-speaker content
                current_texts.append(f"[{seg.speaker}] {seg.text}\n")
            else:
                current_texts.append(seg.text)

        # Flush last block
        if current_texts:
            block_start = current_block_idx * block_seconds
            block_end = block_start + block_seconds
            m1, s1 = divmod(int(block_start), 60)
            m2, s2 = divmod(int(block_end), 60)
            paragraphs.append(TimedParagraph(
                time_start=block_start,
                time_end=block_end,
                time_label=f"{m1:02d}:{s1:02d} - {m2:02d}:{s2:02d}",
                text="".join(current_texts),
            ))

        return paragraphs
