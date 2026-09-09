"""Offline orchestration tests for the ordered multi-document pipeline."""

from pathlib import Path
from datetime import date
from uuid import UUID

from app.knowledge import KnowledgeObject
from app.models.document_chunk import DocumentChunk
from app.models.parsed_document import ParsedDocument
from app.parsers import ParserFactory
from app.reports import EnhancedResearchReport, ResearchReport, SynthesisMetadata
from app.services.pipeline_service import MultiDocumentPipelineArtifacts, PipelineService


_ALPHA = UUID("11111111-1111-4111-8111-111111111111")
_BETA = UUID("22222222-2222-4222-8222-222222222222")


def _document(filename: str) -> ParsedDocument:
    text = f"Evidence from {filename}."
    return ParsedDocument(
        filename=filename, file_type="pdf", extracted_text=text, page_count=1,
        word_count=3, character_count=len(text), metadata={},
    )


def _chunk(document: ParsedDocument, chunk_id: UUID) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=chunk_id, document_filename=document.filename, chunk_index=0,
        text=document.extracted_text, start_char=0, end_char=len(document.extracted_text),
        word_count=document.word_count, character_count=document.character_count,
        metadata={},
    )


def test_process_many_parses_and_chunks_each_source_before_one_combined_run(monkeypatch) -> None:
    """Structured chunks preserve upload order and original source identity."""
    parsed_paths: list[Path] = []
    chunked_documents: list[ParsedDocument] = []
    knowledge_inputs: list[tuple[DocumentChunk, ...]] = []
    calls = {"research": 0, "document": 0, "intelligence": 0, "composer": 0}

    def parse(path: Path) -> ParsedDocument:
        parsed_paths.append(path)
        return _document(path.name)

    class Chunker:
        def chunk(self, document: ParsedDocument) -> list[DocumentChunk]:
            chunked_documents.append(document)
            return [_chunk(document, _ALPHA if document.filename == "alpha.pdf" else _BETA)]

    class KnowledgePipelineDouble:
        def __init__(self, extractor: object) -> None:
            del extractor

        def process(self, chunks: list[DocumentChunk]) -> list[KnowledgeObject]:
            knowledge_inputs.append(tuple(chunks))
            return [
                KnowledgeObject(chunk_id=chunk.chunk_id, facts=(), definitions=(), metrics=(), dates=(), references=(), confidence=0.8)
                for chunk in chunks
            ]

    report = ResearchReport(title="Combined report", executive_summary="Combined evidence.")
    enhanced = EnhancedResearchReport(
        base_report=report, executive_summary="Combined evidence.",
        synthesis_metadata=SynthesisMetadata(provider="groq", model="test", elapsed_ms=0.0, successful=True),
    )

    class Research:
        def synthesize(self, knowledge: tuple[KnowledgeObject, ...]) -> ResearchReport:
            calls["research"] += 1
            assert len(knowledge) == 2
            return report

    class Document:
        def synthesize(self, received: ResearchReport, knowledge: tuple[KnowledgeObject, ...]) -> EnhancedResearchReport:
            calls["document"] += 1
            assert received is report and len(knowledge) == 2
            return enhanced

    class Intelligence:
        def build(self, received: EnhancedResearchReport, knowledge: tuple[KnowledgeObject, ...]) -> EnhancedResearchReport:
            calls["intelligence"] += 1
            assert received is enhanced and len(knowledge) == 2
            return enhanced

    class Composer:
        def compose(self, received: EnhancedResearchReport, **kwargs: object) -> object:
            calls["composer"] += 1
            assert received is enhanced
            assert tuple(document.filename for document in kwargs["source_documents"]) == ("alpha.pdf", "beta.pdf")
            assert tuple(chunk.document_filename for chunk in kwargs["source_chunks"]) == ("alpha.pdf", "beta.pdf")
            assert isinstance(kwargs["generated_on"], date)
            return object()

    monkeypatch.setattr(ParserFactory, "parse", staticmethod(parse))
    monkeypatch.setattr("app.services.pipeline_service.KnowledgePipeline", KnowledgePipelineDouble)
    service = PipelineService(
        chunker=Chunker(), knowledge_extractor=object(), research_synthesizer=Research(),
        document_synthesizer=Document(), intelligence_builder=Intelligence(), composer=Composer(),
    )

    artifacts = service.process_many(
        (Path("sources/001_alpha.pdf"), Path("sources/002_beta.pdf")),
        ("alpha.pdf", "beta.pdf"),
    )

    assert isinstance(artifacts, MultiDocumentPipelineArtifacts)
    assert parsed_paths == [Path("sources/001_alpha.pdf"), Path("sources/002_beta.pdf")]
    assert tuple(document.filename for document in chunked_documents) == ("alpha.pdf", "beta.pdf")
    assert tuple(chunk.chunk_id for chunk in knowledge_inputs[0]) == (_ALPHA, _BETA)
    assert calls == {"research": 1, "document": 1, "intelligence": 1, "composer": 1}
