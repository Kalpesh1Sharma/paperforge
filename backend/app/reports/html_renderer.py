"""Standalone, deterministic HTML rendering for enhanced research reports."""

import re

from pydantic import ValidationError

from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportRenderingError,
)
from app.reports.template_loader import get_html_template, load_html_asset
from app.reports.presentation import EnhancedReportRenderContext

_SUMMARY_PARAGRAPH_SEPARATOR = re.compile(r"\r?\n[ \t]*(?:\r?\n)+")
_EMPTY_STATE = "No information was extracted for this section."


class HTMLRenderer:
    """Render immutable ``EnhancedResearchReport`` values as standalone HTML."""

    def render(self, report: EnhancedResearchReport) -> str:
        """Return a complete, self-contained HTML document for one report."""
        self._validate_report(report)

        try:
            render_context = EnhancedReportRenderContext.from_report(report)
            rendered_html = get_html_template("report.html.j2").render(
                report=report,
                base_report=report.base_report,
                render_context=render_context,
                summary_paragraphs=self._summary_paragraphs(
                    report.executive_summary
                ),
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
