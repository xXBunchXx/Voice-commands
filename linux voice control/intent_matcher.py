"""LLM intent matching for the open-dictionary recognition mode.

The engine runs Vosk WITHOUT a grammar (full dictionary), so the transcript is
free-form and often imperfect.  This module hands that transcript, plus the list
of *valid* command phrases (straight from build_grammar), to a small local LLM
(via Ollama) whose only job is to decide:

  * which allowed command the user most likely meant, OR
  * that it was not a command at all (background talk, a call, a movie, ...).

The LLM is constrained to return strict JSON and can only choose from the
candidate list -- it never invents an action.  Everything fails OPEN: any error,
timeout, or unparseable answer returns None so the engine simply does nothing
rather than misfiring or going silent.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error


def _norm_url(url: str) -> str:
    """Force 127.0.0.1 instead of 'localhost'.  On some systems, resolving
    localhost tries IPv6 (::1) first and stalls ~2s before falling back to IPv4
    -- using the literal IPv4 address makes every request ~10x faster."""
    u = (url or "http://127.0.0.1:11434").strip().rstrip("/")
    return u.replace("//localhost:", "//127.0.0.1:").replace(
        "//localhost/", "//127.0.0.1/")


_SYSTEM = (
    "You map a possibly-misheard speech transcript to a voice command.\n"
    "You are given a list of ALLOWED commands. Decide which single allowed "
    "command the user most likely intended, correcting for speech-to-text "
    "errors (homophones, split/merged words, missing small words).\n"
    "Pick the MOST SPECIFIC matching command: if the transcript names an app or "
    "target (e.g. 'minimise firefox', 'close spotify'), you MUST choose the "
    "command that includes that app name -- never drop it and return only the "
    "bare verb.\n"
    "If the transcript is NOT a command -- e.g. conversation, thinking out loud, "
    "a movie/music playing, or talking to another person -- return null.\n"
    "Only ever choose a command from the allowed list, copied EXACTLY. Never "
    "invent or reword a command.\n"
    'Reply with STRICT JSON only: {"command": <exact allowed command or null>, '
    '"confidence": <0-1>}. No prose.'
)


def _upgrade_specificity(cmd: str, transcript: str, allowed: set) -> str:
    """If the LLM returned a less-specific command (e.g. the bare verb
    'minimise') but the transcript actually names a target that forms a longer
    valid command ('minimise firefox'), prefer the longer command."""
    words = set(transcript.split())
    base_len = len(cmd.split())
    best = cmd
    best_len = base_len
    prefix = cmd + " "
    for c in allowed:
        if c == cmd or not c.startswith(prefix):
            continue
        extra = c.split()[base_len:]
        if extra and all(tok in words for tok in extra) and len(c.split()) > best_len:
            best, best_len = c, len(c.split())
    return best


_FILLER = {"please", "now", "that", "it", "the", "a", "just", "thanks",
           "thank", "you", "can", "could", "would", "okay", "ok"}


def quick_match(transcript: str, candidates) -> str | None:
    """Deterministic, zero-latency match used BEFORE the LLM."""
    allowed = candidates if isinstance(candidates, set) else set(candidates)
    t = " ".join((transcript or "").split())
    if not t:
        return None
    if t in allowed:
        return t
    words = t.split()
    while words and words[-1] in _FILLER:
        words.pop()
    t2 = " ".join(words)
    if t2 and t2 in allowed:
        return t2
    return None


def warm_up(url: str, model: str, keep_alive: str = "30m") -> None:
    """Preload the model into memory so the first real command isn't slow."""
    payload = {
        "model": model, "prompt": "ok", "stream": False,
        "keep_alive": keep_alive, "options": {"num_predict": 1},
    }
    try:
        req = urllib.request.Request(
            _norm_url(url) + "/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=60).read()
    except Exception:
        pass


def _build_prompt(transcript: str, candidates: list[str]) -> str:
    listing = "\n".join(f"- {c}" for c in candidates)
    return (
        f"ALLOWED COMMANDS:\n{listing}\n\n"
        f'TRANSCRIPT: "{transcript}"\n\n'
        "Which allowed command (exact text) did the user mean, or null if none?"
    )


def match(
    transcript: str,
    candidates: list[str],
    *,
    url: str = "http://127.0.0.1:11434",
    model: str = "llama3.2:3b",
    timeout: float = 8.0,
    min_confidence: float = 0.45,
    keep_alive: str = "30m",
    debug: bool = False,
) -> str | None:
    """Return the exact allowed command phrase the user meant, or None."""
    transcript = (transcript or "").strip()
    if not transcript or not candidates:
        return None

    allowed = set(candidates)
    prompt  = _build_prompt(transcript, candidates)

    payload = {
        "model":  model,
        "system": _SYSTEM,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": keep_alive,
        "options": {
            "temperature": 0.0,
            "num_predict": 48,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    endpoint = _norm_url(url) + "/api/generate"

    try:
        req = urllib.request.Request(
            endpoint, data=body,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        if debug:
            print(f"  [intent] LLM unreachable: {e}")
        return None

    try:
        outer = json.loads(raw)
        inner = json.loads(outer.get("response", "").strip())
    except (json.JSONDecodeError, AttributeError) as e:
        if debug:
            print(f"  [intent] bad JSON from LLM: {e}  raw={raw[:200]!r}")
        return None

    cmd = inner.get("command")
    conf = inner.get("confidence", 1.0)
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 1.0

    if not cmd or not isinstance(cmd, str):
        if debug:
            print(f"  [intent] not a command (transcript={transcript!r})")
        return None

    cmd = cmd.strip().lower()

    if cmd not in allowed:
        norm = {c: c for c in allowed}
        match_exact = norm.get(cmd)
        if match_exact is None:
            if debug:
                print(f"  [intent] LLM returned non-allowed {cmd!r}; ignoring")
            return None
        cmd = match_exact

    if conf < min_confidence:
        if debug:
            print(f"  [intent] below confidence ({conf:.2f}): {cmd!r}")
        return None

    upgraded = _upgrade_specificity(cmd, transcript, allowed)
    if debug:
        if upgraded != cmd:
            print(f"  [intent] {transcript!r} -> {cmd!r} upgraded to "
                  f"{upgraded!r} ({conf:.2f})")
        else:
            print(f"  [intent] {transcript!r} -> {cmd!r} ({conf:.2f})")
    return upgraded


def check_connection(url: str, model: str, timeout: float = 4.0) -> tuple[bool, str]:
    """Lightweight reachability + model-availability probe."""
    endpoint = _norm_url(url) + "/api/tags"
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return False, f"Could not reach Ollama at {url}: {e}"

    names = [m.get("name", "") for m in data.get("models", [])]
    base = model.split(":")[0]
    if any(n == model or n.split(":")[0] == base for n in names):
        return True, f"Connected -- model '{model}' is available."
    return True, (f"Connected to Ollama, but model '{model}' isn't pulled. "
                  f"Run:  ollama pull {model}")
