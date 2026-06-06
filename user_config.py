"""
Manages per-user config stored in %APPDATA%\VoiceCommands\config.json.
This file is NEVER overwritten by updates — each user keeps their own entries.
"""
import json
import os
import pathlib

APPDATA_DIR = pathlib.Path(os.getenv("APPDATA", "~")) / "VoiceCommands"
CONFIG_FILE = APPDATA_DIR / "config.json"

# ── Defaults (used only on very first run if no config exists) ───────────────
DEFAULT_APPS: dict[str, str] = {
    "firefox":       r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "steam":         r"C:\Program Files (x86)\Steam\steam.exe",
    "files":         r"C:\Windows\explorer.exe",
    "spotify":       r"C:\Users\Default\AppData\Roaming\Spotify\Spotify.exe",
    "discord":       r"C:\Users\Default\AppData\Local\Discord\Discord.exe",
    "command":       r"C:\Windows\System32\cmd.exe",
    "settings":      r"ms-settings:",
}

DEFAULT_PROC_NAMES: dict[str, str] = {
    "firefox":       "firefox.exe",
    "steam":         "steam.exe",
    "files":         "explorer.exe",
    "spotify":       "spotify.exe",
    "discord":       "discord.exe",
    "command":       "cmd.exe",
    "settings":      "ms-settings:",
}

DEFAULT_MODEL_PATH = r"C:\VoiceCommands\vosk-model-small-en-us-0.15"

# ── Public API ────────────────────────────────────────────────────────────────

def load() -> dict:
    """Load config from disk, creating defaults on first run."""
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        _write_defaults()
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Ensure all expected keys exist (forward-compat for older configs)
        changed = False
        for key, default in _schema_defaults().items():
            if key not in data:
                data[key] = default
                changed = True
        if changed:
            save(data)
        return data
    except (json.JSONDecodeError, OSError):
        _write_defaults()
        return load()


def save(data: dict) -> None:
    """Write config back to disk."""
    APPDATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_apps() -> dict[str, str]:
    return load().get("APPS", DEFAULT_APPS)


def get_proc_names() -> dict[str, str]:
    return load().get("PROC_NAMES", DEFAULT_PROC_NAMES)


def get_model_path() -> str:
    return load().get("MODEL_PATH", DEFAULT_MODEL_PATH)


def set_model_path(path: str) -> None:
    data = load()
    data["MODEL_PATH"] = path
    save(data)


def add_entry(name: str, path: str, proc: str) -> None:
    data = load()
    data["APPS"][name]       = path
    data["PROC_NAMES"][name] = proc
    save(data)


def delete_entry(name: str) -> None:
    data = load()
    data["APPS"].pop(name, None)
    data["PROC_NAMES"].pop(name, None)
    save(data)


def config_path() -> pathlib.Path:
    return CONFIG_FILE


# ── Internal ──────────────────────────────────────────────────────────────────

def _schema_defaults() -> dict:
    return {
        "APPS":       DEFAULT_APPS,
        "PROC_NAMES": DEFAULT_PROC_NAMES,
        "MODEL_PATH": DEFAULT_MODEL_PATH,
    }


def _write_defaults() -> None:
    save(_schema_defaults())
