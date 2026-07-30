"""Playwright-backed PDF rendering for enhanced PaperForge reports."""

import logging
import re
import tempfile
from pathlib import Path

import fitz
from playwright.sync_api import sync_playwright

from app.reports.enhanced_models import EnhancedResearchReport
from app.reports.exceptions import (
    InvalidResearchReportError,
    ReportRenderingError,
)
from app.reports.html_renderer import HTMLRenderer
from app.reports.presentation_models import PresentationModel

logger = logging.getLogger(__name__)

_PDF_INFO_METADATA = {
    "title": "PaperForge Research Report",
    "author": "PaperForge",
    "creator": "PaperForge",
    "subject": "AI Research Report",
}
_PDF_LANGUAGE = "en"
_TOC_PAGE_REFERENCE_PATTERN = re.compile(
    r'(?P<opening><span class="toc-page-reference" data-target="#'
    r'(?P<anchor>[a-z0-9-]+)" aria-hidden="true">)'
    r'(?P<value>.*?)(?P<closing></span>)'
)


class PDFRenderer:
    """Render an enhanced research report into a standalone A4 PDF."""

    def render(
        self,
        report: EnhancedResearchReport,
        output_path: Path,
    ) -> Path:
        """Render ``report`` to ``output_path`` and return its absolute path.

        The existing HTML renderer remains the sole presentation source.  This
        method creates private temporary HTML and PDF files beside the final
        output so replacing an existing PDF happens only after a complete,
        metadata-bearing PDF has been created successfully.
        """
        resolved_output_path = self._prepare_output_path(output_path)
        html = self._render_html(report)

        return self._render_html_document(html, resolved_output_path)

    def render_presentation(
        self,
        presentation: PresentationModel,
        output_path: Path,
    ) -> Path:
        """Render one composed presentation model into a standalone A4 PDF.

        The presentation model is the renderer-facing, immutable report view.
        It is materialized by :class:`ReportComposer` before reaching this
        adapter, so this method deliberately delegates all HTML construction to
        :class:`HTMLRenderer` and shares the existing PDF export lifecycle.
        """
        resolved_output_path = self._prepare_output_path(output_path)
        html = self._render_presentation_html(presentation)

        return self._render_html_document(html, resolved_output_path)

    @classmethod
    def _render_html_document(cls, html: str, resolved_output_path: Path) -> Path:
        """Export already-rendered HTML through the shared PDF lifecycle."""

        try:
            with tempfile.TemporaryDirectory(
                prefix=".paperforge-pdf-",
                dir=str(resolved_output_path.parent),
            ) as temporary_directory:
                temporary_path = Path(temporary_directory)
                html_path = temporary_path / "report.html"
                layout_pdf_path = temporary_path / "toc-layout.pdf"
                pdf_path = temporary_path / "report.pdf"

                cls._write_html(html_path, html)
                cls._render_html_with_toc_references(
                    html,
                    html_path,
                    layout_pdf_path,
                    pdf_path,
                )
                cls._validate_pdf_file(pdf_path)
                cls._write_pdf_metadata(pdf_path)
                cls._validate_pdf_file(pdf_path)
                cls._replace_output(pdf_path, resolved_output_path)
        except (InvalidResearchReportError, ReportRenderingError):
            raise
        except OSError as exc:
            raise ReportRenderingError(
                "Unable to prepare temporary files for PDF rendering."
            ) from exc
        except Exception as exc:
            raise ReportRenderingError("Unable to render the PDF report.") from exc

        logger.info("Rendered PDF report to %s", resolved_output_path)
        return resolved_output_path

    @classmethod
    def _render_html_with_toc_references(
        cls,
        html: str,
        html_path: Path,
        layout_pdf_path: Path,
        pdf_path: Path,
    ) -> None:
        """Render once or resolve model-owned TOC links before final export.

        Chromium does not yet implement CSS ``target-counter()``.  When the
        rendered document contains the existing TOC page-reference markers,
        a private first pass supplies the physical destinations from the
        browser-created internal links.  The second pass remains a pure HTML
        render and keeps ``HTMLRenderer`` as the presentation source of truth.
        """
        anchors = cls._toc_anchor_ids(html)
        if not anchors:
            cls._render_pdf(html_path, pdf_path)
            return

        cls._render_pdf(html_path, layout_pdf_path)
        cls._validate_pdf_file(layout_pdf_path)
        page_numbers = cls._toc_page_numbers(layout_pdf_path, anchors)
        rendered_html = cls._with_toc_page_numbers(html, page_numbers)

        if rendered_html == html:
            layout_pdf_path.replace(pdf_path)
            return

        cls._write_html(html_path, rendered_html)
        cls._render_pdf(html_path, pdf_path)

    @staticmethod
    def _toc_anchor_ids(html: str) -> tuple[str, ...]:
        """Return ordered, renderer-owned TOC anchors from one HTML document."""
        return tuple(
            match.group("anchor")
            for match in _TOC_PAGE_REFERENCE_PATTERN.finditer(html)
        )

    @staticmethod
    def _toc_page_numbers(
        pdf_path: Path,
        anchors: tuple[str, ...],
    ) -> dict[str, int]:
        """Read physical PDF destinations for the already-rendered TOC links."""
        expected_anchors = set(anchors)
        page_numbers: dict[str, int] = {}

        try:
            with fitz.open(pdf_path) as document:
                for page in document:
                    for link in page.get_links():
                        anchor = str(link.get("nameddest", "")).lstrip("#")
                        page_index = link.get("page")
                        if (
                            anchor in expected_anchors
                            and isinstance(page_index, int)
                            and page_index >= 0
                        ):
                            page_numbers.setdefault(anchor, page_index + 1)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.warning("Unable to resolve PDF table-of-contents pages: %s", exc)
            return {}

        if len(page_numbers) != len(expected_anchors):
            logger.warning(
                "Unable to resolve every PDF table-of-contents page reference."
            )
            return {}
        return page_numbers

    @staticmethod
    def _with_toc_page_numbers(
        html: str,
        page_numbers: dict[str, int],
    ) -> str:
        """Fill only complete, browser-measured TOC page references."""
        if not page_numbers:
            return html

        def replace(match: re.Match[str]) -> str:
            page_number = page_numbers.get(match.group("anchor"))
            if page_number is None:
                return match.group(0)
            return (
                f"{match.group('opening')}{page_number}"
                f"{match.group('closing')}"
            )

        return _TOC_PAGE_REFERENCE_PATTERN.sub(replace, html)

    @staticmethod
    def _prepare_output_path(output_path: Path) -> Path:
        """Resolve a writable file target and create its parent directory."""
        if not isinstance(output_path, Path):
            raise ReportRenderingError("PDF output_path must be a pathlib.Path.")

        try:
            resolved_output_path = output_path.expanduser().resolve(strict=False)
            if resolved_output_path.exists() and resolved_output_path.is_dir():
                raise ReportRenderingError(
                    "PDF output_path must name a file, not a directory."
                )

            resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
            if not resolved_output_path.parent.is_dir():
                raise ReportRenderingError(
                    "PDF output directory could not be created."
                )
        except ReportRenderingError:
            raise
        except OSError as exc:
            raise ReportRenderingError(
                "Unable to create the PDF output directory."
            ) from exc

        return resolved_output_path

    @staticmethod
    def _render_html(report: EnhancedResearchReport) -> str:
        """Reuse the HTML presentation layer without duplicating its logic."""
        try:
            html = HTMLRenderer().render(report)
        except (InvalidResearchReportError, ReportRenderingError):
            raise
        except Exception as exc:
            raise ReportRenderingError("Unable to render the report HTML.") from exc

        if not isinstance(html, str) or not html.strip():
            raise ReportRenderingError("HTML report rendering returned no document.")

        return html

    @staticmethod
    def _render_presentation_html(presentation: PresentationModel) -> str:
        """Delegate composed presentation HTML to the existing HTML renderer."""
        try:
            html = HTMLRenderer().render_presentation(presentation)
        except (InvalidResearchReportError, ReportRenderingError):
            raise
        except Exception as exc:
            raise ReportRenderingError(
                "Unable to render the composed presentation HTML."
            ) from exc

        if not isinstance(html, str) or not html.strip():
            raise ReportRenderingError("HTML report rendering returned no document.")

        return html

    @staticmethod
    def _write_html(html_path: Path, html: str) -> None:
        """Write the generated UTF-8 HTML to the private temporary directory."""
        try:
            html_path.write_text(html, encoding="utf-8", newline="\n")
        except (OSError, UnicodeError) as exc:
            raise ReportRenderingError(
                "Unable to write temporary HTML for PDF rendering."
            ) from exc

    @staticmethod
    def _render_pdf(html_path: Path, pdf_path: Path) -> None:
        """Load one local HTML document in Chromium and export an A4 PDF."""
        try:
            with sync_playwright() as playwright:
                browser = None
                context = None
                try:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(html_path.as_uri(), wait_until="networkidle")
                    page.emulate_media(media="print")
                    page.pdf(
                        path=str(pdf_path),
                        format="A4",
                        print_background=True,
                        prefer_css_page_size=True,
                        tagged=True,
                        outline=True,
                    )
                finally:
                    PDFRenderer._close_browser_resources(context, browser)
        except Exception as exc:
            raise ReportRenderingError(
                "Chromium could not render the HTML report as a PDF."
            ) from exc

    @staticmethod
    def _close_browser_resources(context: object, browser: object) -> None:
        """Close browser state without obscuring an earlier render failure."""
        for resource in (context, browser):
            if resource is None:
                continue

            try:
                resource.close()  # type: ignore[union-attr]
            except Exception:
                logger.warning("Unable to close a Playwright PDF resource.")

    @staticmethod
    def _validate_pdf_file(pdf_path: Path) -> None:
        """Reject a missing or empty Chromium output before replacement."""
        try:
            if not pdf_path.is_file() or pdf_path.stat().st_size <= 0:
                raise ReportRenderingError(
                    "Chromium did not produce a usable PDF document."
                )
        except ReportRenderingError:
            raise
        except OSError as exc:
            raise ReportRenderingError(
                "Unable to validate the temporary PDF document."
            ) from exc

    @staticmethod
    def _write_pdf_metadata(pdf_path: Path) -> None:
        """Attach stable PDF information fields and the document language."""
        metadata_path = pdf_path.with_name("report-metadata.pdf")

        try:
            with fitz.open(pdf_path) as document:
                metadata = dict(document.metadata)
                metadata.update(_PDF_INFO_METADATA)
                document.set_metadata(metadata)
                document.set_language(_PDF_LANGUAGE)
                document.save(metadata_path)
            metadata_path.replace(pdf_path)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ReportRenderingError(
                "Unable to apply metadata to the rendered PDF."
            ) from exc

    @staticmethod
    def _replace_output(pdf_path: Path, output_path: Path) -> None:
        """Atomically replace the requested output only after successful rendering."""
        try:
            pdf_path.replace(output_path)
        except OSError as exc:
            raise ReportRenderingError(
                "Unable to finalize the PDF output file."
            ) from exc
