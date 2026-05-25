# ragstudio/chat/session.py

"""Interactive REPL chat session with RAG context.

Flow for each user message:
    1. Embed the query with sentence-transformers (lazy load, then release)
    2. Retrieve top-k relevant chunks from ChromaDB
    3. Build an augmented prompt (system + context + history + question)
    4. Send to LM Studio via httpx
    5. Render the Markdown response in the terminal via Rich

Special commands available during chat:
    to copy   — copy the last AI response to the clipboard (pyperclip)
    to save   — save the last AI response as a timestamped .md file
    exit/quit — leave the chat loop (collection stays open)
"""

import gc
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich import print as rprint

console = Console()

# Maximum number of previous (user + assistant) message pairs to keep in
# the prompt. Keeping this small limits RAM and token usage.
MAX_HISTORY_PAIRS = 6


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def startChatSession(
    collection_name: str,
    collection_path: Path,
    config: dict,
    save_history: bool = False,
) -> None:
    """Launches the interactive REPL chat session for an open collection.

    Connects to LM Studio, opens ChromaDB for the collection, and enters
    the input loop. Exits cleanly on 'exit', 'quit', or Ctrl+C.

    Args:
        collection_name: Name of the currently open collection (display only).
        collection_path: Absolute path to the collection directory.
        config: The loaded application configuration dictionary.
        save_history: If True, the full conversation is exported to a
            Markdown file in output_dir when the session ends.
    """
    from core.llm_client import checkConnection
    from core.vectorstore import openStore

    lm_cfg = config.get("lmstudio", {})
    base_url: str = lm_cfg.get("base_url", "http://127.0.0.1:1234")
    model: str = lm_cfg.get("model", "local-model")
    system_prompt: str = lm_cfg.get(
        "system_prompt",
        "You are a helpful assistant. Answer only based on the provided context.",
    )
    temperature: float = float(lm_cfg.get("temperature", 0.2))
    max_tokens: int = int(lm_cfg.get("max_tokens", 2048))
    top_k: int = int(config.get("retrieval", {}).get("top_k", 5))
    embedding_model: str = config.get("embedding", {}).get(
        "model_name", "all-MiniLM-L6-v2"
    )
    output_dir = _resolveOutputDir(config)

    # ---- Check LM Studio is reachable before entering the loop ----
    with console.status("[cyan]Connecting to LM Studio...[/cyan]", spinner="dots"):
        reachable = checkConnection(base_url)

    if not reachable:
        console.print(
            Panel(
                f"[red]Cannot reach LM Studio at [yellow]{base_url}[/yellow][/red]\n\n"
                "Make sure:\n"
                "  • LM Studio is open and running\n"
                "  • A model is loaded\n"
                "  • The server is started (green button in LM Studio)\n\n"
                f"You can change the URL in [cyan]config.json[/cyan]",
                title="[red]LM Studio Unreachable[/red]",
                border_style="red",
            )
        )
        return

    # ---- Open ChromaDB (stays open for the whole session) ----
    chroma = openStore(collection_path)

    # ---- Welcome banner ----
    console.print()
    console.print(Rule(f"[bold cyan]Chat — {collection_name}[/bold cyan]", style="cyan"))
    console.print(
        f"[dim]Model:[/dim] [cyan]{model}[/cyan]   "
        f"[dim]Server:[/dim] [cyan]{base_url}[/cyan]   "
        f"[dim]Top-k:[/dim] [cyan]{top_k}[/cyan]"
    )
    console.print(
        "[dim]Commands: [cyan]to copy[/cyan] · [cyan]to save[/cyan] · "
        "[cyan]to history[/cyan] · [cyan]exit[/cyan][/dim]"
    )
    console.print(Rule(style="dim"))
    console.print()

    # ---- State for the session ----
    history: list[dict] = []      # conversation history (role/content pairs)
    full_log: list[dict] = []     # complete log for history export (unbounded)
    last_response: str = ""       # last AI reply, used by to copy / to save

    # ---- Main input loop ----
    while True:
        try:
            user_input = console.input("[bold green]You>[/bold green] ").strip()
        except (KeyboardInterrupt, EOFError):
            # Ctrl+C or Ctrl+D: exit cleanly
            console.print("\n[dim]Session ended.[/dim]")
            if save_history and full_log:
                _saveHistory(full_log, collection_name, output_dir)
            break

        if not user_input:
            continue

        # ---- Special commands ----
        cmd = user_input.lower()

        if cmd in ("exit", "quit"):
            console.print("[dim]Leaving chat. Collection stays open.[/dim]")
            if save_history and full_log:
                _saveHistory(full_log, collection_name, output_dir)
            break

        if cmd == "to copy":
            if not last_response:
                console.print("[yellow]No response to copy yet.[/yellow]")
            else:
                _copyToClipboard(last_response)
            continue

        if cmd == "to save":
            if not last_response:
                console.print("[yellow]No response to save yet.[/yellow]")
            else:
                _saveToFile(last_response, output_dir)
            continue

        if cmd == "to history":
            if not full_log:
                console.print("[yellow]No conversation to export yet.[/yellow]")
            else:
                _saveHistory(full_log, collection_name, output_dir)
            continue

        # ---- RAG pipeline ----
        try:
            # Step 1: embed the query (lazy load, then release immediately)
            query_embedding = _embedQuery(user_input, embedding_model)

            # Step 2: retrieve relevant chunks
            from core.vectorstore import queryStore
            chunks = queryStore(chroma, query_embedding, top_k=top_k)

            if not chunks:
                console.print(
                    Panel(
                        "[yellow]No relevant context found in this collection.[/yellow]\n"
                        "Try rephrasing your question or add more documents.",
                        border_style="yellow",
                    )
                )
                continue

            # Step 3: build augmented messages
            from core.llm_client import buildRagMessages, chatCompletion
            messages = buildRagMessages(
                system_prompt=system_prompt,
                context_chunks=chunks,
                question=user_input,
                history=history,
            )

            # Step 4: call LM Studio
            with console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                answer = chatCompletion(
                    base_url=base_url,
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            # Step 5: render response as Markdown
            console.print()
            console.print(Rule("[dim]Assistant[/dim]", style="dim"))
            console.print(Markdown(answer))
            console.print(Rule(style="dim"))

            # Show sources used
            sources = sorted({c["source_file"] for c in chunks})
            console.print(
                f"[dim]Sources: {', '.join(sources)}[/dim]"
            )
            console.print()

            # Update session state
            last_response = answer
            history = _updateHistory(history, user_input, answer)
            full_log.append({"role": "user", "content": user_input})
            full_log.append({"role": "assistant", "content": answer})

        except RuntimeError as e:
            # LM Studio connection errors, timeouts, etc.
            console.print(
                Panel(
                    f"[red]{e}[/red]",
                    title="[red]Error[/red]",
                    border_style="red",
                )
            )
        except Exception as e:
            console.print(
                Panel(
                    f"[red]Unexpected error: {e}[/red]",
                    title="[red]Error[/red]",
                    border_style="red",
                )
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _embedQuery(query: str, model_name: str) -> list[float]:
    """Embeds a single query string and immediately releases the model.

    Loads sentence-transformers, encodes the query, then frees the model
    from memory before returning.

    Args:
        query: The user's question string.
        model_name: HuggingFace model identifier.

    Returns:
        A single embedding vector as a list of floats.
    """
    from core.embedder import loadEmbedder, embedQuery, releaseEmbedder

    embedder = loadEmbedder(model_name)
    try:
        vector = embedQuery(query, embedder)
    finally:
        # Always release, even if embedQuery raises
        releaseEmbedder(embedder)
        del embedder
        gc.collect()

    return vector


def _updateHistory(
    history: list[dict],
    user_message: str,
    assistant_message: str,
) -> list[dict]:
    """Appends the latest exchange to history and trims to MAX_HISTORY_PAIRS.

    Args:
        history: Current conversation history list.
        user_message: The user's question.
        assistant_message: The assistant's reply.

    Returns:
        Updated history list, trimmed to the last MAX_HISTORY_PAIRS pairs.
    """
    history = history + [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_message},
    ]
    # Keep only the last N pairs (each pair = 2 messages)
    max_messages = MAX_HISTORY_PAIRS * 2
    return history[-max_messages:]


def _copyToClipboard(text: str) -> None:
    """Copies text to the system clipboard using pyperclip.

    Args:
        text: The string to copy.
    """
    try:
        import pyperclip
        pyperclip.copy(text)
        console.print("[green]Response copied to clipboard.[/green]")
    except ImportError:
        console.print(
            "[yellow]pyperclip is not installed.[/yellow] "
            "Run: [cyan]pip install pyperclip[/cyan]"
        )
    except Exception as e:
        console.print(f"[red]Could not copy to clipboard: {e}[/red]")


def _saveToFile(text: str, output_dir: Path) -> None:
    """Saves the response as a timestamped Markdown file.

    Filename format: yy-mm-dd_hh-mm-ss.md
    Colons are replaced with dashes for Windows filesystem compatibility.

    Args:
        text: The Markdown text to save.
        output_dir: Directory where the file will be created.
    """
    timestamp = datetime.now().strftime("%y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.md"
    file_path = output_dir / filename

    try:
        file_path.write_text(text, encoding="utf-8")
        console.print(
            f"[green]Saved:[/green] [cyan]{file_path}[/cyan]"
        )
    except Exception as e:
        console.print(f"[red]Could not save file: {e}[/red]")


def _saveHistory(
    full_log: list[dict],
    collection_name: str,
    output_dir: Path,
) -> None:
    """Exports the full conversation log as a Markdown file.

    The file contains all questions and answers from the session,
    formatted with headings so it reads naturally as a document.
    Filename: yy-mm-dd_hh-mm-ss_history.md

    Args:
        full_log: List of message dicts (role/content) for the full session.
        collection_name: Name of the collection (included in the header).
        output_dir: Directory where the file will be created.
    """
    timestamp = datetime.now().strftime("%y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}_history.md"
    file_path = output_dir / filename

    lines: list[str] = [
        f"# Chat history — {collection_name}",
        f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
    ]

    turn = 1
    i = 0
    while i < len(full_log) - 1:
        user_msg = full_log[i]
        assistant_msg = full_log[i + 1]
        if user_msg["role"] == "user" and assistant_msg["role"] == "assistant":
            lines.append(f"## Question {turn}")
            lines.append("")
            lines.append(f"**You:** {user_msg['content']}")
            lines.append("")
            lines.append(f"**Assistant:**")
            lines.append("")
            lines.append(assistant_msg["content"])
            lines.append("")
            lines.append("---")
            lines.append("")
            turn += 1
            i += 2
        else:
            i += 1

    try:
        file_path.write_text("\n".join(lines), encoding="utf-8")
        console.print(
            f"[green]History saved:[/green] [cyan]{file_path}[/cyan]"
        )
    except Exception as e:
        console.print(f"[red]Could not save history: {e}[/red]")


def _resolveOutputDir(config: dict) -> Path:
    """Resolves and creates the output directory from config.

    Args:
        config: The loaded application configuration dictionary.

    Returns:
        An absolute Path to the output directory.
    """
    from core.config_manager import getOutputDir
    return getOutputDir(config)