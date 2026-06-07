"""
Settings widget — embeds directly in the main window as a tab (SettingsWidget).
"""
import tkinter as tk
from tkinter import ttk, messagebox
import user_config

BG       = "#1e1e2e"
CARD     = "#2a2a3e"
ACC      = "#7c6af7"
FG       = "#cdd6f4"
ENTRY_BG = "#313244"
MUTED    = "#585b70"
GRN      = "#a6e3a1"
RED      = "#f38ba8"


def _lbl(parent, text, fg=FG, font=("Segoe UI", 9), **kw):
    return tk.Label(parent, text=text, bg=parent["bg"], fg=fg, font=font, **kw)

def _inp(parent, width=16, **kw):
    return tk.Entry(parent, width=width, bg=ENTRY_BG, fg=FG,
                    insertbackground=FG, relief="flat",
                    font=("Segoe UI", 10), bd=4, **kw)

def _spin(parent, from_, to, var, width=6):
    return tk.Spinbox(parent, from_=from_, to=to, textvariable=var,
                      width=width, bg=ENTRY_BG, fg=FG,
                      buttonbackground=CARD, insertbackground=FG,
                      relief="flat", font=("Segoe UI", 10))

def _section(parent, title):
    f = tk.Frame(parent, bg=BG)
    tk.Label(f, text=title, bg=BG, fg=ACC,
             font=("Segoe UI Semibold", 10)).pack(anchor="w")
    tk.Frame(f, bg=ACC, height=1).pack(fill="x", pady=(2, 8))
    return f

def _card(parent):
    return tk.Frame(parent, bg=CARD, padx=14, pady=10)


class SettingsWidget(tk.Frame):
    """Embeds directly into a parent frame / notebook tab."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._build_ui()
        self._load()
        self.after(200, self._load)

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",      background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",  background=CARD, foreground=FG,
                        padding=[14, 6], font=("Segoe UI Semibold", 9))
        style.map("TNotebook.Tab",
                  background=[("selected", ACC)],
                  foreground=[("selected", "#ffffff")])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        self._tab_engine(nb)
        self._tab_volume(nb)
        self._tab_commands(nb)
        self._tab_context(nb)

        self._status = tk.Label(self, text="", bg=BG, fg=GRN,
                                font=("Segoe UI", 9), anchor="w")
        self._status.pack(fill="x", padx=14, pady=(0, 10))

    # ── Engine tab ────────────────────────────────────────────────────────────

    def _tab_engine(self, nb):
        frame = tk.Frame(nb, bg=BG)
        nb.add(frame, text="⚙  Engine")

        sec = _section(frame, "Recognition")
        sec.pack(fill="x", padx=2, pady=(8, 0))
        card = _card(sec); card.pack(fill="x")

        _lbl(card, "Confidence threshold  (how sure it must be before acting)").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 2))
        self._conf_spin = _spin(card, 1, 100, tk.IntVar())
        self._conf_spin.grid(row=1, column=0, sticky="w")
        _lbl(card, "%", fg=MUTED).grid(row=1, column=1, sticky="w", padx=(4, 20))
        self._conf_note = _lbl(card, "", fg=MUTED)
        self._conf_note.grid(row=1, column=2, sticky="w")
        self._conf_spin.bind("<KeyRelease>", self._on_conf_change)
        self._conf_spin.bind("<<Increment>>", self._on_conf_change)
        self._conf_spin.bind("<<Decrement>>", self._on_conf_change)

        _lbl(card, "Cooldown  (ignore repeated command within this window)").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(12, 2))
        self._cooldown_spin = _spin(card, 0.0, 10.0, tk.DoubleVar(), width=7)
        self._cooldown_spin.grid(row=3, column=0, sticky="w")
        _lbl(card, "seconds", fg=MUTED).grid(row=3, column=1, sticky="w", padx=(4, 0))

        sec2 = _section(frame, "Close-App Undo Window")
        sec2.pack(fill="x", padx=2, pady=(14, 0))
        card2 = _card(sec2); card2.pack(fill="x")

        _lbl(card2, "Duration  (seconds to re-open a closed app)").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 2))
        self._delay_spin = _spin(card2, 1, 60, tk.IntVar(), width=6)
        self._delay_spin.grid(row=1, column=0, sticky="w")
        _lbl(card2, "seconds", fg=MUTED).grid(row=1, column=1, sticky="w", padx=(4, 0))

        sec3 = _section(frame, "Status Overlay")
        sec3.pack(fill="x", padx=2, pady=(14, 0))
        card3 = _card(sec3); card3.pack(fill="x")

        self._overlay_enabled = tk.BooleanVar()
        tk.Checkbutton(card3, text="Show overlay when a command fires",
                       variable=self._overlay_enabled,
                       bg=CARD, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=CARD, activeforeground=FG,
                       font=("Segoe UI", 9)).grid(row=0, column=0, columnspan=2, sticky="w")

        _lbl(card3, "Position:", fg=MUTED).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._overlay_pos = tk.StringVar()
        style2 = ttk.Style(card3); style2.theme_use("clam")
        style2.configure("TCombobox", fieldbackground=ENTRY_BG, foreground=FG,
                         background=CARD, arrowcolor=FG)
        ttk.Combobox(card3, textvariable=self._overlay_pos,
                     state="readonly", width=18,
                     values=["bottom-right", "bottom-center", "bottom-left",
                             "top-right", "top-center", "top-left"]
                     ).grid(row=1, column=1, sticky="w", padx=(10, 0))

        self._make_save_btn(frame, self._save_engine)

    def _on_conf_change(self, _e=None):
        try:
            v = int(self._conf_spin.get())
            if v < 50:
                note = "⚠  Very low — many false triggers"
            elif v < 65:
                note = "Low — occasional false triggers"
            elif v <= 80:
                note = "Recommended"
            else:
                note = "High — may miss quiet speech"
            self._conf_note.config(text=note)
        except ValueError:
            pass

    def _save_engine(self):
        try:
            user_config.set_confidence_threshold(int(self._conf_spin.get()) / 100)
            user_config.set_cooldown(float(self._cooldown_spin.get()))
            user_config.set_close_delay(int(self._delay_spin.get()))
            user_config.set_overlay_enabled(self._overlay_enabled.get())
            user_config.set_overlay_position(self._overlay_pos.get())
            self._flash("✓  Engine settings saved — restart engine to apply.")
        except Exception as e:
            self._flash(f"Error: {e}", RED)

    # ── Volume tab ────────────────────────────────────────────────────────────

    def _tab_volume(self, nb):
        frame = tk.Frame(nb, bg=BG)
        nb.add(frame, text="🔊  Volume")

        sec = _section(frame, "Volume Step Words")
        sec.pack(fill="x", padx=2, pady=(8, 0))
        card = _card(sec); card.pack(fill="x")

        _lbl(card, 'Say  "volume up <word>"  or  "volume down <word>"  to change by that amount.',
             fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 8))

        self._vol_spins = {}
        steps = user_config.DEFAULT_VOLUME_STEPS
        for i, word in enumerate(steps):
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", pady=2)
            _lbl(row, f'"{word}"', width=8, anchor="w").pack(side="left")
            sp = _spin(row, 1, 100, tk.IntVar(), width=5)
            sp.pack(side="left", padx=(4, 0))
            _lbl(row, "%", fg=MUTED).pack(side="left", padx=(4, 0))
            self._vol_spins[word] = sp

        self._make_save_btn(frame, self._save_volume)

    def _save_volume(self):
        try:
            steps = {w: int(sp.get()) for w, sp in self._vol_spins.items()}
            user_config.set_volume_steps(steps)
            self._flash("✓  Volume steps saved — restart engine to apply.")
        except Exception as e:
            self._flash(f"Error: {e}", RED)

    # ── Commands tab ──────────────────────────────────────────────────────────

    def _tab_commands(self, nb):
        frame = tk.Frame(nb, bg=BG)
        nb.add(frame, text="🗣  Commands")

        _lbl(frame,
             "Customise the trigger word for each command.\n"
             "Separate multiple trigger words with a comma (e.g. pause,play)",
             fg=MUTED, font=("Segoe UI", 8), justify="left").pack(
            anchor="w", padx=4, pady=(8, 4))

        canvas = tk.Canvas(frame, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        cwin = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(cwin, width=e.width))
        canvas.bind("<MouseWheel>",
                    lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        inner.bind("<MouseWheel>",
                   lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        self._cmd_entries = {}
        groups = [
            ("Media",       ["skip", "previous", "rewind", "play_pause", "mute"]),
            ("Keyboard",    ["copy", "paste", "save", "enter", "undo"]),
            ("App control", ["open", "close", "minimise", "maximise", "move", "merge"]),
            ("Engine",      ["diagnose", "stop_engine", "restart_engine"]),
        ]
        for group_name, keys in groups:
            sec = _section(inner, group_name)
            sec.pack(fill="x", padx=4, pady=(8, 0))
            card = _card(sec); card.pack(fill="x")
            hdr = tk.Frame(card, bg=CARD)
            hdr.pack(fill="x", pady=(0, 4))
            w = 18
            _lbl(hdr, "Action", fg=ACC, font=("Segoe UI Semibold", 8),
                 width=w, anchor="w").pack(side="left")
            _lbl(hdr, "Trigger word(s)", fg=ACC, font=("Segoe UI Semibold", 8),
                 anchor="w").pack(side="left")
            for key in keys:
                row = tk.Frame(card, bg=CARD)
                row.pack(fill="x", pady=2)
                _lbl(row, key.replace("_", " "), width=w, anchor="w").pack(side="left")
                e = _inp(row, width=28)
                e.pack(side="left")
                self._cmd_entries[key] = e

        self._make_save_btn(inner, self._save_commands)

    def _save_commands(self):
        try:
            words = {k: e.get().strip() for k, e in self._cmd_entries.items()}
            user_config.set_command_words(words)
            self._flash("✓  Command words saved — restart engine to apply.")
        except Exception as e:
            self._flash(f"Error: {e}", RED)

    # ── Context tab ───────────────────────────────────────────────────────────

    def _tab_context(self, nb):
        frame = tk.Frame(nb, bg=BG)
        nb.add(frame, text="🖱  Context")

        _lbl(frame,
             "These commands only fire when the right app is focused.\n"
             "Contexts: browser · explorer · editor · any (always works)",
             fg=MUTED, font=("Segoe UI", 8), justify="left").pack(
            anchor="w", padx=4, pady=(8, 4))

        list_frame = tk.Frame(frame, bg=CARD)
        list_frame.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        hdr = tk.Frame(list_frame, bg=CARD)
        hdr.pack(fill="x", padx=6, pady=(6, 2))
        for text, w in [("Voice phrase", 22), ("Context", 10), ("Shortcut", 16)]:
            _lbl(hdr, text, fg=ACC, font=("Segoe UI Semibold", 8),
                 width=w, anchor="w").pack(side="left")

        canvas = tk.Canvas(list_frame, bg=CARD, highlightthickness=0, height=260)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._ctx_inner = tk.Frame(canvas, bg=CARD)
        _cwin = canvas.create_window((0, 0), window=self._ctx_inner, anchor="nw")
        self._ctx_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(_cwin, width=e.width))
        canvas.bind("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._ctx_inner.bind("<MouseWheel>",
            lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._ctx_canvas = canvas

        bot = tk.Frame(frame, bg=BG)
        bot.pack(fill="x", padx=4, pady=(0, 4))
        tk.Button(bot, text="➕  Add Command", command=self._add_context_cmd,
                  bg=ACC, fg="#fff", activebackground=ACC, activeforeground="#fff",
                  relief="flat", font=("Segoe UI Semibold", 9),
                  padx=10, pady=5, cursor="hand2").pack(side="left")
        tk.Button(bot, text="🗑  Delete Selected", command=self._del_context_cmd,
                  bg=RED, fg="#fff", activebackground=RED, activeforeground="#fff",
                  relief="flat", font=("Segoe UI Semibold", 9),
                  padx=10, pady=5, cursor="hand2").pack(side="left", padx=(8, 0))
        tk.Button(bot, text="↺  Reset Defaults", command=self._reset_context_cmds,
                  bg=MUTED, fg="#fff", activebackground=MUTED, activeforeground="#fff",
                  relief="flat", font=("Segoe UI Semibold", 9),
                  padx=10, pady=5, cursor="hand2").pack(side="right")

    def _reload_context_list(self):
        for w in self._ctx_inner.winfo_children():
            w.destroy()
        self._ctx_row_vars = []
        cmds   = user_config.get_context_commands()
        canvas = self._ctx_canvas

        def _scroll(e):
            canvas.yview_scroll(-1*(e.delta//120), "units")

        for phrase, contexts in sorted(cmds.items()):
            for context, shortcut in contexts.items():
                var = tk.BooleanVar(value=False)
                row = tk.Frame(self._ctx_inner, bg=CARD)
                row.pack(fill="x", padx=4, pady=1)
                cb = tk.Checkbutton(row, variable=var, bg=CARD,
                                    activebackground=CARD, selectcolor=ENTRY_BG)
                cb.pack(side="left")
                l1 = tk.Label(row, text=phrase, bg=CARD, fg=FG,
                              font=("Segoe UI", 9), width=22, anchor="w")
                l1.pack(side="left")
                ctx_color = {"browser": "#89b4fa", "explorer": "#a6e3a1",
                             "editor": "#f9e2af", "any": "#cba6f7"}.get(context, FG)
                l2 = tk.Label(row, text=context, bg=CARD, fg=ctx_color,
                              font=("Segoe UI", 8), width=10, anchor="w")
                l2.pack(side="left")
                l3 = tk.Label(row, text=shortcut, bg=CARD, fg=MUTED,
                              font=("Consolas", 8), width=16, anchor="w")
                l3.pack(side="left")
                for w in (row, cb, l1, l2, l3):
                    w.bind("<MouseWheel>", _scroll)
                self._ctx_row_vars.append((var, phrase, context))

    def _add_context_cmd(self):
        """Show an inline overlay form instead of a separate Toplevel dialog."""
        overlay = tk.Frame(self, bg="#0d0d1a")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()

        card = tk.Frame(overlay, bg=BG, padx=24, pady=20, relief="flat")
        card.place(relx=0.5, rely=0.4, anchor="center")

        tk.Label(card, text="🖱  Add Context Command", bg=BG, fg=ACC,
                 font=("Segoe UI Semibold", 11)).pack(pady=(0, 12))

        fields = tk.Frame(card, bg=BG)
        fields.pack(fill="x")

        def frow(label, widget_fn):
            f = tk.Frame(fields, bg=BG)
            f.pack(fill="x", pady=4)
            _lbl(f, label).pack(anchor="w")
            widget_fn(f).pack(fill="x")

        phrase_var   = tk.StringVar()
        context_var  = tk.StringVar(value="browser")
        shortcut_var = tk.StringVar()

        frow("Voice phrase  (what you say)",
             lambda f: tk.Entry(f, textvariable=phrase_var, bg=ENTRY_BG, fg=FG,
                                insertbackground=FG, relief="flat",
                                font=("Segoe UI", 10), bd=4))

        def ctx_widget(f):
            cb = ttk.Combobox(f, textvariable=context_var, state="normal",
                              values=["browser", "explorer", "editor", "any"],
                              font=("Segoe UI", 10))
            return cb
        frow("Context  (when does it work?)", ctx_widget)

        _lbl(fields,
             "  browser = Chrome/Firefox/Edge    explorer = File Explorer\n"
             "  editor = Notepad/VS Code etc.    any = always\n"
             "  Or type any .exe name (e.g. blender.exe) for a custom app",
             fg=MUTED, font=("Segoe UI", 8), justify="left").pack(anchor="w")

        frow("Keyboard shortcut  (e.g. ctrl+w  or  f5  or  windows+l)",
             lambda f: tk.Entry(f, textvariable=shortcut_var, bg=ENTRY_BG, fg=FG,
                                insertbackground=FG, relief="flat",
                                font=("Consolas", 10), bd=4))

        btn_row = tk.Frame(card, bg=BG)
        btn_row.pack(fill="x", pady=(12, 0))

        def _ok(_e=None):
            phrase   = phrase_var.get().strip().lower()
            context  = context_var.get().strip()
            shortcut = shortcut_var.get().strip().lower()
            if not phrase or not shortcut:
                return
            overlay.destroy()
            cmds = user_config.get_context_commands()
            if phrase not in cmds:
                cmds[phrase] = {}
            cmds[phrase][context] = shortcut
            user_config.set_context_commands(cmds)
            self._reload_context_list()
            self._flash(f'✓  Added "{phrase}" [{context}] → {shortcut}')

        def _cancel(_e=None):
            overlay.destroy()

        overlay.bind("<Escape>", _cancel)

        tk.Button(btn_row, text="Add", command=_ok,
                  bg=ACC, fg="#fff", activebackground=ACC, activeforeground="#fff",
                  relief="flat", font=("Segoe UI Semibold", 9),
                  padx=14, pady=5, cursor="hand2").pack(side="right")
        tk.Button(btn_row, text="Cancel", command=_cancel,
                  bg=MUTED, fg="#fff", activebackground=MUTED, activeforeground="#fff",
                  relief="flat", font=("Segoe UI Semibold", 9),
                  padx=14, pady=5, cursor="hand2").pack(side="right", padx=(0, 8))

    def _del_context_cmd(self):
        to_delete = [(p, c) for v, p, c in self._ctx_row_vars if v.get()]
        if not to_delete:
            self._flash("Select rows to delete first.", GRN)
            return
        cmds = user_config.get_context_commands()
        for phrase, context in to_delete:
            if phrase in cmds and context in cmds[phrase]:
                del cmds[phrase][context]
                if not cmds[phrase]:
                    del cmds[phrase]
        user_config.set_context_commands(cmds)
        self._reload_context_list()
        self._flash(f"✓  Deleted {len(to_delete)} rule(s).")

    def _reset_context_cmds(self):
        if messagebox.askyesno("Reset?",
                               "Reset context commands to defaults?\n"
                               "Your custom additions will be lost.",
                               parent=self.winfo_toplevel()):
            user_config.set_context_commands({})
            self._reload_context_list()
            self._flash("✓  Reset to defaults.")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_save_btn(self, parent, cmd):
        tk.Button(parent, text="💾  Save", command=cmd,
                  bg=ACC, fg="#fff", activebackground=ACC,
                  activeforeground="#fff", relief="flat",
                  font=("Segoe UI Semibold", 10),
                  padx=14, pady=6, cursor="hand2").pack(
            anchor="e", padx=14, pady=(12, 4))

    def _flash(self, msg, color=GRN):
        self._status.config(text=msg, fg=color)
        self.after(5000, lambda: self._status.config(text=""))

    def _set_spin(self, widget, value):
        widget.config(state="normal")
        widget.delete(0, "end")
        widget.insert(0, str(value))

    def _load(self):
        try:
            self._overlay_enabled.set(user_config.get_overlay_enabled())
            self._overlay_pos.set(user_config.get_overlay_position())
            self._set_spin(self._conf_spin,
                           int(user_config.get_confidence_threshold() * 100))
            self._on_conf_change()
            self._set_spin(self._cooldown_spin, user_config.get_cooldown())
            self._set_spin(self._delay_spin,    user_config.get_close_delay())
            steps = user_config.get_volume_steps()
            for word, sp in self._vol_spins.items():
                self._set_spin(sp, steps.get(word,
                               user_config.DEFAULT_VOLUME_STEPS.get(word, 5)))
            words = user_config.get_command_words()
            for key, entry in self._cmd_entries.items():
                val = words.get(key, user_config.DEFAULT_COMMAND_WORDS.get(key, ""))
                entry.config(state="normal")
                entry.delete(0, "end")
                entry.insert(0, val)
                entry.xview_moveto(0)
            self._reload_context_list()
        except Exception as exc:
            import traceback
            self._flash(f"⚠ Settings load error: {exc}", RED)
            traceback.print_exc()


# Backward-compat alias
SettingsWindow = SettingsWidget


# ── Standalone ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.title("Settings")
    root.configure(bg=BG)
    root.geometry("700x600")
    root.deiconify()
    SettingsWidget(root).pack(fill="both", expand=True)
    root.mainloop()
