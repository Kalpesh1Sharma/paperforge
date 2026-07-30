"""Generate standalone HTML and PDF reports from the bundled sample PDF."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.chunking import DocumentChunker
from app.knowledge import GroqKnowledgeProvider, KnowledgeExtractor
from app.parsers import ParserFactory
from app.reports import (
    DocumentSynthesizer,
    HTMLRenderer,
    PDFRenderer,
    ReportIntelligenceBuilder,
    ResearchSynthesizer,
)

HTML_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "report.html"
PDF_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "report.pdf"


def main() -> None:
    """Run the report pipeline and write standalone HTML and PDF artifacts."""
    document = ParserFactory.parse(PROJECT_ROOT / "sample.pdf")
    chunks = DocumentChunker().chunk(document)
    extractor = KnowledgeExtractor(GroqKnowledgeProvider())
    knowledge_objects = tuple(extractor.extract(chunk) for chunk in chunks)
    report = ResearchSynthesizer().synthesize(knowledge_objects)
    enhanced_report = DocumentSynthesizer().synthesize(report, knowledge_objects)
    enhanced_report = ReportIntelligenceBuilder().build(
        enhanced_report,
        knowledge_objects,
    )

    html = HTMLRenderer().render(enhanced_report)
    HTML_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HTML_OUTPUT_PATH.write_text(html, encoding="utf-8")

    pdf_path = PDFRenderer().render(enhanced_report, PDF_OUTPUT_PATH)
    print(f"HTML output: {HTML_OUTPUT_PATH.resolve()}")
    print(f"PDF output: {pdf_path}")


if __name__ == "__main__":
    main()
