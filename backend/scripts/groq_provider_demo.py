"""Run Groq-backed knowledge extraction over the bundled sample PDF."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.chunking import DocumentChunker
from app.knowledge import GroqKnowledgeProvider, KnowledgeExtractor
from app.parsers import ParserFactory


def _print_section(name: str, values: tuple[str, ...]) -> None:
    """Print one ordered collection from a KnowledgeObject."""
    print(name)
    for value in values:
        print(value)
    print()


def main() -> None:
    """Parse, chunk, and extract knowledge from the bundled sample PDF."""
    document = ParserFactory.parse(PROJECT_ROOT / "sample.pdf")
    chunks = DocumentChunker().chunk(document)
    extractor = KnowledgeExtractor(GroqKnowledgeProvider())

    for chunk in chunks:
        knowledge = extractor.extract(chunk)
        print("=" * 50)
        print(f"Chunk {chunk.chunk_index}")
        print(f"Confidence: {knowledge.confidence}")
        _print_section("Entities", knowledge.entities)
        _print_section("Facts", knowledge.facts)
        _print_section("Definitions", knowledge.definitions)
        _print_section("Metrics", knowledge.metrics)
        _print_section("Dates", knowledge.dates)
        _print_section("References", knowledge.references)


if __name__ == "__main__":
    main()
