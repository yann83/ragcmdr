# ragstudio/core/state_manager.py

import json
from datetime import datetime
from pathlib import Path

# session.json sits next to ragcmdr.py so it is easy to locate and delete
APP_DIR = Path(__file__).parent.parent.resolve()
SESSION_PATH = APP_DIR / "session.json"


def getActiveCollection() -> str | None:
    """Returns the name of the currently open collection, or None.

    Reads session.json. Returns None if the file is missing or corrupted.

    Returns:
        The active collection name as a string, or None if no session exists.
    """
    if not SESSION_PATH.exists():
        return None
    try:
        with SESSION_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("active_collection")
    except (json.JSONDecodeError, KeyError):
        # Corrupt session file: treat as no active session
        clearSession()
        return None


def setActiveCollection(name: str) -> None:
    """Persists the given collection name as the active session.

    Creates or overwrites session.json with the collection name and a
    timestamp marking when it was opened.

    Args:
        name: The name of the collection to mark as active.
    """
    data = {
        "active_collection": name,
        "opened_at": datetime.now().isoformat(timespec="seconds"),
    }
    with SESSION_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def clearSession() -> None:
    """Removes session.json, marking no collection as active.

    Safe to call even if the file does not exist.
    """
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()