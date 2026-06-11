"""
App Manager -- Linux implementation.
Scans .desktop files instead of the Windows registry.
"""
import os
import pathlib
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import user_config

BG          = "#0a1020"
CARD        = "#0f1a2e"
ACC         = "#1a56db"
ACCENT_TEXT = "#4a8fe8"
FG          = "#ffffff"
ENTRY_BG    = "#162033"
MUTED       = "#3d5470"
GRN         = "#4ade80"
RED         = "#f87171"


# ── Built-in Linux apps ───────────────────────────────────────────────────────

_BUILTIN_APPS = [
    ("Files (Nautilus)",    "nautilus",              "nautilus"),
    ("Terminal",            "gnome-terminal",        "gnome-terminal-server"),
    ("Text Editor (gedit)", "gedit",                 "gedit"),
    ("Calculator",          "gnome-calculator",      "gnome-calculator"),
    ("System Monitor",      "gnome-system-monitor",  "gnome-system-monitor"),
    ("Settings",            "gnome-control-center",  "gnome-control-center"),
    ("Firefox",             "firefox",               "firefox"),
    ("Chromium",            "chromium-browser",      "chromium"),
    ("VLC",                 "vlc",                   "vlc"),
    ("Rhythmbox",           "rhythmbox",             "rhythmbox"),
    ("Thunderbird",         "thunderbird",           "thunderbird"),
    ("Inkscape",            "inkscape",              "inkscape"),
    ("GIMP",                "gimp",                  "gimp-2.10"),
    ("LibreOffice Writer",  "libreoffice --writer",  "soffice.bin"),
    ("Spotify",             "spotify",               "spotify"),
    ("Discord",             "discord",               "discord"),
    ("VS Code",             "code",                  "code"),
]


def _builtin_apps() -> list[dict]:
    results = []
    for display, path, proc in _BUILTIN_APPS:
        voice_name = _to_voice_name(display)
        results.append({"display": f"{display}  (built-in)",
                        "name": voice_name, "path": path, "proc": proc})
    return results


def _to_voice_name(display: str) -> str:
    name = re.sub(r"\d[\d.]*", "", display)
    name = re.sub(r"[^a-z ]", "", name.lower()).strip()
    words = [w for w in name.split() if len(w) > 1]
    return words[-1] if words else name


# ── .desktop file scanner ─────────────────────────────────────────────────────

_DESKTOP_DIRS = [
    pathlib.Path("/usr/share/applications"),
    pathlib.Path("/usr/local/share/applications"),
    pathlib.Path.home() / ".local/share/applications",
    pathlib.Path("/var/lib/flatpak/exports/share/applications"),
    pathlib.Path.home() / ".local/share/flatpak/exports/share/applications",
    pathlib.Path("/var/lib/snapd/desktop/applications"),
]

_SKIP_CATEGORIES = {"Settings", "System", "Core"}
_SKIP_NAMES      = ("uninstall", "setup", "readme", "help", "release notes",
                    "website", "homepage", "documentation", "license", "man ")


def _parse_desktop(path: pathlib.Path) -> dict | None:
    """Parse a .desktop file and return a candidate dict or None."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    section = ""
    props: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line.strip("[]")
        if section != "Desktop Entry":
            continue
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            props.setdefault(k.strip(), v.strip())

    # Must be an Application visible in menus
    if props.get("Type") != "Application":
        return None
    if props.get("NoDisplay", "false").lower() == "true":
        return None
    if props.get("Hidden", "false").lower() == "true":
        return None

    name = props.get("Name", "").strip()
    if not name:
        return None
    low = name.lower()
    if any(s in low for s in _SKIP_NAMES):
        return None

    # Extract the executable from the Exec line, stripping % placeholders
    exec_raw = props.get("Exec", "").strip()
    exec_clean = re.sub(r"%[a-zA-Z]", "", exec_raw).strip()
    # Strip env-var prefixes (env VAR=val cmd)
    exec_clean = re.sub(r"^env\s+\S+=\S+\s+", "", exec_clean)
    # First token is the command
    parts = exec_clean.split()
    if not parts:
        return None
    exe = parts[0]
    # For absolute paths, just take the basename
    proc = pathlib.Path(exe).name if exe.startswith("/") else exe

    return {
        "display": name,
        "name":    _to_voice_name(name),
        "path":    exe,          # command to launch (gtk-launch handles .desktop)
        "proc":    proc,
        "desktop": str(path),   # for gtk-launch
    }


def _scan_desktop_files() -> list[dict]:
    results = []
    seen = set()
    for d in _DESKTOP_DIRS:
        if not d.is_dir():
            continue
        try:
            for f in d.glob("*.desktop"):
                key = f.stem.lower()
                if key in seen:
                    continue
                seen.add(key)
                r = _parse_desktop(f)
                if r:
                    results.append(r)
        except Exception:
            pass
    # Append built-ins for common apps not always in .desktop dirs
    results += _builtin_apps()
    results.sort(key=lambda x: x["display"].lower())
    return results


def _scan_folder(folder: str) -> list[dict]:
    """Scan a directory for executables (e.g. a custom install folder)."""
    results = []
    seen = set()
    base = pathlib.Path(folder)
    if not base.is_dir():
        return results
    for exe in (list(base.glob("*")) +
                list(base.glob("*/*")) +
                list(base.glob("*/*/*"))):
        if not exe.is_file():
            continue
        key = str(exe).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            # Check executable bit
            if not os.access(str(exe), os.X_OK):
                continue
            if exe.stat().st_size < 10_000:
                continue
        except Exception:
            continue
        results.append({
            "display": f"{exe.stem}  ({base.name})",
            "name":    _to_voice_name(exe.stem),
            "path":    str(exe),
            "proc":    exe.name,
        })
    results.sort(key=lambda x: x["display"].lower())
    return results


# ── App Manager Widget ────────────────────────────────────────────────────────

class AppManagerWidget(tk.Frame):

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._apps  = {}
        self._procs = {}
        self._scan_results   = []
        self._scan_visible   = []
        self._scan_vars      = []
        self._scan_name_vars = []
        self._all_candidates = None
        self._build_ui()
        self._reload()
        self._load_candidates_bg()

    def _btn(self, parent, text, cmd, color=ACC, **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="#fff", activebackground=color,
                         activeforeground="#fff", relief="flat",
                         font=("Sans", 9),
                         padx=10, pady=5, cursor="hand2", bd=0, **kw)

    def _inp(self, parent, width=42):
        return tk.Entry(parent, width=width, bg=ENTRY_BG, fg=FG,
                        insertbackground=FG, relief="flat",
                        font=("Sans", 10), bd=4)

    def _lbl(self, parent, text, **kw):
        kw.setdefault("fg", FG)
        kw.setdefault("font", ("Sans", 9))
        return tk.Label(parent, text=text, bg=parent["bg"], **kw)

    def _make_listen_widget(self, parent, target_entry):
        fr = tk.Frame(parent, bg=parent["bg"])
        dur = tk.DoubleVar(value=2.0)
        spin = tk.Spinbox(fr, from_=0.2, to=10.0, increment=0.1, textvariable=dur,
                          width=4, bg=ENTRY_BG, fg=FG, buttonbackground=CARD,
                          insertbackground=FG, relief="flat",
                          font=("Sans", 9), justify="center")
        spin.pack(side="left")
        tk.Label(fr, text="s", bg=parent["bg"], fg=MUTED,
                 font=("Sans", 8)).pack(side="left", padx=(2, 6))
        btn = self._btn(fr, "Listen", lambda: None, color=MUTED)
        btn.config(command=lambda: self._do_listen(target_entry, dur, btn))
        btn.pack(side="left")
        return fr

    def _do_listen(self, entry, dur_var, btn):
        try:
            secs = float(dur_var.get())
        except Exception:
            secs = 2.0
        btn.config(state="disabled", text="Preparing...")
        self._flash("Preparing microphone...", "#fbbf24")
        self.update_idletasks()

        def _on_start():
            def _u():
                btn.config(text="Listening...")
                self._flash(f"Say the name now...  ({secs:.1f}s)", "#fbbf24")
            self.after(0, _u)

        def _work():
            text, err = "", ""
            try:
                import voice_controls
                text = voice_controls.listen_once(secs, on_start=_on_start)
            except Exception as e:
                err = str(e)

            def _done():
                btn.config(state="normal", text="Listen")
                if err:
                    self._flash(f"Listen failed: {err}", RED)
                elif text:
                    entry.delete(0, "end")
                    entry.insert(0, text)
                    self._flash(f'Heard "{text}" -- set as spoken name.')
                else:
                    self._flash("Didn't catch anything -- try again.", RED)
            self.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()

    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG)
        tk.Label(f, text=title, bg=BG, fg=FG,
                 font=("Sans Bold", 10)).pack(anchor="w")
        tk.Frame(f, bg=ACC, height=1).pack(fill="x", pady=(2, 6))
        return f

    def _build_ui(self):
        self._main_page = tk.Frame(self, bg=BG)
        self._scan_page = tk.Frame(self, bg=BG)
        self._build_main_page(self._main_page)
        self._build_scan_page(self._scan_page)
        self._main_page.pack(fill="both", expand=True)

    def _build_main_page(self, outer):
        PAD = 12
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vbar   = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        page = tk.Frame(canvas, bg=BG)
        _win = canvas.create_window((0, 0), window=page, anchor="nw")
        page.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(_win, width=e.width))

        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        self._main_canvas   = canvas
        self._wheel_handler = _on_wheel
        canvas.bind("<MouseWheel>", _on_wheel)
        page.bind("<MouseWheel>", _on_wheel)
        self._main_inner = page

        tk.Label(page, text=f"Config: {user_config.config_path()}",
                 bg=BG, fg=MUTED, font=("Sans", 8), anchor="w").pack(
            fill="x", padx=PAD, pady=(PAD, 0))

        find_sec = self._section(page, "Find an App")
        find_sec.pack(fill="x", padx=PAD, pady=(8, 0))
        find_card = tk.Frame(find_sec, bg=CARD, padx=10, pady=10)
        find_card.pack(fill="x")
        self._lbl(find_card,
                  'Type part of an app\'s name (e.g. "code") and click the right one.',
                  fg=MUTED, font=("Sans", 8), wraplength=620, justify="left").pack(anchor="w")
        self._search_var = tk.StringVar()
        se = tk.Entry(find_card, textvariable=self._search_var, bg=ENTRY_BG, fg=FG,
                      insertbackground=FG, relief="flat", font=("Sans", 11), bd=5)
        se.pack(fill="x", pady=(6, 4))
        self._search_var.trace_add("write", lambda *a: self._refresh_search_results())
        self._search_results = tk.Frame(find_card, bg=CARD)
        self._results_packed = False

        quick = tk.Frame(page, bg=BG)
        quick.pack(fill="x", padx=PAD, pady=(8, 0))
        self._btn(quick, "Browse Executable", self._browse_exe,     MUTED).pack(side="left")
        self._btn(quick, "Add Website",        self._add_website,    MUTED).pack(side="left", padx=(8, 0))
        self._btn(quick, "Add Folder",         self._add_folder,     MUTED).pack(side="left", padx=(8, 0))

        add_sec = self._section(page, "Add / Edit Entry")
        add_sec.pack(fill="x", padx=PAD, pady=(8, 0))
        add_card = tk.Frame(add_sec, bg=CARD, padx=10, pady=10)
        add_card.pack(fill="x")

        self._lbl(add_card, "Display name").grid(row=0, column=0, sticky="w")
        self._lbl(add_card, "Command / path").grid(row=0, column=1, sticky="w", padx=(10,0))
        self._lbl(add_card, "Process name  (auto from path)").grid(row=0, column=2, sticky="w", padx=(10,0))

        self.e_name = self._inp(add_card, 18)
        self.e_path = self._inp(add_card, 38)
        self.e_proc = self._inp(add_card, 26)
        self.e_name.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.e_path.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(2, 0))
        self.e_proc.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(2, 0))
        self.e_path.bind("<KeyRelease>", lambda e: self._sync_proc_from_path())

        self._lbl(add_card,
                  'Spoken name  (what you SAY, blank = display name).  '
                  'Comma-separate aliases: "code, editor, vs code".',
                  fg=MUTED, font=("Sans", 8)).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

        self.e_spoken = self._inp(add_card, 30)
        self.e_spoken.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self._make_listen_widget(add_card, self.e_spoken).grid(
            row=3, column=2, sticky="w", padx=(10, 0), pady=(2, 0))

        self._btn(add_card, "Add Entry", self._on_add).grid(
            row=4, column=0, columnspan=3, pady=(10, 0), sticky="e")

        del_sec = self._section(page, "Edit / Rename / Delete Entry")
        del_sec.pack(fill="x", padx=PAD, pady=(PAD, 0))
        del_card = tk.Frame(del_sec, bg=CARD, padx=10, pady=10)
        del_card.pack(fill="x")

        self._lbl(del_card, "Select entry:").pack(anchor="w")
        style = ttk.Style(del_card); style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=ENTRY_BG, background=CARD,
                        foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", ENTRY_BG)])

        self.combo_var = tk.StringVar()
        self.combo = ttk.Combobox(del_card, textvariable=self.combo_var,
                                  state="readonly", width=52, font=("Sans", 10))
        self.combo.pack(fill="x", pady=(4, 6))
        self.combo.bind("<<ComboboxSelected>>", self._on_select)

        edit_grid = tk.Frame(del_card, bg=CARD)
        edit_grid.pack(fill="x", pady=(0, 6))

        self._lbl(edit_grid, "Path / URL").grid(row=0, column=0, sticky="w")
        self._lbl(edit_grid, "Process name").grid(row=0, column=1, sticky="w", padx=(10, 0))
        self._lbl(edit_grid, "Spoken name").grid(row=0, column=2, sticky="w", padx=(10, 0))

        self.e_edit_path   = self._inp(edit_grid, 36)
        self.e_edit_proc   = self._inp(edit_grid, 22)
        self.e_edit_spoken = self._inp(edit_grid, 20)
        self.e_edit_path.grid  (row=1, column=0, sticky="ew", pady=(2, 0))
        self.e_edit_proc.grid  (row=1, column=1, sticky="ew", padx=(10, 0), pady=(2, 0))
        self.e_edit_spoken.grid(row=1, column=2, sticky="ew", padx=(10, 0), pady=(2, 0))
        self._make_listen_widget(edit_grid, self.e_edit_spoken).grid(
            row=2, column=2, sticky="w", padx=(10, 0), pady=(4, 0))

        browse_row = tk.Frame(del_card, bg=CARD)
        browse_row.pack(fill="x", pady=(4, 0))
        self._btn(browse_row, "Browse",       self._browse_edit_exe,    MUTED).pack(side="left")
        self._btn(browse_row, "Detect",       self._detect_proc_edit,   MUTED).pack(side="left", padx=(8, 0))
        self._btn(browse_row, "Save Changes", self._on_save_edit, GRN).pack(side="left", padx=(8, 0))

        rename_row = tk.Frame(del_card, bg=CARD)
        rename_row.pack(fill="x", pady=(10, 4))
        self._lbl(rename_row, "Rename display name to:").pack(side="left")
        self.e_rename = self._inp(rename_row, width=20)
        self.e_rename.pack(side="left", padx=(8, 8))
        self._btn(rename_row, "Rename", self._on_rename).pack(side="left")

        self._btn(del_card, "Delete Selected", self._on_delete, RED).pack(anchor="e")

        self._status_lbl = tk.Label(page, text="", bg=BG, fg=GRN,
                                    font=("Sans", 9), anchor="w")
        self._status_lbl.pack(fill="x", padx=PAD, pady=(PAD, PAD))

        self._bind_wheel(page)

    def _bind_wheel(self, widget):
        try:
            widget.bind("<MouseWheel>", self._wheel_handler)
            # Linux scroll events
            widget.bind("<Button-4>", lambda e: self._main_canvas.yview_scroll(-1, "units"))
            widget.bind("<Button-5>", lambda e: self._main_canvas.yview_scroll(1, "units"))
        except Exception:
            pass
        for child in widget.winfo_children():
            self._bind_wheel(child)

    def _build_scan_page(self, page):
        hdr = tk.Frame(page, bg=BG)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        self._btn(hdr, "Back", self._go_main, MUTED).pack(side="left")
        tk.Label(hdr, text="Scan Installed Apps", bg=BG, fg=FG,
                 font=("Sans Bold", 12)).pack(side="left", padx=(12, 0))

        self._scan_status = tk.Label(page, text="", bg=BG, fg=MUTED,
                                     font=("Sans", 9))
        self._scan_status.pack()

        sr = tk.Frame(page, bg=BG)
        sr.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(sr, text="Filter:", bg=BG, fg=FG, font=("Sans", 9)).pack(side="left")
        self._scan_search = tk.StringVar()
        self._scan_search.trace_add("write", lambda *_: self._filter_scan())
        tk.Entry(sr, textvariable=self._scan_search, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat", font=("Sans", 10), bd=4).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        fr = tk.Frame(page, bg=BG)
        fr.pack(fill="x", padx=12, pady=(4, 0))
        tk.Label(fr, text="Extra search folders:", bg=BG, fg=MUTED,
                 font=("Sans Bold", 8)).pack(side="left")
        self._folders_lbl = tk.Label(fr, text="", bg=BG, fg=FG,
                                     font=("Sans", 8), anchor="w")
        self._folders_lbl.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self._btn(fr, "Add Folder",  self._add_scan_folder,    MUTED).pack(side="left", padx=(8, 0))
        self._btn(fr, "Clear",       self._clear_scan_folders, MUTED).pack(side="left", padx=(4, 0))
        self._refresh_folders_lbl()

        lf = tk.Frame(page, bg=CARD)
        lf.pack(fill="both", expand=True, padx=12, pady=8)

        self._scan_canvas = tk.Canvas(lf, bg=CARD, highlightthickness=0)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self._scan_canvas.yview)
        self._scan_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._scan_canvas.pack(side="left", fill="both", expand=True)

        self._scan_inner = tk.Frame(self._scan_canvas, bg=CARD)
        cwin = self._scan_canvas.create_window((0, 0), window=self._scan_inner, anchor="nw")
        self._scan_inner.bind("<Configure>",
            lambda e: self._scan_canvas.configure(scrollregion=self._scan_canvas.bbox("all")))
        self._scan_canvas.bind("<Configure>",
            lambda e: self._scan_canvas.itemconfig(cwin, width=e.width))
        for w in (self._scan_canvas, self._scan_inner):
            w.bind("<Button-4>",
                   lambda e: self._scan_canvas.yview_scroll(-1, "units"))
            w.bind("<Button-5>",
                   lambda e: self._scan_canvas.yview_scroll(1, "units"))

        bot = tk.Frame(page, bg=BG)
        bot.pack(fill="x", padx=12, pady=(0, 10))

        self._btn(bot, "Select All",   self._sel_all_scan, MUTED).pack(side="left")
        self._btn(bot, "Deselect All",
                  lambda: [v.set(False) for v in self._scan_vars],
                  MUTED).pack(side="left", padx=(6, 0))

        self._scan_count_lbl = tk.Label(bot, text="", bg=BG, fg=GRN, font=("Sans", 9))
        self._scan_count_lbl.pack(side="right", padx=(0, 10))

        self._btn(bot, "Add Selected", self._add_scan_selected).pack(side="right")

    def _go_scan(self):
        self._scan_search.set("")
        self._scan_status.config(text="Scanning .desktop files...")
        for w in self._scan_inner.winfo_children():
            w.destroy()
        self._main_page.pack_forget()
        self._scan_page.pack(fill="both", expand=True)
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _go_main(self):
        self._scan_page.pack_forget()
        self._main_page.pack(fill="both", expand=True)
        self._reload()

    def _show_overlay(self, title, icon, fields, on_submit):
        overlay = tk.Frame(self, bg="#0d0d1a")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        card = tk.Frame(overlay, bg=CARD, padx=24, pady=20)
        card.place(relx=0.5, rely=0.4, anchor="center")
        tk.Label(card, text=f"{icon}  {title}", bg=CARD, fg=FG,
                 font=("Sans Bold", 11)).pack(pady=(0, 12))
        entries = []
        for label, hint in fields:
            f = tk.Frame(card, bg=CARD)
            f.pack(fill="x", pady=(0, 8))
            tk.Label(f, text=label, bg=CARD, fg=FG, font=("Sans", 9)).pack(anchor="w")
            e = tk.Entry(f, width=44, bg=ENTRY_BG, fg=FG,
                         insertbackground=FG, relief="flat",
                         font=("Sans", 10), bd=4)
            e.pack(fill="x")
            if hint:
                tk.Label(f, text=hint, bg=CARD, fg=MUTED,
                         font=("Sans", 8)).pack(anchor="w")
            entries.append(e)
        btn_row = tk.Frame(card, bg=CARD)
        btn_row.pack(fill="x", pady=(8, 0))

        def _ok(_e=None):
            vals = [e.get() for e in entries]
            overlay.destroy()
            on_submit(vals)

        def _cancel(_e=None):
            overlay.destroy()

        for e in entries:
            e.bind("<Return>", _ok)
        overlay.bind("<Escape>", _cancel)
        self._btn(btn_row, "OK",     _ok,     ACC ).pack(side="right")
        self._btn(btn_row, "Cancel", _cancel, MUTED).pack(side="right", padx=(0, 8))
        entries[0].focus_set()

    @staticmethod
    def _auto_proc_from_path(path: str) -> str:
        p = path.strip().strip('"')
        if not p or "://" in p:
            return ""
        base = pathlib.Path(p).name
        return base if base else ""

    def _sync_proc_from_path(self):
        proc = self._auto_proc_from_path(self.e_path.get())
        if proc:
            self.e_proc.delete(0, "end")
            self.e_proc.insert(0, proc)

    def _browse_exe(self):
        path = filedialog.askopenfilename(
            title="Select executable",
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        p = pathlib.Path(path)
        self.e_name.delete(0, "end"); self.e_name.insert(0, _to_voice_name(p.stem))
        self.e_path.delete(0, "end"); self.e_path.insert(0, str(p))
        self.e_proc.delete(0, "end"); self.e_proc.insert(0, p.name)
        self.e_spoken.delete(0, "end")
        self._flash(f"Auto-filled from {p.name}")

    def _add_website(self):
        def on_submit(vals):
            name, url = vals
            name = name.strip().lower(); url = url.strip()
            if not name or not url:
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            user_config.add_entry(name, url, "")
            self._reload()
            self._flash(f'Added website "{name}" -> {url}')
        self._show_overlay("Add Website", "", [
            ("Voice command name", "e.g.  youtube"),
            ("URL", "e.g.  https://www.youtube.com"),
        ], on_submit)

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select folder to open",
                                         parent=self.winfo_toplevel())
        if not folder:
            return
        suggested = pathlib.Path(folder).name.lower().replace("_", " ").replace("-", " ")

        def on_submit(vals):
            name = vals[0].strip().lower()
            if not name:
                return
            user_config.add_entry(name, folder, "nautilus")
            self._reload()
            self._flash(f'Added folder "{name}" -> {folder}')
        self._show_overlay("Add Folder", "", [
            ("Voice command name  (pre-filled from folder name)", ""),
        ], on_submit)
        self.after(50, lambda: self._prefill_overlay(suggested))

    def _prefill_overlay(self, text: str):
        for child in self.winfo_children():
            if isinstance(child, tk.Frame) and str(child.place_info()):
                for card in child.winfo_children():
                    if isinstance(card, tk.Frame):
                        for f in card.winfo_children():
                            if isinstance(f, tk.Frame):
                                for w in f.winfo_children():
                                    if isinstance(w, tk.Entry):
                                        w.delete(0, "end")
                                        w.insert(0, text)
                                        return

    def _load_candidates_bg(self):
        def _work():
            cands = []
            for fn in (_scan_desktop_files,):
                try:
                    cands += fn()
                except Exception:
                    pass
            for folder in user_config.get_scan_folders():
                try:
                    cands += _scan_folder(folder)
                except Exception:
                    pass
            by_name = {}
            for r in cands:
                key = r["display"].strip().lower()
                if not key:
                    continue
                cur = by_name.get(key)
                if cur is None or (not cur.get("proc") and r.get("proc")):
                    by_name[key] = r
            deduped = sorted(by_name.values(), key=lambda x: x["display"].lower())
            self._all_candidates = deduped
            self.after(0, self._refresh_search_results)
        threading.Thread(target=_work, daemon=True).start()

    @staticmethod
    def _candidate_matches(query: str, r: dict) -> bool:
        q = query.lower().strip()
        if not q:
            return False
        disp    = r["display"].lower()
        hay     = disp + " " + r["proc"].lower()
        acronym = "".join(w[0] for w in re.split(r"[\s\-]+", disp) if w)
        if acronym and acronym.startswith(q.replace(" ", "")):
            return True
        for tok in q.split():
            if tok in hay or (acronym and acronym.startswith(tok)):
                continue
            return False
        return True

    def _show_results(self, show: bool):
        if show and not self._results_packed:
            self._search_results.pack(fill="x", pady=(4, 0))
            self._results_packed = True
        elif not show and self._results_packed:
            self._search_results.pack_forget()
            self._results_packed = False

    def _refresh_search_results(self):
        for w in self._search_results.winfo_children():
            w.destroy()
        q = self._search_var.get().strip()
        if not q:
            self._show_results(False)
            return
        self._show_results(True)
        if self._all_candidates is None:
            self._lbl(self._search_results, "Loading installed apps...",
                      fg=MUTED, font=("Sans", 8)).pack(anchor="w", pady=2)
            return
        matches = [r for r in self._all_candidates if self._candidate_matches(q, r)]
        ql = q.lower()
        matches.sort(key=lambda r: (not r["display"].lower().startswith(ql),
                                    len(r["display"])))
        matches = matches[:8]
        if not matches:
            self._lbl(self._search_results, "No matches -- try a different word.",
                      fg=MUTED, font=("Sans", 8)).pack(anchor="w", pady=2)
            return
        existing = {p.lower() for p in user_config.get_apps().values()}
        for r in matches:
            self._make_search_row(r, r["path"].lower() in existing)

    def _make_search_row(self, r, already):
        row = tk.Frame(self._search_results, bg=CARD)
        row.pack(fill="x", pady=1)
        btn = tk.Button(row, text=f"  {r['display']}", anchor="w",
                        bg=ENTRY_BG, fg=(MUTED if already else FG),
                        activebackground=ACC, activeforeground="#fff",
                        relief="flat", font=("Sans", 10), cursor="hand2",
                        bd=0, padx=8, pady=4,
                        command=lambda rr=r: self._pick_candidate(rr))
        btn.pack(side="left", fill="x", expand=True)
        tag = "  added" if already else r["proc"]
        tk.Label(row, text=tag, bg=CARD, fg=MUTED,
                 font=("Monospace", 8)).pack(side="right", padx=(6, 2))
        if getattr(self, "_wheel_handler", None):
            self._bind_wheel(row)

    def _pick_candidate(self, r):
        for entry, val in ((self.e_name, r["name"]),
                           (self.e_path, r["path"]),
                           (self.e_proc, r["proc"])):
            entry.delete(0, "end")
            entry.insert(0, val)
            entry.xview_moveto(0)
        self.e_spoken.focus_set()
        self._search_var.set("")
        self._flash(f'Selected "{r["display"]}" -- set a spoken name (optional), '
                    f'then click Add Entry.')

    def _do_scan(self):
        results = _scan_desktop_files()
        for folder in user_config.get_scan_folders():
            results += _scan_folder(folder)
        seen = set(); deduped = []
        for r in results:
            k = r["path"].lower()
            if k not in seen:
                seen.add(k); deduped.append(r)
        deduped.sort(key=lambda x: x["display"].lower())
        self.after(0, lambda: self._populate_scan(deduped))

    def _populate_scan(self, results):
        for w in self._scan_inner.winfo_children():
            w.destroy()
        self._scan_results   = results
        self._scan_visible   = results
        self._scan_vars      = []
        self._scan_name_vars = []
        existing = set(user_config.get_apps().keys())
        for r in results:
            v  = tk.BooleanVar(value=False)
            nv = tk.StringVar(value=r["name"])
            v.trace_add("write", self._update_scan_count)
            self._scan_vars.append(v)
            self._scan_name_vars.append(nv)
            self._make_scan_row(r, v, nv, r["name"] in existing)
        extra = len(user_config.get_scan_folders())
        suffix = f" + {extra} extra folder(s)" if extra else ""
        self._scan_status.config(text=f"Found {len(results)} apps{suffix}")
        self._update_scan_count()

    def _make_scan_row(self, r, var, name_var, already_added):
        row = tk.Frame(self._scan_inner, bg=CARD, pady=3)
        row.pack(fill="x", padx=4, pady=1)
        cb = tk.Checkbutton(row, variable=var, bg=CARD, activebackground=CARD,
                            selectcolor=ENTRY_BG, fg=FG, disabledforeground=MUTED,
                            activeforeground=FG,
                            state="disabled" if already_added else "normal")
        cb.pack(side="left")
        info = tk.Frame(row, bg=CARD)
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=r["display"], bg=CARD,
                 fg=MUTED if already_added else FG,
                 font=("Sans Bold", 9), anchor="w").pack(anchor="w")
        if already_added:
            tk.Label(info, text="  already added", bg=CARD, fg=MUTED,
                     font=("Sans", 8)).pack(anchor="w")
        else:
            nr = tk.Frame(info, bg=CARD)
            nr.pack(anchor="w", fill="x")
            tk.Label(nr, text="  display name:", bg=CARD, fg=GRN,
                     font=("Sans", 8)).pack(side="left")
            tk.Entry(nr, textvariable=name_var, width=20, bg=ENTRY_BG, fg=FG,
                     insertbackground=FG, relief="flat",
                     font=("Sans", 8), bd=2).pack(side="left", padx=(4, 0))
        scroll4 = lambda e: self._scan_canvas.yview_scroll(-1, "units")
        scroll5 = lambda e: self._scan_canvas.yview_scroll(1, "units")
        for w in (row, cb, info):
            w.bind("<Button-4>", scroll4)
            w.bind("<Button-5>", scroll5)

    def _filter_scan(self):
        query = self._scan_search.get().lower()
        for w in self._scan_inner.winfo_children():
            w.destroy()
        existing = set(user_config.get_apps().keys())
        self._scan_visible   = [r for r in self._scan_results
                                 if query in r["display"].lower() or query in r["name"]]
        self._scan_vars      = []
        self._scan_name_vars = []
        for r in self._scan_visible:
            v  = tk.BooleanVar(value=False)
            nv = tk.StringVar(value=r["name"])
            v.trace_add("write", self._update_scan_count)
            self._scan_vars.append(v)
            self._scan_name_vars.append(nv)
            self._make_scan_row(r, v, nv, r["name"] in existing)
        self._update_scan_count()

    def _update_scan_count(self, *_):
        n = sum(v.get() for v in self._scan_vars)
        self._scan_count_lbl.config(text=f"{n} selected" if n else "")

    def _sel_all_scan(self):
        existing = set(user_config.get_apps().keys())
        for v, r in zip(self._scan_vars, self._scan_visible):
            if r["name"] not in existing:
                v.set(True)

    def _add_scan_folder(self):
        folder = filedialog.askdirectory(
            title="Select extra folder to scan for executables",
            parent=self.winfo_toplevel())
        if not folder:
            return
        folders = user_config.get_scan_folders()
        if folder not in folders:
            folders.append(folder)
            user_config.set_scan_folders(folders)
        self._refresh_folders_lbl()
        self._scan_status.config(text="Rescanning with new folder...")
        for w in self._scan_inner.winfo_children():
            w.destroy()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _clear_scan_folders(self):
        user_config.set_scan_folders([])
        self._refresh_folders_lbl()
        self._scan_status.config(text="Rescanning...")
        for w in self._scan_inner.winfo_children():
            w.destroy()
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _refresh_folders_lbl(self):
        folders = user_config.get_scan_folders()
        self._folders_lbl.config(
            text=("  .  ".join(pathlib.Path(f).name for f in folders))
                 if folders else "none -- add a folder to search other locations")

    def _add_scan_selected(self):
        selected = [(r, nv.get().strip().lower())
                    for r, v, nv in zip(self._scan_visible, self._scan_vars, self._scan_name_vars)
                    if v.get()]
        if not selected:
            messagebox.showwarning("Nothing selected", "Tick at least one app to add.",
                                   parent=self.winfo_toplevel())
            return
        if any(not name for _, name in selected):
            messagebox.showwarning("Empty name", "One or more display names are empty.",
                                   parent=self.winfo_toplevel())
            return
        existing = user_config.get_apps()
        conflicts = [name for _, name in selected if name in existing]
        if conflicts:
            names = ", ".join(f'"{n}"' for n in conflicts)
            if not messagebox.askyesno("Overwrite?",
                    f"These already exist: {names}\n\nOverwrite them?",
                    parent=self.winfo_toplevel()):
                return
        for r, name in selected:
            user_config.add_entry(name, r["path"], r["proc"])
        messagebox.showinfo("Done",
                            f"Added {len(selected)} app(s).\n\n" +
                            "\n".join(f'  - {r["display"]} -> "{name}"'
                                      for r, name in selected),
                            parent=self.winfo_toplevel())
        self._go_main()

    def _reload(self):
        self._apps  = user_config.get_apps()
        self._procs = user_config.get_proc_names()
        names = sorted(self._apps.keys())
        prev  = self.combo_var.get()
        self.combo["values"] = names
        if names:
            sel = prev if prev in names else names[0]
            self.combo.set(sel)
            self._show_preview(sel)
            self.e_rename.delete(0, "end")
            self.e_rename.insert(0, sel)
        else:
            self.combo.set("")
            for e in (self.e_edit_path, self.e_edit_proc, self.e_edit_spoken):
                e.delete(0, "end")
            self.e_rename.delete(0, "end")

    def _show_preview(self, name: str):
        path   = self._apps.get(name, "")
        proc   = self._procs.get(name, "")
        spoken = user_config.get_spoken_names().get(name, "")
        for e, val in ((self.e_edit_path, path),
                       (self.e_edit_proc, proc),
                       (self.e_edit_spoken, spoken)):
            e.delete(0, "end")
            e.insert(0, val)

    def _on_select(self, _=None):
        name = self.combo_var.get()
        self._show_preview(name)
        self.e_rename.delete(0, "end")
        self.e_rename.insert(0, name)

    def _browse_edit_exe(self):
        path = filedialog.askopenfilename(
            title="Select executable",
            parent=self.winfo_toplevel(),
        )
        if not path:
            return
        p = pathlib.Path(path)
        self.e_edit_path.delete(0, "end"); self.e_edit_path.insert(0, str(p))
        self.e_edit_proc.delete(0, "end"); self.e_edit_proc.insert(0, p.name)

    def _detect_proc_edit(self):
        """Capture the process name of whatever window the user focuses next."""
        if not self.combo_var.get():
            self._flash("Pick an app from the list first.", RED)
            return

        secs = 5

        def _tick(remaining):
            if remaining > 0:
                self._status_lbl.config(
                    text=f"Switch to the app's window now -- capturing in {remaining}s ...",
                    fg=ACCENT_TEXT)
                self.after(1000, lambda: _tick(remaining - 1))
                return
            name = self._capture_foreground_proc()
            if not name:
                self._flash(
                    "Couldn't read the foreground app -- try again.", RED)
                return
            self.e_edit_proc.delete(0, "end")
            self.e_edit_proc.insert(0, name)
            self._flash(f'Detected "{name}".  Press Save Changes to keep it.', GRN)

        self.after(1000, lambda: _tick(secs - 1))

    def _capture_foreground_proc(self) -> str:
        """Return the process name of the current foreground window."""
        try:
            out = subprocess.check_output(
                ["xdotool", "getactivewindow", "getwindowpid"],
                text=True, stderr=subprocess.DEVNULL).strip()
            pid = int(out)
            import psutil
            name = psutil.Process(pid).name()
            if not name or name.lower() in ("echo", "python", "python3", "python3.11"):
                return ""
            return name
        except Exception:
            return ""

    def _on_save_edit(self):
        name   = self.combo_var.get()
        path   = self.e_edit_path.get().strip()
        proc   = self.e_edit_proc.get().strip()
        spoken = self.e_edit_spoken.get().strip().lower()
        if not name:
            return
        if not path or not proc:
            messagebox.showwarning("Missing fields",
                                   "Path and Process name cannot be empty.",
                                   parent=self.winfo_toplevel())
            return
        user_config.add_entry(name, path, proc)
        user_config.set_spoken_name(name, spoken)
        self._reload()
        self.combo.set(name)
        self._show_preview(name)
        note = f'  (say "{spoken}")' if spoken else ""
        self._flash(f'Updated "{name}"{note}.')

    def _flash(self, msg: str, color=GRN):
        self._status_lbl.config(text=msg, fg=color)
        self.after(6000, lambda: self._status_lbl.config(text=""))

    def _on_add(self):
        name   = self.e_name.get().strip().lower()
        path   = self.e_path.get().strip()
        proc   = self.e_proc.get().strip() or self._auto_proc_from_path(path)
        spoken = self.e_spoken.get().strip().lower()
        if not name or not path:
            messagebox.showwarning("Missing fields",
                                   "Display name and path are required.",
                                   parent=self.winfo_toplevel())
            return
        if name in self._apps and not messagebox.askyesno(
                "Overwrite?", f'"{name}" already exists. Overwrite it?',
                parent=self.winfo_toplevel()):
            return
        user_config.add_entry(name, path, proc)
        user_config.set_spoken_name(name, spoken)
        self._reload()
        for e in (self.e_name, self.e_path, self.e_proc, self.e_spoken):
            e.delete(0, "end")
        note = f'  (say "{spoken}")' if spoken else ""
        self._flash(f'Added "{name}"{note}.')

    def _on_rename(self):
        old = self.combo_var.get()
        new = self.e_rename.get().strip().lower()
        if not old or not new or new == old:
            return
        if new in self._apps and not messagebox.askyesno(
                "Overwrite?", f'"{new}" already exists. Overwrite it?',
                parent=self.winfo_toplevel()):
            return
        spoken_names = user_config.get_spoken_names()
        old_spoken   = spoken_names.pop(old, "")
        if old_spoken:
            spoken_names[new] = old_spoken
        user_config.delete_entry(old)
        user_config.add_entry(new, self._apps.get(old, ""), self._procs.get(old, ""))
        user_config.set_spoken_names(spoken_names)
        self._reload()
        self._flash(f'Renamed "{old}" -> "{new}".')

    def _on_delete(self):
        name = self.combo_var.get()
        if not name:
            return
        if not messagebox.askyesno("Confirm delete", f'Delete "{name}" from your config?',
                                   parent=self.winfo_toplevel()):
            return
        user_config.delete_entry(name)
        user_config.set_spoken_name(name, "")
        self._reload()
        self._flash(f'Deleted "{name}".', color=RED)


AppManagerWindow = AppManagerWidget


if __name__ == "__main__":
    root = tk.Tk()
    root.title("App Manager")
    root.configure(bg=BG)
    root.geometry("960x680")
    AppManagerWidget(root).pack(fill="both", expand=True)
    root.mainloop()
