"""Deterministic research report foundation primitives."""

from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportCompositionError,
    ReportError,
    ReportRenderingError,
    ReportSynthesisError,
)
from app.reports.composer import ReportComposer
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
from app.reports.presentation_models import (
    AppendixGroup,
    CompressionStatistic,
    ConceptCard,
    DocumentMetadata,
    EntityCard,
    EntityPresentationGroup,
    EvidenceTable,
    GroupedFinding,
    HiddenPresentationData,
    InsightCard,
    MetricCard,
    PresentationBudget,
    PresentationEvidence,
    PresentationModel,
    PresentationSection,
    ReferenceCard,
    ReportMode,
    TableOfContents,
    TableOfContentsEntry,
    TimelineCard,
)
from app.reports.renderer import MarkdownRenderer
from app.reports.synthesizer import ResearchSynthesizer

__all__ = [
    "EnhancedResearchReport",
    "DocumentSynthesizer",
    "ConsolidatedDefinition",
    "ConsolidatedReference",
    "CompressionStatistic",
    "ConceptCard",
    "DocumentMetadata",
    "EnrichedFinding",
    "EntityGroup",
    "EntityCard",
    "EntityPresentationGroup",
    "EvidenceTable",
    "Finding",
    "GroupedFinding",
    "HiddenPresentationData",
    "HTMLRenderer",
    "InvalidResearchReportError",
    "InsightCard",
    "IntelligentTimelineEvent",
    "MarkdownRenderer",
    "MetricCard",
    "NormalizedEntity",
    "PDFRenderer",
    "ReportError",
    "ReportComposer",
    "ReportCompositionError",
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
    "PresentationEvidence",
    "PresentationBudget",
    "PresentationModel",
    "PresentationSection",
    "ReferenceCard",
    "ReportMode",
    "TableOfContents",
    "TableOfContentsEntry",
    "TimelineCard",
    "TimelineEvent",
]
