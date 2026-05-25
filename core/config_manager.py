# ragstudio/core/config_manager.py

import json
import sys
from pathlib import Path

# Absolute path to the application root directory (where ragcmdr.py lives)
APP_DIR = Path(__file__).parent.parent.resolve()

# Path to the global configuration file
CONFIG_PATH = APP_DIR / "config.json"

# Default configuration used if config.json is missing
DEFAULT_CONFIG = {
    "lmstudio": {
        "base_url": "http://127.0.0.1:1234",
        "model": "local-model",
        "system_prompt": (
            "You are a helpful assistant. "
            "Answer only based on the provided context."
        ),
        "temperature": 0.2,
        "max_tokens": 2048,
    },
    "paths": {
        "collections_dir": "./collections",
        "output_dir": "./output",
    },
    "embedding": {
        "model_name": "all-MiniLM-L6-v2",
        "chunk_size": 512,
        "chunk_overlap": 64,
    },
    "retrieval": {
        "top_k": 5,
    },
}


def loadConfig() -> dict:
    """Loads the application configuration from config.json.

    If the file does not exist, creates it with default values.

    Returns:
        A dictionary containing the full application configuration.

    Raises:
        SystemExit: If config.json exists but contains invalid JSON.
    """
    if not CONFIG_PATH.exists():
        # First run: write default config so the user can edit it
        saveConfig(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        # Unrecoverable: the user must fix the file manually
        print(f"[ERROR] config.json is invalid: {e}", file=sys.stderr)
        print(f"        Fix or delete: {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)


def saveConfig(config: dict) -> None:
    """Saves the configuration dictionary to config.json.

    Args:
        config: The configuration dictionary to persist.
    """
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def getCollectionsDir(config: dict) -> Path:
    """Resolves the absolute path of the collections directory.

    The path in config.json may be relative (to APP_DIR) or absolute.

    Args:
        config: The loaded configuration dictionary.

    Returns:
        An absolute Path to the collections directory.
    """
    raw = config["paths"]["collections_dir"]
    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    # Create the directory if it does not exist yet
    path.mkdir(parents=True, exist_ok=True)
    return path


def getOutputDir(config: dict) -> Path:
    """Resolves the absolute path of the markdown output directory.

    Args:
        config: The loaded configuration dictionary.

    Returns:
        An absolute Path to the output directory.
    """
    raw = config["paths"]["output_dir"]
    path = Path(raw)
    if not path.is_absolute():
        path = APP_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path