"""Safe, provider-neutral transforms for user-controlled report editing."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai import CompatibleChatClient, GeminiNativeChatClient
from app.ai.configuration import ProviderConfiguration, configured_provider_order
from app.ai.exceptions import CompatibleAIError
from app.config import settings
from app.reports.presentation_models import PresentationSection

logger = logging.getLogger(__name__)

TransformAction = Literal["rewrite", "shorten", "expand"]
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")


class _TransformResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=30000)


@dataclass(frozen=True, slots=True)
class SectionTransformResult:
    content: str
    provider: str
    fallback: bool


def editable_section_text(section: PresentationSection) -> str:
    """Project typed presentation content into a readable editor buffer."""
    if section.edited_content is not None:
        return section.edited_content

    blocks: list[str] = list(section.intro)
    for group in section.finding_groups:
        if group.heading != "General":
            blocks.append(group.heading)
        for finding in group.findings:
            if not finding.summary_includes_title:
                blocks.append(finding.title)
            if finding.summary != finding.title or finding.summary_includes_title:
                blocks.append(finding.summary)
    for group in section.entity_groups:
        blocks.append(group.category)
        blocks.extend(entity.name for entity in group.entities)
    for concept in section.concepts:
        blocks.extend((concept.concept, concept.definition))
        if concept.why_it_matters:
            blocks.append(f"Why it matters: {concept.why_it_matters}")
    for event in section.timeline:
        blocks.append(f"{event.date}: {event.description}")
    for table in section.evidence_tables:
        blocks.append(table.title)
        blocks.extend(" | ".join(row) for row in table.rows)
    for group in section.appendix_groups:
        blocks.append(group.heading)
        blocks.extend(finding.summary for finding in group.findings)
        blocks.extend(concept.definition for concept in group.concepts)
        blocks.extend(reference.reference for reference in group.references)
    blocks.extend(reference.reference for reference in section.references)
    return "\n\n".join(block.strip() for block in blocks if block.strip()) or (
        "No material is currently available for this section."
    )


class SectionTransformer:
    """Try the configured BYOK chain and retain a safe local fallback."""

    def transform(
        self,
        content: str,
        action: TransformAction,
        *,
        heading: str,
    ) -> SectionTransformResult:
        source = content.strip()
        if not source:
            raise ValueError("Section content must not be blank.")
        for configuration in configured_provider_order():
            if configuration.name == "deterministic" or not self._complete(configuration):
                continue
            try:
                client = self._client(configuration)
                response = client.complete(self._messages(source, action, heading))
                parsed = _TransformResponse.model_validate_json(response)
                return SectionTransformResult(
                    content=parsed.content.strip(),
                    provider=configuration.name,
                    fallback=False,
                )
            except (CompatibleAIError, ValidationError, ValueError, json.JSONDecodeError):
                logger.warning(
                    "Section edit provider failed; trying next provider | provider=%s | action=%s",
                    configuration.name,
                    action,
                )
        return SectionTransformResult(
            content=self._deterministic(source, action),
            provider="deterministic",
            fallback=True,
        )

    @staticmethod
    def _complete(configuration: ProviderConfiguration) -> bool:
        return bool(configuration.api_key and configuration.model) and (
            configuration.name == "groq" or bool(configuration.base_url)
        )

    @staticmethod
    def _client(configuration: ProviderConfiguration) -> CompatibleChatClient:
        if configuration.name == "groq":
            configuration = ProviderConfiguration(
                name="groq",
                api_key=configuration.api_key,
                model=configuration.model,
                base_url="https://api.groq.com/openai/v1",
            )
        client_type = (
            GeminiNativeChatClient
            if configuration.name == "gemini"
            else CompatibleChatClient
        )
        return client_type(
            configuration,
            max_retries=settings.ai_max_retries,
            retry_base_seconds=settings.ai_retry_base_seconds,
            timeout_seconds=settings.ai_timeout_seconds,
        )

    @staticmethod
    def _messages(
        content: str,
        action: TransformAction,
        heading: str,
    ) -> list[dict[str, str]]:
        instructions = {
            "rewrite": "Improve clarity and flow while preserving every supported fact.",
            "shorten": "Make the text materially shorter while preserving its central supported claims.",
            "expand": "Add helpful explanation and transitions without adding unsupported facts.",
        }
        payload = json.dumps(
            {"heading": heading, "action": action, "content": content},
            ensure_ascii=False,
        )
        return [
            {
                "role": "system",
                "content": (
                    "You edit one evidence-grounded report section. "
                    f"{instructions[action]} Return JSON only as {{\"content\": \"...\"}}. "
                    "Do not add citations, statistics, names, or claims absent from the supplied text."
                ),
            },
            {"role": "user", "content": payload},
        ]

    @staticmethod
    def _deterministic(content: str, action: TransformAction) -> str:
        normalized = "\n\n".join(
            " ".join(block.split())
            for block in re.split(r"\n\s*\n", content)
            if block.strip()
        )
        if action != "shorten":
            return normalized
        sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(normalized) if part.strip()]
        if len(sentences) <= 1:
            words = normalized.split()
            return " ".join(words[: max(1, round(len(words) * 0.65))])
        keep = max(1, round(len(sentences) * 0.6))
        return " ".join(sentences[:keep])
