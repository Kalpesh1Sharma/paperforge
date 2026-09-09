"""Synchronous orchestration of the existing PaperForge domain pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.ai.factory import build_provider_collaborators
from app.chunking import DocumentChunker
from app.chunking.exceptions import ChunkingError
from app.knowledge import KnowledgeExtractor, KnowledgePipeline, KnowledgeObject
from app.knowledge.exceptions import (
    GroqRateLimitError,
    GroqTemporaryServiceError,
    KnowledgeError,
)
from app.models.document_chunk import DocumentChunk
from app.models.parsed_document import ParsedDocument
from app.parsers import ParserFactory
from app.parsers.base import DocumentParsingError
from app.reports import (
    DocumentSynthesizer,
    EnhancedResearchReport,
    PresentationModel,
    ReportMode,
    ReportComposer,
    ReportIntelligenceBuilder,
    ResearchReport,
    ResearchSynthesizer,
)
from app.reports.exceptions import ReportError

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, str], None]


class PipelineServiceError(RuntimeError):
    """Base error raised by the HTTP-facing pipeline adapter."""


class InvalidDocumentError(PipelineServiceError):
    """Raised when a persisted upload cannot produce a source document."""


class ProviderRateLimitedError(PipelineServiceError):
    """Raised when a provider rate limit reaches the integration boundary."""


class TemporaryProviderUnavailableError(PipelineServiceError):
    """Raised when a nonrecoverable temporary provider error reaches the API."""


class PipelineGenerationError(PipelineServiceError):
    """Raised when validated pipeline inputs cannot form a report artifact."""


@dataclass(frozen=True, slots=True)
class PipelineArtifacts:
    """Immutable values produced by one complete document-processing run."""

    source_document: ParsedDocument
    chunks: tuple[DocumentChunk, ...]
    knowledge_objects: tuple[KnowledgeObject, ...]
    research_report: ResearchReport
    enhanced_report: EnhancedResearchReport
    presentation: PresentationModel


@dataclass(frozen=True, slots=True)
class MultiDocumentPipelineArtifacts:
    """Immutable values produced by one combined structured-evidence run."""

    source_documents: tuple[ParsedDocument, ...]
    chunks: tuple[DocumentChunk, ...]
    knowledge_objects: tuple[KnowledgeObject, ...]
    research_report: ResearchReport
    enhanced_report: EnhancedResearchReport
    presentation: PresentationModel


class PipelineService:
    """Run established PaperForge components in their canonical order.

    This class deliberately owns no parsing, extraction, synthesis, or
    rendering logic. Collaborators are injectable so HTTP tests and future
    deployments can replace an integration without changing the pipeline.
    """

    def __init__(
        self,
        *,
        chunker: DocumentChunker | None = None,
        knowledge_extractor: KnowledgeExtractor | None = None,
        research_synthesizer: ResearchSynthesizer | None = None,
        document_synthesizer: DocumentSynthesizer | None = None,
        intelligence_builder: ReportIntelligenceBuilder | None = None,
        composer: ReportComposer | None = None,
    ) -> None:
        provider_collaborators = None
        if knowledge_extractor is None or document_synthesizer is None:
            provider_collaborators = build_provider_collaborators()
        self._chunker = chunker or DocumentChunker()
        self._knowledge_extractor = knowledge_extractor or KnowledgeExtractor(
            provider_collaborators.knowledge_provider
        )
        self._research_synthesizer = research_synthesizer or ResearchSynthesizer()
        self._document_synthesizer = (
            document_synthesizer or provider_collaborators.document_synthesizer
        )
        self._intelligence_builder = intelligence_builder or ReportIntelligenceBuilder()
        self._composer = composer or ReportComposer()

    def process(
        self,
        input_path: Path,
        *,
        mode: ReportMode | None = None,
        progress: ProgressCallback | None = None,
    ) -> PipelineArtifacts:
        """Produce immutable presentation data from one persisted PDF upload."""
        path = Path(input_path)
        try:
            logger.info("Pipeline stage=parse | filename=%s", path.name)
            self._progress(progress, "parsing", 18, "Reading the source document")
            source_document = ParserFactory.parse(path)

            logger.info("Pipeline stage=chunk | filename=%s", path.name)
            self._progress(progress, "chunking", 32, "Organising source passages")
            chunks = tuple(self._chunker.chunk(source_document))

            logger.info("Pipeline stage=knowledge | filename=%s", path.name)
            self._progress(progress, "extracting", 48, "Extracting grounded evidence")
            knowledge_objects = KnowledgePipeline(self._knowledge_extractor).process(
                list(chunks)
            )
            knowledge_tuple = tuple(knowledge_objects)

            logger.info("Pipeline stage=research | filename=%s", path.name)
            self._progress(progress, "researching", 60, "Structuring the research findings")
            research_report = self._research_synthesizer.synthesize(knowledge_tuple)

            logger.info("Pipeline stage=document_synthesis | filename=%s", path.name)
            self._progress(progress, "synthesizing", 72, "Writing the grounded report")
            enhanced_report = self._document_synthesizer.synthesize(
                research_report,
                knowledge_tuple,
            )

            logger.info("Pipeline stage=intelligence | filename=%s", path.name)
            self._progress(progress, "reviewing", 82, "Checking evidence and report structure")
            intelligent_report = self._intelligence_builder.build(
                enhanced_report,
                knowledge_tuple,
            )

            logger.info("Pipeline stage=composition | filename=%s", path.name)
            self._progress(progress, "composing", 88, "Composing the publication layout")
            composer = self._composer if mode is None else ReportComposer(mode=mode)
            presentation = composer.compose(
                intelligent_report,
                source_document=source_document,
                generated_on=datetime.now(timezone.utc).date(),
            )
        except DocumentParsingError as exc:
            raise InvalidDocumentError("The uploaded file is not a valid PDF.") from exc
        except ChunkingError as exc:
            raise InvalidDocumentError(
                "The uploaded PDF does not contain usable document text."
            ) from exc
        except GroqRateLimitError as exc:
            raise ProviderRateLimitedError(
                "The knowledge provider is currently rate limited."
            ) from exc
        except GroqTemporaryServiceError as exc:
            raise TemporaryProviderUnavailableError(
                "The knowledge provider is temporarily unavailable."
            ) from exc
        except KnowledgeError as exc:
            raise TemporaryProviderUnavailableError(
                "Knowledge extraction could not complete."
            ) from exc
        except ReportError as exc:
            raise TemporaryProviderUnavailableError(
                "Report generation could not complete."
            ) from exc

        return PipelineArtifacts(
            source_document=source_document,
            chunks=chunks,
            knowledge_objects=knowledge_tuple,
            research_report=research_report,
            enhanced_report=intelligent_report,
            presentation=presentation,
        )

    def process_many(
        self,
        input_paths: tuple[Path, ...],
        source_filenames: tuple[str, ...],
        *,
        mode: ReportMode | None = None,
        progress: ProgressCallback | None = None,
    ) -> MultiDocumentPipelineArtifacts:
        """Process ordered PDFs independently before one combined synthesis."""
        if len(input_paths) < 2 or len(input_paths) != len(source_filenames):
            raise InvalidDocumentError("At least two valid source PDFs are required.")
        try:
            source_documents: list[ParsedDocument] = []
            self._progress(progress, "parsing", 15, "Reading the source documents")
            for path, filename in zip(input_paths, source_filenames, strict=True):
                logger.info("Pipeline stage=parse | filename=%s", filename)
                parsed = ParserFactory.parse(Path(path)).model_copy(
                    update={"filename": filename}
                )
                source_documents.append(parsed)
            chunks: list[DocumentChunk] = []
            self._progress(progress, "chunking", 32, "Organising source passages")
            for parsed, filename in zip(
                source_documents, source_filenames, strict=True
            ):
                logger.info("Pipeline stage=chunk | filename=%s", filename)
                chunks.extend(self._chunker.chunk(parsed))
            chunk_tuple = tuple(chunks)
            logger.info("Pipeline stage=knowledge | sources=%d", len(source_documents))
            self._progress(progress, "extracting", 48, "Extracting grounded evidence")
            knowledge_tuple = tuple(
                KnowledgePipeline(self._knowledge_extractor).process(list(chunk_tuple))
            )
            self._progress(progress, "researching", 60, "Structuring the research findings")
            research_report = self._research_synthesizer.synthesize(knowledge_tuple)
            self._progress(progress, "synthesizing", 72, "Writing the grounded report")
            enhanced_report = self._document_synthesizer.synthesize(
                research_report, knowledge_tuple
            )
            self._progress(progress, "reviewing", 82, "Checking evidence and report structure")
            intelligent_report = self._intelligence_builder.build(
                enhanced_report, knowledge_tuple
            )
            self._progress(progress, "composing", 88, "Composing the publication layout")
            composer = self._composer if mode is None else ReportComposer(mode=mode)
            presentation = composer.compose(
                intelligent_report,
                source_documents=tuple(source_documents),
                source_chunks=chunk_tuple,
                generated_on=datetime.now(timezone.utc).date(),
            )
        except DocumentParsingError as exc:
            raise InvalidDocumentError("The uploaded file is not a valid PDF.") from exc
        except ChunkingError as exc:
            raise InvalidDocumentError("The uploaded PDF does not contain usable document text.") from exc
        except GroqRateLimitError as exc:
            raise ProviderRateLimitedError("The knowledge provider is currently rate limited.") from exc
        except GroqTemporaryServiceError as exc:
            raise TemporaryProviderUnavailableError("The knowledge provider is temporarily unavailable.") from exc
        except KnowledgeError as exc:
            raise TemporaryProviderUnavailableError("Knowledge extraction could not complete.") from exc
        except ReportError as exc:
            raise TemporaryProviderUnavailableError("Report generation could not complete.") from exc
        return MultiDocumentPipelineArtifacts(
            source_documents=tuple(source_documents), chunks=chunk_tuple,
            knowledge_objects=knowledge_tuple, research_report=research_report,
            enhanced_report=intelligent_report, presentation=presentation,
        )

    @staticmethod
    def _progress(
        callback: ProgressCallback | None,
        stage: str,
        percent: int,
        message: str,
    ) -> None:
        if callback is not None:
            callback(stage, percent, message)
