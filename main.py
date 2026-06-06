"""
VoiceCommands — main launcher.
"""
import os
import sys
import pathlib
import subprocess
import ssl
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import urllib.request

import user_config

VERSION = "1.0.0"

GITHUB_RAW     = "https://raw.githubusercontent.com/xXBunchXx/voice-commands/master/"
GITHUB_EXE_URL = "https://github.com/xXBunchXx/voice-commands/releases/latest/download/VoiceCommands.exe"

# ── SSL context (PyInstaller doesn't bundle certs) ────────────────────────────

def _ssl_ctx():
    """Return an SSL context that works both frozen and in dev."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # certifi not available — disable verification as a fallback
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
    return ctx


def _urlopen(url: str, timeout: int = 6):
    return urllib.request.urlopen(url, context=_ssl_ctx(), timeout=timeout)


# ── Update helpers ─────────────────────────────────────────────────────────────

def _fetch_latest_version() -> str | None:
    try:
        with _urlopen(GITHUB_RAW + "version.txt") as r:
            return r.read().decode().strip()
    except Exception as e:
        print(f"Update check error: {e}")
        return None


def _version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def _do_update(root: tk.Tk, status_var: tk.StringVar) -> None:
    exe_path = pathlib.Path(sys.executable)
    new_exe  = exe_path.with_name("VoiceCommands_new.exe")

    def _download():
        try:
            root.after(0, lambda: status_var.set("Downloading update…"))
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
            root.after(0, root.destroy)
        except Exception as e:
            root.after(0, lambda: messagebox.showerror("Update failed", str(e), parent=root))
            root.after(0, lambda: status_var.set("○ Stopped"))

    threading.Thread(target=_download, daemon=True).start()


# ── Voice engine ───────────────────────────────────────────────────────────────

_stop_event    = threading.Event()
_engine_thread: threading.Thread | None = None


def _engine_loop(stop_event: threading.Event, root: tk.Tk,
                 status_var: tk.StringVar, b_start: tk.Button, b_stop: tk.Button):
    """Runs in a background thread. Handles restart requests automatically."""
    import voice_controls
    while True:
        stop_event.clear()
        wants_restart = voice_controls.run(stop_event)
        if not wants_restart:
            break
        print("Restarting engine…")
    # Engine stopped — update UI from the main thread
    root.after(0, lambda: _ui_stopped(status_var, b_start, b_stop))


def _ui_stopped(status_var, b_start, b_stop):
    status_var.set("○ Stopped")
    b_start.config(state="normal")
    b_stop.config(state="disabled")


def _start_engine(root, status_var, b_start, b_stop, path_lbl):
    global _stop_event, _engine_thread
    if _engine_thread and _engine_thread.is_alive():
        return

    model_path = user_config.get_model_path()
    if not pathlib.Path(model_path).is_dir():
        messagebox.showerror(
            "Model not found",
            f"Could not find the Vosk model at:\n{model_path}\n\n"
            "Use the Browse… button to point to your model folder.",
            parent=root,
        )
        return

    _stop_event = threading.Event()
    _engine_thread = threading.Thread(
        target=_engine_loop,
        args=(_stop_event, root, status_var, b_start, b_stop),
        daemon=True,
    )
    _engine_thread.start()
    status_var.set("● Running")
    b_start.config(state="disabled")
    b_stop.config(state="normal")


def _stop_engine(status_var, b_start, b_stop):
    _stop_event.set()
    _ui_stopped(status_var, b_start, b_stop)


# ── App Manager ────────────────────────────────────────────────────────────────

def _open_manager(root: tk.Tk):
    """Open the App Manager as a child Toplevel of the main window."""
    from manage_apps import AppManagerWindow
    win = AppManagerWindow(root)
    win.grab_set()   # make it modal
    win.focus_set()


# ── Update check UI ────────────────────────────────────────────────────────────

def _check_updates_ui(root, status_var):
    status_var.set("Checking for updates…")
    root.update()

    latest = _fetch_latest_version()
    if latest is None:
        messagebox.showinfo(
            "Update check failed",
            "Could not reach GitHub.\n\nCheck your internet connection.",
            parent=root,
        )
        status_var.set("○ Stopped")
        return

    if _version_tuple(latest) > _version_tuple(VERSION):
        if messagebox.askyesno(
            "Update available",
            f"Version {latest} is available (you have {VERSION}).\n\nInstall now?",
            parent=root,
        ):
            _do_update(root, status_var)
        else:
            status_var.set("○ Stopped")
    else:
        messagebox.showinfo("Up to date",
                            f"You're on the latest version ({VERSION}).",
                            parent=root)
        status_var.set("○ Stopped")


# ── Main window ───────────────────────────────────────────────────────────────

def main():
    BG    = "#1e1e2e"
    CARD  = "#2a2a3e"
    ACC   = "#7c6af7"
    FG    = "#cdd6f4"
    GRN   = "#a6e3a1"
    RED   = "#f38ba8"
    MUTED = "#585b70"

    root = tk.Tk()
    root.title(f"Voice Commands  v{VERSION}")
    root.configure(bg=BG)
    root.resizable(False, False)

    def mkbtn(parent, text, cmd, color=ACC, state="normal", width=22):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="#ffffff", activebackground=color,
                         activeforeground="#ffffff", relief="flat",
                         font=("Segoe UI Semibold", 10),
                         padx=14, pady=7, cursor="hand2", bd=0,
                         state=state, width=width)

    # Header
    hdr = tk.Frame(root, bg=ACC, pady=10)
    hdr.pack(fill="x")
    tk.Label(hdr, text="🎙  Voice Commands", bg=ACC, fg="#ffffff",
             font=("Segoe UI Semibold", 14)).pack()
    tk.Label(hdr, text=f"v{VERSION}", bg=ACC, fg="#c8b8ff",
             font=("Segoe UI", 9)).pack()

    # Status
    card = tk.Frame(root, bg=CARD, padx=20, pady=14)
    card.pack(fill="x", padx=16, pady=(14, 0))
    status_var = tk.StringVar(value="○ Stopped")
    tk.Label(card, textvariable=status_var, bg=CARD, fg=GRN,
             font=("Segoe UI Semibold", 13)).pack()

    # Buttons (defined in two steps so lambdas can reference each other)
    btns = tk.Frame(root, bg=BG, pady=4)
    btns.pack(fill="x", padx=16)

    b_start = mkbtn(btns, "▶  Start Voice Commands", lambda: None)
    b_stop  = mkbtn(btns, "■  Stop Voice Commands",
                    lambda: _stop_engine(status_var, b_start, b_stop),
                    color=MUTED, state="disabled")

    # Model path row — defined before b_start.config so path_lbl exists
    model_row = tk.Frame(root, bg=CARD, padx=12, pady=8)
    model_row.pack(fill="x", padx=16, pady=(10, 0))
    tk.Label(model_row, text="Vosk model path:", bg=CARD, fg=FG,
             font=("Segoe UI", 9)).pack(anchor="w")
    path_row = tk.Frame(model_row, bg=CARD)
    path_row.pack(fill="x", pady=(3, 0))

    model_var = tk.StringVar(value=user_config.get_model_path())
    exists     = pathlib.Path(model_var.get()).is_dir()
    path_lbl   = tk.Label(path_row, textvariable=model_var, bg=CARD,
                          fg=GRN if exists else RED,
                          font=("Consolas", 8), anchor="w",
                          wraplength=310, justify="left")
    path_lbl.pack(side="left", fill="x", expand=True)

    def _pick_model():
        chosen = filedialog.askdirectory(title="Select Vosk model folder", parent=root)
        if chosen:
            user_config.set_model_path(chosen)
            model_var.set(chosen)
            path_lbl.config(fg=GRN if pathlib.Path(chosen).is_dir() else RED)

    mkbtn(path_row, "Browse…", _pick_model, color=MUTED, width=8).pack(
        side="right", padx=(6, 0))

    # Wire start button now that path_lbl exists
    b_start.config(command=lambda: _start_engine(
        root, status_var, b_start, b_stop, path_lbl))

    b_apps = mkbtn(btns, "⚙  Manage Apps", lambda: _open_manager(root))
    b_upd  = mkbtn(btns, "🔄  Check for Updates",
                   lambda: _check_updates_ui(root, status_var), color=MUTED)

    for b in (b_start, b_stop, b_apps, b_upd):
        b.pack(pady=3, fill="x")

    # Footer
    tk.Label(root, text=f"Config: {user_config.config_path()}",
             bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w").pack(
        fill="x", padx=16, pady=(8, 10))

    # Silent background update notification
    def _bg_check():
        latest = _fetch_latest_version()
        if latest and _version_tuple(latest) > _version_tuple(VERSION):
            root.after(0, lambda: status_var.set(f"⬆  Update {latest} available!"))

    threading.Thread(target=_bg_check, daemon=True).start()

    root.mainloop()


if __name__ == "__main__":
    main()
