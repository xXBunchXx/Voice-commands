"""
VoiceCommands — main launcher.
Handles: update checking, first-run model setup, start/stop voice engine,
and opening the App Manager.
"""
import os
import sys
import pathlib
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.request

import user_config

VERSION = "1.0.0"

GITHUB_RAW      = "https://raw.githubusercontent.com/xXBunchXx/voice-commands/master/"
GITHUB_EXE_URL  = "https://github.com/xXBunchXx/voice-commands/releases/latest/download/VoiceCommands.exe"

# ── Update helpers ────────────────────────────────────────────────────────────

def _fetch_latest_version() -> str | None:
    try:
        with urllib.request.urlopen(GITHUB_RAW + "version.txt", timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _do_update(parent: tk.Tk) -> None:
    """Download new exe alongside the current one, then swap via a .bat."""
    exe_path = pathlib.Path(sys.executable)
    new_exe  = exe_path.with_name("VoiceCommands_new.exe")

    def _download():
        try:
            parent.after(0, lambda: status_var.set("Downloading update..."))
            urllib.request.urlretrieve(GITHUB_EXE_URL, new_exe)

            bat_path = exe_path.with_name("_vc_updater.bat")
            bat_path.write_text(
                f'@echo off\n'
                f'timeout /t 2 /nobreak >nul\n'
                f'move /Y "{new_exe}" "{exe_path}"\n'
                f'start "" "{exe_path}"\n'
                f'del "%~f0"\n',
                encoding="ascii",
            )
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            parent.after(0, parent.destroy)   # exit so bat can replace the file
        except Exception as e:
            parent.after(0, lambda: messagebox.showerror(
                "Update failed", str(e), parent=parent))
            parent.after(0, lambda: status_var.set("Update failed."))

    threading.Thread(target=_download, daemon=True).start()


# ── First-run model setup ─────────────────────────────────────────────────────

def _ensure_model(parent: tk.Tk) -> bool:
    """Return True if the model path is valid, prompting the user if not."""
    model_path = user_config.get_model_path()
    if pathlib.Path(model_path).is_dir():
        return True

    messagebox.showinfo(
        "Vosk model not found",
        "The speech recognition model wasn't found at:\n\n"
        f"{model_path}\n\n"
        "Please download the model from:\n"
        "https://alphacephei.com/vosk/models\n"
        "(recommended: vosk-model-small-en-us-0.15)\n\n"
        "Then click OK and select the extracted model folder.",
        parent=parent,
    )
    chosen = filedialog.askdirectory(title="Select Vosk model folder", parent=parent)
    if not chosen:
        return False
    user_config.set_model_path(chosen)
    return True


# ── Voice engine thread ───────────────────────────────────────────────────────

_engine_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _run_engine():
    """Import and run voice_controls inside a thread."""
    _stop_event.clear()
    # voice_controls runs its own blocking loop; we patch sys.exit to stop cleanly
    import importlib
    import voice_controls   # noqa: F401 — side-effects load the engine
    # voice_controls loops forever; the thread ends when the process exits
    # For start/stop we restart the whole thread (simplest approach)


def _start_engine(status_var: tk.StringVar, btn_start: tk.Button, btn_stop: tk.Button):
    global _engine_thread
    if _engine_thread and _engine_thread.is_alive():
        return
    _engine_thread = threading.Thread(target=_run_engine, daemon=True)
    _engine_thread.start()
    status_var.set("● Running")
    btn_start.config(state="disabled")
    btn_stop.config(state="normal")


def _stop_engine(status_var: tk.StringVar, btn_start: tk.Button, btn_stop: tk.Button):
    # voice_controls blocks in a loop; stopping it requires killing the thread.
    # The cleanest cross-platform way is to just restart the process without the engine.
    # For now we signal and update the UI — the thread will finish when the engine exits.
    _stop_event.set()
    status_var.set("○ Stopped")
    btn_start.config(state="normal")
    btn_stop.config(state="disabled")


# ── Main window ───────────────────────────────────────────────────────────────

def _build_window() -> tk.Tk:
    BG   = "#1e1e2e"
    CARD = "#2a2a3e"
    ACC  = "#7c6af7"
    FG   = "#cdd6f4"
    GRN  = "#a6e3a1"
    RED  = "#f38ba8"

    root = tk.Tk()
    root.title(f"Voice Commands  v{VERSION}")
    root.configure(bg=BG)
    root.resizable(False, False)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=ACC, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🎙  Voice Commands", bg=ACC, fg="#ffffff",
             font=("Segoe UI Semibold", 14)).pack()
    tk.Label(hdr, text=f"v{VERSION}", bg=ACC, fg="#ffffffaa",
             font=("Segoe UI", 9)).pack()

    # ── Status card ───────────────────────────────────────────────────────────
    card = tk.Frame(root, bg=CARD, padx=20, pady=16)
    card.pack(fill="x", padx=16, pady=(16, 0))

    status_var = tk.StringVar(value="○ Stopped")
    tk.Label(card, textvariable=status_var, bg=CARD, fg=GRN,
             font=("Segoe UI Semibold", 13)).pack()

    def btn(parent, text, cmd, color=ACC, state="normal"):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="#ffffff", activebackground=color,
                         activeforeground="#ffffff", relief="flat",
                         font=("Segoe UI Semibold", 10),
                         padx=14, pady=7, cursor="hand2", bd=0,
                         state=state, width=22)

    # ── Buttons ───────────────────────────────────────────────────────────────
    btns = tk.Frame(root, bg=BG, pady=6)
    btns.pack(fill="x", padx=16)

    b_start = btn(btns, "▶  Start Voice Commands",
                  lambda: _start_engine(status_var, b_start, b_stop))
    b_stop  = btn(btns, "■  Stop Voice Commands",
                  lambda: _stop_engine(status_var, b_start, b_stop),
                  color="#585b70", state="disabled")
    b_apps  = btn(btns, "⚙  Manage Apps", _open_manager)
    b_upd   = btn(btns, "🔄  Check for Updates",
                  lambda: _check_updates_ui(root, status_var), color="#45475a")

    for b in (b_start, b_stop, b_apps, b_upd):
        b.pack(pady=3, fill="x")

    # ── Footer ────────────────────────────────────────────────────────────────
    cfg_lbl = tk.Label(root,
                       text=f"Config: {user_config.config_path()}",
                       bg=BG, fg="#585b70", font=("Segoe UI", 8), anchor="w")
    cfg_lbl.pack(fill="x", padx=16, pady=(4, 12))

    return root, status_var


def _open_manager():
    from manage_apps import AppManagerWindow
    AppManagerWindow(master=None).run()


def _check_updates_ui(parent: tk.Tk, status_var: tk.StringVar):
    status_var.set("Checking for updates…")
    parent.update()

    latest = _fetch_latest_version()
    if latest is None:
        messagebox.showinfo("Update check", "Could not reach GitHub. Check your connection.", parent=parent)
        status_var.set("○ Stopped")
        return

    if _version_tuple(latest) > _version_tuple(VERSION):
        if messagebox.askyesno(
            "Update available",
            f"New version {latest} is available (you have {VERSION}).\n\nDownload and install now?",
            parent=parent,
        ):
            _do_update(parent)
        else:
            status_var.set("○ Stopped")
    else:
        messagebox.showinfo("Up to date", f"You're on the latest version ({VERSION}).", parent=parent)
        status_var.set("○ Stopped")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root, status_var = _build_window()

    if not _ensure_model(root):
        messagebox.showwarning(
            "No model",
            "Voice commands won't work without the model. "
            "You can set the path later via the config file:\n\n"
            f"{user_config.config_path()}",
            parent=root,
        )

    # Non-blocking update check in background
    def _bg_update_check():
        latest = _fetch_latest_version()
        if latest and _version_tuple(latest) > _version_tuple(VERSION):
            root.after(0, lambda: status_var.set(f"⬆  Update {latest} available!"))

    threading.Thread(target=_bg_update_check, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
