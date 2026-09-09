"""Ordered document-synthesis failover with deterministic completion."""

import logging

from app.knowledge.models import KnowledgeObject
from app.reports.deterministic_document_synthesizer import (
    DeterministicDocumentSynthesizer,
)
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import ReportSynthesisError
from app.reports.models import ResearchReport

logger = logging.getLogger(__name__)


class FailoverDocumentSynthesizer(DocumentSynthesizer):
    """Try every configured remote synthesizer before local synthesis."""

    def __init__(
        self,
        synthesizers: tuple[tuple[str, DocumentSynthesizer], ...],
    ) -> None:
        self._synthesizers = synthesizers

    def synthesize(
        self,
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> EnhancedResearchReport:
        self._validate_report(report)
        self._validate_knowledge_objects(knowledge_objects)
        self._validate_base_provenance(report, knowledge_objects)

        for index, (name, synthesizer) in enumerate(self._synthesizers):
            try:
                result = synthesizer.synthesize(report, knowledge_objects)
            except ReportSynthesisError:
                self._log_failover(name, index, "request_rejected")
                continue
            if not result.synthesis_metadata.fallback:
                return result
            self._log_failover(
                name,
                index,
                result.synthesis_metadata.reason or "provider_failure",
            )

        reason = (
            "providers_exhausted"
            if self._synthesizers
            else "no_provider_configured"
        )
        return DeterministicDocumentSynthesizer(reason=reason).synthesize(
            report, knowledge_objects
        )

    def _log_failover(self, provider: str, index: int, reason: str) -> None:
        next_provider = (
            self._synthesizers[index + 1][0]
            if index + 1 < len(self._synthesizers)
            else "deterministic"
        )
        logger.warning(
            "Document synthesis failover | from_provider=%s | to_provider=%s | "
            "reason=%s",
            provider,
            next_provider,
            reason,
        )
