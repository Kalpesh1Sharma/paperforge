"""Document refinement that never sends source material to an AI provider."""

from time import perf_counter

from app.knowledge.models import KnowledgeObject
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.models import ResearchReport
from app.reports.refinement import ReportRefiner


class DeterministicDocumentSynthesizer(DocumentSynthesizer):
    """Build the standard deterministic refinement with no API key."""

    def __init__(self, reason: str = "provider_disabled") -> None:
        self._reason = reason

    def synthesize(
        self,
        report: ResearchReport,
        knowledge_objects: tuple[KnowledgeObject, ...],
    ) -> EnhancedResearchReport:
        started_at = perf_counter()
        self._validate_report(report)
        self._validate_knowledge_objects(knowledge_objects)
        self._validate_base_provenance(report, knowledge_objects)
        plan = ReportRefiner.build_plan(report, knowledge_objects)
        return self._build_fallback_report(
            report,
            plan,
            started_at,
            self._reason,
        )
