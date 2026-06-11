"""
Audio output switching — Linux implementation using pactl (PulseAudio / PipeWire).

Public API
----------
list_output_devices()  -> [(device_id, friendly_name), ...]
set_default_output(id) -> bool
"""
import subprocess
import re


def list_output_devices() -> list[tuple[str, str]]:
    """Return [(sink_name, friendly_name), ...] for available playback sinks."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sinks"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []

    devices = []
    sink_name = ""
    for line in out.splitlines():
        line = line.strip()
        # "Name: alsa_output.pci-..." line
        m = re.match(r"^Name:\s+(.+)$", line)
        if m:
            sink_name = m.group(1).strip()
        # "Description: ..." gives the human-readable name
        m = re.match(r"^Description:\s+(.+)$", line)
        if m and sink_name:
            friendly = m.group(1).strip()
            devices.append((sink_name, friendly))
            sink_name = ""
    return devices


def set_default_output(sink_name: str) -> bool:
    """Set *sink_name* as the default PulseAudio/PipeWire output sink."""
    try:
        subprocess.run(
            ["pactl", "set-default-sink", sink_name],
            check=True, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"  Audio switch failed: {e}")
        return False
