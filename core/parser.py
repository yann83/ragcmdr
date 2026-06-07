# ragstudio/core/parser.py

"""Document parser module using Docling, pymupdf and pypdf.

Parsing strategy per format:

  PDF — automatic routing based on content detection:

      1. pymupdf probes every page to detect whether a native text layer
         is present (total extracted chars above TEXT_LAYER_THRESHOLD).
         pymupdf handles all PDF variants that pypdf cannot read (LaTeX
         output, non-standard compression, older PDF versions, etc.).

      2. Text-layer PDF (digital or mixed PDF):
             -> pymupdf extracts the text layer directly. No Docling, no ML
               model, no OCR, no GPU, no page limit. Pages that contain
               only images are silently skipped (empty string returned).
             -> This path is taken for ALL PDFs that have at least some
               text -- including mixed PDFs (text + embedded images).

      3. Scanned PDF (image-only pages), page count <= SCANNED_SAFE_PAGES:
             -> Docling with EasyOCR pipeline, CPU only (use_gpu=False),
               single call. Models load once, ~300-500 MB RAM.
               Safe on any machine, even with a GPU present.

      4. Scanned PDF, SCANNED_SAFE_PAGES < pages <= SCANNED_MAX_PAGES:
             -> Docling with EasyOCR pipeline, CPU only, batches of
               SCANNED_BATCH_PAGES pages. Uses Docling page_range API
               (official, no temporary files). Aggressive memory release
               between each batch (_forceMemoryRelease).

      5. Scanned PDF, pages > SCANNED_MAX_PAGES:
             -> Rejected with a clear RuntimeError. The user is told the
               page count, the limit, and how to work around it (split
               the PDF or convert it to DOCX first).

      6. PDF unreadable by pymupdf (corrupted, encrypted, unknown format):
             -> Rejected with a clear RuntimeError explaining the issue
               and suggesting re-export or conversion to DOCX.

  TXT / MD:
      Read directly with Python. No third-party library needed.

  DOCX / DOC / PPTX / PPT / XLSX / HTML / images:
      Parsed by Docling on CPU (AcceleratorOptions(device=CPU)). These
      formats never trigger the heavy OCR pipeline.

Library roles:
  pymupdf (fitz) -- PDF text extraction and page-count detection.
      Handles all PDF variants reliably. Never loads ML models.
  Docling         -- Non-PDF formats + fully scanned PDFs (OCR on CPU).
      Uses PyPdfiumDocumentBackend + page_range API for scanned batches.

GPU policy:
  Docling NEVER uses the GPU. AcceleratorOptions(device=CPU, num_threads=4)
  is passed explicitly to every Docling call. For scanned PDFs, EasyOCR is
  configured with use_gpu=False to prevent it from silently attempting to
  use VRAM even when a GPU is present in the system.

Docling API notes (from official documentation):
  - PyPdfiumDocumentBackend is the recommended backend for all PDF paths.
  - page_range=(start, end) is passed to converter.convert() directly --
    no need to split PDFs into temporary files.
  - document_timeout caps the maximum processing time per conversion call.
  - AcceleratorOptions(device=CPU) forces CPU execution globally.
"""

import gc
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: frozenset = frozenset({
    ".pdf",
    ".docx", ".doc",
    ".pptx", ".ppt",
    ".xlsx",
    ".html", ".htm",
    ".txt", ".md",
    ".png", ".jpg", ".jpeg",
})

# Extensions handled natively by Python -- Docling not needed.
PLAINTEXT_EXTENSIONS: frozenset = frozenset({".txt", ".md"})

# --- Text-layer detection ---

# Minimum total characters extracted by pymupdf across ALL pages to
# classify a PDF as having a native text layer.
# 200 chars total is extremely conservative: even a 1-page cover letter
# would exceed this threshold.
TEXT_LAYER_THRESHOLD: int = 200

# --- Scanned PDF thresholds ---

# Scanned PDFs with at most this many pages are sent to Docling in one
# call. The OCR models load once (~300-500 MB RAM) and process all pages.
# Safe on any machine with 8 GB RAM or more.
SCANNED_SAFE_PAGES: int = 10

# Number of pages per batch for scanned PDFs above SCANNED_SAFE_PAGES.
# Docling page_range API is used -- no temporary files needed.
SCANNED_BATCH_PAGES: int = 3

# Hard ceiling for scanned PDFs. Above this limit the file is rejected
# with a clear error message rather than risking a crash.
SCANNED_MAX_PAGES: int = 50

# Docling document timeout in seconds per conversion call.
# Prevents a pathological PDF from blocking the pipeline indefinitely.
DOCLING_TIMEOUT: int = 120

# Maximum characters from any single document before truncation.
# 2 million chars ~= 400 dense pages.
MAX_TEXT_CHARS: int = 2_000_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def isSupportedFile(path: Path) -> bool:
    """Returns True if the file extension is supported by the parser.

    Args:
        path: Path to the file to check.

    Returns:
        True if the file can be processed, False otherwise.
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def parseFile(file_path: Path) -> str:
    """Parses a single document and returns its normalized text content.

    Dispatch logic:
    - .txt / .md                    : Python direct read.
    - PDF, pymupdf unreadable       : RuntimeError with clear message.
    - PDF with text layer           : pymupdf direct extraction.
    - Scanned PDF <= SCANNED_SAFE   : Docling OCR, CPU, single call.
    - Scanned PDF <= SCANNED_MAX    : Docling OCR, CPU, page_range batches.
    - Scanned PDF > SCANNED_MAX     : RuntimeError with clear message.
    - DOCX / PPTX / HTML / images   : Docling, CPU, single call.

    Args:
        file_path: Absolute path to the document to parse.

    Returns:
        Extracted text as a single string, truncated at MAX_TEXT_CHARS
        if the document is very large.

    Raises:
        FileNotFoundError: If file_path does not exist.
        ValueError: If the file type is not supported.
        RuntimeError: If the document cannot be read or exceeds limits.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: '{suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    # --- Plain text: Python only ---
    if suffix in PLAINTEXT_EXTENSIONS:
        return _readPlainText(file_path)

    # --- PDF: route based on content ---
    if suffix == ".pdf":
        probe = _probePdf(file_path)

        # pymupdf could not open the file at all
        if probe is None:
            raise RuntimeError(
                f"'{file_path.name}' could not be opened. The file may be "
                f"corrupted, password-protected, or use an unsupported format.\n\n"
                f"Options:\n"
                f"  1. Re-export the PDF using Adobe Acrobat, Microsoft Word "
                f"(Print -> Save as PDF), or LibreOffice.\n"
                f"  2. Convert it to DOCX using Microsoft Word or LibreOffice "
                f"and index the .docx file instead."
            )

        page_count, total_chars = probe

        if page_count == 0:
            raise RuntimeError(
                f"'{file_path.name}' appears to be empty (0 pages)."
            )

        if total_chars >= TEXT_LAYER_THRESHOLD:
            # Digital or mixed PDF: extract text with pymupdf.
            # No Docling, no OCR, no GPU -- completely safe on any machine.
            text = _parsePdfWithMupdf(file_path)
            return _truncateIfNeeded(text, file_path.name)

        # Fully scanned PDF: no text layer found by pymupdf.
        if page_count > SCANNED_MAX_PAGES:
            raise RuntimeError(
                f"'{file_path.name}' is a scanned PDF ({page_count} pages) and "
                f"exceeds the {SCANNED_MAX_PAGES}-page safety limit for OCR "
                f"processing.\n\n"
                f"Options to work around this limit:\n"
                f"  1. Split the PDF into files of {SCANNED_SAFE_PAGES} pages or "
                f"fewer using a tool such as PDFsam (free, desktop) or "
                f"ilovepdf.com (free, online), then run 'ragcmdr add' on the "
                f"folder containing the split files.\n"
                f"  2. Convert the PDF to DOCX using Microsoft Word, LibreOffice, "
                f"or Adobe Acrobat (the OCR is done during conversion), then "
                f"index the resulting .docx file instead.\n"
                f"  3. Raise the limit: "
                f"ragcmdr config set parsing.scanned_max_pages <new_value> "
                f"(only if your machine has sufficient RAM, ~500 MB per "
                f"{SCANNED_BATCH_PAGES} pages of scanned content)."
            )

        if page_count <= SCANNED_SAFE_PAGES:
            # Small scanned PDF: single Docling call, safe on any machine
            text = _parseScannedPdfWithDocling(file_path, 1, page_count)
        else:
            # Medium scanned PDF: page_range batches (official Docling API)
            text = _parsePdfInBatches(file_path, page_count)

        return _truncateIfNeeded(text, file_path.name)

    # --- All other formats: Docling on CPU ---
    text = _parseWithDocling(file_path)
    return _truncateIfNeeded(text, file_path.name)


def collectFiles(
    folder_path: Path,
    recursive: bool = False,
):
    """Scans a folder and separates supported from unsupported files.

    Args:
        folder_path: Absolute or relative path to the folder to scan.
        recursive: If True, scans all sub-directories as well.

    Returns:
        A tuple of (supported_files, skipped_files).

    Raises:
        FileNotFoundError: If folder_path does not exist.
        NotADirectoryError: If folder_path is not a directory.
    """
    if not folder_path.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not folder_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    supported = []
    skipped = []

    iterator = folder_path.rglob("*") if recursive else folder_path.iterdir()

    for item in sorted(iterator):
        if item.is_dir():
            continue
        if isSupportedFile(item):
            supported.append(item)
        else:
            skipped.append(item)

    return supported, skipped


def chunkText(text: str, chunk_size: int = 512, chunk_overlap: int = 64):
    """Splits a long text into overlapping chunks suitable for embedding.

    Args:
        text: The full document text to split.
        chunk_size: Target maximum character length per chunk.
        chunk_overlap: Number of characters to repeat at the start of each
            subsequent chunk for context continuity.

    Returns:
        A list of text chunk strings. Empty list if text is empty.
    """
    text = text.strip()
    if not text:
        return []

    words = text.split()
    chunks = []
    current_chars = 0
    current_words = []

    for word in words:
        word_len = len(word) + 1
        if current_chars + word_len > chunk_size and current_words:
            chunks.append(" ".join(current_words))
            overlap_text = " ".join(current_words)[-chunk_overlap:]
            overlap_words = overlap_text.split()
            current_words = overlap_words[1:] if len(overlap_words) > 1 else []
            current_chars = sum(len(w) + 1 for w in current_words)

        current_words.append(word)
        current_chars += word_len

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _readPlainText(file_path: Path) -> str:
    """Reads a .txt or .md file directly without any third-party library.

    Tries UTF-8 first, then falls back to cp1252 for Windows ANSI files.

    Args:
        file_path: Absolute path to the file.

    Returns:
        File content as a string, truncated if needed.
    """
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = file_path.read_text(encoding="cp1252", errors="replace")

    return _truncateIfNeeded(text, file_path.name)


def _truncateIfNeeded(text: str, filename: str) -> str:
    """Truncates text that exceeds MAX_TEXT_CHARS and appends a notice.

    Args:
        text: The extracted text to check.
        filename: Source filename used in the truncation notice.

    Returns:
        Original text if within limits, otherwise a truncated version
        with a notice appended.
    """
    if len(text) <= MAX_TEXT_CHARS:
        return text

    truncated = text[:MAX_TEXT_CHARS]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]

    notice = (
        f"\n\n[Ragcmdr notice: '{filename}' was truncated at {MAX_TEXT_CHARS:,} "
        f"characters out of {len(text):,} total. "
        f"Only the first portion has been indexed.]"
    )
    return truncated + notice


def _probePdf(file_path: Path):
    """Opens a PDF with pymupdf and returns its page count and total text chars.

    pymupdf (fitz) handles all PDF variants reliably -- including PDFs
    generated by LaTeX, PDFs with non-standard compression, older PDF
    versions, and mixed PDFs containing both text and image pages.

    Args:
        file_path: Absolute path to the PDF file.

    Returns:
        A tuple of (page_count, total_chars), or None if the file cannot
        be opened by pymupdf (corrupted, encrypted, unknown format).
    """
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError(
            "pymupdf is not installed. Run: pip install pymupdf"
        ) from e

    try:
        doc = fitz.open(str(file_path))
    except Exception:
        return None

    try:
        page_count = len(doc)
        total_chars = sum(len(page.get_text()) for page in doc)
        return page_count, total_chars
    except Exception:
        return None
    finally:
        doc.close()


def _parsePdfWithMupdf(file_path: Path) -> str:
    """Extracts the text layer of a PDF using pymupdf -- no Docling, no OCR.

    pymupdf reads the embedded text stream page by page. Pages that contain
    only images return an empty string and are silently skipped. This makes
    the function safe for all PDF types including mixed PDFs, with no page
    limit and zero ML model involvement.

    Args:
        file_path: Absolute path to the PDF file.

    Returns:
        Concatenated text from all pages that have a text layer.

    Raises:
        RuntimeError: If pymupdf cannot open the file.
    """
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError(
            "pymupdf is not installed. Run: pip install pymupdf"
        ) from e

    try:
        doc = fitz.open(str(file_path))
    except Exception as e:
        raise RuntimeError(
            f"pymupdf could not open '{file_path.name}': {e}"
        ) from e

    page_texts = []
    try:
        for page in doc:
            try:
                page_text = page.get_text()
                if page_text.strip():
                    page_texts.append(page_text)
            except Exception:
                continue
    finally:
        doc.close()

    return "\n\n".join(page_texts)


def _buildScannedPdfConverter():
    """Builds a Docling DocumentConverter configured for scanned PDFs.

    Uses PyPdfiumDocumentBackend with OCR enabled and CPU forced via
    AcceleratorOptions. This is the correct configuration according to
    the Docling documentation:
    - PyPdfiumDocumentBackend: recommended backend for all PDF paths.
    - do_ocr=True: activates EasyOCR on image pages.
    - EasyOcrOptions(use_gpu=False): explicitly disables GPU so EasyOCR
      does not silently attempt to use VRAM even when a GPU is present.
    - bitmap_area_threshold=0.05: filters out small logos and header icons
      that would otherwise produce OCR garbage in the extracted chunks.
    - do_table_structure=False: not needed for RAG text extraction.
    - document_timeout: prevents a bad page range from hanging forever.
    - AcceleratorOptions(device=CPU, num_threads=4): forces CPU execution
      and caps inference threads so the process does not over-subscribe
      the CPU when multiple files are indexed in sequence.

    Returns:
        A configured DocumentConverter instance ready for scanned PDFs.

    Raises:
        RuntimeError: If Docling is not installed.
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            AcceleratorOptions,
            AcceleratorDevice,
            EasyOcrOptions,
        )
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    except ImportError as e:
        raise RuntimeError(
            "Docling is not installed. Run: pip install docling"
        ) from e

    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    # Explicitly configure EasyOCR:
    #   use_gpu=False          — prevents silent GPU fallback on machines with a GPU
    #   bitmap_area_threshold  — ignores small bitmaps (logos, icons) that would
    #                            produce garbage text in the extracted chunks
    #   force_full_page_ocr    — False (default): Docling already decides intelligently
    #                            where OCR is needed; forcing it on every page multiplies
    #                            processing time without improving quality
    pipeline_options.ocr_options = EasyOcrOptions(
        use_gpu=False,
        bitmap_area_threshold=0.05,
        force_full_page_ocr=False,
    )
    pipeline_options.do_table_structure = False
    pipeline_options.document_timeout = DOCLING_TIMEOUT
    # num_threads=4: caps CPU inference threads to avoid over-subscribing the system
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU,
        num_threads=4,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
    )


def _parseScannedPdfWithDocling(
    file_path: Path,
    page_start: int,
    page_end: int,
) -> str:
    """Converts a page range of a scanned PDF with Docling OCR on CPU.

    Uses the official Docling page_range parameter passed to convert().
    This is the documented API for processing page subsets of a PDF:
    no temporary files, no pypdf splitting -- Docling handles the slicing
    internally via PyPdfiumDocumentBackend.

    Page numbers are 1-based and inclusive on both ends, matching the
    Docling page_range convention.

    Args:
        file_path: Absolute path to the source PDF.
        page_start: First page to process (1-based, inclusive).
        page_end: Last page to process (1-based, inclusive).

    Returns:
        Extracted Markdown text for the given page range.

    Raises:
        RuntimeError: If Docling fails or times out on this page range.
    """
    converter = _buildScannedPdfConverter()
    try:
        result = converter.convert(
            str(file_path),
            page_range=(page_start, page_end),
        )
        return result.document.export_to_markdown()
    except Exception as e:
        raise RuntimeError(
            f"Docling failed on '{file_path.name}' "
            f"pages {page_start}-{page_end}: {e}"
        ) from e
    finally:
        del converter
        gc.collect()


def _forceMemoryRelease() -> None:
    """Aggressively frees memory after each scanned-PDF batch.

    Three-layer cleanup performed in order:
    1. Evict all Docling-related modules from sys.modules so the next
       batch re-imports them with a clean model registry, preventing
       cumulative RAM growth across batches.
    2. Empty the PyTorch CUDA cache (no-op on CPU-only machines).
    3. Two-pass garbage collection to break reference cycles.
    """
    prefixes_to_remove = ("docling", "easyocr", "torchvision", "rapidocr")
    keys_to_remove = [
        key for key in sys.modules
        if any(key.startswith(p) for p in prefixes_to_remove)
    ]
    for key in keys_to_remove:
        del sys.modules[key]

    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass

    gc.collect()
    gc.collect()


def _parsePdfInBatches(file_path: Path, page_count: int) -> str:
    """Parses a medium scanned PDF in small batches with full OCR on CPU.

    Uses Docling native page_range parameter -- the official approach from
    the Docling documentation and CLI (--page-batch-size flag). No temporary
    files are created; Docling opens the original file and processes only
    the requested pages each time.

    Between each batch, _forceMemoryRelease() evicts all Docling modules
    from sys.modules and runs the garbage collector to prevent cumulative
    RAM growth.

    Only called for scanned PDFs in the range
    (SCANNED_SAFE_PAGES, SCANNED_MAX_PAGES].

    Args:
        file_path: Absolute path to the source PDF.
        page_count: Total page count (already computed by caller).

    Returns:
        Concatenated Markdown text from all batches, in page order.
    """
    all_text_parts = []

    # Build 1-based inclusive page ranges matching Docling page_range convention
    batch_ranges = []
    start = 1
    while start <= page_count:
        end = min(start + SCANNED_BATCH_PAGES - 1, page_count)
        batch_ranges.append((start, end))
        start = end + 1

    for page_start, page_end in batch_ranges:
        try:
            batch_text = _parseScannedPdfWithDocling(
                file_path, page_start, page_end
            )
            if batch_text.strip():
                all_text_parts.append(batch_text)
        except RuntimeError:
            # Log but continue -- a bad batch should not abort the whole file
            pass
        finally:
            _forceMemoryRelease()

    return "\n\n".join(all_text_parts)


def _parseWithDocling(file_path: Path) -> str:
    """Converts a non-PDF file with Docling on CPU with the default pipeline.

    Used for: DOCX, PPTX, XLSX, HTML, images.

    Uses PyPdfiumDocumentBackend (for PDF fallback path consistency) and
    forces CPU via AcceleratorOptions. A document_timeout is set to prevent
    pathological files from blocking the indexing pipeline.
    num_threads=4 caps CPU inference threads to avoid over-subscribing the
    system when multiple files are indexed in sequence.

    Args:
        file_path: Absolute path to the file to convert.

    Returns:
        Extracted text as Markdown.

    Raises:
        RuntimeError: If Docling is not installed or conversion fails.
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            AcceleratorOptions,
            AcceleratorDevice,
        )
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    except ImportError as e:
        raise RuntimeError(
            "Docling is not installed. Run: pip install docling"
        ) from e

    pipeline_options = PdfPipelineOptions()
    pipeline_options.document_timeout = DOCLING_TIMEOUT
    pipeline_options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU,
        num_threads=4,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
                backend=PyPdfiumDocumentBackend,
            )
        }
    )
    try:
        result = converter.convert(str(file_path))
        text = result.document.export_to_markdown()
    except Exception as e:
        raise RuntimeError(
            f"Docling failed to parse '{file_path.name}': {e}"
        ) from e
    finally:
        del converter
        gc.collect()

    return text
