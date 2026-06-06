"""
VoiceCommands — main launcher.
Handles: update checking, model path setup, start/stop voice engine,
and opening the App Manager.
"""
import os
import sys
import pathlib
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.request

import user_config

VERSION = "1.0.0"

GITHUB_RAW     = "https://raw.githubusercontent.com/xXBunchXx/voice-commands/master/"
GITHUB_EXE_URL = "https://github.com/xXBunchXx/voice-commands/releases/latest/download/VoiceCommands.exe"

# ── Update helpers ─────────────────────────────────────────────────────────────

def _fetch_latest_version() -> str | None:
    try:
        with urllib.request.urlopen(GITHUB_RAW + "version.txt", timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _do_update(parent: tk.Tk, status_var: tk.StringVar) -> None:
    exe_path = pathlib.Path(sys.executable)
    new_exe  = exe_path.with_name("VoiceCommands_new.exe")

    def _download():
        try:
            parent.after(0, lambda: status_var.set("Downloading update…"))
            urllib.request.urlretrieve(GITHUB_EXE_URL, new_exe)
            bat = exe_path.with_name("_vc_updater.bat")
            bat.write_text(
                f'@echo off\ntimeout /t 2 /nobreak >nul\n'
                f'move /Y "{new_exe}" "{exe_path}"\n'
                f'start "" "{exe_path}"\ndel "%~f0"\n',
                encoding="ascii",
            )
            subprocess.Popen(["cmd", "/c", str(bat)],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            parent.after(0, parent.destroy)
        except Exception as e:
            parent.after(0, lambda: messagebox.showerror(
                "Update failed", str(e), parent=parent))
            parent.after(0, lambda: status_var.set("○ Stopped"))

    threading.Thread(target=_download, daemon=True).start()


# ── Voice engine thread ────────────────────────────────────────────────────────

_engine_thread: threading.Thread | None = None


def _run_engine():
    import voice_controls  # noqa: F401 — runs its own blocking loop


def _start_engine(status_var, b_start, b_stop, model_row):
    global _engine_thread
    if _engine_thread and _engine_thread.is_alive():
        return
    # Validate model path before starting
    if not pathlib.Path(user_config.get_model_path()).is_dir():
        messagebox.showerror(
            "Model not found",
            f"Could not find the Vosk model at:\n{user_config.get_model_path()}\n\n"
            "Use the 'Set Model Path' button to point to your model folder.",
        )
        return
    _engine_thread = threading.Thread(target=_run_engine, daemon=True)
    _engine_thread.start()
    status_var.set("● Running")
    b_start.config(state="disabled")
    b_stop.config(state="normal")


def _stop_engine(status_var, b_start, b_stop):
    status_var.set("○ Stopped")
    b_start.config(state="normal")
    b_stop.config(state="disabled")


# ── Model path picker (inline, no blocking popup on launch) ───────────────────

def _pick_model(model_var: tk.StringVar):
    chosen = filedialog.askdirectory(title="Select Vosk model folder")
    if chosen:
        user_config.set_model_path(chosen)
        model_var.set(chosen)


# ── Main window ───────────────────────────────────────────────────────────────

def _build_window():
    BG   = "#1e1e2e"
    CARD = "#2a2a3e"
    ACC  = "#7c6af7"
    FG   = "#cdd6f4"
    GRN  = "#a6e3a1"
    RED  = "#f38ba8"
    MUTED = "#585b70"

    root = tk.Tk()
    root.title(f"Voice Commands  v{VERSION}")
    root.configure(bg=BG)
    root.resizable(False, False)

    def btn(parent, text, cmd, color=ACC, state="normal", width=22):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="#ffffff", activebackground=color,
                         activeforeground="#ffffff", relief="flat",
                         font=("Segoe UI Semibold", 10),
                         padx=14, pady=7, cursor="hand2", bd=0,
                         state=state, width=width)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = tk.Frame(root, bg=ACC, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🎙  Voice Commands", bg=ACC, fg="#ffffff",
             font=("Segoe UI Semibold", 14)).pack()
    tk.Label(hdr, text=f"v{VERSION}", bg=ACC, fg="#c8b8ff",
             font=("Segoe UI", 9)).pack()

    # ── Status ────────────────────────────────────────────────────────────────
    card = tk.Frame(root, bg=CARD, padx=20, pady=14)
    card.pack(fill="x", padx=16, pady=(14, 0))
    status_var = tk.StringVar(value="○ Stopped")
    tk.Label(card, textvariable=status_var, bg=CARD, fg=GRN,
             font=("Segoe UI Semibold", 13)).pack()

    # ── Engine buttons ────────────────────────────────────────────────────────
    btns = tk.Frame(root, bg=BG, pady=4)
    btns.pack(fill="x", padx=16)

    b_start = btn(btns, "▶  Start Voice Commands", lambda: None)
    b_stop  = btn(btns, "■  Stop Voice Commands",
                  lambda: _stop_engine(status_var, b_start, b_stop),
                  color=MUTED, state="disabled")

    # Wire start after both buttons exist
    b_start.config(command=lambda: _start_engine(
        status_var, b_start, b_stop, model_row))

    b_apps = btn(btns, "⚙  Manage Apps", _open_manager)
    b_upd  = btn(btns, "🔄  Check for Updates",
                 lambda: _check_updates_ui(root, status_var), color="#45475a")

    for b in (b_start, b_stop, b_apps, b_upd):
        b.pack(pady=3, fill="x")

    # ── Model path row ────────────────────────────────────────────────────────
    model_row = tk.Frame(root, bg=CARD, padx=12, pady=8)
    model_row.pack(fill="x", padx=16, pady=(10, 0))

    tk.Label(model_row, text="Vosk model path:", bg=CARD, fg=FG,
             font=("Segoe UI", 9)).pack(anchor="w")

    path_row = tk.Frame(model_row, bg=CARD)
    path_row.pack(fill="x", pady=(3, 0))

    model_var = tk.StringVar(value=user_config.get_model_path())

    # Colour the path label red if the folder doesn't exist
    path_colour = GRN if pathlib.Path(model_var.get()).is_dir() else RED
    path_lbl = tk.Label(path_row, textvariable=model_var, bg=CARD,
                        fg=path_colour, font=("Consolas", 8),
                        anchor="w", wraplength=320, justify="left")
    path_lbl.pack(side="left", fill="x", expand=True)

    def _on_pick():
        _pick_model(model_var)
        exists = pathlib.Path(model_var.get()).is_dir()
        path_lbl.config(fg=GRN if exists else RED)

    btn(path_row, "Browse…", _on_pick, color="#45475a", width=8).pack(
        side="right", padx=(6, 0))

    # ── Footer ────────────────────────────────────────────────────────────────
    tk.Label(root,
             text=f"Config: {user_config.config_path()}",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w").pack(
        fill="x", padx=16, pady=(8, 10))

    return root, status_var


def _open_manager():
    from manage_apps import AppManagerWindow
    AppManagerWindow(master=None).run()


def _check_updates_ui(parent, status_var):
    status_var.set("Checking for updates…")
    parent.update()
    latest = _fetch_latest_version()
    if latest is None:
        messagebox.showinfo("Update check",
                            "Could not reach GitHub. Check your connection.",
                            parent=parent)
        status_var.set("○ Stopped")
        return
    if _version_tuple(latest) > _version_tuple(VERSION):
        if messagebox.askyesno(
            "Update available",
            f"Version {latest} is available (you have {VERSION}).\n\nInstall now?",
            parent=parent,
        ):
            _do_update(parent, status_var)
        else:
            status_var.set("○ Stopped")
    else:
        messagebox.showinfo("Up to date",
                            f"You're on the latest version ({VERSION}).",
                            parent=parent)
        status_var.set("○ Stopped")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root, status_var = _build_window()

    # Silent background update check
    def _bg_check():
        latest = _fetch_latest_version()
        if latest and _version_tuple(latest) > _version_tuple(VERSION):
            root.after(0, lambda: status_var.set(f"⬆  Update {latest} available!"))

    threading.Thread(target=_bg_check, daemon=True).start()
    root.mainloop()


if __name__ == "__main__":
    main()
