# ragstudio/ragcmdr.py

"""Ragstudio — Lightweight RAG CLI for local AI (LM Studio).

Entry point. Registers all command groups and handles the special
multi-word sub-commands that Typer does not support natively
(e.g. "create collection <name>", "open collection <name>").

Usage examples:
    python ragcmdr.py create collection my-docs
    python ragcmdr.py open collection my-docs
    python ragcmdr.py add C:\\temp\\report.pdf
    python ragcmdr.py chat
    python ragcmdr.py chat --save-history
    python ragcmdr.py add C:\\temp\\folder\\ --recursive
    python ragcmdr.py list collections
    python ragcmdr.py list docs
    python ragcmdr.py info collection my-docs
    python ragcmdr.py close collection
    python ragcmdr.py update collection my-docs C:\\temp\\
    python ragcmdr.py delete collection my-docs
    python ragcmdr.py config show
    python ragcmdr.py config set lmstudio.model mistral-7b
    python ragcmdr.py status
"""

import os
import sys
import typer
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

# Suppress the HuggingFace symlink warning on Windows.
# Models are cached after the first download so this only affects first run.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# ---------------------------------------------------------------------------
# Bootstrap: make imports work from the project root
# ---------------------------------------------------------------------------
from pathlib import Path

# Ensure the ragstudio root is on sys.path so relative imports resolve
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from commands import collection as col_cmd
from commands import document as doc_cmd
from core.config_manager import loadConfig
from core.state_manager import getActiveCollection

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

# Main Typer application — invoke_without_command=True lets us print help
# when the user types just "ragstudio" with no arguments.
app = typer.Typer(
    name="ragcmdr",
    help="ragcmdr — Query your documents with a local AI (Like LM Studio).",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

console = Console()

# ---------------------------------------------------------------------------
# Multi-word command routing
#
# Typer does not natively support commands like "create collection <name>".
# We solve this with a single top-level callback that intercepts the raw
# sys.argv list BEFORE Typer parses it and rewrites it into a form Typer
# understands.
#
# Mapping table:  user input  →  internal Typer command
#
#   create collection <name>      → collection create <name>
#   open collection <name>        → collection open <name>
#   close collection              → collection close
#   list collections              → collection list
#   delete collection <name>      → collection delete <name>
#   update collection <name> <p>  → collection update <name> <p>  (Phase 2)
#   add <path>                    → document add <path>
#   list docs                     → document list-docs
#   remove doc <filename>         → document remove-doc <filename>
# ---------------------------------------------------------------------------

MULTI_WORD_ROUTES: list[tuple[list[str], list[str]]] = [
    # Pattern                          Replacement prefix
    (["create", "collection"],         ["collection", "create"]),
    (["open", "collection"],           ["collection", "open"]),
    (["close", "collection"],          ["collection", "close"]),
    (["list", "collections"],          ["collection", "list"]),
    (["delete", "collection"],         ["collection", "delete"]),
    (["update", "collection"],         ["collection", "update"]),
    (["info", "collection"],           ["collection", "info"]),
    (["list", "docs"],                 ["document", "list-docs"]),
    (["remove", "doc"],                ["document", "remove-doc"]),
    (["add"],                          ["document", "add"]),
    (["config", "show"],               ["config-show"]),
    (["config", "set"],                ["config-set"]),
]


def _rewriteArgs(args: list[str]) -> list[str]:
    """Rewrites natural-language multi-word commands into Typer sub-commands.

    Iterates over MULTI_WORD_ROUTES and replaces matching prefixes in *args*
    so that Typer can dispatch to the correct command handler.

    Args:
        args: The raw argument list (typically sys.argv[1:]).

    Returns:
        A rewritten argument list suitable for Typer dispatch.
    """
    for pattern, replacement in MULTI_WORD_ROUTES:
        n = len(pattern)
        if args[:n] == pattern:
            # Replace the matched prefix; keep any trailing arguments
            return replacement + args[n:]
    return args


# ---------------------------------------------------------------------------
# Sub-application groups
# ---------------------------------------------------------------------------

app.add_typer(col_cmd.app, name="collection", help="Manage collections.")
app.add_typer(doc_cmd.app, name="document", help="Manage documents.")


# ---------------------------------------------------------------------------
# Status command — shows current session at a glance
# ---------------------------------------------------------------------------

@app.command("status")
def showStatus():
    """Displays the current session state and configuration summary."""
    config = loadConfig()
    active = getActiveCollection()

    lm = config.get("lmstudio", {})
    paths = config.get("paths", {})

    status_text = (
        f"[bold]Active collection:[/bold] "
        + (f"[green]{active}[/green]" if active else "[dim]None[/dim]")
        + f"\n\n[bold]LM Studio:[/bold]  {lm.get('base_url', '—')}  "
        + f"  model: [cyan]{lm.get('model', '—')}[/cyan]"
        + f"\n[bold]Collections:[/bold]  {paths.get('collections_dir', '—')}"
        + f"\n[bold]Output:[/bold]       {paths.get('output_dir', '—')}"
    )

    console.print(
        Panel(
            status_text,
            title="[bold cyan]Ragstudio — Status[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        )
    )


# ---------------------------------------------------------------------------
# chat — launch interactive chat session for the active collection
# ---------------------------------------------------------------------------

@app.command("chat")
def startChat(
    save_history: bool = typer.Option(
        False, "--save-history", "-s",
        help="Auto-export the full conversation to a Markdown file when the session ends.",
    ),
):
    """Starts an interactive RAG chat session for the active collection.

    A collection must be open and contain at least one document.
    LM Studio must be running with a model loaded.

    Args:
        save_history: When True, the full conversation is saved to output_dir on exit.
    """
    from core.config_manager import getCollectionsDir
    from core.vectorstore import openStore, getDocumentCount

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

    # Verify the collection has documents before entering the chat loop
    try:
        chroma = openStore(collection_path)
        doc_count = getDocumentCount(chroma)
    except Exception:
        doc_count = 0

    if doc_count == 0:
        console.print(
            Panel(
                f"[yellow]Collection '[cyan]{active}[/cyan]' has no documents yet.[/yellow]\n"
                "Use [cyan]add <path>[/cyan] to index documents first.",
                title="[yellow]Empty Collection[/yellow]",
                border_style="yellow",
            )
        )
        raise typer.Exit(code=1)

    from chat.session import startChatSession
    startChatSession(
        collection_name=active,
        collection_path=collection_path,
        config=config,
        save_history=save_history,
    )


# ---------------------------------------------------------------------------
# config show — display current config.json
# ---------------------------------------------------------------------------

@app.command("config-show")
def configShow():
    """Displays the current configuration from config.json."""
    import json
    from core.config_manager import CONFIG_PATH

    config = loadConfig()
    console.print(
        Panel(
            f"[dim]{CONFIG_PATH}[/dim]",
            title="[bold cyan]config.json[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print_json(json.dumps(config, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# config set <key> <value> — update a top-level lmstudio setting
# ---------------------------------------------------------------------------

@app.command("config-set")
def configSet(
    key: str = typer.Argument(
        ...,
        help="Dot-notation key to update. Example: lmstudio.model",
    ),
    value: str = typer.Argument(..., help="New value to assign."),
):
    """Updates a single value in config.json using dot-notation.

    Supports lmstudio.* and retrieval.top_k keys.
    Numeric values are automatically converted to int or float.

    Examples:
        python ragcmdr.py config set lmstudio.model mistral-7b
        python ragcmdr.py config set lmstudio.temperature 0.5
        python ragcmdr.py config set retrieval.top_k 8
    """
    from core.config_manager import saveConfig

    config = loadConfig()
    parts = key.split(".", 1)

    if len(parts) != 2:
        console.print(
            Panel(
                f"[red]Key must use dot-notation: [yellow]section.field[/yellow][/red]\n"
                f"Example: [cyan]lmstudio.model[/cyan]",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    section, field = parts

    if section not in config:
        console.print(
            Panel(
                f"[red]Unknown section '[yellow]{section}[/yellow]'.[/red]\n"
                f"Available: {', '.join(config.keys())}",
                title="[red]Error[/red]",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)

    # Auto-convert numeric strings
    parsed_value: int | float | str = value
    try:
        parsed_value = int(value)
    except ValueError:
        try:
            parsed_value = float(value)
        except ValueError:
            pass  # keep as string

    config[section][field] = parsed_value
    saveConfig(config)

    console.print(
        Panel(
            f"[green]Updated:[/green] [cyan]{key}[/cyan] = [yellow]{parsed_value}[/yellow]",
            title="[green]✓ Config Updated[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Application entry point.

    Rewrites sys.argv so multi-word commands work, then hands off to Typer.
    """
    # sys.argv[0] is the script name; we only rewrite the arguments after it
    if len(sys.argv) > 1:
        rewritten = _rewriteArgs(sys.argv[1:])
        sys.argv = [sys.argv[0]] + rewritten

    app()


if __name__ == "__main__":
    main()