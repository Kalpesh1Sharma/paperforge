from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.chunking import ChunkingConfig, DocumentChunker
from app.parsers import ParserFactory

doc = ParserFactory.parse(Path("sample.pdf"))

chunks = DocumentChunker().chunk(
    doc,
    ChunkingConfig(
        max_chars=1000,
        overlap_chars=150,
    ),
)

print(f"Chunks: {len(chunks)}")

for chunk in chunks:
    print("=" * 60)
    print(chunk.chunk_index)
    print(chunk.word_count)
    print(chunk.start_char, chunk.end_char)
    print(chunk.text[:200])