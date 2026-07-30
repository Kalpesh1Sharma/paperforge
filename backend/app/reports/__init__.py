"""Deterministic research report foundation primitives."""

from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportError,
    ReportRenderingError,
    ReportSynthesisError,
)
from app.reports.enhanced_models import (
    EnhancedResearchReport,
    SynthesisSourceEvidence,
    SynthesizedSection,
    SynthesisMetadata,
)
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.html_renderer import HTMLRenderer
from app.reports.intelligence import (
    ConsolidatedDefinition,
    ConsolidatedReference,
    EnrichedFinding,
    EntityGroup,
    IntelligentTimelineEvent,
    NormalizedEntity,
    ReportIntelligence,
    ReportIntelligenceBuilder,
)
from app.reports.pdf_renderer import PDFRenderer
from app.reports.models import Finding, ReportSection, ResearchReport, TimelineEvent
from app.reports.renderer import MarkdownRenderer
from app.reports.synthesizer import ResearchSynthesizer

__all__ = [
    "EnhancedResearchReport",
    "DocumentSynthesizer",
    "ConsolidatedDefinition",
    "ConsolidatedReference",
    "EnrichedFinding",
    "EntityGroup",
    "Finding",
    "HTMLRenderer",
    "InvalidResearchReportError",
    "IntelligentTimelineEvent",
    "MarkdownRenderer",
    "NormalizedEntity",
    "PDFRenderer",
    "ReportError",
    "ReportRenderingError",
    "ReportSection",
    "ReportSynthesisError",
    "ResearchReport",
    "ReportIntelligence",
    "ReportIntelligenceBuilder",
    "ResearchSynthesizer",
    "SynthesisSourceEvidence",
    "SynthesizedSection",
    "SynthesisMetadata",
    "TimelineEvent",
]
