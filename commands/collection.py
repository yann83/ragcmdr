# ragstudio/commands/collection.py

import typer
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel

from core.config_manager import loadConfig, getCollectionsDir
from core.state_manager import getActiveCollection, setActiveCollection, clearSession

# Shared Rich console for all output in this module
console = Console()

# Typer sub-application registered in ragcmdr.py
app = typer.Typer(help="Manage document collections.")


def _collectionExists(name: str, collections_dir: Path) -> bool:
    """Checks whether a collection directory already exists on disk.

    Args:
        name: The collection name to check.
        collections_dir: The root directory that stores all collections.

    Returns:
        True if the collection folder exists, False otherwise.
    """
    return (collections_dir / name).exists()


def _getDocumentCount(collection_path: Path) -> int:
    """Counts the number of indexed documents stored in a collection folder.

    Looks for a 'docs' metadata file written during indexing (Phase 2).
    Falls back to 0 if the file is not yet present (Phase 1 skeleton).

    Args:
        collection_path: Absolute path to the collection directory.

    Returns:
        The number of indexed documents, or 0 if unknown.
    """
    # This metadata file will be created in Phase 2 by vectorstore.py
    meta_file = collection_path / "doc_count.txt"
    if meta_file.exists():
        try:
            return int(meta_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return 0
    return 0


# ---------------------------------------------------------------------------
# Command: create collection <name>
# ---------------------------------------------------------------------------

@app.command("create")
def createCollection(
    name: str = typer.Argument(..., help="Unique name for the new collection."),
):
    """Creates a new empty collection.

    Fails if a collection with the same name already exists.
    The collection folder is created inside the configured collections directory.
    """
    config = loadConfig()
    collections_dir = getCollectionsDir(config)

    # Business rule: collection names must be unique
    if _collectionExists(name, collections_dir):
        console.print(
            Panel(
                f"[bold red]Collection '[yellow]{name}[/yellow]' already exists.[/bold red]\n"
                f"Use [cyan]open collection {name}[/cyan] to open it, or choose a different name.",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # Create the physical directory that ChromaDB will use in Phase 2
    collection_path = collections_dir / name
    collection_path.mkdir(parents=True)

    console.print(
        Panel(
            f"[bold green]Collection '[yellow]{name}[/yellow]' created successfully.[/bold green]\n"
            f"Use [cyan]add <path>[/cyan] after opening it to index documents.",
            title="[green]✓ Collection Created[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command: open collection <name>
# ---------------------------------------------------------------------------

@app.command("open")
def openCollection(
    name: str = typer.Argument(..., help="Name of the collection to open."),
):
    """Opens an existing collection for querying and document management.

    If another collection is currently open, it is closed first.
    Use the [cyan]chat[/cyan] command to start a chat session after opening.

    Args:
        name: The collection to open.
    """
    config = loadConfig()
    collections_dir = getCollectionsDir(config)

    # Validate that the collection exists
    if not _collectionExists(name, collections_dir):
        _printCollectionNotFound(name, collections_dir)
        raise typer.Exit(code=1)

    # Close any previously open collection (silent, no error)
    current = getActiveCollection()
    if current and current != name:
        console.print(f"[dim]Closing '[yellow]{current}[/yellow]' first...[/dim]")
        clearSession()

    # Persist the new active session
    setActiveCollection(name)

    doc_count = _getDocumentCount(collections_dir / name)

    console.print(
        Panel(
            f"[bold green]Collection '[yellow]{name}[/yellow]' is now open.[/bold green]\n"
            + (
                f"[dim]{doc_count} document(s) indexed.[/dim]\n"
                f"Use [cyan]chat[/cyan] to start chatting, or [cyan]add <path>[/cyan] to index more documents."
                if doc_count > 0
                else "[dim]No documents yet.[/dim]\n"
                f"Use [cyan]add <path>[/cyan] to index documents, then [cyan]chat[/cyan] to start."
            ),
            title=f"[green]✓ Opened: {name}[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command: close collection
# ---------------------------------------------------------------------------

@app.command("close")
def closeCollection():
    """Closes the currently open collection and frees associated resources."""
    current = getActiveCollection()

    if not current:
        console.print(
            Panel(
                "[yellow]No collection is currently open.[/yellow]",
                title="[yellow]Nothing to close[/yellow]",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=0)

    clearSession()

    console.print(
        Panel(
            f"[bold green]Collection '[yellow]{current}[/yellow]' closed.[/bold green]",
            title="[green]✓ Closed[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command: list collections
# ---------------------------------------------------------------------------

@app.command("list")
def listCollections():
    """Lists all existing collections with their document count and status."""
    config = loadConfig()
    collections_dir = getCollectionsDir(config)
    active = getActiveCollection()

    # Find all subdirectories — each one is a collection
    collection_dirs = sorted(
        [d for d in collections_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )

    if not collection_dirs:
        console.print(
            Panel(
                "[yellow]No collections found.[/yellow]\n"
                "Use [cyan]create collection <name>[/cyan] to create your first one.",
                title="Collections",
                border_style="dim",
            )
        )
        return

    # Build a Rich table for a clean display
    table = Table(
        title="Available Collections",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Status", width=8, justify="center")
    table.add_column("Name", style="bold white")
    table.add_column("Documents", justify="right")
    table.add_column("Path", style="dim")

    for d in collection_dirs:
        is_active = d.name == active
        status = "[green]● OPEN[/green]" if is_active else "[dim]○[/dim]"
        doc_count = _getDocumentCount(d)
        docs_display = (
            f"[green]{doc_count}[/green]" if doc_count > 0 else "[dim]0[/dim]"
        )
        table.add_row(status, d.name, docs_display, str(d))

    console.print(table)


# ---------------------------------------------------------------------------
# Command: update collection <name> <folder>
# ---------------------------------------------------------------------------

@app.command("update")
def updateCollection(
    name: str = typer.Argument(..., help="Name of the collection to update."),
    folder: str = typer.Argument(..., help="Folder whose contents replace the collection."),
):
    """Wipes a collection and re-indexes all files from a folder.

    The collection must exist but does NOT need to be open. If it is
    currently open, the update proceeds and the session remains active.

    Args:
        name: The collection to update.
        folder: Path to the folder to re-index.
    """
    config = loadConfig()
    collections_dir = getCollectionsDir(config)

    if not _collectionExists(name, collections_dir):
        _printCollectionNotFound(name, collections_dir)
        raise typer.Exit(code=1)

    # Delegate to document.runUpdate which owns the indexing pipeline
    from commands.document import runUpdate
    runUpdate(name, folder, collections_dir / name, config)


# ---------------------------------------------------------------------------
# Command: delete collection <name>
# ---------------------------------------------------------------------------

@app.command("delete")
def deleteCollection(
    name: str = typer.Argument(..., help="Name of the collection to delete."),
):
    """Permanently deletes a collection after confirmation.

    The active collection cannot be deleted while it is open.
    """
    import shutil

    config = loadConfig()
    collections_dir = getCollectionsDir(config)

    if not _collectionExists(name, collections_dir):
        _printCollectionNotFound(name, collections_dir)
        raise typer.Exit(code=1)

    # Prevent accidental deletion of the open collection
    active = getActiveCollection()
    if active == name:
        console.print(
            Panel(
                f"[red]Cannot delete '[yellow]{name}[/yellow]' while it is open.[/red]\n"
                f"Run [cyan]close collection[/cyan] first.",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # Confirmation prompt to avoid accidental deletions
    confirmed = typer.confirm(
        f"⚠  Permanently delete collection '{name}'? This cannot be undone.",
        default=False,
    )
    if not confirmed:
        console.print("[dim]Deletion cancelled.[/dim]")
        raise typer.Exit(code=0)

    shutil.rmtree(collections_dir / name)

    console.print(
        Panel(
            f"[bold green]Collection '[yellow]{name}[/yellow]' has been deleted.[/bold green]",
            title="[green]✓ Deleted[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Command: info collection <name>
# ---------------------------------------------------------------------------

@app.command("info")
def infoCollection(
    name: str = typer.Argument(..., help="Name of the collection to inspect."),
):
    """Shows detailed information about a specific collection.

    Displays document list, chunk counts, disk usage, and current status.

    Args:
        name: The collection name to inspect.
    """
    from rich.table import Table
    from rich import box as rich_box

    config = loadConfig()
    collections_dir = getCollectionsDir(config)

    if not _collectionExists(name, collections_dir):
        _printCollectionNotFound(name, collections_dir)
        raise typer.Exit(code=1)

    collection_path = collections_dir / name
    active = getActiveCollection()
    is_active = active == name

    # Compute disk usage
    total_bytes = sum(
        f.stat().st_size
        for f in collection_path.rglob("*")
        if f.is_file()
    )
    disk_mb = total_bytes / (1024 * 1024)

    # Try to read document list from ChromaDB
    doc_rows: list[dict] = []
    try:
        from core.vectorstore import openStore, listDocuments, loadEmbeddingParams
        chroma = openStore(collection_path)
        doc_rows = listDocuments(chroma)
        emb_params = loadEmbeddingParams(collection_path)
    except Exception:
        emb_params = None

    status_str = "[green]● OPEN[/green]" if is_active else "[dim]○ closed[/dim]"

    # Build embedding params line for display
    if emb_params:
        emb_line = (
            f"\n[bold]Embedding:[/bold]  "
            f"model=[cyan]{emb_params.get('model_name', '—')}[/cyan]  "
            f"chunk=[cyan]{emb_params.get('chunk_size', '—')}[/cyan]  "
            f"overlap=[cyan]{emb_params.get('chunk_overlap', '—')}[/cyan]  "
            f"[dim](indexed {emb_params.get('indexed_at', '—')})[/dim]"
        )
    else:
        emb_line = f"\n[bold]Embedding:[/bold]  [dim]not indexed yet[/dim]"

    sep = "\n"
    summary = (
        f"[bold]Status:[/bold]     {status_str}{sep}"
        f"[bold]Documents:[/bold]  {len(doc_rows)}{sep}"
        f"[bold]Chunks:[/bold]     {sum(d['chunk_count'] for d in doc_rows)}{sep}"
        f"[bold]Disk:[/bold]       {disk_mb:.1f} MB{sep}"
        f"[bold]Path:[/bold]       [dim]{collection_path}[/dim]"
        f"{emb_line}"
    )

    console.print(
        Panel(
            summary,
            title=f"[bold cyan]Collection: {name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )

    if doc_rows:
        table = Table(
            box=rich_box.SIMPLE,
            header_style="bold cyan",
            show_edge=False,
        )
        table.add_column("#", width=4, justify="right", style="dim")
        table.add_column("Filename", style="white")
        table.add_column("Chunks", justify="right")

        for i, doc in enumerate(doc_rows, start=1):
            table.add_row(str(i), doc["source_file"], str(doc["chunk_count"]))

        console.print(table)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _printCollectionNotFound(name: str, collections_dir: Path) -> None:
    """Prints a formatted error when a collection is not found.

    Lists available collections to help the user correct the name.

    Args:
        name: The collection name that was not found.
        collections_dir: Root directory of all collections.
    """
    existing = [d.name for d in collections_dir.iterdir() if d.is_dir()]
    hint = (
        "Available: " + ", ".join(f"[yellow]{n}[/yellow]" for n in existing)
        if existing
        else "No collections exist yet. Use [cyan]create collection <name>[/cyan]."
    )
    console.print(
        Panel(
            f"[red]Collection '[yellow]{name}[/yellow]' not found.[/red]\n{hint}",
            title="[red]Error[/red]",
            border_style="red",
        )
    )