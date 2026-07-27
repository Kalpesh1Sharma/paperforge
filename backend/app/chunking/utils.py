"""Linear-time utilities shared by deterministic chunking strategies."""

import math
import re
from dataclasses import dataclass
from hashlib import sha256

from app.models.parsed_document import MetadataValue

_BULLET_PATTERN = re.compile(r"^\s*(?:[-*+•]\s+|\d+[.)]\s+)")
_MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_NUMBERED_HEADING_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+\S")
_SENTENCE_ENDINGS = frozenset(".!?")
FINGERPRINT_BLOCK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class StructuralGroup:
    """A semantic text group represented entirely by source indices."""

    start: int
    end: int
    kind: str
    item_starts: tuple[int, ...] = ()


def count_words_and_content(text: str) -> tuple[int, bool]:
    """Count words without allocating the list produced by str.split()."""
    word_count = 0
    in_word = False
    has_non_whitespace = False

    for character in text:
        if character.isspace():
            in_word = False
            continue

        has_non_whitespace = True
        if not in_word:
            word_count += 1
            in_word = True

    return word_count, has_non_whitespace


def is_valid_metadata(metadata: object) -> bool:
    """Accept the JSON-safe primitive metadata contract of ParsedDocument."""
    if not isinstance(metadata, dict):
        return False

    for key, value in metadata.items():
        if not isinstance(key, str):
            return False
        if isinstance(value, float) and not math.isfinite(value):
            return False
        if not isinstance(value, (str, int, float, bool, type(None))):
            return False

    return True


def document_fingerprint(filename: str, file_type: str, text: str) -> str:
    """Hash text in bounded blocks without encoding the whole document at once."""
    hasher = sha256()
    hasher.update(filename.encode("utf-8"))
    hasher.update(b"\x1f")
    hasher.update(file_type.encode("utf-8"))
    hasher.update(b"\x1f")

    for offset in range(0, len(text), FINGERPRINT_BLOCK_SIZE):
        hasher.update(text[offset : offset + FINGERPRINT_BLOCK_SIZE].encode("utf-8"))

    return hasher.hexdigest()


def scan_structural_groups(text: str) -> tuple[StructuralGroup, ...]:
    """Find paragraph, heading, and list groups without copying the full text."""
    raw_groups: list[StructuralGroup] = []
    cursor = 0
    text_length = len(text)

    while cursor < text_length:
        content_end, next_cursor = _line_bounds(text, cursor)
        line = _line_text(text, cursor, content_end)
        if not line.strip():
            cursor = next_cursor
            continue

        if _is_heading(text, cursor, content_end, next_cursor):
            raw_groups.append(StructuralGroup(cursor, next_cursor, "heading"))
            cursor = next_cursor
            continue

        if _is_bullet(line):
            list_start = cursor
            list_end = next_cursor
            item_starts = [cursor]
            cursor = next_cursor

            while cursor < text_length:
                content_end, next_cursor = _line_bounds(text, cursor)
                list_line = _line_text(text, cursor, content_end)
                if not _is_bullet(list_line):
                    break
                item_starts.append(cursor)
                list_end = next_cursor
                cursor = next_cursor

            raw_groups.append(
                StructuralGroup(
                    list_start,
                    list_end,
                    "list",
                    tuple(item_starts),
                )
            )
            continue

        paragraph_start = cursor
        paragraph_end = next_cursor
        cursor = next_cursor

        while cursor < text_length:
            content_end, next_cursor = _line_bounds(text, cursor)
            next_line = _line_text(text, cursor, content_end)
            if not next_line.strip() or _is_bullet(next_line):
                break
            if _is_heading(text, cursor, content_end, next_cursor):
                break
            paragraph_end = next_cursor
            cursor = next_cursor

        raw_groups.append(StructuralGroup(paragraph_start, paragraph_end, "paragraph"))

    return _attach_headings(raw_groups)


def find_forced_end(text: str, start: int, limit: int) -> int:
    """Prefer a sentence or word boundary before falling back to a hard split."""
    for index in range(limit - 1, start, -1):
        if text[index] in _SENTENCE_ENDINGS and (
            index + 1 == len(text) or text[index + 1].isspace()
        ):
            return index + 1

    for index in range(limit - 1, start, -1):
        if text[index].isspace():
            return index + 1

    return limit


def find_forced_end_after(text: str, minimum_end: int, limit: int) -> int:
    """Find the earliest useful boundary at or after a required position."""
    for index in range(max(minimum_end - 1, 0), limit):
        if text[index] in _SENTENCE_ENDINGS and (
            index + 1 == len(text) or text[index + 1].isspace()
        ):
            return index + 1

    for index in range(minimum_end, limit):
        if text[index - 1].isspace():
            return index

    return minimum_end


def find_overlap_boundary(
    text: str,
    minimum_start: int,
    end: int,
    target: int,
) -> int:
    """Find the nearest word boundary around an overlap target."""
    candidates: list[int] = []
    target = min(max(target, minimum_start), end - 1)

    for index in range(target, minimum_start, -1):
        if text[index - 1].isspace():
            candidates.append(index)
            break

    for index in range(target, end):
        if index > minimum_start and text[index - 1].isspace():
            candidates.append(index)
            break

    if not candidates:
        return target

    return min(candidates, key=lambda index: (abs(index - target), index))


def has_non_whitespace(text: str, start: int, end: int) -> bool:
    """Check an indexed source span without creating a substring."""
    for index in range(start, end):
        if not text[index].isspace():
            return True
    return False


def _attach_headings(
    raw_groups: list[StructuralGroup],
) -> tuple[StructuralGroup, ...]:
    """Prevent a heading boundary from separating it from following content."""
    groups: list[StructuralGroup] = []
    index = 0

    while index < len(raw_groups):
        current = raw_groups[index]
        if (
            current.kind == "heading"
            and index + 1 < len(raw_groups)
            and raw_groups[index + 1].kind in {"paragraph", "list"}
        ):
            following = raw_groups[index + 1]
            groups.append(
                StructuralGroup(
                    current.start,
                    following.end,
                    "heading_with_content",
                    following.item_starts,
                )
            )
            index += 2
            continue

        groups.append(current)
        index += 1

    return tuple(groups)


def _is_bullet(line: str) -> bool:
    return bool(_BULLET_PATTERN.match(line))


def _is_heading(text: str, start: int, end: int, next_start: int) -> bool:
    """Recognize explicit Markdown plus conservative standalone headings."""
    line = _line_text(text, start, end)
    stripped = line.strip()

    if _MARKDOWN_HEADING_PATTERN.match(line):
        return True
    if not stripped or _is_bullet(line):
        return False
    if len(stripped) > 120 or len(stripped.split()) > 12:
        return False
    if stripped[-1] in ".?!;:":
        return False
    if not _next_line_is_blank(text, next_start):
        return False

    return bool(
        _NUMBERED_HEADING_PATTERN.match(line)
        or (stripped == stripped.title() and any(char.isalpha() for char in stripped))
    )


def _next_line_is_blank(text: str, start: int) -> bool:
    if start >= len(text):
        return False
    end, _ = _line_bounds(text, start)
    return not _line_text(text, start, end).strip()


def _line_bounds(text: str, start: int) -> tuple[int, int]:
    newline = text.find("\n", start)
    if newline == -1:
        return len(text), len(text)
    return newline, newline + 1


def _line_text(text: str, start: int, end: int) -> str:
    line = text[start:end]
    return line[:-1] if line.endswith("\r") else line
