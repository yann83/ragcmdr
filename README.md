# Ragcmdr

<p align="center">
  <img src="img/banner.png" width="720px" border="0" alt="banner">
  <br>
  <a href="https://github.com/yann83/userslinker/releases/latest"><img src="https://img.shields.io/github/v/release/yann83/userslinker" alt="Version"></a>
  <img src="https://img.shields.io/badge/Python-3.12-blue">
</p>

A lightweight RAG (Retrieval-Augmented Generation) CLI for querying document collections
using a local AI server (LM Studio), with a rich terminal interface and minimal RAM footprint.

---

## Requirements

- Python 3.12+
- Windows 11
- A local LLM, I use [LM Studio](https://lmstudio.ai/) running locally (default: `http://127.0.0.1:1234`) but it may work with Ollama.

---

## Installation

You can use the setup and launch `ragcmdr` with console command.

Or you could install il manually :

```bash
pip install -r requirements.txt
```

---

## Quick Start

**From console command:**
```bash
ragcmdr create collection my-docs
ragcmdr open collection my-docs
ragcmdr add C:\temp\report.pdf
ragcmdr add C:\temp\folder\
ragcmdr add C:\temp\folder\ --recursive
ragcmdr chat
ragcmdr chat --save-history
```

**From source:**
```bash
python ragcmdr.py create collection my-docs
python ragcmdr.py open collection my-docs
python ragcmdr.py add C:\temp\report.pdf
python ragcmdr.py add C:\temp\folder\
python ragcmdr.py add C:\temp\folder\ --recursive
python ragcmdr.py chat
python ragcmdr.py chat --save-history
```

---

## Command Reference

> All examples below use `ragcmdr`. Replace with `python ragcmdr.py` if running from source.

### Collection Management

| Command | Description |
|---|---|
| `ragcmdr create collection <name>` | Create a new empty collection |
| `ragcmdr open collection <name>` | Open a collection (closes any currently open one) |
| `ragcmdr close collection` | Close the active collection |
| `ragcmdr list collections` | List all collections with document count and status |
| `ragcmdr info collection <name>` | Detailed info: docs, chunks, disk usage, embedding parameters, indexing date |
| `ragcmdr update collection <name> <folder>` | Wipe and re-index from a folder |
| `ragcmdr delete collection <name>` | Delete a collection (with confirmation prompt) |

### Document Management

Requires an open collection.

| Command | Description |
|---|---|
| `ragcmdr add <path>` | Add a file or folder to the open collection |
| `ragcmdr add <path> --recursive` | Add a folder and all its sub-folders |
| `ragcmdr list docs` | List indexed documents with chunk counts |
| `ragcmdr remove doc <filename>` | Remove a specific document from the collection |

### Configuration

| Command | Description |
|---|---|
| `ragcmdr status` | Show active collection and configuration summary |
| `ragcmdr config show` | Display full `config.json` in the terminal |
| `ragcmdr config set <key> <value>` | Update a config value using dot-notation |

**`config set` examples:**

```bash
ragcmdr config set lmstudio.model mistral-7b
ragcmdr config set lmstudio.temperature 0.5
ragcmdr config set lmstudio.max_tokens 4096
ragcmdr config set lmstudio.base_url http://127.0.0.1:1234
ragcmdr config set retrieval.top_k 20
```

> **Note:** `chunk_size`, `chunk_overlap`, and `model_name` changes only apply to newly created
> collections. Existing collections always use the embedding parameters that were active at
> first indexing (stored in `embedding_params.json` inside each collection folder).
> Use `ragcmdr update collection` to re-index with new parameters.
> `top_k` can be changed at any time with no re-indexing required.

### Chat

Requires an open collection with at least one indexed document.

| Command | Description |
|---|---|
| `ragcmdr chat` | Start an interactive RAG chat session |
| `ragcmdr chat --save-history` | Same, auto-exports the full conversation on exit |

**Inside the chat session:**

| Input | Action |
|---|---|
| Any text | Query the AI with RAG context from the collection |
| `to copy` | Copy the last AI response to the clipboard |
| `to save` | Save the last AI response as a Markdown file |
| `to history` | Export the full conversation to a Markdown file |
| `exit` / `quit` | Leave the chat session (collection stays open) |

---

## Configuration

Edit `config.json` directly or use `ragcmdr config set`:

```json
{
  "lmstudio": {
    "base_url": "http://127.0.0.1:1234",
    "model": "local-model",
    "system_prompt": "You are a helpful assistant. Answer only based on the provided context.",
    "temperature": 0.2,
    "max_tokens": 2048
  },
  "paths": {
    "collections_dir": "./collections",
    "output_dir": "./output"
  },
  "embedding": {
    "model_name": "all-MiniLM-L6-v2",
    "chunk_size": 512,
    "chunk_overlap": 64
  },
  "retrieval": {
    "top_k": 5
  }
}
```

### Embedding Parameters Snapshot

When a collection is indexed for the first time, the active embedding parameters
(`chunk_size`, `chunk_overlap`, `model_name`) are saved in
`collections/<name>/embedding_params.json`.

This snapshot is used automatically on subsequent operations, so changing the global
`config.json` values never silently corrupts an existing collection. If the saved
embedding model is no longer available, Ragcmdr will raise a blocking error rather
than index with a mismatched model.

To fully re-index a collection with new embedding parameters:

```bash
ragcmdr update collection my-docs C:\temp\my-folder\
```

---

## Supported File Types (via Docling)

| Format | Extensions |
|---|---|
| PDF | `.pdf` |
| Word | `.docx`, `.doc` |
| PowerPoint | `.pptx`, `.ppt` |
| Excel | `.xlsx` |
| HTML | `.html`, `.htm` |
| Plain text | `.txt`, `.md` |
| Images (OCR) | `.png`, `.jpg`, `.jpeg` |

Unsupported files found in a folder are skipped with a warning and do not interrupt indexing.

---

## Memory Footprint

| Phase | RAM usage |
|---|---|
| Idle (collection open, chat ready) | ~50 MB |
| During indexing (`add` / `update`) | ~140 MB (embedding model loaded, then freed) |
| Chat query | Stateless HTTP call — no extra RAM |

Docling and the sentence-transformers model are loaded lazily only when needed,
then released immediately with `del` + `gc.collect()`.

---

## Output Files

All files are saved in `./output/` (configurable via `paths.output_dir` in `config.json`).

| Command | Filename format |
|---|---|
| `to save` | `yy-mm-dd_hh-mm-ss.md` |
| `to history` | `yy-mm-dd_hh-mm-ss_history.md` |
| `ragcmdr chat --save-history` on exit | `yy-mm-dd_hh-mm-ss_history.md` |

Files are never overwritten: each name includes a timestamp with second precision.

---

## Backup & Restore

Collections are fully portable. Each collection is a self-contained folder:

```
collections/my-docs/
```

Copy it to back up, paste it back into `collections/` to restore. The `embedding_params.json`
snapshot inside the folder ensures the collection can be re-opened without any configuration
changes on the target machine.

---

## Project Structure

```
ragstudio/
├── ragcmdr.py                # Entry point (Typer app, multi-word command routing)
├── config.json                 # Global configuration
├── session.json                # Runtime session state (active collection)
├── requirements.txt
├── README.md
├── commands/
│   ├── __init__.py
│   ├── collection.py           # create, open, close, update, delete, list, info
│   └── document.py             # add, list-docs, remove-doc
├── core/
│   ├── __init__.py
│   ├── config_manager.py       # Load/save config.json
│   ├── state_manager.py        # Active collection state (session.json)
│   ├── parser.py               # Docling wrapper (lazy load, chunkText)
│   ├── embedder.py             # sentence-transformers wrapper (lazy load + GC)
│   ├── vectorstore.py          # ChromaDB wrapper
│   └── llm_client.py           # LM Studio HTTP client (httpx)
├── chat/
│   ├── __init__.py
│   └── session.py              # Interactive REPL chat loop
├── collections/                # Default ChromaDB storage directory
│   └── <name>/
│       ├── chroma/             # ChromaDB data files
│       ├── embedding_params.json  # Embedding snapshot (locked at first indexing)
│       └── doc_count.txt       # Fast document count cache
└── output/                     # Default Markdown export directory
```
