"""Tests for the deterministic, dependency-free mock knowledge provider."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import inspect
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.knowledge import KnowledgeExtractor, KnowledgeObject, MockKnowledgeProvider
from app.models.document_chunk import DocumentChunk


def _chunk(text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(),
        document_filename="research.txt",
        chunk_index=0,
        text=text,
        start_char=0,
        end_char=len(text),
        word_count=len(text.split()),
        character_count=len(text),
        metadata={"source_file_type": "txt", "source_metadata": {}},
    )


def test_provider_extracts_all_rule_based_knowledge_in_source_order() -> None:
    chunk = _chunk(
        "Albert Einstein collaborated with NASA in New York. "
        "Apollo Mission launched in 1969 on 2025-07-28. "
        "July 2025 recorded 95% of 12 kg across 25 km, costing $250 with "
        "a value of 3.14 and 1000 samples. "
        "Relativity refers to a theory of space and time. "
        "Read [project notes](https://example.com/notes) and visit "
        "http://example.org/reference."
    )

    knowledge = MockKnowledgeProvider().extract(chunk)

    assert knowledge.entities == (
        "Albert Einstein",
        "NASA",
        "New York",
        "Apollo Mission",
    )
    assert knowledge.dates == ("1969", "2025-07-28", "July 2025")
    assert knowledge.metrics == ("95%", "12 kg", "25 km", "$250", "3.14", "1000")
    assert knowledge.definitions == (
        "Relativity refers to a theory of space and time.",
    )
    assert knowledge.facts == (
        "Albert Einstein collaborated with NASA in New York.",
        "Apollo Mission launched in 1969 on 2025-07-28.",
        "July 2025 recorded 95% of 12 kg across 25 km, costing $250 with "
        "a value of 3.14 and 1000 samples.",
        "Relativity refers to a theory of space and time.",
        "Read [project notes](https://example.com/notes) and visit "
        "http://example.org/reference.",
    )
    assert knowledge.references == (
        "[project notes](https://example.com/notes)",
        "http://example.org/reference",
    )
    assert knowledge.confidence == 1.0


def test_entities_are_deduplicated_while_preserving_first_occurrence() -> None:
    chunk = _chunk("NASA collaborated with NASA. Albert Einstein met Albert Einstein.")

    knowledge = MockKnowledgeProvider().extract(chunk)

    assert knowledge.entities == ("NASA", "Albert Einstein")


def test_composite_matches_suppress_nested_year_urls_and_numbers() -> None:
    chunk = _chunk(
        "NASA reported 95% from 12 kg for $250 on 2025-07-28. "
        "Read [source](https://example.com/2025) and http://example.org/1000."
    )

    knowledge = MockKnowledgeProvider().extract(chunk)

    assert knowledge.dates == ("2025-07-28",)
    assert knowledge.metrics == ("95%", "12 kg", "$250")
    assert knowledge.references == (
        "[source](https://example.com/2025)",
        "http://example.org/1000",
    )


def test_provider_returns_empty_collections_when_no_rules_match() -> None:
    chunk = _chunk("lowercase tokens without ending punctuation")

    knowledge = MockKnowledgeProvider().extract(chunk)

    assert knowledge.chunk_id == chunk.chunk_id
    assert knowledge.entities == ()
    assert knowledge.facts == ()
    assert knowledge.definitions == ()
    assert knowledge.metrics == ()
    assert knowledge.dates == ()
    assert knowledge.references == ()
    assert knowledge.confidence == 1.0


def test_provider_is_deterministic_stateless_synchronous_and_thread_safe() -> None:
    chunk = _chunk("Albert Einstein worked with NASA in 2025.")
    provider = MockKnowledgeProvider()

    first = provider.extract(chunk)
    second = provider.extract(chunk)
    with ThreadPoolExecutor(max_workers=4) as executor:
        concurrent_results = list(executor.map(provider.extract, [chunk] * 8))

    assert not inspect.iscoroutinefunction(provider.extract)
    assert provider.__dict__ == {}
    assert first == second
    assert first is not second
    assert concurrent_results == [first] * 8


def test_provider_preserves_input_and_returns_immutable_knowledge_object() -> None:
    chunk = _chunk("NASA completed the research in 2025.")
    before = deepcopy(chunk.model_dump(mode="python"))

    knowledge = MockKnowledgeProvider().extract(chunk)

    assert isinstance(knowledge, KnowledgeObject)
    assert knowledge.chunk_id == chunk.chunk_id
    assert chunk.model_dump(mode="python") == before
    with pytest.raises(ValidationError):
        knowledge.confidence = 0.5
    with pytest.raises(AttributeError):
        knowledge.entities.append("New entity")  # type: ignore[attr-defined]


def test_mock_provider_integrates_with_knowledge_extractor() -> None:
    chunk = _chunk("Albert Einstein worked with NASA in 2025.")

    knowledge = KnowledgeExtractor(MockKnowledgeProvider()).extract(chunk)

    assert isinstance(knowledge, KnowledgeObject)
    assert knowledge.chunk_id == chunk.chunk_id
    assert knowledge.confidence == 1.0


def test_demo_script_processes_the_bundled_sample_pdf() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    script_path = backend_root / "scripts" / "mock_provider_demo.py"

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert "=" * 50 in result.stdout
    assert "Chunk 0" in result.stdout
    assert "Entities" in result.stdout
    assert "Dates" in result.stdout
    assert "Metrics" in result.stdout
    assert "Definitions" in result.stdout
    assert "Facts" in result.stdout
    assert "References" in result.stdout
    assert "Confidence\n1.0" in result.stdout
