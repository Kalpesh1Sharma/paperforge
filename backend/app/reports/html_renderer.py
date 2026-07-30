"""Standalone, deterministic HTML rendering for enhanced research reports."""

import re

from pydantic import ValidationError

from app.reports.composer import ReportComposer
from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportCompositionError,
    ReportRenderingError,
)
from app.reports.presentation_models import PresentationModel
from app.reports.template_loader import get_html_template, load_html_asset

_SUMMARY_PARAGRAPH_SEPARATOR = re.compile(r"\r?\n[ \t]*(?:\r?\n)+")
_EMPTY_STATE = "No information was extracted for this section."


class HTMLRenderer:
    """Render immutable ``EnhancedResearchReport`` values as standalone HTML."""

    def render(self, report: EnhancedResearchReport) -> str:
        """Compose and render one enhanced report with default source metadata."""
        try:
            presentation = ReportComposer().compose(report)
        except InvalidResearchReportError:
            raise
        except ReportCompositionError as exc:
            raise ReportRenderingError(
                "Unable to compose the enhanced research report."
            ) from exc
        return self.render_presentation(presentation)

    def render_presentation(self, presentation: PresentationModel) -> str:
        """Return a standalone HTML document from one presentation model."""
        self._validate_presentation_model(presentation)

        try:
            rendered_html = get_html_template("report.html.j2").render(
                presentation=presentation,
                css=load_html_asset("report.css"),
                print_css=load_html_asset("print.css"),
                empty_state=_EMPTY_STATE,
            )
        except InvalidResearchReportError:
            raise
        except ReportRenderingError:
            raise
        except Exception as exc:
            raise ReportRenderingError(
                "Unable to render the enhanced research report as HTML."
            ) from exc

        if not isinstance(rendered_html, str) or not rendered_html.strip():
            raise ReportRenderingError("HTML report rendering returned no document.")

        return rendered_html.rstrip("\n") + "\n"

    @staticmethod
    def _validate_presentation_model(presentation: object) -> None:
        """Defensively validate immutable, renderer-facing presentation data."""
        if not isinstance(presentation, PresentationModel):
            raise InvalidResearchReportError(
                "Input must be a PresentationModel instance."
            )
        if getattr(presentation, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "PresentationModel must not contain extra fields."
            )
        try:
            PresentationModel.model_validate(
                presentation.model_dump(mode="python", warnings="error")
            )
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "PresentationModel failed structural validation."
            ) from exc

    @classmethod
    def _validate_report(cls, report: object) -> None:
        """Defensively validate models, including validation-bypassed instances."""
        if not isinstance(report, EnhancedResearchReport):
            raise InvalidResearchReportError(
                "Input must be an EnhancedResearchReport instance."
            )
        if getattr(report, "__pydantic_extra__", None):
            raise InvalidResearchReportError(
                "EnhancedResearchReport must not contain extra fields."
            )

        try:
            payload = report.model_dump(mode="python", warnings="error")
            validated_report = EnhancedResearchReport.model_validate(payload)
        except (AttributeError, TypeError, ValidationError, ValueError) as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport failed structural validation."
            ) from exc
        except Exception as exc:
            raise InvalidResearchReportError(
                "EnhancedResearchReport could not be validated safely."
            ) from exc

        if not cls._summary_paragraphs(validated_report.executive_summary):
            raise InvalidResearchReportError(
                "EnhancedResearchReport executive_summary must not be blank."
            )

    @staticmethod
    def _summary_paragraphs(summary: str) -> tuple[str, ...]:
        """Split summary prose into semantic paragraphs without normalization."""
        return tuple(
            paragraph.strip()
            for paragraph in _SUMMARY_PARAGRAPH_SEPARATOR.split(summary.strip())
            if paragraph.strip()
        )
