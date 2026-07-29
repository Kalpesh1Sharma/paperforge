"""Deterministic research report foundation primitives."""

from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportError,
    ReportRenderingError,
    ReportSynthesisError,
)
from app.reports.enhanced_models import (
    EnhancedResearchReport,
    SynthesizedSection,
    SynthesisMetadata,
)
from app.reports.document_synthesizer import DocumentSynthesizer
from app.reports.models import Finding, ReportSection, ResearchReport, TimelineEvent
from app.reports.renderer import MarkdownRenderer
from app.reports.synthesizer import ResearchSynthesizer

__all__ = [
    "EnhancedResearchReport",
    "DocumentSynthesizer",
    "Finding",
    "InvalidResearchReportError",
    "MarkdownRenderer",
    "ReportError",
    "ReportRenderingError",
    "ReportSection",
    "ReportSynthesisError",
    "ResearchReport",
    "ResearchSynthesizer",
    "SynthesizedSection",
    "SynthesisMetadata",
    "TimelineEvent",
]
