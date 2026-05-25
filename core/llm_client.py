# ragstudio/core/llm_client.py

"""LM Studio HTTP client (OpenAI-compatible API).

Stateless: a new httpx client is created per request and closed immediately
after the response is received, keeping idle memory at zero.

LM Studio exposes a local OpenAI-compatible server at:
    POST /v1/chat/completions
"""

import httpx
from typing import Generator


# Default timeout for a single chat completion request (seconds).
# Increase this in config if your model is slow to respond.
REQUEST_TIMEOUT = 120


def checkConnection(base_url: str) -> bool:
    """Verifies that the LM Studio server is reachable.

    Sends a lightweight GET request to /v1/models. Does not raise —
    returns False on any network error so callers can show a friendly message.

    Args:
        base_url: The LM Studio base URL (e.g. 'http://127.0.0.1:1234').

    Returns:
        True if the server responded, False otherwise.
    """
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(f"{base_url}/v1/models")
            return response.status_code == 200
    except Exception:
        return False


def chatCompletion(
    base_url: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.2,
    max_tokens: int = 2048,
) -> str:
    """Sends a chat completion request to LM Studio and returns the reply.

    Args:
        base_url: LM Studio server URL (e.g. 'http://127.0.0.1:1234').
        model: Model identifier as configured in LM Studio.
        messages: List of message dicts with 'role' and 'content' keys.
            Example: [{'role': 'user', 'content': 'Hello'}]
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
        max_tokens: Maximum number of tokens in the response.

    Returns:
        The assistant's reply as a plain string.

    Raises:
        RuntimeError: If the server is unreachable or returns an error.
    """
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            response = client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    except httpx.ConnectError:
        raise RuntimeError(
            f"Cannot connect to LM Studio at {base_url}.\n"
            "Make sure LM Studio is running and a model is loaded."
        )
    except httpx.TimeoutException:
        raise RuntimeError(
            f"LM Studio request timed out after {REQUEST_TIMEOUT}s.\n"
            "The model may be overloaded. Try again or increase REQUEST_TIMEOUT."
        )
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"LM Studio returned HTTP {e.response.status_code}: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Unexpected response format from LM Studio: {e}")


def buildRagMessages(
    system_prompt: str,
    context_chunks: list[dict],
    question: str,
    history: list[dict],
) -> list[dict]:
    """Builds the messages list for a RAG-augmented chat completion.

    Injects the retrieved document chunks as context into the system prompt,
    then appends the conversation history and the current question.

    Args:
        system_prompt: The base system prompt from config.json.
        context_chunks: List of chunk dicts returned by vectorstore.queryStore().
            Each dict has 'text' and 'source_file' keys.
        question: The user's current question.
        history: Previous (user, assistant) message dicts for multi-turn context.
            Pass an empty list for single-turn mode.

    Returns:
        A list of message dicts ready to pass to chatCompletion().
    """
    # Build a context block from retrieved chunks
    context_parts: list[str] = []
    for i, chunk in enumerate(context_chunks, start=1):
        source = chunk.get("source_file", "unknown")
        text = chunk.get("text", "").strip()
        context_parts.append(f"[{i}] (source: {source})\n{text}")

    context_block = "\n\n".join(context_parts)

    # Augment the system prompt with the retrieved context
    augmented_system = (
        f"{system_prompt}\n\n"
        f"---\n"
        f"Use the following document excerpts to answer the user's question.\n"
        f"If the answer is not in the excerpts, say so clearly.\n\n"
        f"{context_block}\n"
        f"---"
    )

    messages: list[dict] = [{"role": "system", "content": augmented_system}]

    # Append conversation history (last N turns kept by the caller)
    messages.extend(history)

    # Append the current question
    messages.append({"role": "user", "content": question})

    return messages