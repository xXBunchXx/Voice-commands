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
AMBER    = "#fab387"

_KNOWN_CONTEXTS = ("browser", "explorer", "editor", "any")
_CTX_ICONS      = {"browser": "🌐", "explorer": "📁", "editor": "✏️", "any": "🌍"}
_CTX_COLOURS    = {"browser": "#89b4fa", "explorer": "#a6e3a1",
                   "editor": "#f9e2af",  "any":     "#cba6f7"}

_MOD_MAP = {
    "control_l": "ctrl",  "control_r": "ctrl",
    "shift_l":   "shift", "shift_r":   "shift",
    "alt_l":     "alt",   "alt_r":     "alt",
    "super_l":   "windows", "super_r": "windows",
    "alt_gr":    "altgr",
}
_MODS = frozenset(_MOD_MAP.values()) | frozenset(_MOD_MAP.keys())


def _norm_key(sym: str) -> str:
    s = sym.lower()
    return _MOD_MAP.get(s, s)


def _combo_str(held: set) -> str:
    order = ["windows", "ctrl", "shift", "alt", "altgr"]
    mods  = [m for m in order if m in held]
    rest  = sorted(k for k in held if k not in order and k not in _MODS)
    return "+".join(mods + rest)


def _value_preview(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("type") == "macro":
        n   = len(value.get("steps", []))
        rep = value.get("repeat", 1)
        s   = f"Macro · {n} step{'s' if n != 1 else ''}"
        if rep > 1:
            s += f" × {rep}"
        return s
    return str(value)


def _lbl(parent, text, fg=FG, font=("Segoe UI", 9), **kw):
    return tk.Label(parent, text=text, bg=parent["bg"], fg=fg, font=font, **kw)

def _inp(parent, width=28, **kw):
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

def _btn(parent, text, cmd, color=ACC, **kw):
    return tk.Button(parent, text=text, command=cmd,
                     bg=color, fg="#fff", activebackground=color,
                     activeforeground="#fff", relief="flat",
                     font=("Segoe UI Semibold", 9), cursor="hand2",
                     padx=10, pady=5, **kw)


# ─────────────────────────────────────────────────────────────────────────────

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
        for word in user_config.DEFAULT_VOLUME_STEPS:
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

        # Top bar
        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x", padx=4, pady=(8, 4))
        _lbl(top,
             "Commands that only fire when the right app is focused, grouped by context.",
             fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        _btn(top, "➕  Add Command", self._add_context_cmd).pack(side="right")

        # Scrollable grouped list
        list_outer = tk.Frame(frame, bg=CARD)
        list_outer.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        self._ctx_canvas = tk.Canvas(list_outer, bg=BG, highlightthickness=0)
        ctx_sb = ttk.Scrollbar(list_outer, orient="vertical",
                               command=self._ctx_canvas.yview)
        self._ctx_canvas.configure(yscrollcommand=ctx_sb.set)
        ctx_sb.pack(side="right", fill="y")
        self._ctx_canvas.pack(side="left", fill="both", expand=True)

        self._ctx_inner = tk.Frame(self._ctx_canvas, bg=BG)
        _cwin = self._ctx_canvas.create_window(
            (0, 0), window=self._ctx_inner, anchor="nw")
        self._ctx_inner.bind(
            "<Configure>",
            lambda e: self._ctx_canvas.configure(
                scrollregion=self._ctx_canvas.bbox("all")))
        self._ctx_canvas.bind(
            "<Configure>",
            lambda e: self._ctx_canvas.itemconfig(_cwin, width=e.width))

        def _scroll(e):
            self._ctx_canvas.yview_scroll(-1*(e.delta//120), "units")
        self._ctx_canvas.bind("<MouseWheel>", _scroll)
        self._ctx_inner.bind("<MouseWheel>", _scroll)

        # Bottom buttons
        bot = tk.Frame(frame, bg=BG)
        bot.pack(fill="x", padx=4, pady=(0, 4))
        _btn(bot, "🗑  Delete Selected", self._del_selected_ctx,
             color=RED).pack(side="left")
        _btn(bot, "↺  Reset Defaults", self._reset_context_cmds,
             color=MUTED).pack(side="right")

    def _reload_context_list(self):
        """Rebuild the grouped context list."""
        for w in self._ctx_inner.winfo_children():
            w.destroy()
        self._ctx_row_vars = []   # [(BoolVar, phrase, context)]

        cmds = user_config.get_context_commands()

        # Build groups dict: known contexts first, then custom .exe names
        groups: dict[str, list] = {c: [] for c in _KNOWN_CONTEXTS}
        for phrase, contexts in sorted(cmds.items()):
            for ctx, value in contexts.items():
                if ctx in _KNOWN_CONTEXTS:
                    groups[ctx].append((phrase, value))
                else:
                    groups.setdefault(ctx, []).append((phrase, value))

        def _scroll_pass(e):
            self._ctx_canvas.yview_scroll(-1*(e.delta//120), "units")

        for ctx_name, entries in groups.items():
            if not entries:
                continue

            icon  = _CTX_ICONS.get(ctx_name, "🔧")
            color = _CTX_COLOURS.get(ctx_name, AMBER)
            label = ctx_name if ctx_name in _KNOWN_CONTEXTS else f"{ctx_name}  (custom)"

            hdr = tk.Frame(self._ctx_inner, bg=CARD)
            hdr.pack(fill="x", pady=(8, 1))
            tk.Label(hdr, text=f"  {icon}  {label}", bg=CARD, fg=color,
                     font=("Segoe UI Semibold", 10),
                     padx=6, pady=5).pack(side="left")
            hdr.bind("<MouseWheel>", _scroll_pass)

            for phrase, value in sorted(entries, key=lambda x: x[0]):
                var = tk.BooleanVar(value=False)
                row = tk.Frame(self._ctx_inner, bg=BG)
                row.pack(fill="x", padx=2, pady=1)

                cb = tk.Checkbutton(row, variable=var, bg=BG,
                                    activebackground=BG, selectcolor=ENTRY_BG)
                cb.pack(side="left")

                tk.Label(row, text=phrase, bg=BG, fg=FG,
                         font=("Segoe UI", 9), width=24, anchor="w").pack(side="left")

                preview   = _value_preview(value)
                is_macro  = isinstance(value, dict)
                prev_fg   = AMBER if is_macro else MUTED
                tk.Label(row, text=preview, bg=BG, fg=prev_fg,
                         font=("Consolas", 8), width=26, anchor="w").pack(side="left")

                _btn(row, "✏ Edit",
                     lambda p=phrase, c=ctx_name, v=value: self._edit_cmd(p, c, v),
                     color=ACC).pack(side="right", padx=(2, 0))
                _btn(row, "✕",
                     lambda p=phrase, c=ctx_name: self._del_one_ctx(p, c),
                     color=RED).pack(side="right", padx=(2, 0))

                for w in (row, cb):
                    w.bind("<MouseWheel>", _scroll_pass)
                self._ctx_row_vars.append((var, phrase, ctx_name))

    # ── Context CRUD ──────────────────────────────────────────────────────────

    def _add_context_cmd(self):
        self._show_cmd_editor()

    def _edit_cmd(self, phrase, context, value):
        self._show_cmd_editor(phrase=phrase, context=context, value=value,
                              old_phrase=phrase, old_context=context)

    def _del_one_ctx(self, phrase, context):
        cmds = user_config.get_context_commands()
        if phrase in cmds and context in cmds[phrase]:
            del cmds[phrase][context]
            if not cmds[phrase]:
                del cmds[phrase]
        user_config.set_context_commands(cmds)
        self._reload_context_list()
        self._flash(f'✓  Deleted "{phrase}" [{context}].')

    def _del_selected_ctx(self):
        to_del = [(p, c) for v, p, c in self._ctx_row_vars if v.get()]
        if not to_del:
            self._flash("Select rows to delete first.", GRN)
            return
        cmds = user_config.get_context_commands()
        for phrase, context in to_del:
            if phrase in cmds and context in cmds[phrase]:
                del cmds[phrase][context]
                if not cmds[phrase]:
                    del cmds[phrase]
        user_config.set_context_commands(cmds)
        self._reload_context_list()
        self._flash(f"✓  Deleted {len(to_del)} rule(s).")

    def _reset_context_cmds(self):
        if messagebox.askyesno("Reset?",
                               "Reset context commands to defaults?\n"
                               "Your custom additions will be lost.",
                               parent=self.winfo_toplevel()):
            user_config.set_context_commands({})
            self._reload_context_list()
            self._flash("✓  Reset to defaults.")

    # ── Command editor overlay ────────────────────────────────────────────────

    def _show_cmd_editor(self, *, phrase="", context="browser",
                         value=None, old_phrase=None, old_context=None):
        """
        Full-screen overlay for adding or editing a context command.

        Supports two action types:
          shortcut — a keyboard shortcut string (ctrl+w, f5, windows+l …)
          macro    — an ordered sequence of Press / Wait steps, repeated N times
        """

        # ── Overlay backdrop ──────────────────────────────────────────────────
        overlay = tk.Frame(self, bg="#0d0d1a")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        overlay.focus_set()

        # ── Card ──────────────────────────────────────────────────────────────
        card = tk.Frame(overlay, bg=CARD)
        card.place(relx=0.5, rely=0.5, anchor="center",
                   relwidth=0.84, relheight=0.93)

        # Title bar
        title_text = "✏  Edit Command" if old_phrase else "➕  Add Command"
        title_bar = tk.Frame(card, bg=ACC, pady=8)
        title_bar.pack(fill="x", side="top")
        tk.Label(title_bar, text=title_text, bg=ACC, fg="#fff",
                 font=("Segoe UI Semibold", 12)).pack()

        # Key-capture hint bar (hidden by default)
        cap_bar     = tk.Frame(card, bg="#1a1a2e", pady=5)
        cap_bar_lbl = tk.Label(cap_bar, text="", bg="#1a1a2e", fg=AMBER,
                               font=("Segoe UI Semibold", 9))
        cap_bar_lbl.pack()

        # Fixed footer (Save / Cancel) — packed before the scroll area so it
        # stays at the bottom even when content is short.
        footer = tk.Frame(card, bg=CARD, padx=16, pady=10)
        footer.pack(fill="x", side="bottom")

        # Scrollable body
        scroll_host = tk.Frame(card, bg=CARD)
        scroll_host.pack(fill="both", expand=True, side="top")

        body_canvas = tk.Canvas(scroll_host, bg=CARD, highlightthickness=0)
        body_sb = ttk.Scrollbar(scroll_host, orient="vertical",
                                command=body_canvas.yview)
        body_canvas.configure(yscrollcommand=body_sb.set)
        body_sb.pack(side="right", fill="y")
        body_canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(body_canvas, bg=CARD, padx=18, pady=12)
        _bwin = body_canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>",
                  lambda e: body_canvas.configure(
                      scrollregion=body_canvas.bbox("all")))
        body_canvas.bind("<Configure>",
                         lambda e: body_canvas.itemconfig(_bwin, width=e.width))

        def _scroll_body(e):
            body_canvas.yview_scroll(-1*(e.delta//120), "units")
        body.bind("<MouseWheel>", _scroll_body)
        body_canvas.bind("<MouseWheel>", _scroll_body)

        # ── Detect initial mode ───────────────────────────────────────────────
        if isinstance(value, dict) and value.get("type") == "macro":
            init_mode     = "macro"
            init_shortcut = ""
            init_steps    = [dict(s) for s in value.get("steps", [])]
            init_repeat   = int(value.get("repeat", 1))
        else:
            init_mode     = "shortcut"
            init_shortcut = value if isinstance(value, str) else ""
            init_steps    = []
            init_repeat   = 1

        # ── Form variables ────────────────────────────────────────────────────
        phrase_var   = tk.StringVar(value=phrase)
        context_var  = tk.StringVar(value=context)
        mode_var     = tk.StringVar(value=init_mode)
        shortcut_var = tk.StringVar(value=init_shortcut)
        repeat_var   = tk.IntVar(value=init_repeat)
        steps        = list(init_steps)   # mutable list shared with step callbacks

        # ── Voice phrase ──────────────────────────────────────────────────────
        def field_row(label, widget_fn):
            f = tk.Frame(body, bg=CARD)
            f.pack(fill="x", pady=4)
            tk.Label(f, text=label, bg=CARD, fg=MUTED,
                     font=("Segoe UI", 8)).pack(anchor="w")
            widget_fn(f).pack(fill="x")

        field_row("Voice phrase  (what you say)",
                  lambda f: tk.Entry(f, textvariable=phrase_var,
                                     bg=ENTRY_BG, fg=FG, insertbackground=FG,
                                     relief="flat", font=("Segoe UI", 10), bd=4))

        field_row("Context",
                  lambda f: ttk.Combobox(f, textvariable=context_var, state="normal",
                                         values=list(_KNOWN_CONTEXTS),
                                         font=("Segoe UI", 10)))

        tk.Label(body,
                 text="  browser · explorer · editor · any — "
                      "or type any .exe name (e.g. blender.exe)",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        tk.Frame(body, bg=MUTED, height=1).pack(fill="x", pady=(10, 8))

        # ── Mode toggle ───────────────────────────────────────────────────────
        mode_row = tk.Frame(body, bg=CARD)
        mode_row.pack(fill="x", pady=(0, 8))
        tk.Label(mode_row, text="Action:", bg=CARD, fg=FG,
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 12))

        # Frames for each mode (defined before the radio command callback)
        sc_frame  = tk.Frame(body, bg=CARD)
        mac_frame = tk.Frame(body, bg=CARD)

        def _toggle_mode():
            if mode_var.get() == "shortcut":
                mac_frame.pack_forget()
                sc_frame.pack(fill="x", pady=4)
            else:
                sc_frame.pack_forget()
                mac_frame.pack(fill="x", pady=4)

        for lbl_text, val in [("Keyboard shortcut", "shortcut"),
                               ("Macro / sequence", "macro")]:
            tk.Radiobutton(mode_row, text=lbl_text, variable=mode_var, value=val,
                           bg=CARD, fg=FG, selectcolor=ENTRY_BG,
                           activebackground=CARD, activeforeground=FG,
                           font=("Segoe UI", 9),
                           command=_toggle_mode).pack(side="left", padx=(0, 14))

        # ── Shortcut section ──────────────────────────────────────────────────
        tk.Label(sc_frame,
                 text="Shortcut  (e.g.  ctrl+w  ·  f5  ·  windows+l  ·  ctrl+shift+t)",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))

        sc_inp_row = tk.Frame(sc_frame, bg=CARD)
        sc_inp_row.pack(fill="x")
        sc_entry = tk.Entry(sc_inp_row, textvariable=shortcut_var,
                            bg=ENTRY_BG, fg=FG, insertbackground=FG,
                            relief="flat", font=("Consolas", 10), bd=4)
        sc_entry.pack(side="left", fill="x", expand=True)

        sc_cap_btn = tk.Button(sc_inp_row, text="🎹  Capture",
                               bg=MUTED, fg="#fff", activebackground=MUTED,
                               activeforeground="#fff", relief="flat",
                               font=("Segoe UI Semibold", 9),
                               padx=8, pady=5, cursor="hand2")
        sc_cap_btn.pack(side="left", padx=(8, 0))

        # ── Macro section ─────────────────────────────────────────────────────
        rep_row = tk.Frame(mac_frame, bg=CARD)
        rep_row.pack(fill="x", pady=(0, 10))
        tk.Label(rep_row, text="Repeat:", bg=CARD, fg=FG,
                 font=("Segoe UI", 9)).pack(side="left")
        tk.Spinbox(rep_row, from_=1, to=999, textvariable=repeat_var, width=5,
                   bg=ENTRY_BG, fg=FG, buttonbackground=CARD, insertbackground=FG,
                   relief="flat", font=("Segoe UI", 10)).pack(side="left", padx=(6, 0))
        tk.Label(rep_row, text="times", bg=CARD, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", padx=(6, 0))

        tk.Label(mac_frame, text="Steps:", bg=CARD, fg=FG,
                 font=("Segoe UI Semibold", 9)).pack(anchor="w")

        steps_outer = tk.Frame(mac_frame, bg=ENTRY_BG)
        steps_outer.pack(fill="x", pady=(4, 0))
        steps_cv = tk.Canvas(steps_outer, bg=ENTRY_BG, highlightthickness=0, height=200)
        steps_sb2 = ttk.Scrollbar(steps_outer, orient="vertical",
                                  command=steps_cv.yview)
        steps_cv.configure(yscrollcommand=steps_sb2.set)
        steps_sb2.pack(side="right", fill="y")
        steps_cv.pack(side="left", fill="both", expand=True)
        steps_inner = tk.Frame(steps_cv, bg=ENTRY_BG)
        _swin = steps_cv.create_window((0, 0), window=steps_inner, anchor="nw")
        steps_inner.bind("<Configure>",
                         lambda e: steps_cv.configure(
                             scrollregion=steps_cv.bbox("all")))
        steps_cv.bind("<Configure>",
                      lambda e: steps_cv.itemconfig(_swin, width=e.width))
        steps_cv.bind("<MouseWheel>", _scroll_body)
        steps_inner.bind("<MouseWheel>", _scroll_body)

        def _redraw_steps():
            for w in steps_inner.winfo_children():
                w.destroy()
            if not steps:
                tk.Label(steps_inner,
                         text="  No steps yet — use the buttons below to build your macro.",
                         bg=ENTRY_BG, fg=MUTED, font=("Segoe UI", 8),
                         pady=10).pack(anchor="w")
            for idx, step in enumerate(steps):
                _make_step_row(idx, step)
            steps_cv.update_idletasks()
            steps_cv.yview_moveto(1.0)

        def _make_step_row(idx, step):
            alt = idx % 2 == 0
            row_bg = "#2e2e44" if alt else ENTRY_BG

            f = tk.Frame(steps_inner, bg=row_bg, pady=4, padx=6)
            f.pack(fill="x")
            f.bind("<MouseWheel>", _scroll_body)

            # Number
            tk.Label(f, text=f"{idx+1:2d}.", bg=row_bg, fg=MUTED,
                     font=("Consolas", 9), width=3).pack(side="left")

            # Type toggle button
            t_color = ACC if step["type"] == "press" else AMBER
            def _toggle_type(i=idx):
                steps[i]["type"] = "wait" if steps[i]["type"] == "press" else "press"
                steps[i].setdefault("ms", 200)
                _redraw_steps()

            tk.Button(f, text=step["type"].upper(), command=_toggle_type,
                      bg=t_color, fg="#fff", activebackground=t_color,
                      activeforeground="#fff", relief="flat",
                      font=("Segoe UI Semibold", 8), padx=6, pady=2,
                      cursor="hand2", width=5).pack(side="left", padx=(2, 6))

            e_bg = CARD if alt else "#3a3a54"

            if step["type"] == "press":
                key_var = tk.StringVar(value=step.get("keys", ""))
                def _kchange(*_, i=idx, v=key_var):
                    steps[i]["keys"] = v.get()
                key_var.trace_add("write", _kchange)

                e = tk.Entry(f, textvariable=key_var, bg=e_bg, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Consolas", 9), bd=2, width=18)
                e.pack(side="left", padx=(0, 4))
                e.bind("<MouseWheel>", _scroll_body)

                def _cap_step(v=key_var):
                    _start_capture(v, None)
                tk.Button(f, text="🎹", command=_cap_step,
                          bg=MUTED, fg="#fff", activebackground=MUTED,
                          activeforeground="#fff", relief="flat",
                          font=("Segoe UI", 8), padx=5, pady=2,
                          cursor="hand2").pack(side="left", padx=(0, 6))
            else:
                ms_var = tk.StringVar(value=str(step.get("ms", 200)))
                def _mschange(*_, i=idx, v=ms_var):
                    try:
                        steps[i]["ms"] = max(1, int(v.get()))
                    except ValueError:
                        pass
                ms_var.trace_add("write", _mschange)

                e = tk.Entry(f, textvariable=ms_var, bg=e_bg, fg=FG,
                             insertbackground=FG, relief="flat",
                             font=("Consolas", 9), bd=2, width=7)
                e.pack(side="left", padx=(0, 4))
                e.bind("<MouseWheel>", _scroll_body)
                tk.Label(f, text="ms", bg=row_bg, fg=MUTED,
                         font=("Segoe UI", 8)).pack(side="left", padx=(0, 8))

            # Reorder / delete
            def _up(i=idx):
                if i > 0:
                    steps[i-1], steps[i] = steps[i], steps[i-1]
                    _redraw_steps()
            def _dn(i=idx):
                if i < len(steps)-1:
                    steps[i+1], steps[i] = steps[i], steps[i+1]
                    _redraw_steps()
            def _del(i=idx):
                steps.pop(i)
                _redraw_steps()

            for txt, cmd, col in [("↑", _up, MUTED), ("↓", _dn, MUTED), ("✕", _del, RED)]:
                tk.Button(f, text=txt, command=cmd,
                          bg=col, fg="#fff", activebackground=col,
                          activeforeground="#fff", relief="flat",
                          font=("Segoe UI", 8), padx=5, pady=2,
                          cursor="hand2").pack(side="right", padx=1)

        # Add / record row
        add_row = tk.Frame(mac_frame, bg=CARD)
        add_row.pack(fill="x", pady=(8, 0))

        rec_state   = {"on": False}
        rec_btn_ref = [None]

        def _add_press_step():
            steps.append({"type": "press", "keys": ""})
            _redraw_steps()

        def _add_wait_step():
            steps.append({"type": "wait", "ms": 200})
            _redraw_steps()

        def _toggle_record():
            if rec_state["on"]:
                _stop_record()
            else:
                _start_record()

        for txt, cmd in [("+ Press", _add_press_step), ("+ Wait", _add_wait_step)]:
            _btn(add_row, txt, cmd).pack(side="left", padx=(0, 6))

        rec_b = tk.Button(add_row, text="🔴  Record", command=_toggle_record,
                          bg=MUTED, fg="#fff", activebackground=MUTED,
                          activeforeground="#fff", relief="flat",
                          font=("Segoe UI Semibold", 9), padx=8, pady=5,
                          cursor="hand2")
        rec_b.pack(side="left")
        rec_btn_ref[0] = rec_b

        tk.Label(mac_frame,
                 text="Record: click here to focus, then press key combos — "
                      "each combo becomes a Press step.",
                 bg=CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
            anchor="w", pady=(4, 0))

        _redraw_steps()

        # Show correct mode initially
        if init_mode == "shortcut":
            sc_frame.pack(fill="x", pady=4)
        else:
            mac_frame.pack(fill="x", pady=4)

        # ── Key capture ───────────────────────────────────────────────────────
        _held    = set()
        _cap_tgt = {"var": None, "btn": None}

        def _start_capture(target_var, target_btn):
            _cap_tgt["var"] = target_var
            _cap_tgt["btn"] = target_btn
            _held.clear()
            overlay.focus_set()
            cap_bar_lbl.config(
                text="🎹  Hold your key combination then release the last key…")
            cap_bar.pack(fill="x", after=title_bar)

        def _stop_capture_mode():
            _cap_tgt["var"] = None
            btn = _cap_tgt.get("btn")
            _cap_tgt["btn"] = None
            _held.clear()
            cap_bar.pack_forget()
            if btn:
                try:
                    btn.config(text="🎹  Capture", bg=MUTED)
                except tk.TclError:
                    pass

        # Wire shortcut capture button
        sc_cap_btn.config(command=lambda: _start_capture(shortcut_var, sc_cap_btn))

        def _start_record():
            rec_state["on"] = True
            rec_btn_ref[0].config(text="⏹  Stop", bg=RED)
            _held.clear()
            overlay.focus_set()
            cap_bar_lbl.config(
                text="🔴  Recording — press key combos. Click ⏹ Stop when finished.")
            cap_bar.pack(fill="x", after=title_bar)

        def _stop_record():
            rec_state["on"] = False
            rec_btn_ref[0].config(text="🔴  Record", bg=MUTED)
            _held.clear()
            cap_bar.pack_forget()

        def _on_kp(e):
            sym = _norm_key(e.keysym)
            _held.add(sym)

            # Record mode: each non-modifier keydown → new Press step
            if rec_state["on"] and sym not in _MODS:
                combo = _combo_str(_held)
                _held.clear()
                steps.append({"type": "press", "keys": combo})
                _redraw_steps()

        def _on_kr(e):
            sym = _norm_key(e.keysym)
            # Single-capture mode: register combo on non-modifier key release
            if (not rec_state["on"]
                    and _cap_tgt["var"] is not None
                    and sym not in _MODS
                    and _held):
                combo = _combo_str(_held)
                _cap_tgt["var"].set(combo)
                _stop_capture_mode()
            _held.discard(sym)

        overlay.bind("<KeyPress>",   _on_kp, add="+")
        overlay.bind("<KeyRelease>", _on_kr, add="+")

        # ── Footer buttons ────────────────────────────────────────────────────
        def _cancel(_e=None):
            _stop_record()
            _stop_capture_mode()
            overlay.destroy()

        def _save(_e=None):
            phrase_txt  = phrase_var.get().strip().lower()
            context_txt = context_var.get().strip()
            if not phrase_txt or not context_txt:
                messagebox.showwarning("Missing fields",
                                       "Voice phrase and context are required.",
                                       parent=overlay)
                return

            if mode_var.get() == "shortcut":
                sc = shortcut_var.get().strip().lower()
                if not sc:
                    messagebox.showwarning("Missing shortcut",
                                           "Enter a shortcut or switch to Macro mode.",
                                           parent=overlay)
                    return
                new_value = sc
            else:
                if not steps:
                    messagebox.showwarning("Empty macro",
                                          "Add at least one Press step.",
                                          parent=overlay)
                    return
                new_value = {
                    "type":   "macro",
                    "repeat": max(1, repeat_var.get()),
                    "steps":  [dict(s) for s in steps],
                }

            cmds = user_config.get_context_commands()

            # Remove old entry when editing
            if old_phrase and old_context:
                if old_phrase in cmds and old_context in cmds[old_phrase]:
                    del cmds[old_phrase][old_context]
                    if not cmds[old_phrase]:
                        del cmds[old_phrase]

            cmds.setdefault(phrase_txt, {})[context_txt] = new_value
            user_config.set_context_commands(cmds)
            overlay.destroy()
            self._reload_context_list()
            verb = "Updated" if old_phrase else "Added"
            self._flash(f'✓  {verb} "{phrase_txt}" [{context_txt}]')

        overlay.bind("<Escape>", _cancel)

        _btn(footer, "Save", _save).pack(side="right", padx=(8, 0))
        _btn(footer, "Cancel", _cancel, color=MUTED).pack(side="right")

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
            v_steps = user_config.get_volume_steps()
            for word, sp in self._vol_spins.items():
                self._set_spin(sp, v_steps.get(
                    word, user_config.DEFAULT_VOLUME_STEPS.get(word, 5)))
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
    root.title("Settings")
    root.configure(bg=BG)
    root.geometry("820x700")
    SettingsWidget(root).pack(fill="both", expand=True)
    root.mainloop()
