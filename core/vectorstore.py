# ragstudio/core/vectorstore.py

"""ChromaDB vector store wrapper.

Each Ragstudio collection maps to one ChromaDB collection stored on disk
inside the configured ``collections_dir``. The ChromaDB client is opened
when a collection is opened and closed when the collection is closed,
keeping idle memory usage low.

Metadata stored per chunk:
    - source_file : original filename (used for list-docs and remove-doc)
    - chunk_index : position of this chunk within the source document
    - doc_id      : unique identifier combining filename + chunk index
"""

import json
import gc
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# ChromaDB client lifecycle
# ---------------------------------------------------------------------------

def openStore(collection_path: Path) -> Any:
    """Opens a persistent ChromaDB client for the given collection path.

    Args:
        collection_path: Absolute path to the collection directory.
            ChromaDB will store its data files inside this folder.

    Returns:
        A ChromaDB Collection object ready for queries and inserts.

    Raises:
        RuntimeError: If chromadb is not installed.
    """
    try:
        import chromadb
    except ImportError as e:
        raise RuntimeError(
            "chromadb is not installed. Run: pip install chromadb"
        ) from e

    # PersistentClient stores data on disk — no server process needed
    client = chromadb.PersistentClient(path=str(collection_path / "chroma"))

    # get_or_create: safe whether the collection is brand new or already exists
    collection = client.get_or_create_collection(
        name="documents",
        # cosine distance works well for sentence-transformers embeddings
        metadata={"hnsw:space": "cosine"},
    )
    return collection


def closeStore(collection: Any) -> None:
    """Releases the ChromaDB collection object from memory.

    Args:
        collection: The ChromaDB Collection object returned by ``openStore``.
    """
    del collection
    gc.collect()


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def addChunks(
    collection: Any,
    chunks: list[str],
    embeddings: list[list[float]],
    source_file: str,
) -> int:
    """Adds text chunks and their embeddings to the vector store.

    Existing chunks from the same source file are replaced to prevent
    duplicates when a file is re-indexed.

    Args:
        collection: The ChromaDB Collection object (from ``openStore``).
        chunks: List of text chunk strings to store.
        embeddings: Embedding vectors aligned with ``chunks``.
        source_file: Original filename (used as metadata for filtering).

    Returns:
        The number of chunks successfully added.
    """
    if not chunks:
        return 0

    # Remove any existing chunks from this file before re-inserting
    removeDocument(collection, source_file)

    # Build unique IDs: filename + chunk index guarantees no collisions
    ids = [f"{source_file}::{i}" for i in range(len(chunks))]
    metadatas = [
        {"source_file": source_file, "chunk_index": i}
        for i in range(len(chunks))
    ]

    # ChromaDB upsert is idempotent — safe to call multiple times
    collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


def removeDocument(collection: Any, source_file: str) -> int:
    """Removes all chunks associated with a specific source file.

    Args:
        collection: The ChromaDB Collection object.
        source_file: Original filename to remove.

    Returns:
        The number of chunks deleted. Returns 0 if the file was not found.
    """
    # Query existing IDs for this file before deleting
    results = collection.get(where={"source_file": source_file})
    ids_to_delete = results.get("ids", [])

    if ids_to_delete:
        collection.delete(ids=ids_to_delete)

    return len(ids_to_delete)


def wipeStore(collection: Any) -> None:
    """Removes ALL chunks from the collection (used by update collection).

    Args:
        collection: The ChromaDB Collection object to wipe.
    """
    all_items = collection.get()
    ids = all_items.get("ids", [])
    if ids:
        collection.delete(ids=ids)


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

def queryStore(
    collection: Any,
    query_embedding: list[float],
    top_k: int = 5,
) -> list[dict]:
    """Retrieves the top-k most relevant chunks for a query embedding.

    Args:
        collection: The ChromaDB Collection object.
        query_embedding: The embedding vector of the user's question.
        top_k: Maximum number of chunks to return.

    Returns:
        A list of result dictionaries, each containing:
            - ``text``        : the chunk text
            - ``source_file`` : originating filename
            - ``chunk_index`` : chunk position in the source document
            - ``distance``    : cosine distance (lower = more similar)
    """
    count = collection.count()
    if count == 0:
        return []

    # Clamp top_k to the number of available chunks
    effective_k = min(top_k, count)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=effective_k,
        include=["documents", "metadatas", "distances"],
    )

    output: list[dict] = []
    for text, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        output.append({
            "text": text,
            "source_file": meta.get("source_file", "unknown"),
            "chunk_index": meta.get("chunk_index", 0),
            "distance": round(dist, 4),
        })

    return output


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def listDocuments(collection: Any) -> list[dict]:
    """Returns one entry per unique source file indexed in the collection.

    Args:
        collection: The ChromaDB Collection object.

    Returns:
        A list of dicts with keys ``source_file`` and ``chunk_count``.
    """
    all_items = collection.get(include=["metadatas"])
    metadatas = all_items.get("metadatas", [])

    # Aggregate chunk counts per source file
    counts: dict[str, int] = {}
    for meta in metadatas:
        name = meta.get("source_file", "unknown")
        counts[name] = counts.get(name, 0) + 1

    return [
        {"source_file": name, "chunk_count": count}
        for name, count in sorted(counts.items())
    ]


def getDocumentCount(collection: Any) -> int:
    """Returns the number of unique source files in the collection.

    Args:
        collection: The ChromaDB Collection object.

    Returns:
        Number of distinct source files indexed.
    """
    return len(listDocuments(collection))


def saveDocCount(collection_path: Path, collection: Any) -> None:
    """Writes the document count to a small metadata file on disk.

    This file is read by ``commands/collection.py`` to show counts in
    ``list collections`` without needing to open ChromaDB.

    Args:
        collection_path: Absolute path to the collection directory.
        collection: The ChromaDB Collection object.
    """
    count = getDocumentCount(collection)
    (collection_path / "doc_count.txt").write_text(str(count), encoding="utf-8")


# Filename for the per-collection embedding parameters snapshot
EMBEDDING_PARAMS_FILE = "embedding_params.json"


def saveEmbeddingParams(collection_path: Path, embedding_cfg: dict) -> None:
    """Saves the embedding parameters used to index this collection.

    Called on the first ``add`` to snapshot the active config so that
    subsequent ``add`` calls always use the same parameters, regardless
    of what ``config.json`` currently says.

    The ``_warning`` field discourages manual editing.

    Args:
        collection_path: Absolute path to the collection directory.
        embedding_cfg: Dict with keys ``model_name``, ``chunk_size``,
            ``chunk_overlap`` taken from the ``embedding`` section of
            ``config.json``.
    """
    from datetime import datetime

    params = {
        "_warning": "Do not edit this file manually. "
                    "Use 'update collection' to reindex with new parameters.",
        "model_name": embedding_cfg.get("model_name", "all-MiniLM-L6-v2"),
        "chunk_size": embedding_cfg.get("chunk_size", 512),
        "chunk_overlap": embedding_cfg.get("chunk_overlap", 64),
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
    }

    params_path = collection_path / EMBEDDING_PARAMS_FILE
    with params_path.open("w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)


def loadEmbeddingParams(collection_path: Path) -> dict | None:
    """Loads the embedding parameters snapshot for a collection.

    Returns None if the file does not exist yet (collection never indexed).

    Args:
        collection_path: Absolute path to the collection directory.

    Returns:
        A dict with ``model_name``, ``chunk_size``, ``chunk_overlap`` and
        ``indexed_at``, or None if no snapshot exists.
    """
    params_path = collection_path / EMBEDDING_PARAMS_FILE
    if not params_path.exists():
        return None

    try:
        with params_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted file — treat as missing so a fresh snapshot is created
        return None


def checkEmbeddingModel(collection_path: Path) -> None:
    """Verifies that the model recorded in embedding_params.json is available.

    Raises a RuntimeError if the model cannot be loaded by
    sentence-transformers, so the caller can show a clear error message
    before any heavy work begins.

    Does nothing if no snapshot exists yet (first indexing run).

    Args:
        collection_path: Absolute path to the collection directory.

    Raises:
        RuntimeError: If the recorded model is not available locally or
            cannot be downloaded.
    """
    params = loadEmbeddingParams(collection_path)
    if params is None:
        # No snapshot yet — nothing to check
        return

    model_name = params.get("model_name", "")
    if not model_name:
        return

    try:
        # Attempt a lightweight import check without loading the full model
        from sentence_transformers import SentenceTransformer
        # SentenceTransformer constructor triggers the download/cache check
        model = SentenceTransformer(model_name)
        del model
    except Exception as e:
        raise RuntimeError(
            f"The embedding model '{model_name}' recorded for this collection "
            f"is no longer available.\n"
            f"Details: {e}\n\n"
            f"Options:\n"
            f"  • Restore the model '{model_name}' (re-download or reinstall)\n"
            f"  • Run: update collection <name> <folder>  to reindex with a "
            f"different model (set the new model in config.json first)"
        ) from e