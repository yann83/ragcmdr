# ragstudio/core/parser.py

"""Document parser module using Docling.

Docling is loaded lazily: the heavy converter object is only instantiated
when a parsing job actually starts, then discarded immediately after so
its memory is released.

Supported formats (handled natively by Docling):
    PDF, DOCX, DOC, PPTX, PPT, XLSX, HTML, HTM, TXT, MD, PNG, JPG, JPEG
"""

import gc
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# File extensions that Docling can process.
# Unsupported files found in a folder are skipped with a warning.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx",
    ".html", ".htm",
    ".txt", ".md",
    ".png", ".jpg", ".jpeg",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def isSupportedFile(path: Path) -> bool:
    """Returns True if the file extension is supported by Docling.

    Args:
        path: Path to the file to check.

    Returns:
        True if the file can be processed, False otherwise.
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def parseFile(file_path: Path) -> str:
    """Parses a single document and returns its normalized text content.

    Docling is instantiated here and discarded immediately after use
    to keep the memory footprint as small as possible.

    Args:
        file_path: Absolute path to the document to parse.

    Returns:
        The full extracted text as a single string.

    Raises:
        FileNotFoundError: If file_path does not exist.
        ValueError: If the file type is not supported.
        RuntimeError: If Docling fails to convert the document.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not isSupportedFile(file_path):
        raise ValueError(
            f"Unsupported file type: '{file_path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # --- Lazy import: Docling is only loaded here, not at module import time ---
    try:
        from docling.document_converter import DocumentConverter
    except ImportError as e:
        raise RuntimeError(
            "Docling is not installed. Run: pip install docling"
        ) from e

    # Instantiate converter, convert, then immediately discard
    converter = DocumentConverter()
    try:
        result = converter.convert(str(file_path))
        text = result.document.export_to_markdown()
    except Exception as e:
        raise RuntimeError(f"Docling failed to parse '{file_path.name}': {e}") from e
    finally:
        # Explicit cleanup — Docling may hold torch models in memory
        del converter
        gc.collect()

    return text


def collectFiles(
    folder_path: Path,
    recursive: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Scans a folder and separates supported from unsupported files.

    Args:
        folder_path: Absolute or relative path to the folder to scan.
        recursive: If True, scans all sub-directories as well.
            Defaults to False (flat scan only).

    Returns:
        A tuple of (supported_files, skipped_files) where each element is a
        list of Path objects sorted by path.

    Raises:
        FileNotFoundError: If folder_path does not exist.
        NotADirectoryError: If folder_path is not a directory.
    """
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    supported: list[Path] = []
    skipped: list[Path] = []

    # rglob("*") walks all sub-directories; iterdir() stays flat
    iterator = folder_path.rglob("*") if recursive else folder_path.iterdir()

    for item in sorted(iterator):
        if item.is_dir():
            continue
        if isSupportedFile(item):
            supported.append(item)
        else:
            skipped.append(item)

    return supported, skipped


def chunkText(text: str, chunk_size: int = 512, chunk_overlap: int = 64) -> list[str]:
    """Splits a long text into overlapping chunks suitable for embedding.

    Uses a simple word-boundary splitter to avoid cutting words mid-token.
    Each chunk is approximately ``chunk_size`` characters long, with an
    overlap of ``chunk_overlap`` characters carried over from the previous chunk.

    Args:
        text: The full document text to split.
        chunk_size: Target maximum character length per chunk.
        chunk_overlap: Number of characters to repeat at the start of each
            subsequent chunk for context continuity.

    Returns:
        A list of text chunk strings. Returns an empty list if *text* is empty.
    """
    text = text.strip()
    if not text:
        return []

    # Split on whitespace boundaries to avoid mid-word cuts
    words = text.split()
    chunks: list[str] = []
    current_chars = 0
    current_words: list[str] = []

    for word in words:
        word_len = len(word) + 1  # +1 for the space
        if current_chars + word_len > chunk_size and current_words:
            # Flush the current chunk
            chunks.append(" ".join(current_words))

            # Carry over the overlap from the end of the current chunk
            overlap_text = " ".join(current_words)[-chunk_overlap:]
            # Trim to a clean word boundary for the overlap start
            overlap_words = overlap_text.split()
            # Drop the first (potentially partial) word from the overlap
            current_words = overlap_words[1:] if len(overlap_words) > 1 else []
            current_chars = sum(len(w) + 1 for w in current_words)

        current_words.append(word)
        current_chars += word_len

    # Flush any remaining words as the last chunk
    if current_words:
        chunks.append(" ".join(current_words))

    return chunks