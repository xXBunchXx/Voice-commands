import re
import tkinter as tk
from tkinter import ttk, messagebox

VOICE_CONTROLS_PATH = r"C:\Users\shark\Desktop\AI\Skip spotify track\voice_controls.py"


# ── File parsing ─────────────────────────────────────────────────────────────

def _extract_dict(source: str, dict_name: str) -> dict[str, str]:
    """Pull a dict literal out of the source file and return it as {key: value}."""
    pattern = rf'{dict_name}\s*=\s*\{{(.*?)\}}'
    match = re.search(pattern, source, re.DOTALL)
    if not match:
        return {}
    body = match.group(1)
    entries = {}
    for m in re.finditer(r'"([^"]+)"\s*:\s*r?"([^"]*)"', body):
        entries[m.group(1)] = m.group(2)
    return entries


def _replace_dict(source: str, dict_name: str, data: dict[str, str]) -> str:
    """Rebuild a dict literal in the source file with the given data."""
    lines = [f'    "{k}": r"{v}",' for k, v in data.items()]
    new_body = "\n".join(lines)
    new_dict = f'{dict_name} = {{\n{new_body}\n}}'
    pattern = rf'{dict_name}\s*=\s*\{{.*?\}}'
    return re.sub(pattern, new_dict, source, flags=re.DOTALL)


def load_entries() -> tuple[dict, dict]:
    with open(VOICE_CONTROLS_PATH, encoding="utf-8") as f:
        src = f.read()
    return _extract_dict(src, "APPS"), _extract_dict(src, "PROC_NAMES")


def save_entries(apps: dict, procs: dict) -> None:
    with open(VOICE_CONTROLS_PATH, encoding="utf-8") as f:
        src = f.read()
    src = _replace_dict(src, "APPS", apps)
    src = _replace_dict(src, "PROC_NAMES", procs)
    with open(VOICE_CONTROLS_PATH, "w", encoding="utf-8") as f:
        f.write(src)


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Voice Commands — App Manager")
        self.resizable(False, False)
        self.configure(bg="#1e1e2e")

        self.apps: dict[str, str] = {}
        self.procs: dict[str, str] = {}

        self._build_ui()
        self._reload()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = 12
        BG   = "#1e1e2e"
        CARD = "#2a2a3e"
        ACC  = "#7c6af7"
        FG   = "#cdd6f4"
        ENTRY_BG = "#313244"
        RED  = "#f38ba8"

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=ENTRY_BG, background=CARD,
                        foreground=FG, selectbackground=ACC,
                        arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", ENTRY_BG)])

        def label(parent, text, **kw):
            return tk.Label(parent, text=text, bg=BG, fg=FG,
                            font=("Segoe UI", 9), **kw)

        def entry(parent, width=42):
            e = tk.Entry(parent, width=width, bg=ENTRY_BG, fg=FG,
                         insertbackground=FG, relief="flat",
                         font=("Segoe UI", 10), bd=4)
            return e

        def btn(parent, text, cmd, color=ACC):
            return tk.Button(parent, text=text, command=cmd,
                             bg=color, fg="#ffffff", activebackground=color,
                             activeforeground="#ffffff", relief="flat",
                             font=("Segoe UI Semibold", 9), padx=10, pady=5,
                             cursor="hand2", bd=0)

        def section(text):
            f = tk.Frame(self, bg=BG)
            tk.Label(f, text=text, bg=BG, fg=ACC,
                     font=("Segoe UI Semibold", 10)).pack(anchor="w")
            tk.Frame(f, bg=ACC, height=1).pack(fill="x", pady=(2, 6))
            return f

        # ── Add section ───────────────────────────────────────────────────────
        add_sec = section("➕  Add New Entry")
        add_sec.pack(fill="x", padx=PAD, pady=(PAD, 0))

        add_card = tk.Frame(add_sec, bg=CARD, padx=10, pady=10)
        add_card.pack(fill="x")

        label(add_card, "App name  (e.g. notepad)").grid(row=0, column=0, sticky="w")
        label(add_card, "Exe / path  (e.g. notepad.exe or full path)").grid(row=0, column=1, sticky="w", padx=(10,0))
        label(add_card, "Process name  (e.g. notepad.exe or notepad*)").grid(row=0, column=2, sticky="w", padx=(10,0))

        self.e_name  = entry(add_card, 20)
        self.e_path  = entry(add_card, 38)
        self.e_proc  = entry(add_card, 28)

        self.e_name.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.e_path.grid(row=1, column=1, sticky="ew", padx=(10,0), pady=(2, 0))
        self.e_proc.grid(row=1, column=2, sticky="ew", padx=(10,0), pady=(2, 0))

        btn(add_card, "Add Entry", self._on_add).grid(
            row=2, column=0, columnspan=3, pady=(10, 0), sticky="e")

        # ── Delete section ────────────────────────────────────────────────────
        del_sec = section("🗑  Delete Entry")
        del_sec.pack(fill="x", padx=PAD, pady=(PAD, 0))

        del_card = tk.Frame(del_sec, bg=CARD, padx=10, pady=10)
        del_card.pack(fill="x")

        label(del_card, "Select entry to delete:").pack(anchor="w")

        self.combo_var = tk.StringVar()
        self.combo = ttk.Combobox(del_card, textvariable=self.combo_var,
                                  state="readonly", width=50,
                                  font=("Segoe UI", 10))
        self.combo.pack(fill="x", pady=(4, 8))

        # Preview frame
        self.preview = tk.Label(del_card, text="", bg=CARD, fg="#a6adc8",
                                font=("Consolas", 9), anchor="w", justify="left")
        self.preview.pack(fill="x", pady=(0, 8))
        self.combo.bind("<<ComboboxSelected>>", self._on_combo_select)

        btn(del_card, "Delete Selected", self._on_delete, color=RED).pack(anchor="e")

        # ── Status bar ────────────────────────────────────────────────────────
        self.status = tk.Label(self, text="", bg=BG, fg="#a6e3a1",
                               font=("Segoe UI", 9), anchor="w")
        self.status.pack(fill="x", padx=PAD, pady=(PAD, PAD))

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _reload(self):
        self.apps, self.procs = load_entries()
        names = sorted(self.apps.keys())
        self.combo["values"] = names
        if names:
            self.combo.set(names[0])
            self._refresh_preview(names[0])
        else:
            self.combo.set("")
            self.preview.config(text="")

    def _refresh_preview(self, name: str):
        path = self.apps.get(name, "—")
        proc = self.procs.get(name, "—")
        self.preview.config(
            text=f"  Path : {path}\n  Proc : {proc}"
        )

    def _on_combo_select(self, _event=None):
        self._refresh_preview(self.combo_var.get())

    def _set_status(self, msg: str, color="#a6e3a1"):
        self.status.config(text=msg, fg=color)
        self.after(4000, lambda: self.status.config(text=""))

    def _on_add(self):
        name = self.e_name.get().strip().lower()
        path = self.e_path.get().strip()
        proc = self.e_proc.get().strip()

        if not name or not path or not proc:
            messagebox.showwarning("Missing fields",
                                   "Please fill in all three fields.", parent=self)
            return

        if name in self.apps:
            if not messagebox.askyesno("Overwrite?",
                                       f'"{name}" already exists. Overwrite it?',
                                       parent=self):
                return

        self.apps[name]  = path
        self.procs[name] = proc
        save_entries(self.apps, self.procs)
        self._reload()

        self.e_name.delete(0, "end")
        self.e_path.delete(0, "end")
        self.e_proc.delete(0, "end")
        self._set_status(f'✓  Added "{name}" successfully.')

    def _on_delete(self):
        name = self.combo_var.get()
        if not name:
            return
        if not messagebox.askyesno("Confirm delete",
                                   f'Delete "{name}" from APPS and PROC_NAMES?',
                                   parent=self):
            return

        self.apps.pop(name, None)
        self.procs.pop(name, None)
        save_entries(self.apps, self.procs)
        self._reload()
        self._set_status(f'✓  Deleted "{name}" successfully.', color="#f38ba8")


if __name__ == "__main__":
    app = App()
    app.mainloop()
