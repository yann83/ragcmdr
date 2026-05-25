# ragstudio/commands/document.py

"""Document management commands.

Requires an active open collection (tracked by state_manager).
Heavy dependencies (Docling, sentence-transformers, ChromaDB) are loaded
lazily inside each command so that idle memory usage stays minimal.
"""

import gc
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table
from rich import box

from core.config_manager import loadConfig, getCollectionsDir
from core.state_manager import getActiveCollection

console = Console()

# Typer sub-application registered in ragcmdr.py
app = typer.Typer(help="Manage documents within the active collection.")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _requireOpenCollection() -> tuple[str, Path, dict]:
    """Ensures a collection is open and returns its context.

    Returns:
        A tuple of (collection_name, collection_path, config).

    Raises:
        SystemExit: If no collection is currently open.
    """
    active = getActiveCollection()
    if not active:
        console.print(
            Panel(
                "[red]No collection is open.[/red]\n"
                "Use [cyan]open collection <name>[/cyan] first.",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    config = loadConfig()
    collections_dir = getCollectionsDir(config)
    collection_path = collections_dir / active
    return active, collection_path, config


def _indexFiles(
    files: list[Path],
    collection_path: Path,
    config: dict,
    progress_label: str = "Indexing",
) -> tuple[int, int]:
    """Parses and indexes a list of files into ChromaDB.

    Loads Docling and the embedding model, processes all files, then
    explicitly releases both from memory with del + gc.collect().

    On the first call for a collection (no ``embedding_params.json`` yet),
    the current ``config.json`` embedding parameters are snapshotted so that
    all future ``add`` calls use the same model and chunk settings.

    On subsequent calls the snapshot is loaded instead of ``config.json``,
    keeping the collection consistent even if the global config has changed.

    Args:
        files: List of file paths to parse and index.
        collection_path: Absolute path to the collection directory.
        config: The loaded application configuration dictionary.
        progress_label: Label shown in the progress bar.

    Returns:
        A tuple of (indexed_count, failed_count).

    Raises:
        SystemExit: If the recorded embedding model is no longer available.
    """
    # Lazy imports: heavy libraries are loaded only for the duration of this call
    from core.parser import parseFile, chunkText
    from core.embedder import loadEmbedder, embedTexts, releaseEmbedder
    #from core.vectorstore import openStore, addChunks, saveDocCount
    from core.vectorstore import openStore, addChunks, saveDocCount, loadEmbeddingParams, saveEmbeddingParams, checkEmbeddingModel

    # ------------------------------------------------------------------
    # Resolve embedding parameters
    #
    # Priority:
    #   1. embedding_params.json already exists → use its values (collection
    #      was previously indexed; we must stay consistent with ChromaDB)
    #   2. No snapshot yet (first add) → use config.json and save a snapshot
    # ------------------------------------------------------------------

    # Check that the recorded model is still available before doing any work
    checkEmbeddingModel(collection_path)

    saved_params = loadEmbeddingParams(collection_path)

    if saved_params is not None:
        # Collection already has a snapshot — honour it
        model_name = saved_params.get("model_name", "all-MiniLM-L6-v2")
        chunk_size = saved_params.get("chunk_size", 512)
        chunk_overlap = saved_params.get("chunk_overlap", 64)
        embedding_cfg = {
            "model_name": model_name,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        }
    else:
        # First indexing run — snapshot current config.json values

        embedding_cfg = config.get("embedding", {})
        model_name = embedding_cfg.get("model_name", "all-MiniLM-L6-v2")
        chunk_size = embedding_cfg.get("chunk_size", 512)
        chunk_overlap = embedding_cfg.get("chunk_overlap", 64)
        saveEmbeddingParams(collection_path, embedding_cfg)

    indexed = 0
    failed = 0

    # Open ChromaDB collection
    chroma = openStore(collection_path)

    # Load embedding model (released after all files are processed)
    with console.status(
        f"[cyan]Loading embedding model ({model_name})...[/cyan]", spinner="dots"
    ):
        embedder = loadEmbedder(model_name)

    # Process files one by one with a progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"[cyan]{progress_label}...[/cyan]", total=len(files))

        for file_path in files:
            progress.update(task, description=f"[cyan]{file_path.name}[/cyan]")

            try:
                # Step 1: parse document into normalized text via Docling
                text = parseFile(file_path)

                if not text.strip():
                    console.print(
                        f"  [yellow]Skipped (empty content):[/yellow] {file_path.name}"
                    )
                    failed += 1
                    progress.advance(task)
                    continue

                # Step 2: split text into overlapping chunks
                chunks = chunkText(
                    text,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                )

                if not chunks:
                    console.print(
                        f"  [yellow]Skipped (no chunks):[/yellow] {file_path.name}"
                    )
                    failed += 1
                    progress.advance(task)
                    continue

                # Step 3: embed all chunks with sentence-transformers
                embeddings = embedTexts(chunks, embedder)

                # Step 4: store in ChromaDB (replaces existing chunks for this file)
                added = addChunks(chroma, chunks, embeddings, file_path.name)

                console.print(
                    f"  [green]OK[/green] {file_path.name} "
                    f"[dim]({added} chunks)[/dim]"
                )
                indexed += 1

            except Exception as e:
                console.print(
                    f"  [red]FAIL[/red] {file_path.name} -- {e}"
                )
                failed += 1

            progress.advance(task)

    # Release embedding model to free ~90 MB RAM
    releaseEmbedder(embedder)
    del embedder
    gc.collect()

    # Update doc_count.txt so list collections can show counts without opening ChromaDB
    saveDocCount(collection_path, chroma)

    return indexed, failed


# ---------------------------------------------------------------------------
# Command: add <path>
# ---------------------------------------------------------------------------

@app.command("add")
def addDocuments(
    path: str = typer.Argument(..., help="File path or folder path to index."),
    recursive: bool = typer.Option(
        False, "--recursive", "-r",
        help="Scan sub-directories recursively (folder mode only).",
    ),
):
    """Adds a file or all files in a folder to the active collection.

    Supported file types are parsed by Docling, split into chunks, embedded
    with sentence-transformers, and stored in ChromaDB. Unsupported files
    are skipped with a warning. Existing documents with the same filename
    are replaced (re-indexed).

    Args:
        path: Absolute or relative path to a file or directory.
        recursive: When True and path is a folder, scans all sub-folders too.
    """
    from core.parser import isSupportedFile, collectFiles

    active, collection_path, config = _requireOpenCollection()

    # Strip trailing backslashes and stray quotes that Windows shells sometimes
    # leave when a quoted path ends with a backslash (e.g. "C:\\folder\\")
    target = Path(path.strip().rstrip('\\"'))

    # ---- Single file mode ----
    if target.is_file():
        if not isSupportedFile(target):
            console.print(
                Panel(
                    f"[red]Unsupported file type:[/red] [yellow]{target.suffix}[/yellow]\n"
                    f"Supported: .pdf .docx .pptx .xlsx .html .txt .md .png .jpg",
                    title="[red]Error[/red]",
                    border_style="red",
                )
            )
            raise typer.Exit(code=1)

        console.print(
            Panel(
                f"Indexing [cyan]{target.name}[/cyan] into collection "
                f"[yellow]{active}[/yellow]...",
                border_style="cyan",
            )
        )
        indexed, failed = _indexFiles([target], collection_path, config)

    # ---- Folder mode ----
    elif target.is_dir():
        supported, skipped = collectFiles(target, recursive=recursive)

        if not supported:
            console.print(
                Panel(
                    f"[yellow]No supported files found in:[/yellow] {target}\n"
                    f"Skipped {len(skipped)} unsupported file(s).",
                    title="[yellow]Nothing to index[/yellow]",
                    border_style="yellow",
                )
            )
            raise typer.Exit(code=0)

        for s in skipped:
            console.print(f"  [dim]Skipped (unsupported): {s.name}[/dim]")

        scan_mode = "[cyan](recursive)[/cyan]" if recursive else "[dim](flat)[/dim]"
        console.print(
            Panel(
                f"Found [green]{len(supported)}[/green] supported file(s) in "
                f"[white]{target}[/white] {scan_mode}\n"
                f"Indexing into collection [yellow]{active}[/yellow]...",
                border_style="cyan",
            )
        )
        indexed, failed = _indexFiles(supported, collection_path, config)

    else:
        console.print(
            Panel(
                f"[red]Path not found:[/red] {path}",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # ---- Summary ----
    status_color = "green" if failed == 0 else "yellow"
    console.print(
        Panel(
            f"[green]Indexed:[/green]  {indexed} file(s)\n"
            + (f"[yellow]Failed:[/yellow]   {failed} file(s)" if failed else ""),
            title=f"[{status_color}] Indexing Complete[/{status_color}]",
            border_style=status_color,
        )
    )


# ---------------------------------------------------------------------------
# Command: list docs
# ---------------------------------------------------------------------------

@app.command("list-docs")
def listDocs():
    """Lists all documents indexed in the currently open collection."""
    from core.vectorstore import openStore, listDocuments

    active, collection_path, _ = _requireOpenCollection()
    chroma = openStore(collection_path)
    docs = listDocuments(chroma)

    if not docs:
        console.print(
            Panel(
                f"[yellow]Collection '[cyan]{active}[/cyan]' has no documents yet.[/yellow]\n"
                "Use [cyan]add <path>[/cyan] to index files.",
                border_style="yellow",
            )
        )
        return

    table = Table(
        title=f"Documents in '{active}'",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
    )
    table.add_column("#", width=4, justify="right", style="dim")
    table.add_column("Filename", style="bold white")
    table.add_column("Chunks", justify="right")

    for i, doc in enumerate(docs, start=1):
        table.add_row(
            str(i),
            doc["source_file"],
            str(doc["chunk_count"]),
        )

    console.print(table)
    console.print(
        f"[dim]Total: {len(docs)} document(s) -- "
        f"{sum(d['chunk_count'] for d in docs)} chunk(s)[/dim]"
    )


# ---------------------------------------------------------------------------
# Command: remove doc <filename>
# ---------------------------------------------------------------------------

@app.command("remove-doc")
def removeDoc(
    filename: str = typer.Argument(..., help="Filename of the document to remove."),
):
    """Removes a specific document from the active collection.

    Args:
        filename: The original filename of the document to remove
            (as shown by list-docs).
    """
    from core.vectorstore import openStore, removeDocument, listDocuments, saveDocCount

    active, collection_path, _ = _requireOpenCollection()
    chroma = openStore(collection_path)

    docs = listDocuments(chroma)
    known = [d["source_file"] for d in docs]

    if filename not in known:
        console.print(
            Panel(
                f"[red]Document '[yellow]{filename}[/yellow]' not found in collection "
                f"'[cyan]{active}[/cyan]'.[/red]\n"
                f"Available: {', '.join(known) if known else '(none)'}",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    deleted = removeDocument(chroma, filename)
    saveDocCount(collection_path, chroma)

    console.print(
        Panel(
            f"[green]Removed '[yellow]{filename}[/yellow]' from collection "
            f"'[cyan]{active}[/cyan]'.[/green]\n"
            f"[dim]{deleted} chunk(s) deleted.[/dim]",
            title="[green] Document Removed[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# update helper (called from commands/collection.py)
# ---------------------------------------------------------------------------

def runUpdate(name: str, folder: str, collection_path: Path, config: dict) -> None:
    """Wipes a collection and re-indexes all files from a folder.

    Called by commands/collection.py for the update collection command.

    After wiping ChromaDB the existing ``embedding_params.json`` snapshot is
    deleted so that ``_indexFiles`` treats the re-indexing as a first run and
    writes a fresh snapshot from the current ``config.json`` values

    Args:
        name: Collection name (used for display messages only).
        folder: Path to the folder whose contents replace the collection.
        collection_path: Absolute path to the collection directory.
        config: The loaded application configuration.
    """
    from core.parser import collectFiles
    from core.vectorstore import openStore, wipeStore, saveDocCount, EMBEDDING_PARAMS_FILE

    # Same Windows backslash-quote stripping as in addDocuments
    target = Path(folder.strip().rstrip('\\"'))

    if not target.is_dir():
        console.print(
            Panel(
                f"[red]Folder not found:[/red] {folder}",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    supported, skipped = collectFiles(target)

    if not supported:
        console.print(
            Panel(
                f"[yellow]No supported files found in:[/yellow] {folder}",
                title="[yellow]Nothing to index[/yellow]",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    for s in skipped:
        console.print(f"  [dim]Skipped (unsupported): {s.name}[/dim]")

    # Wipe existing content
    console.print(f"[dim]Wiping collection '[cyan]{name}[/cyan]'...[/dim]")
    chroma = openStore(collection_path)
    wipeStore(chroma)
    saveDocCount(collection_path, chroma)

    # Delete the embedding params snapshot so _indexFiles creates a fresh one
    # from the current config.json values (this is the purpose of update collection)
    params_file = collection_path / EMBEDDING_PARAMS_FILE
    if params_file.exists():
        params_file.unlink()

    # Re-index from the folder
    console.print(
        Panel(
            f"Re-indexing [green]{len(supported)}[/green] file(s) from "
            f"[white]{folder}[/white] into [yellow]{name}[/yellow]...",
            border_style="cyan",
        )
    )
    indexed, failed = _indexFiles(
        supported, collection_path, config, progress_label="Re-indexing"
    )

    status_color = "green" if failed == 0 else "yellow"
    console.print(
        Panel(
            f"[green]Indexed:[/green]  {indexed} file(s)\n"
            + (f"[yellow]Failed:[/yellow]   {failed} file(s)" if failed else ""),
            title=f"[{status_color}] Update Complete[/{status_color}]",
            border_style=status_color,
        )
    )