# Ragcmdr

<p align="center">
  <img src="img/banner.png" width="720px" border="0" alt="banner">
  <br>
  <a href="https://github.com/yann83/ragcmdr/releases/latest"><img src="https://img.shields.io/github/v/release/yann83/ragcmdr" alt="Version"></a>
  <img src="https://img.shields.io/badge/Python-3.12-blue">
</p>

A lightweight RAG (Retrieval-Augmented Generation) CLI for querying document collections
using a local AI server (LM Studio), with a rich terminal interface and minimal RAM footprint.

---

A small gesture, a big support! Buy me a coffee ☕ if you appreciate my work. Thanks in advance!

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/yann83)

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

1. Like a library, a collection contains the files that will be used to populate the theme of your choice.

`ragcmdr create collection my-docs`

2. Then open your collection

`ragcmdr open collection my-docs`

3. Add a file, a folder, or an entire file tree.

```bash
ragcmdr add C:\temp\report.pdf
ragcmdr add C:\temp\folder\
ragcmdr add C:\temp\folder\ --recursive
```

4. After the feeding process is complete, you can chat with your files

`ragcmdr chat`

5. When you done you can exit the chat then close your collection.

```bash
exit
ragcmdr close collection
```


**From source:**

Replace `ragcmdr` by `python ragcmdr.py`

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

---

## F.A.Q

 - Do I need administrator right to install `ragcmdr` ?

 >No, it's an user installer, I made this choice to avoid suspicions about my program, `ragcmdr` will never ask you for privilege elevation.

 - When I type `ragcmdr` in the console windows, I get `'ragcmdr' is not recognized as an internal command`, why ?

 >The installer add `ragcmdr` to the user path variable, if it's not enough add it to the system path too. You'll need administrator right.

 - Can I use Ollama with it ?

 >The URL to configure would be http://127.0.0.1:11434 via `ragcmdr config set lmstudio.base_url http://127.0.0.1:11434`. Tell me if it doesn't work.

- Where is my data stored? 
  
>Collections are located in %LOCALAPPDATA%\Ragcmdr\collections\ or the specified installation folder. Everything is local.

 - How do I update a collection after modifying files? 
 
>You muse use `ragcmdr update collection <name> <folder>` command. Your collection content will be wiped then re-indexed from your source folder.

 - LM Studio is not connected, what to do? 
 
>Is the server status is started (green button) ? Check for serveur response in Developer Logs.

- Which LLM can I use ?

>The most important criteria are: a large context window (minimum 32k tokens, 128k+ recommended) to absorb the retrieved chunks, and a good ability to follow instructions—the model must respond solely based on the provided snippets, without making things up. The model's language must match that of your documentation and questions.

 - Why is indexing slow the first time? 
 
>Docling and the embedding template are downloaded on the first launch (~300 MB). 

 - Can I index files in multiple languages? 
 
>The `all-MiniLM-L6-v2` model is multilingual but optimized for English. For dense French, for example, the results may be less accurate.

 - My documents are in French (or another language), should I change the embedding model?

>The default model `all-MiniLM-L6-v2` works in French but is optimized for English. For better results with French documents, use `paraphrase-multilingual-MiniLM-L12-v2`, use 
`ragcmdr config set embedding.model_name paraphrase-multilingual-MiniLM-L12-v2`
Then re-index your existing collections with `ragcmdr update collection <name> <folder>`.

- Could you explain the embedding parameters: `chunk_size`, `chunk_overlap` and the retrieval parameter: `top_k` ?

`chunk_size` — Chunk Size

>When you index a 30-page PDF, Docling converts it to plain text (approximately 50,000 to 90,000 characters depending on the density). This text is then broken down into small chunks. `chunk_size = 512` means that each chunk is a maximum of 512 characters.
>Why not send the entire PDF to the LLM? Because ChromaDB needs to compare your query to each chunk individually. The smaller the chunks, the more accurate the comparison—but if they're too small, they lose their context.

`chunk_overlap` — Overlap

>Imagine a sentence split precisely between two chunks: *"The maximum temperature is"* in chunk 1, and *"25°C according to regulations"* in chunk 2. Without overlap, if you search for "maximum temperature," chunk 1 would be selected but would be incomplete.
>With `chunk_overlap = 64`, the last 64 characters of chunk 1 are copied to the beginning of chunk 2. The two chunks then contain the complete sentence. This is essential for protecting information that overlaps a chunk.

`top_k` — the number of chunks sent to the LLM

>After indexing, ChromaDB contains hundreds of chunks. When you ask a question, it is transformed into a vector and compared to all the chunks using cosine distance. `top_k = 50` means that the 50 semantically closest chunks are sent to the LLM prompt as context. The default value in `config.json` is `5`.

 - Can you give me an example ?

>With `gpt-oss-20b` with 100k+ context windows :
a `chunk_size 1024` provides chunks richer in context, perfect for dense technical or legal documents.
a `chunk_overlap 200` (≈20% of the chunk) better preserves continuity between paragraphs.
a `top_k 20` sends more relevant context to the LLM without overloading the prompt.

>If your documents are very short (forms, emails), you can lower `chunk_size` to 512 for greater precision. For long and dense reports, increase it to 2048.

 - I asked something but the answer was out of context or limited. Does it really work ?

>You must be precise in your questions, starting by indicating which files are relevant to your search and using the exact words found in those files. If you are asking for information about a blue car, but the word "car" is not mentioned in your files and is replaced by "automobile," then you must use the same terms.
---

## Acknowledgements

- **[Docling](https://github.com/DS4SD/docling)** — the document parser
- **[ChromaDB](https://github.com/chroma-core/chroma)** — the local vector base
- **[sentence-transformers](https://github.com/UKPLab/sentence-transformers)** — embeddings (`all-MiniLM-L6-v2`)
- **[Typer](https://github.com/fastapi/typer)** — the CLI framework
- **[Rich](https://github.com/Textualize/rich)** — terminal rendering