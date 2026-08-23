"""Meaningful exceptions raised by the research report layer."""


class ReportError(Exception):
    """Base exception raised by the research report layer."""


class InvalidResearchReportError(ReportError):
    """Raised when a report fails structural or invariant validation."""


class ReportSynthesisError(ReportError):
    """Raised when knowledge objects cannot be synthesized into a report."""


class ReportCompositionError(ReportError):
    """Raised when a validated report cannot be composed for presentation."""


class ReportRenderingError(ReportError):
    """Raised when a validated report cannot be rendered as Markdown."""
