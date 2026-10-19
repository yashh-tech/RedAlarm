"""Five lightweight built-in RedAlarm ringtones generated on-device.

No bundled audio assets or extra binary downloads are needed. Local tracks are
copied into the app ringtone cache by main.py, so switching back to a built-in
sound is always possible without losing the local file.
"""
import math
import os
import struct
import wave

SAMPLE_RATE = 22050
_BUILTIN_SPECS = (
    ("classic", "Classic Beep", ((880, .16), (0, .08), (1175, .18), (0, .46))),
    ("double", "Double Beep", ((988, .12), (0, .07), (988, .12), (0, .50))),
    ("digital", "Digital Pulse", ((740, .10), (0, .07), (740, .10), (0, .07), (1047, .18), (0, .42))),
    ("chime", "Gentle Chime", ((659, .20), (784, .20), (988, .24), (1318, .34), (0, .34))),
    ("rise", "Morning Rise", ((523, .18), (659, .18), (784, .22), (1047, .36), (0, .34))),
)


def builtin_tone_specs():
    return [{"id": key, "name": name} for key, name, _segments in _BUILTIN_SPECS]


def _write_wave(path, segments):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    frames = bytearray()
    fade_samples = max(1, int(SAMPLE_RATE * .012))
    for frequency, seconds in segments:
        sample_count = max(1, int(SAMPLE_RATE * seconds))
        for index in range(sample_count):
            if frequency <= 0:
                value = 0
            else:
                envelope = min(1.0, index / fade_samples,
                               (sample_count - 1 - index) / fade_samples)
                envelope = max(0.0, envelope)
                value = int(32767 * 0.45 * envelope *
                            math.sin(2.0 * math.pi * frequency * index / SAMPLE_RATE))
            frames.extend(struct.pack("<h", value))
    temporary = path + ".tmp"
    with wave.open(temporary, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(frames)
    os.replace(temporary, path)


def ensure_builtin_ringtones(cache_dir):
    """Create missing tone files once and return the five selectable tones."""
    if not cache_dir:
        raise ValueError("A writable ringtone cache directory is required")
    os.makedirs(cache_dir, exist_ok=True)
    tones = []
    for key, name, segments in _BUILTIN_SPECS:
        path = os.path.join(cache_dir, "redalarm_tone_" + key + ".wav")
        if not os.path.isfile(path) or os.path.getsize(path) < 128:
            _write_wave(path, segments)
        tones.append({"id": key, "name": name, "path": path, "built_in": True})
    return tones


def default_builtin_ringtone(cache_dir):
    tones = ensure_builtin_ringtones(cache_dir)
    return next((tone for tone in tones if tone["id"] == "classic"), tones[0])
