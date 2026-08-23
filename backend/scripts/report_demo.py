"""Generate a Markdown research report from the bundled sample PDF."""

from datetime import date
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
    MarkdownRenderer,
    ReportIntelligenceBuilder,
    ResearchSynthesizer,
)
from app.reports.composer import ReportComposer


def main() -> None:
    """Run the pipeline and print its Groq-enhanced Markdown report."""
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
    presentation = ReportComposer().compose(
        enhanced_report,
        source_document=document,
        generated_on=date.today(),
    )
    markdown = MarkdownRenderer().render_presentation(presentation)
    print(markdown, end="")


if __name__ == "__main__":
    main()
