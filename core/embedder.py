# ragstudio/core/embedder.py

"""Embedding module using sentence-transformers.

The model is loaded lazily (only when needed) and released with an explicit
``del`` + ``gc.collect()`` call as soon as the indexing batch is complete,
keeping idle RAM usage minimal.

Default model: all-MiniLM-L6-v2  (~90 MB RAM, fast, good quality for RAG)
"""

import gc
from typing import TYPE_CHECKING

# TYPE_CHECKING guard: SentenceTransformer type hint without importing at
# module load time (the import is deferred to the functions that need it).
if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def loadEmbedder(model_name: str = "all-MiniLM-L6-v2") -> "SentenceTransformer":
    """Loads and returns the sentence-transformers embedding model.

    Call this only when you are about to generate embeddings, and call
    ``releaseEmbedder()`` as soon as you are done.

    Args:
        model_name: HuggingFace model identifier. Defaults to all-MiniLM-L6-v2.

    Returns:
        A loaded SentenceTransformer model instance.

    Raises:
        RuntimeError: If sentence-transformers is not installed.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Run: pip install sentence-transformers"
        ) from e

    # The model is downloaded automatically on first use and cached by HuggingFace
    model = SentenceTransformer(model_name)
    return model


def releaseEmbedder(model: "SentenceTransformer") -> None:
    """Explicitly releases a loaded embedding model from memory.

    Deletes the model object and calls the garbage collector to free
    the underlying PyTorch tensors as promptly as possible.

    Args:
        model: The SentenceTransformer instance to release.
    """
    del model
    gc.collect()


def embedTexts(
    texts: list[str],
    model: "SentenceTransformer",
    batch_size: int = 32,
) -> list[list[float]]:
    """Converts a list of text strings into embedding vectors.

    Args:
        texts: List of text chunks to embed.
        model: A loaded SentenceTransformer model (from ``loadEmbedder``).
        batch_size: Number of texts to encode per batch. Lower values use
            less RAM at the cost of slightly more processing time.

    Returns:
        A list of embedding vectors. Each vector is a list of floats.
        The order matches the input ``texts`` list.
    """
    # encode() returns a numpy array; .tolist() converts it to plain Python
    # lists that ChromaDB can serialize without extra dependencies.
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return embeddings.tolist()


def embedQuery(query: str, model: "SentenceTransformer") -> list[float]:
    """Converts a single query string into an embedding vector.

    Args:
        query: The user's question or search string.
        model: A loaded SentenceTransformer model (from ``loadEmbedder``).

    Returns:
        A single embedding vector as a list of floats.
    """
    embedding = model.encode([query], convert_to_numpy=True)
    return embedding[0].tolist()