"""Tests for the Playwright-backed standalone PDF report renderer."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

import fitz
import pytest

from app.reports import (
    EnhancedResearchReport,
    Finding,
    InvalidResearchReportError,
    PDFRenderer,
    ReportIntelligence,
    ReportRenderingError,
    ResearchReport,
    SynthesisMetadata,
    SynthesizedSection,
)
from app.reports.composer import ReportComposer
from app.reports import pdf_renderer
from app.reports.presentation_models import PresentationModel

_CHUNK_ID = UUID("12345678-1234-5678-1234-567812345678")
_HTML_DOCUMENT = "<!doctype html><html><body>Report</body></html>"
_TOC_HTML_DOCUMENT = """<!doctype html><html><body>
<nav><a class="toc-link" href="#abstract"><span class="toc-page-reference" data-target="#abstract" aria-hidden="true"></span></a></nav>
<section id="abstract"><h2>Abstract</h2></section>
</body></html>"""


def _report() -> EnhancedResearchReport:
    """Build a valid local enhanced report without any provider calls."""
    base_report = ResearchReport(
        title="Research Report",
        executive_summary="Deterministic report summary.",
        findings=(),
        important_entities=("PaperForge",),
        important_definitions=(),
        important_metrics=("95%",),
        timeline=(),
        references=("https://example.com/source",),
        sections=(),
    )
    return EnhancedResearchReport(
        base_report=base_report,
        executive_summary=(
            "The source describes backend engineering work.\n\n"
            "It records measurable production improvements."
        ),
        findings=(
            Finding(
                title="Backend engineering",
                description="The document covers APIs and middleware.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        sections=(
            SynthesizedSection(
                heading="Professional Experience",
                content="The source documents backend delivery work.",
                supporting_chunk_ids=(_CHUNK_ID,),
            ),
        ),
        synthesis_metadata=SynthesisMetadata(
            provider="groq",
            model="test-model",
            elapsed_ms=0.0,
            successful=True,
        ),
    )


def _anchor_bearing_html(presentation: PresentationModel) -> str:
    """Materialize minimal navigation HTML directly from a presentation model.

    This deliberately mirrors the adapter boundary rather than any report
    template: the PDF renderer must treat the already-rendered HTML as opaque.
    """
    toc = "".join(
        f'<a href="#{entry.anchor_id}">{entry.heading}</a>'
        for entry in presentation.table_of_contents.entries
    )
    sections = "".join(
        f'<section id="{section.anchor_id}"><h2>{section.heading}</h2></section>'
        for section in presentation.sections
    )
    return (
        "<!doctype html><html><body>"
        f'<nav aria-label="Table of contents">{toc}</nav>'
        f"{sections}"
        "</body></html>"
    )


def _minimal_pdf_bytes() -> bytes:
    """Create a valid PDF payload for a mocked Playwright export."""
    document = fitz.open()
    try:
        document.new_page()
        return document.tobytes()
    finally:
        document.close()


class FakePage:
    """Record page operations and write a minimal selectable PDF on export."""

    def __init__(
        self,
        pdf_bytes: bytes,
        *,
        export_error: Exception | None = None,
    ) -> None:
        self._pdf_bytes = pdf_bytes
        self._export_error = export_error
        self.goto_calls: list[tuple[str, dict[str, object]]] = []
        self.html_file_existed_at_navigation: list[bool] = []
        self.html_contents_at_navigation: list[str] = []
        self.media_calls: list[dict[str, object]] = []
        self.pdf_calls: list[dict[str, object]] = []

    def goto(self, url: str, **kwargs: object) -> None:
        """Record navigation to the temporary file URI."""
        self.goto_calls.append((url, kwargs))
        parsed_url = urlparse(url)
        encoded_path = unquote(parsed_url.path)
        if len(encoded_path) >= 3 and encoded_path[0] == "/" and (
            encoded_path[2] == ":"
        ):
            encoded_path = encoded_path[1:]
        html_path = Path(encoded_path)
        self.html_file_existed_at_navigation.append(html_path.is_file())
        if html_path.is_file():
            self.html_contents_at_navigation.append(
                html_path.read_text(encoding="utf-8")
            )

    def emulate_media(self, **kwargs: object) -> None:
        """Record print-media selection."""
        self.media_calls.append(kwargs)

    def pdf(self, **kwargs: object) -> None:
        """Write a valid PDF unless a configured export error is requested."""
        self.pdf_calls.append(kwargs)
        if self._export_error is not None:
            raise self._export_error

        Path(str(kwargs["path"])).write_bytes(self._pdf_bytes)


class FakeContext:
    """Minimal browser-context double with visible close lifecycle state."""

    def __init__(self, page: FakePage) -> None:
        self._page = page
        self.closed = False
        self.new_page_calls = 0

    def new_page(self) -> FakePage:
        """Return the one fake page."""
        self.new_page_calls += 1
        return self._page

    def __enter__(self) -> "FakeContext":
        """Support either explicit or context-manager cleanup styles."""
        return self

    def __exit__(self, *_: object) -> bool:
        """Close the context when used as a context manager."""
        self.close()
        return False

    def close(self) -> None:
        """Record context cleanup."""
        self.closed = True


class FakeBrowser:
    """Minimal Chromium browser double."""

    def __init__(self, context: FakeContext) -> None:
        self._context = context
        self.closed = False
        self.new_context_calls: list[dict[str, object]] = []

    def new_context(self, **kwargs: object) -> FakeContext:
        """Return the fake isolated browser context."""
        self.new_context_calls.append(kwargs)
        return self._context

    def __enter__(self) -> "FakeBrowser":
        """Support either explicit or context-manager cleanup styles."""
        return self

    def __exit__(self, *_: object) -> bool:
        """Close the browser when used as a context manager."""
        self.close()
        return False

    def close(self) -> None:
        """Record browser cleanup."""
        self.closed = True


class FakeChromium:
    """Record launch options and optionally emulate a browser launch failure."""

    def __init__(
        self,
        browser: FakeBrowser,
        *,
        launch_error: Exception | None = None,
    ) -> None:
        self._browser = browser
        self._launch_error = launch_error
        self.launch_calls: list[dict[str, object]] = []

    def launch(self, **kwargs: object) -> FakeBrowser:
        """Return the fake browser or raise the configured failure."""
        self.launch_calls.append(kwargs)
        if self._launch_error is not None:
            raise self._launch_error
        return self._browser


class FakePlaywright:
    """Expose Chromium through the same shape used by the synchronous SDK."""

    def __init__(self, chromium: FakeChromium) -> None:
        self.chromium = chromium


class FakePlaywrightManager:
    """Context-manager wrapper that records clean Playwright shutdown."""

    def __init__(self, playwright: FakePlaywright) -> None:
        self._playwright = playwright
        self.entered = False
        self.exited = False

    def __enter__(self) -> FakePlaywright:
        """Enter the fake synchronous Playwright lifecycle."""
        self.entered = True
        return self._playwright

    def __exit__(self, *_: object) -> bool:
        """Record lifecycle exit without suppressing errors."""
        self.exited = True
        return False


class FakeHTMLRenderer:
    """Simple HTML renderer double that records report reuse."""

    def __init__(
        self,
        html: str = _HTML_DOCUMENT,
        *,
        error: Exception | None = None,
    ) -> None:
        self._html = html
        self._error = error
        self.calls: list[EnhancedResearchReport] = []
        self.presentation_calls: list[object] = []

    def render(self, report: EnhancedResearchReport) -> str:
        """Return supplied HTML or raise a configured rendering error."""
        self.calls.append(report)
        if self._error is not None:
            raise self._error
        return self._html

    def render_presentation(self, presentation: object) -> str:
        """Return supplied HTML for one already-composed presentation model."""
        self.presentation_calls.append(presentation)
        if self._error is not None:
            raise self._error
        return self._html


def _install_html_renderer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    html: str = _HTML_DOCUMENT,
    error: Exception | None = None,
) -> list[FakeHTMLRenderer]:
    """Replace the renderer dependency with a factory recording each instance."""
    renderers: list[FakeHTMLRenderer] = []

    def factory() -> FakeHTMLRenderer:
        renderer = FakeHTMLRenderer(html, error=error)
        renderers.append(renderer)
        return renderer

    monkeypatch.setattr(pdf_renderer, "HTMLRenderer", factory)
    return renderers


def _install_playwright(
    monkeypatch: pytest.MonkeyPatch,
    *,
    launch_error: Exception | None = None,
    export_error: Exception | None = None,
) -> tuple[FakePlaywrightManager, FakeChromium, FakeBrowser, FakeContext, FakePage]:
    """Install a fully mocked synchronous Playwright lifecycle."""
    page = FakePage(_minimal_pdf_bytes(), export_error=export_error)
    context = FakeContext(page)
    browser = FakeBrowser(context)
    chromium = FakeChromium(browser, launch_error=launch_error)
    manager = FakePlaywrightManager(FakePlaywright(chromium))
    monkeypatch.setattr(pdf_renderer, "sync_playwright", lambda: manager)
    return manager, chromium, browser, context, page


def _assert_no_temporary_artifacts(output_parent: Path) -> None:
    """Assert the renderer cleaned its private temporary directory."""
    assert not list(output_parent.glob(".paperforge-pdf-*"))


def test_pdf_renderer_writes_a4_pdf_and_closes_all_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public renderer reuses HTML and atomically creates a PDF output."""
    report = _report()
    before = deepcopy(report.model_dump(mode="python"))
    html_renderers = _install_html_renderer(monkeypatch)
    manager, chromium, browser, context, page = _install_playwright(monkeypatch)
    output_path = tmp_path / "nested" / "report.pdf"

    returned_path = PDFRenderer().render(report, output_path)

    assert returned_path == output_path.resolve()
    assert returned_path.is_absolute()
    assert returned_path.is_file()
    assert html_renderers[0].calls == [report]
    assert report.model_dump(mode="python") == before
    assert chromium.launch_calls == [{"headless": True}]
    assert browser.new_context_calls == [{}]
    assert context.new_page_calls == 1
    assert page.media_calls == [{"media": "print"}]
    assert len(page.goto_calls) == 1
    source_url, navigation_options = page.goto_calls[0]
    assert source_url.startswith("file:///")
    assert navigation_options == {"wait_until": "networkidle"}
    assert page.html_file_existed_at_navigation == [True]
    assert page.html_contents_at_navigation == [_HTML_DOCUMENT]
    assert len(page.pdf_calls) == 1
    pdf_options = page.pdf_calls[0]
    assert Path(str(pdf_options["path"])).name == "report.pdf"
    assert pdf_options["format"] == "A4"
    assert pdf_options["print_background"] is True
    assert pdf_options["prefer_css_page_size"] is True
    assert pdf_options["tagged"] is True
    assert pdf_options["outline"] is True
    assert context.closed is True
    assert browser.closed is True
    assert manager.entered is True
    assert manager.exited is True
    _assert_no_temporary_artifacts(output_path.parent)

    document = fitz.open(returned_path)
    try:
        metadata = document.metadata
        assert metadata["title"] == "PaperForge Research Report"
        assert metadata["author"] == "PaperForge"
        assert metadata["creator"] == "PaperForge"
        assert metadata["subject"] == "AI Research Report"
        assert document.language == "en"
    finally:
        document.close()


def test_pdf_renderer_materializes_physical_toc_page_references(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A private preflight keeps printed TOC numbers accurate in Chromium."""
    html_renderers = _install_html_renderer(monkeypatch, html=_TOC_HTML_DOCUMENT)
    _, _, _, _, page = _install_playwright(monkeypatch)
    monkeypatch.setattr(
        PDFRenderer,
        "_toc_page_numbers",
        staticmethod(lambda _pdf_path, _anchors: {"abstract": 3}),
    )

    PDFRenderer().render(_report(), tmp_path / "toc.pdf")

    assert len(html_renderers) == 1
    assert page.html_contents_at_navigation == [
        _TOC_HTML_DOCUMENT,
        _TOC_HTML_DOCUMENT.replace(
            'aria-hidden="true"></span>',
            'aria-hidden="true">3</span>',
        ),
    ]
    assert len(page.pdf_calls) == 2
    _assert_no_temporary_artifacts(tmp_path)


def test_pdf_renderer_delegates_composed_presentation_to_html_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The presentation adapter shares PDF export while preserving model identity."""
    presentation = ReportComposer().compose(_report())
    html_renderers = _install_html_renderer(monkeypatch)
    manager, chromium, browser, context, page = _install_playwright(monkeypatch)
    output_path = tmp_path / "presentation" / "report.pdf"

    returned_path = PDFRenderer().render_presentation(
        presentation,
        output_path,
    )

    assert returned_path == output_path.resolve()
    assert returned_path.is_file()
    assert html_renderers[0].calls == []
    assert html_renderers[0].presentation_calls == [presentation]
    assert chromium.launch_calls == [{"headless": True}]
    assert page.media_calls == [{"media": "print"}]
    assert context.closed is True
    assert browser.closed is True
    assert manager.exited is True
    _assert_no_temporary_artifacts(output_path.parent)


def test_pdf_renderer_preserves_anchor_bearing_presentation_html_through_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF export treats shared navigation HTML as opaque renderer output."""
    presentation = ReportComposer().compose(_report())
    before = deepcopy(presentation.model_dump(mode="python"))
    expected_html = _anchor_bearing_html(presentation)
    html_renderers = _install_html_renderer(monkeypatch, html=expected_html)
    _, _, _, _, page = _install_playwright(monkeypatch)

    PDFRenderer().render_presentation(presentation, tmp_path / "anchors.pdf")

    assert html_renderers[0].calls == []
    assert html_renderers[0].presentation_calls == [presentation]
    assert presentation.model_dump(mode="python") == before
    assert page.html_contents_at_navigation == [expected_html]
    temporary_html = page.html_contents_at_navigation[0]
    for entry in presentation.table_of_contents.entries:
        assert f'href="#{entry.anchor_id}"' in temporary_html
    for section in presentation.sections:
        assert f'<section id="{section.anchor_id}">' in temporary_html


def test_pdf_renderer_auto_creates_parent_and_overwrites_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated rendering returns the same absolute path and replaces old files."""
    _install_html_renderer(monkeypatch)
    _install_playwright(monkeypatch)
    output_path = tmp_path / "generated" / "report.pdf"

    first_path = PDFRenderer().render(_report(), output_path)
    first_path.write_bytes(b"stale output")
    second_path = PDFRenderer().render(_report(), output_path)

    assert first_path == second_path == output_path.resolve()
    assert output_path.parent.is_dir()
    assert second_path.read_bytes() != b"stale output"
    _assert_no_temporary_artifacts(output_path.parent)


def test_pdf_renderer_remains_an_html_only_consumer_of_refined_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Appendix refinement data is passed unchanged to the HTML presentation layer."""
    refined_report = _report().model_copy(
        update={
            "appendix_findings": (
                Finding(
                    title="Appendix finding",
                    description="A lower-ranked supported fact.",
                    supporting_chunk_ids=(_CHUNK_ID,),
                ),
            )
        }
    )
    html_renderers = _install_html_renderer(monkeypatch)
    _install_playwright(monkeypatch)

    PDFRenderer().render(refined_report, tmp_path / "refined.pdf")

    assert html_renderers[0].calls == [refined_report]


def test_pdf_renderer_passes_the_intelligence_overlay_to_html_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PDF rendering remains an HTML-only downstream consumer of intelligence."""
    enriched_report = _report().model_copy(
        update={"report_intelligence": ReportIntelligence()}
    )
    html_renderers = _install_html_renderer(monkeypatch)
    _install_playwright(monkeypatch)

    PDFRenderer().render(enriched_report, tmp_path / "intelligence.pdf")

    assert html_renderers[0].calls == [enriched_report]


def test_pdf_renderer_preserves_invalid_report_errors(
    tmp_path: Path,
) -> None:
    """Input validation remains the responsibility of the reused HTML renderer."""
    invalid_report = object()

    with pytest.raises(InvalidResearchReportError):
        PDFRenderer().render(
            invalid_report,  # type: ignore[arg-type]
            tmp_path / "report.pdf",
        )


@pytest.mark.parametrize("html", ("", " \n\t "))
def test_pdf_renderer_rejects_blank_html_before_browser_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    html: str,
) -> None:
    """A blank HTML result cannot reach browser rendering."""
    _install_html_renderer(monkeypatch, html=html)

    with pytest.raises(ReportRenderingError, match="HTML"):
        PDFRenderer().render(_report(), tmp_path / "report.pdf")


def test_pdf_renderer_maps_html_and_output_target_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTML and filesystem precondition failures remain report-layer errors."""
    _install_html_renderer(monkeypatch, error=OSError("template unavailable"))

    with pytest.raises(ReportRenderingError):
        PDFRenderer().render(_report(), tmp_path / "report.pdf")

    target_directory = tmp_path / "directory-target"
    target_directory.mkdir()
    with pytest.raises(ReportRenderingError):
        PDFRenderer().render(_report(), target_directory)

    blocked_parent = tmp_path / "blocked-parent"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ReportRenderingError):
        PDFRenderer().render(_report(), blocked_parent / "report.pdf")

    with pytest.raises(ReportRenderingError, match="output_path"):
        PDFRenderer().render(_report(), "report.pdf")  # type: ignore[arg-type]


def test_pdf_renderer_maps_browser_launch_and_export_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Browser failures are wrapped and any acquired resources are closed."""
    _install_html_renderer(monkeypatch)
    launch_manager, _, launch_browser, launch_context, _ = _install_playwright(
        monkeypatch,
        launch_error=RuntimeError("Chromium unavailable"),
    )

    with pytest.raises(ReportRenderingError, match="Chromium"):
        PDFRenderer().render(_report(), tmp_path / "launch.pdf")

    assert launch_manager.exited is True
    assert launch_browser.closed is False
    assert launch_context.closed is False
    _assert_no_temporary_artifacts(tmp_path)

    export_manager, _, export_browser, export_context, _ = _install_playwright(
        monkeypatch,
        export_error=RuntimeError("PDF export failed"),
    )
    output_path = tmp_path / "export.pdf"
    output_path.write_bytes(b"previous output")

    with pytest.raises(ReportRenderingError, match="PDF"):
        PDFRenderer().render(_report(), output_path)

    assert output_path.read_bytes() == b"previous output"
    assert export_context.closed is True
    assert export_browser.closed is True
    assert export_manager.exited is True
    _assert_no_temporary_artifacts(tmp_path)


def test_pdf_renderer_maps_metadata_and_final_replacement_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata and atomic-replacement errors never leak low-level failures."""
    _install_html_renderer(monkeypatch)
    _install_playwright(monkeypatch)

    def fail_metadata_open(*_: object, **__: object) -> object:
        raise OSError("metadata write failed")

    monkeypatch.setattr(pdf_renderer.fitz, "open", fail_metadata_open)
    metadata_output = tmp_path / "metadata.pdf"
    with pytest.raises(ReportRenderingError, match="metadata"):
        PDFRenderer().render(_report(), metadata_output)
    assert not metadata_output.exists()
    _assert_no_temporary_artifacts(tmp_path)

    monkeypatch.undo()
    _install_html_renderer(monkeypatch)
    _install_playwright(monkeypatch)
    original_replace = pdf_renderer.Path.replace

    def fail_replace(path: Path, target: str | Path) -> Path:
        if path.name == "report.pdf" and Path(target).name == "replacement.pdf":
            raise OSError("replacement failed")
        return original_replace(path, target)

    monkeypatch.setattr(pdf_renderer.Path, "replace", fail_replace)
    replacement_output = tmp_path / "replacement.pdf"
    with pytest.raises(ReportRenderingError, match="output|replace"):
        PDFRenderer().render(_report(), replacement_output)
    assert not replacement_output.exists()
    _assert_no_temporary_artifacts(tmp_path)
