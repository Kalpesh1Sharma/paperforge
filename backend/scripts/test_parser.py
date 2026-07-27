from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.parsers import ParserFactory

# Change this path to whatever file you want to test
file_path = Path("sample.pdf")

document = ParserFactory.parse(file_path)

print("=" * 60)
print("Filename:", document.filename)
print("Type:", document.file_type)
print("Pages:", document.page_count)
print("Words:", document.word_count)
print("Characters:", document.character_count)
print("Metadata:", document.metadata)
print("=" * 60)

print(document.extracted_text[:1000])