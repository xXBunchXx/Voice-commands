"""
Echo voice engine -- Linux implementation.

Window management uses xdotool / wmctrl (must be installed).
Audio uses pactl (PulseAudio / PipeWire).
Keyboard simulation uses xdotool key / xdotool type.

Install deps:
    sudo apt install xdotool wmctrl
    pip install pyaudio vosk psutil keyboard pynput
"""

import json
import os
import pathlib
import time
import threading as _threading
import subprocess
import sys
import pyaudio
import psutil
from vosk import Model, KaldiRecognizer
import user_config
import audio_devices

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# ── CONFIG ────────────────────────────────────────────────────────────────────
_cfg        = user_config.load()
MODEL_PATH  = _cfg.get("MODEL_PATH", "vosk-model-small-en-us-0.15")
APPS        = _cfg.get("APPS", {})
PROC_NAMES  = _cfg.get("PROC_NAMES", {})

SAMPLE_RATE       = 16000
FRAMES_PER_BUFFER = 512
COOLDOWN          = 1.5
PARTIAL_STABLE_SECS  = 0.12
CONFIDENCE_THRESHOLD = 0.65

_COMMAND_WORDS:   dict[str, str]             = user_config.DEFAULT_COMMAND_WORDS.copy()
_VOLUME_STEPS:    dict[str, int]             = user_config.DEFAULT_VOLUME_STEPS.copy()
_CONTEXT_COMMANDS:  dict[str, dict[str, str]]  = user_config.DEFAULT_CONTEXT_COMMANDS.copy()
_SPOKEN_NAMES:      dict[str, str]             = {}
_SPOKEN_TO_DISPLAY: dict[str, str]             = {}
_WORD_DELAYS:       dict[str, int]             = {}
_CONTEXT_DELAYS:    dict[str, int]             = {}
_AUDIO_DEVICES:     dict[str, dict]            = {}
_MODES:             dict[str, dict]            = {}
_ACTIVE_MODE:       str                        = "default"


def _mode_names() -> list:
    return ["default"] + sorted(_MODES.keys())

def _active_groups() -> set:
    if _ACTIVE_MODE == "default":
        return set(user_config.MODE_GROUPS)
    g = _MODES.get(_ACTIVE_MODE, {}).get("groups", {})
    return {k for k in user_config.MODE_GROUPS if g.get(k)}

def _active_context_commands() -> dict:
    if _ACTIVE_MODE == "default":
        return _CONTEXT_COMMANDS
    return _MODES.get(_ACTIVE_MODE, {}).get("commands", {})

def set_active_mode(name: str) -> None:
    global _ACTIVE_MODE
    name = (name or "").strip().lower()
    if name not in _mode_names():
        print(f"  No mode called '{name}'")
        return
    _ACTIVE_MODE = name
    print(f"  Mode -> {name}")
    _status(f"Mode: {name.title()}")


def _spoken_all(app: str) -> list[str]:
    raw = _SPOKEN_NAMES.get(app, "") or ""
    aliases = [w.strip() for w in raw.split(",") if w.strip()]
    return aliases or [app]

def _spoken(app: str) -> str:
    return _spoken_all(app)[0]

def _cw_all(key: str) -> list[str]:
    raw = _COMMAND_WORDS.get(key, user_config.DEFAULT_COMMAND_WORDS.get(key, key))
    return [w.strip() for w in raw.split(",") if w.strip()]

def _cw(key: str) -> str:
    parts = _cw_all(key)
    return parts[0] if parts else key


# ── Callbacks ──────────────────────────────────────────────────────────────
_status_cb = None

def _status(msg: str) -> None:
    if _status_cb:
        try:
            _status_cb(msg)
        except Exception:
            pass

_self_window_cb = None
_SELF_EXE = os.path.basename(sys.executable).lower()

def _is_self_app(app_name: str | None) -> bool:
    if not app_name:
        return False
    proc = (PROC_NAMES.get(app_name, "") or "").lower()
    return bool(proc) and proc == _SELF_EXE


# ── Process / window helpers ───────────────────────────────────────────────

def _run(*cmd, capture=True) -> str:
    """Run a command, return stdout (stripped), or '' on failure."""
    try:
        r = subprocess.run(list(cmd),
                           capture_output=capture,
                           text=True, timeout=4)
        return r.stdout.strip() if capture else ""
    except Exception:
        return ""


def _get_active_proc() -> str:
    """Return the process name of the currently focused window."""
    try:
        pid_str = _run("xdotool", "getactivewindow", "getwindowpid")
        if not pid_str:
            return ""
        pid = int(pid_str)
        return psutil.Process(pid).name().lower()
    except Exception:
        return ""


def _get_active_wid() -> str:
    """Return the window id (hex string) of the currently active window."""
    return _run("xdotool", "getactivewindow")


def _pids_for_proc(proc_pattern: str) -> list[int]:
    """Return PIDs whose name matches *proc_pattern* (exact or prefix*)."""
    pids = []
    pattern = proc_pattern.lower()
    prefix = pattern.endswith("*")
    if prefix:
        pattern = pattern[:-1]
    for p in psutil.process_iter(["pid", "name"]):
        try:
            name = (p.info["name"] or "").lower()
            if prefix:
                if name.startswith(pattern):
                    pids.append(p.info["pid"])
            else:
                if name == pattern:
                    pids.append(p.info["pid"])
        except Exception:
            pass
    return pids


def _wids_for_pid(pid: int) -> list[str]:
    """Return xdotool window ids owned by *pid*."""
    out = _run("xdotool", "search", "--pid", str(pid), "--onlyvisible",
               "--name", "")
    if not out:
        # try without --onlyvisible
        out = _run("xdotool", "search", "--pid", str(pid))
    return [w for w in out.splitlines() if w.strip()]


def _wids_for_app(app_name: str) -> list[str]:
    """Return visible window ids belonging to *app_name*'s processes."""
    pattern = PROC_NAMES.get(app_name, "")
    if not pattern:
        return []
    wids = []
    for pid in _pids_for_proc(pattern):
        wids.extend(_wids_for_pid(pid))
    if not wids:
        # Fallback: search by name substring
        out = _run("xdotool", "search", "--classname",
                   pattern.replace(".exe", "").lower())
        wids = [w for w in out.splitlines() if w.strip()]
    return wids


def _proc_matches_context(proc: str, context: str) -> bool:
    if context == "any":
        return True
    if context == "browser":
        return proc in user_config.BROWSER_PROCS
    if context == "explorer":
        return proc in user_config.EXPLORER_PROCS
    if context == "editor":
        return proc in user_config.EDITOR_PROCS
    groups = user_config.get_custom_groups()
    if context in groups:
        return proc.lower() in [p.lower() for p in groups[context]]
    return bool(proc) and proc.lower() == context.lower()


# ── Keyboard simulation ────────────────────────────────────────────────────

# Map Windows keyboard shortcut strings to xdotool key names
_KEY_MAP = {
    "ctrl+c":            "ctrl+c",
    "ctrl+v":            "ctrl+v",
    "ctrl+s":            "ctrl+s",
    "ctrl+t":            "ctrl+t",
    "ctrl+l":            "ctrl+l",
    "ctrl+w":            "ctrl+w",
    "enter":             "Return",
    "windows+d":         "super+d",
    "windows+shift+s":   "super+shift+s",
    "windows+down":      "super+Down",
    "next track":        "XF86AudioNext",
    "previous track":    "XF86AudioPrev",
    "play/pause media":  "XF86AudioPlay",
    "super+shift+s":     "super+shift+s",
}


def _xdotool_key(shortcut: str) -> None:
    """Send a key combination using xdotool."""
    mapped = _KEY_MAP.get(shortcut.lower(), shortcut)
    _run("xdotool", "key", "--clearmodifiers", mapped)


def _execute_action(action) -> None:
    """Execute a shortcut string or a macro dict."""
    if isinstance(action, str):
        _xdotool_key(action)
    elif isinstance(action, dict) and action.get("type") == "macro":
        repeat = max(1, int(action.get("repeat", 1)))
        for _ in range(repeat):
            for step in action.get("steps", []):
                stype = step.get("type", "press")
                if stype == "press":
                    keys = step.get("keys", "")
                    if keys:
                        _xdotool_key(keys)
                elif stype == "wait":
                    time.sleep(max(0, step.get("ms", 100)) / 1000.0)


# ── Audio control ──────────────────────────────────────────────────────────

def change_volume(direction: str, step_word: str) -> None:
    pct = _VOLUME_STEPS.get(step_word)
    if pct is None:
        print(f"  Unknown step '{step_word}'")
        return
    sign = "+" if direction == "up" else "-"
    _run("pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{pct}%")
    arrow = "  Volume up" if direction == "up" else "  Volume down"
    print(f"{arrow} {pct}%")
    _status(f"Volume {'up' if direction == 'up' else 'down'} {pct}%")


def toggle_mute() -> None:
    _run("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle")
    print("  Toggle mute")
    _status("Mute toggled")


def switch_audio(name: str) -> None:
    dev = _AUDIO_DEVICES.get(name)
    if not dev or not dev.get("id"):
        print(f"  No audio device set up for '{name}'")
        return
    if audio_devices.set_default_output(dev["id"]):
        label = dev.get("name", name)
        print(f"  Switched audio to {name}  ({label})")
        _status(f"Audio -> {name.title()}")
    else:
        print(f"  Couldn't switch audio to '{name}'")


# ── Media ──────────────────────────────────────────────────────────────────

def _play_in_app(app_name: str) -> bool:
    """Send XF86AudioPlay to the app's window directly."""
    try:
        wids = _wids_for_app(app_name)
        if not wids:
            return False
        wid = wids[0]
        _run("xdotool", "key", "--window", wid, "XF86AudioPlay")
        print(f"  XF86AudioPlay -> {app_name} (wid {wid})")
        return True
    except Exception as e:
        print(f"  WM key failed: {e}")
        return False


# ── Window control ─────────────────────────────────────────────────────────

def _set_foreground(wid: str) -> None:
    """Raise and focus a window by its id."""
    try:
        _run("xdotool", "windowactivate", "--sync", wid)
    except Exception as e:
        print(f"  Warning: couldn't bring window to foreground ({e})")


def _get_work_area() -> tuple[int, int, int, int]:
    """Return (x, y, w, h) of the primary monitor work area."""
    try:
        # Try xrandr for primary display geometry
        out = _run("xrandr", "--query")
        for line in out.splitlines():
            if " connected primary" in line or (" connected" in line and "primary" not in out):
                import re
                m = re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)", line)
                if m:
                    w, h, x, y = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
                    # Subtract typical taskbar height (40px) from bottom
                    return x, y, w, h - 40
    except Exception:
        pass
    # Fallback: use wmctrl workarea
    try:
        out = _run("wmctrl", "-d")
        for line in out.splitlines():
            parts = line.split()
            # wmctrl -d: id  * DG WxH  VP x,y  WA x,y WxH  title
            for i, p in enumerate(parts):
                if p == "WA":
                    pos = parts[i + 1].rstrip(",").split(",")
                    size = parts[i + 2].split("x")
                    return int(pos[0]), int(pos[1]), int(size[0]), int(size[1])
    except Exception:
        pass
    return 0, 0, 1920, 1040


def _apply_snap(wid: str, position: str) -> None:
    """Snap a window to a position using wmctrl."""
    wx, wy, ww, wh = _get_work_area()
    hw, hh = ww // 2, wh // 2

    coords: dict[str, tuple[int, int, int, int]] = {
        "left":         (wx,       wy,       hw,  wh),
        "right":        (wx + hw,  wy,       hw,  wh),
        "top left":     (wx,       wy,       hw,  hh),
        "top right":    (wx + hw,  wy,       hw,  hh),
        "bottom left":  (wx,       wy + hh,  hw,  hh),
        "bottom right": (wx + hw,  wy + hh,  hw,  hh),
    }

    # Unmaximise first
    _run("wmctrl", "-ir", wid, "-b", "remove,maximized_vert,maximized_horz")
    time.sleep(0.05)

    if position == "fullscreen":
        _run("wmctrl", "-ir", wid, "-b", "add,maximized_vert,maximized_horz")
    elif position in coords:
        x, y, w, h = coords[position]
        # wmctrl -e: gravity,x,y,w,h  (gravity 0 = no change)
        _run("wmctrl", "-ir", wid, "-e", f"0,{x},{y},{w},{h}")


SNAP_POSITIONS: set[str] = {
    "left", "right", "fullscreen",
    "top left", "top right",
    "bottom left", "bottom right",
}

_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
}


def snap_app(app_name: str | None, position: str) -> None:
    if position not in SNAP_POSITIONS:
        print(f"  Unknown position '{position}'")
        return

    if app_name is None:
        wid = _get_active_wid()
    elif app_name not in APPS:
        print(f"  Don't know '{app_name}'")
        return
    else:
        wids = _wids_for_app(app_name)
        if not wids:
            print(f"  Couldn't find a window for '{app_name}'")
            return
        wid = wids[0]
        _set_foreground(wid)
        time.sleep(0.1)

    if wid:
        _apply_snap(wid, position)
    label = app_name or "current window"
    print(f"  Snapped {label} to {position}!")
    _status(f"Moved {label} -> {position}")


def send_to_background(app_name: str | None = None) -> None:
    """Lower a window to the bottom of the z-order."""
    if app_name:
        if app_name not in APPS:
            print(f"  Don't know '{app_name}'")
            return
        wids = _wids_for_app(app_name)
        wid = wids[0] if wids else None
        label = app_name
    else:
        wid = _get_active_wid()
        label = "current window"
    if not wid:
        print(f"  Couldn't find window for '{app_name or 'current'}'")
        return
    _run("xdotool", "windowlower", wid)
    print(f"  Sent {label} to background!")
    _status(f"{label.title()} -> background")


def minimise_app(app_name: str | None = None) -> None:
    if app_name:
        if app_name not in APPS:
            print(f"  Don't know '{app_name}'")
            return
        if _is_self_app(app_name) and _self_window_cb:
            _self_window_cb("minimise")
            print(f"  Minimised {app_name}!")
            _status(f"Minimising {app_name}")
            return
        wids = _wids_for_app(app_name)
        if wids:
            for wid in wids:
                _run("xdotool", "windowminimize", wid)
            print(f"  Minimised {app_name}!")
            _status(f"Minimising {app_name}")
        else:
            print(f"  Couldn't find a window for '{app_name}'")
    else:
        wid = _get_active_wid()
        if wid:
            _run("xdotool", "windowminimize", wid)
            print("  Minimised current window!")
            _status("Minimising current window")


# ── Pending-close state ────────────────────────────────────────────────────
_pending_close: dict | None = None
_pending_cancel = _threading.Event()


def _commit_close(app_name: str, wids: list[str]) -> None:
    global _pending_close
    _pending_close = None
    # Kill all matching processes
    pattern = PROC_NAMES.get(app_name, "")
    if pattern:
        for pid in _pids_for_proc(pattern):
            try:
                psutil.Process(pid).terminate()
            except Exception:
                pass
    elif wids:
        for wid in wids:
            _run("wmctrl", "-ic", wid)
    print(f"  Closed {app_name}!")


def close_app(app_name: str) -> None:
    global _pending_close
    if app_name not in APPS:
        print(f"  Don't know '{app_name}'")
        return

    if _pending_close is not None:
        _pending_cancel.set()

    delay = user_config.get_close_delay()
    wids = _wids_for_app(app_name)
    if not wids and not PROC_NAMES.get(app_name):
        print(f"  Couldn't find a window for '{app_name}'")
        return

    # Minimise so user sees something happened
    for wid in wids:
        _run("xdotool", "windowminimize", wid)

    _pending_cancel.clear()
    _pending_close = {"app": app_name, "wids": wids}

    print(f"  Closing {app_name} in {delay}s -- say 'undo' to cancel!")
    _status(f"Closing {app_name} in {delay}s  --  say '{_cw('undo')}' to cancel")

    def _timer():
        global _pending_close
        cancelled = _pending_cancel.wait(timeout=delay)
        if not cancelled and _pending_close and _pending_close["app"] == app_name:
            _commit_close(app_name, wids)

    t = _threading.Thread(target=_timer, daemon=True)
    t.start()
    _pending_close["timer"] = t


def undo_close() -> None:
    global _pending_close
    if _pending_close is None:
        print("  Nothing to undo.")
        return
    app_name = _pending_close["app"]
    wids = _pending_close["wids"]
    _pending_cancel.set()
    _pending_close = None
    for wid in wids:
        try:
            _run("xdotool", "windowactivate", "--sync", wid)
        except Exception:
            pass
    print(f"  Cancelled close -- {app_name} restored!")
    _status(f"Undo -- {app_name} restored")


# ── Launching / opening apps ───────────────────────────────────────────────

def _is_url(path: str) -> bool:
    return "://" in path or path.startswith("ms-")

def _is_folder(path: str) -> bool:
    return pathlib.Path(path).is_dir()


def _launch(app_name: str) -> None:
    if app_name in APPS:
        path = APPS[app_name]
        if _is_url(path):
            import webbrowser
            webbrowser.open(path)
        elif _is_folder(path):
            subprocess.Popen(["xdg-open", path])
        elif path.startswith("/") or path.startswith("~"):
            # Absolute path to an executable
            subprocess.Popen([os.path.expanduser(path)])
        else:
            # Bare command / .desktop app name
            try:
                subprocess.Popen(["gtk-launch", path])
            except Exception:
                subprocess.Popen([path], shell=True)
    else:
        print(f"  Don't know how to open '{app_name}'")
        return
    print(f"  Opened {app_name}!")
    _status(f"Opening {app_name}")


def open_or_focus(app_name: str) -> None:
    if app_name not in APPS:
        print(f"  Don't know '{app_name}'")
        return
    if _is_self_app(app_name) and _self_window_cb:
        _self_window_cb("restore")
        print(f"  Focused {app_name}!")
        _status(f"Focusing {app_name}")
        return

    path = APPS[app_name]
    if _is_url(path) or _is_folder(path):
        _launch(app_name)
        return

    wids = _wids_for_app(app_name)
    if wids:
        _set_foreground(wids[0])
        print(f"  Focused {app_name}!")
        _status(f"Focusing {app_name}")
        return

    _launch(app_name)


def open_and_snap(app_name: str, position: str) -> None:
    if app_name not in APPS:
        print(f"  Don't know '{app_name}'")
        return
    if position not in SNAP_POSITIONS:
        print(f"  Unknown position '{position}'")
        return

    needs_launch = not _wids_for_app(app_name)
    if needs_launch:
        _launch(app_name)
        print(f"  Waiting for {app_name} to start...")
        time.sleep(2.5)

    snap_app(app_name, position)


# ── Layouts ────────────────────────────────────────────────────────────────

def _app_for_proc(proc: str) -> "str | None":
    proc = (proc or "").lower()
    if not proc:
        return None
    for app, pattern in PROC_NAMES.items():
        p = (pattern or "").lower()
        if p.endswith("*"):
            if proc.startswith(p[:-1]):
                return app
        elif proc == p:
            return app
    return None


def save_layout(n: int) -> None:
    """Snapshot open windows belonging to configured apps into layout *n*."""
    entries: list = []
    seen_apps: dict = {}

    try:
        out = _run("wmctrl", "-lGp")
        for line in out.splitlines():
            parts = line.split(None, 7)
            if len(parts) < 7:
                continue
            wid  = parts[0]
            pid  = int(parts[2]) if parts[2].isdigit() else 0
            x, y, w, h = int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6].split()[0])
            if pid <= 0:
                continue
            try:
                proc = psutil.Process(pid).name().lower()
            except Exception:
                continue
            app = _app_for_proc(proc)
            if not app:
                continue
            # Check if window is minimised via xdotool
            winfo = _run("xdotool", "getwindowgeometry", "--shell", wid)
            minimised = "X=-1" in winfo or "Y=-1" in winfo
            entries.append({
                "app": app,
                "minimised": minimised,
                "x": x, "y": y, "w": w, "h": h,
            })
            seen_apps[app] = seen_apps.get(app, 0) + 1
    except Exception as e:
        print(f"  Layout save error: {e}")

    user_config.set_layout(n, entries)
    apps = ", ".join(sorted(seen_apps)) or "nothing"
    print(f"  Saved layout {n}  ({len(entries)} window(s): {apps})")
    _status(f"Saved layout {n}")


def restore_layout(n: int) -> None:
    entries = user_config.get_layout(n)
    if not entries:
        print(f"  Layout {n} is empty -- say 'save layout {n}' first.")
        _status(f"Layout {n} is empty")
        return

    print(f"  Restoring layout {n}  ({len(entries)} window(s))...")
    _status(f"Restoring layout {n}")

    def _worker():
        needed = []
        for e in entries:
            if e["app"] not in needed:
                needed.append(e["app"])
        launched = False
        for app in needed:
            if app in APPS and not _wids_for_app(app):
                try:
                    open_or_focus(app)
                    launched = True
                except Exception as ex:
                    print(f"  couldn't open {app}: {ex}")
        if launched:
            time.sleep(2.5)

        used: set = set()
        placed = 0
        for e in entries:
            wids = _wids_for_app(e["app"])
            target = next((w for w in wids if w not in used), None)
            if target is None:
                continue
            used.add(target)
            try:
                _run("wmctrl", "-ir", target, "-b",
                     "remove,maximized_vert,maximized_horz")
                if e.get("minimised"):
                    _run("xdotool", "windowminimize", target)
                else:
                    x, y, w, h = e["x"], e["y"], e["w"], e["h"]
                    _run("wmctrl", "-ir", target, "-e",
                         f"0,{x},{y},{w},{h}")
                    _set_foreground(target)
                placed += 1
            except Exception as ex:
                print(f"  couldn't place {e['app']}: {ex}")

        print(f"  Layout {n} restored  ({placed}/{len(entries)} window(s) placed)")
        _status(f"Layout {n} restored")

    _threading.Thread(target=_worker, daemon=True).start()


# ── Context commands ───────────────────────────────────────────────────────

def _try_context_command(text: str) -> bool:
    cmds = _active_context_commands()
    if text not in cmds:
        return False
    proc    = _get_active_proc()
    targets = cmds[text]
    for context, action in targets.items():
        if _proc_matches_context(proc, context):
            try:
                _execute_action(action)
            except Exception as _ae:
                print(f"  Action error ({text!r}): {_ae}")
            preview = action if isinstance(action, str) else "macro"
            print(f"  {text}  [{context}]  -> {preview}")
            _status(f"{text.title()}  [{context}]")
            return True
    contexts = " / ".join(targets.keys())
    print(f"  '{text}' only works in: {contexts}  (active: {proc or 'unknown'})")
    return True


def _try_specific_context(text: str) -> bool:
    cmds = _active_context_commands()
    if text not in cmds:
        return False
    proc    = _get_active_proc()
    targets = cmds[text]
    for context, action in targets.items():
        if context == "any":
            continue
        if _proc_matches_context(proc, context):
            try:
                _execute_action(action)
            except Exception as _ae:
                print(f"  Action error ({text!r}): {_ae}")
            preview = action if isinstance(action, str) else "macro"
            print(f"  {text}  [{context}]  -> {preview}  (overrides default)")
            _status(f"{text.title()}  [{context}]")
            return True
    return False


# ── Diagnostic ─────────────────────────────────────────────────────────────

def print_diagnostic() -> None:
    print("\n-- Window diagnostic --")
    for app_name, pattern in PROC_NAMES.items():
        pids = _pids_for_proc(pattern)
        if not pids:
            print(f"  {app_name:14s}  x  '{pattern}' not running")
        else:
            wids = _wids_for_app(app_name)
            if not wids:
                print(f"  {app_name:14s}  !  process running but no windows found")
            else:
                print(f"  {app_name:14s}  ok  {len(wids)} win(s)")
    print("--\n")


# ── Grammar ────────────────────────────────────────────────────────────────

def build_grammar(active_proc: str = "") -> str:
    words = ["[unk]"]
    groups = _active_groups()

    for key in ("undo", "diagnose", "stop_engine", "restart_engine"):
        words.extend(_cw_all(key))
    for mw in _cw_all("set_mode"):
        for mode in _mode_names():
            words.append(f"{mw} {mode}")

    if "media" in groups:
        for key in ("skip", "previous", "rewind", "play_pause", "mute"):
            words.extend(_cw_all(key))
        words.append("play")
        _play_words = list(dict.fromkeys(_cw_all("play_pause") + ["play"]))
        for pw in _play_words:
            for app in APPS:
                for sp in _spoken_all(app):
                    words.append(f"{pw} {sp}")
        for step in _VOLUME_STEPS:
            words.append(f"volume up {step}")
            words.append(f"volume down {step}")

    if "keyboard" in groups:
        for key in ("copy", "paste", "save", "enter"):
            words.extend(_cw_all(key))

    if "apps" in groups:
        for ow in _cw_all("open"):
            words.append(ow)
            words.append(f"{ow} all")
            for app in APPS:
                for sp in _spoken_all(app):
                    words.append(f"{ow} {sp}")
                    words.append(f"{ow} new {sp}")
                    for pos in SNAP_POSITIONS:
                        words.append(f"{ow} {sp} {pos}")
        for mw in _cw_all("minimise"):
            words.append(mw)
            words.append(f"{mw} all")
            for app in APPS:
                for sp in _spoken_all(app):
                    words.append(f"{mw} {sp}")
        for xw in _cw_all("maximise"):
            words.append(xw)
            for app in APPS:
                for sp in _spoken_all(app):
                    words.append(f"{xw} {sp}")
        for cw in _cw_all("close"):
            words.append(cw)
            words.append(f"{cw} current")
            for app in APPS:
                for sp in _spoken_all(app):
                    words.append(f"{cw} {sp}")
        for mvw in _cw_all("move"):
            for pos in SNAP_POSITIONS:
                words.append(f"{mvw} {pos}")
            words.append(f"{mvw} to background")
            for app in APPS:
                for sp in _spoken_all(app):
                    for pos in SNAP_POSITIONS:
                        words.append(f"{mvw} {sp} {pos}")
                    words.append(f"{mvw} {sp} to background")
        for app in APPS:
            for sp in _spoken_all(app):
                words.append(sp)

    if "layouts" in groups:
        for nw in _NUMBER_WORDS:
            for sw in _cw_all("save"):
                words.append(f"{sw} layout {nw}")
            for ow in _cw_all("open"):
                words.append(f"{ow} layout {nw}")

    if "audio" in groups:
        for cw in _cw_all("switch_audio"):
            for dev_name in _AUDIO_DEVICES:
                words.append(f"{cw} {dev_name}")

    for phrase, targets in _active_context_commands().items():
        for context in targets:
            if context == "any" or _proc_matches_context(active_proc, context):
                words.append(phrase)
                break

    seen = set(); out = []
    for w in words:
        if w not in seen:
            seen.add(w); out.append(w)
    return json.dumps(out)


def _early_fire_set(grammar_json: str) -> set:
    try:
        phrases = set(json.loads(grammar_json))
    except Exception:
        return set()
    phrases.discard("[unk]")
    for key in ("open", "close", "minimise", "maximise", "move", "merge"):
        for v in _cw_all(key):
            phrases.discard(v)
    return phrases


def _prefix_fire_set(grammar_json: str, early_set: set) -> set:
    try:
        all_phrases = [p for p in json.loads(grammar_json) if p != "[unk]"]
    except Exception:
        return set()
    out = set()
    for p in early_set:
        pfx = p + " "
        if any(q != p and q.startswith(pfx) for q in all_phrases):
            out.add(p)
    return out


_APP_SETTLE_EXTRA = 0.12

def _app_forms_set() -> set:
    return {sp.lower() for a in APPS for sp in _spoken_all(a)}

def _phrase_has_app(phrase: str, app_forms: set) -> bool:
    parts = phrase.split()
    for i in range(len(parts)):
        for n in (3, 2, 1):
            if i + n <= len(parts) and " ".join(parts[i:i + n]) in app_forms:
                return True
    return False


_NULL_BARE_KEYS = ("open", "close", "move")

def _is_null_bare(text: str) -> bool:
    for key in _NULL_BARE_KEYS:
        if text in _cw_all(key):
            return True
    return False


def _command_trigger_words() -> set:
    keys = ("skip", "previous", "rewind", "play_pause", "mute", "copy", "paste",
            "save", "enter", "undo", "diagnose", "stop_engine", "restart_engine",
            "open", "close", "minimise", "maximise", "move", "merge")
    s = set()
    for k in keys:
        s.update(_cw_all(k))
    s.add("play")
    return s


def _build_cmd_timing() -> dict:
    out = {}
    for key, ms in (_WORD_DELAYS or {}).items():
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            continue
        if ms > 0:
            for w in _cw_all(key):
                out[w] = ms / 1000.0
    for phrase, ms in (_CONTEXT_DELAYS or {}).items():
        try:
            ms = int(ms)
        except (TypeError, ValueError):
            continue
        if ms > 0:
            out[phrase.strip().lower()] = ms / 1000.0
    return out


def average_confidence(result: dict) -> float:
    words = result.get("result", [])
    if not words:
        return 0.0
    return sum(w.get("conf", 0.0) for w in words) / len(words)


def _parse_app(words: list[str], start: int) -> tuple[str | None, list[str]]:
    for length in range(min(3, len(words) - start), 0, -1):
        candidate = " ".join(words[start : start + length])
        if candidate in APPS:
            return candidate, words[start + length:]
        if candidate in _SPOKEN_TO_DISPLAY:
            display = _SPOKEN_TO_DISPLAY[candidate]
            if display in APPS:
                return display, words[start + length:]
    return None, words[start:]


last_command = None
last_command_time = 0


def handle_command(text: str) -> bool:
    global last_command, last_command_time
    if not text:
        return False
    words = text.split()
    now = time.time()

    if text == last_command and (now - last_command_time) < COOLDOWN:
        return False
    last_command = text
    last_command_time = now

    for _smw in _cw_all("set_mode"):
        if text.startswith(_smw + " "):
            target = text[len(_smw) + 1:].strip()
            if target in _mode_names():
                set_active_mode(target)
            else:
                print(f"  No mode called '{target}'")
            return False

    if _try_specific_context(text):
        return False

    if len(words) == 3 and words[1] == "layout" and words[2] in _NUMBER_WORDS:
        num = _NUMBER_WORDS[words[2]]
        if words[0] in _cw_all("save"):
            save_layout(num)
            return False
        if words[0] in _cw_all("open"):
            restore_layout(num)
            return False

    for _aw in _cw_all("switch_audio"):
        if text.startswith(_aw + " "):
            target = text[len(_aw) + 1:].strip()
            if target in _AUDIO_DEVICES:
                switch_audio(target)
                return False

    if text in _cw_all("skip"):
        print("  Skipping track!")
        _status("Skipping track")
        _xdotool_key("next track")
    elif text in _cw_all("previous"):
        print("  Previous track!")
        _status("Previous track")
        _xdotool_key("previous track")
    elif text in _cw_all("rewind"):
        print("  Restarting track!")
        _status("Restarting track")
        _xdotool_key("previous track")
        time.sleep(0.05)
        _xdotool_key("previous track")
    elif text in _cw_all("play_pause") or text == "play" or (
            text.split()[0] in (_cw_all("play_pause") + ["play"])
            and len(text.split()) > 1):
        words_l = text.split()
        if len(words_l) > 1:
            app, _ = _parse_app(words_l, 1)
            if app:
                print(f"  Play {app}!")
                _status(f"Play {app.title()}")
                open_or_focus(app)
                time.sleep(1.2)
                if not _play_in_app(app):
                    _xdotool_key("play/pause media")
            else:
                print("  Toggling playback!")
                _status("Play / Pause")
                _xdotool_key("play/pause media")
        else:
            print("  Toggling playback!")
            _status("Play / Pause")
            _xdotool_key("play/pause media")
    elif text in _cw_all("copy"):
        print("  Copy!")
        _status("Copy")
        _xdotool_key("ctrl+c")
    elif text in _cw_all("paste"):
        print("  Paste!")
        _status("Paste")
        _xdotool_key("ctrl+v")
    elif text in _cw_all("save"):
        print("  Save!")
        _status("Save")
        _xdotool_key("ctrl+s")
    elif text in _cw_all("enter"):
        print("  Enter!")
        _status("Enter")
        _xdotool_key("enter")
    elif text in _cw_all("undo"):
        undo_close()
    elif text in _cw_all("stop_engine"):
        print("  Closing Echo!")
        _status("Stopping Echo")
        _stop_event.set()
    elif text in _cw_all("restart_engine"):
        print("  Restarting Echo!")
        _status("Restarting Echo")
        _restart_requested = True
        _stop_event.set()
    elif words[0] == "volume" and len(words) == 3 and words[1] in ("up", "down"):
        change_volume(words[1], words[2])
    elif text in _cw_all("mute"):
        toggle_mute()
    elif text in _cw_all("diagnose"):
        _status("Running diagnostic")
        print_diagnostic()
    elif words[0] in _cw_all("move"):
        if len(words) < 2:
            print(f"  Say '{_cw('move')}' followed by an app name and/or position")
        elif words[-2:] == ["to", "background"]:
            app_words = words[1:-2]
            if app_words:
                app, _ = _parse_app(words[:-2], 1)
                send_to_background(app) if app else send_to_background(None)
            else:
                send_to_background(None)
        else:
            app, rest = _parse_app(words, 1)
            if app:
                snap_app(app, " ".join(rest))
            else:
                snap_app(None, " ".join(words[1:]))
    elif words[0] in _cw_all("open"):
        if len(words) == 1:
            print(f"  Say '{_cw('open')}' followed by an app name")
        elif words[1] == "all":
            _xdotool_key("windows+d")
            print("  Showing all windows!")
            _status("Show all windows")
        elif words[1] == "new":
            if len(words) > 2:
                app, _ = _parse_app(words, 2)
                _launch(app) if app else print(f"  Say '{_cw('open')} new' followed by an app name")
            else:
                print(f"  Say '{_cw('open')} new' followed by an app name")
        else:
            app, rest = _parse_app(words, 1)
            if app:
                position = " ".join(rest)
                if position in SNAP_POSITIONS:
                    open_and_snap(app, position)
                else:
                    open_or_focus(app)
            else:
                print(f"  Don't know '{' '.join(words[1:])}'")
    elif words[0] in _cw_all("minimise"):
        if len(words) > 1:
            if words[1] == "all":
                _xdotool_key("super+d")
                print("  Minimised all windows!")
                _status("Minimise all windows")
            else:
                app, _ = _parse_app(words, 1)
                minimise_app(app) if app else minimise_app()
        else:
            minimise_app()
    elif words[0] in _cw_all("maximise"):
        app, _ = _parse_app(words, 1) if len(words) > 1 else (None, [])
        snap_app(app, "fullscreen")
    elif words[0] in _cw_all("close") and len(words) > 1 and words[1] == "current":
        _xdotool_key("ctrl+w")
        print("  Closed current tab!")
        _status("Close current tab")
    elif words[0] in _cw_all("close"):
        if len(words) > 1:
            app, _ = _parse_app(words, 1)
            close_app(app) if app else print(f"  Say '{_cw('close')}' followed by an app name")
        else:
            print(f"  Say '{_cw('close')}' followed by an app name")
    elif _try_context_command(text):
        pass
    return False


# ── ENGINE ─────────────────────────────────────────────────────────────────
_stop_event        = _threading.Event()
_restart_requested = False

_SMALL_MODEL_NAME = "vosk-model-small-en-us-0.15"
_listen_model = None


def listen_once(seconds: float = 2.0, on_start=None) -> str:
    global _listen_model
    if _listen_model is None:
        _listen_model = Model(user_config.get_model_path())
    rec = KaldiRecognizer(_listen_model, SAMPLE_RATE)
    rec.SetWords(True)

    pa = pyaudio.PyAudio()
    stream = pa.open(format=pyaudio.paInt16, channels=1, rate=SAMPLE_RATE,
                     input=True, frames_per_buffer=FRAMES_PER_BUFFER)
    try:
        stream.start_stream()
        if on_start:
            try: on_start()
            except Exception: pass
        needed = int(SAMPLE_RATE * max(0.2, seconds))
        read = 0
        while read < needed:
            data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
            rec.AcceptWaveform(data)
            read += FRAMES_PER_BUFFER
    finally:
        try:
            stream.stop_stream(); stream.close()
        except Exception:
            pass
        pa.terminate()
    return json.loads(rec.FinalResult()).get("text", "").strip().lower()


def _dual_model_filter(main_text: str, ref_text: str) -> tuple[str, str | None]:
    if not ref_text or not main_text:
        return main_text, None
    main_words = main_text.split()
    ref_words  = ref_text.split()
    if len(main_words) <= 1:
        return main_text, None
    if ref_words[0] == main_words[1] and main_words[1] in _command_trigger_words():
        stripped = " ".join(main_words[1:])
        return stripped, main_words[0]
    return main_text, None


def run(stop_event: _threading.Event | None = None) -> bool:
    global APPS, PROC_NAMES, MODEL_PATH, _stop_event, _restart_requested
    global CONFIDENCE_THRESHOLD, COOLDOWN, _COMMAND_WORDS, _VOLUME_STEPS, _CONTEXT_COMMANDS
    global _SPOKEN_NAMES, _SPOKEN_TO_DISPLAY, PARTIAL_STABLE_SECS, _WORD_DELAYS
    global _AUDIO_DEVICES, _CONTEXT_DELAYS, _MODES, _ACTIVE_MODE
    _cfg                 = user_config.load()
    MODEL_PATH           = user_config.get_model_path()
    _MODES               = user_config.get_modes()
    _ACTIVE_MODE         = "default"
    APPS                 = _cfg.get("APPS", APPS)
    PROC_NAMES           = _cfg.get("PROC_NAMES", PROC_NAMES)
    CONFIDENCE_THRESHOLD = user_config.get_confidence_threshold()
    COOLDOWN             = user_config.get_cooldown()
    PARTIAL_STABLE_SECS  = user_config.get_response_delay()
    _WORD_DELAYS         = user_config.get_word_delays()
    _CONTEXT_DELAYS      = user_config.get_context_delays()
    _AUDIO_DEVICES       = user_config.get_audio_devices()
    _COMMAND_WORDS       = user_config.get_command_words()
    _VOLUME_STEPS        = user_config.get_volume_steps()
    _CONTEXT_COMMANDS    = user_config.get_context_commands()
    _spoken_raw          = user_config.get_spoken_names()
    _SPOKEN_NAMES        = _spoken_raw
    _SPOKEN_TO_DISPLAY   = {}
    for _disp, _raw in _spoken_raw.items():
        for _alias in (_raw or "").split(","):
            _alias = _alias.strip()
            if _alias:
                _SPOKEN_TO_DISPLAY[_alias] = _disp

    if stop_event is None:
        stop_event = _threading.Event()
    _stop_event        = stop_event
    _restart_requested = False

    print("Loading model...")
    model   = Model(MODEL_PATH)
    grammar = build_grammar(_get_active_proc())
    rec     = KaldiRecognizer(model, SAMPLE_RATE, grammar)
    rec.SetWords(True)

    rec_ref   = None
    model_ref = None
    _ref_last_text = ""

    small_path = pathlib.Path(MODEL_PATH).parent / _SMALL_MODEL_NAME
    dual_enabled = user_config.get_dual_model_check()
    if dual_enabled and small_path.exists() and pathlib.Path(MODEL_PATH).name != _SMALL_MODEL_NAME:
        try:
            print(f"Loading reference model ({_SMALL_MODEL_NAME})...")
            model_ref = Model(str(small_path))
            rec_ref   = KaldiRecognizer(model_ref, SAMPLE_RATE, grammar)
            print("  Dual-model ghost check active.")
        except Exception as _e:
            print(f"  Could not load reference model: {_e}")
            rec_ref = None

    print_diagnostic()

    p = pyaudio.PyAudio()
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=FRAMES_PER_BUFFER,
    )
    stream.start_stream()

    print("Listening...")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD:.0%}")
    print("Say 'diagnose' at any time to recheck running apps.\n")

    _current_grammar = [grammar]
    _pending_grammar = [None]

    def _grammar_watcher():
        while not stop_event.is_set():
            proc        = _get_active_proc()
            new_grammar = build_grammar(proc)
            if new_grammar != _current_grammar[0]:
                _current_grammar[0] = new_grammar
                _pending_grammar[0] = (new_grammar, proc)
            stop_event.wait(0.8)

    _threading.Thread(target=_grammar_watcher, daemon=True).start()

    _early_set     = _early_fire_set(grammar)
    _prefix_set    = _prefix_fire_set(grammar, _early_set)
    _cmd_timing    = _build_cmd_timing()
    _app_forms     = _app_forms_set()
    _partial_text  = ""
    _partial_since = 0.0

    try:
        while not stop_event.is_set():
            pend = _pending_grammar[0]
            if pend is not None:
                _pending_grammar[0] = None
                new_grammar, proc = pend
                try:
                    rec = KaldiRecognizer(model, SAMPLE_RATE, new_grammar)
                    rec.SetWords(True)
                    if rec_ref is not None and model_ref is not None:
                        rec_ref = KaldiRecognizer(model_ref, SAMPLE_RATE, new_grammar)
                        _ref_last_text = ""
                    _early_set    = _early_fire_set(new_grammar)
                    _prefix_set   = _prefix_fire_set(new_grammar, _early_set)
                    _partial_text = ""
                    print(f"  Grammar updated for '{proc or 'unknown'}'")
                except Exception as _ge:
                    print(f"  Grammar update failed: {_ge}")

            data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)

            if rec_ref is not None:
                if rec_ref.AcceptWaveform(data):
                    r = json.loads(rec_ref.Result())
                    t = r.get("text", "").strip().lower()
                    if t:
                        _ref_last_text = t

            if rec.AcceptWaveform(data):
                _partial_text = ""
                result = json.loads(rec.Result())
                text   = result.get("text", "").strip().lower()
                if not text or text == "[unk]":
                    continue

                noise_word = None
                if rec_ref is not None:
                    ref_partial = json.loads(
                        rec_ref.PartialResult()
                    ).get("partial", "").strip().lower()
                    ref  = ref_partial or _ref_last_text
                    text, noise_word = _dual_model_filter(text, ref)
                    if not text:
                        continue

                if _is_null_bare(text):
                    continue

                conf = average_confidence(result)
                if conf >= CONFIDENCE_THRESHOLD:
                    notes = []
                    if noise_word: notes.append(f"noise filter removed '{noise_word}'")
                    note_str = f"  [{', '.join(notes)}]" if notes else ""
                    print(f"  '{text}'{note_str}")
                    if handle_command(text):
                        rec.Reset()
                        if rec_ref is not None:
                            rec_ref.Reset()
                            _ref_last_text = ""
                else:
                    print(f"  Low confidence ({conf:.0%}): ignored")
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "").strip().lower()
                tnow = time.time()
                if partial != _partial_text:
                    _partial_text  = partial
                    _partial_since = tnow
                elif partial:
                    if _is_null_bare(partial):
                        required = None
                    elif partial in _cmd_timing:
                        required = _cmd_timing[partial]
                    elif partial in _early_set:
                        required = PARTIAL_STABLE_SECS
                        if (_phrase_has_app(partial, _app_forms)
                                or partial in _prefix_set):
                            required += _APP_SETTLE_EXTRA
                    else:
                        required = None
                    if required is not None and (tnow - _partial_since) >= required:
                        print(f"  '{partial}'")
                        handle_command(partial)
                        rec.Reset()
                        if rec_ref is not None:
                            rec_ref.Reset()
                            _ref_last_text = ""
                        _partial_text = ""
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

    return _restart_requested


if __name__ == "__main__":
    while run():
        print("Restarting...\n")
