"""Prompt definitions for structured knowledge extraction."""

KNOWLEDGE_EXTRACTION_SYSTEM_PROMPT = """
Extract structured research knowledge from the supplied document chunk.

Return exactly one JSON object and nothing else. Do not use Markdown, prose,
explanations, or code fences. The object must contain only these fields:
entities, facts, definitions, metrics, dates, references, and confidence.
Each collection field must be an array of strings. confidence must be a number
from 0 to 1. Include every field even when its value is empty.
""".strip()

KNOWLEDGE_EXTRACTION_USER_PROMPT = ""
