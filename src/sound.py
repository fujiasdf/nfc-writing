from __future__ import annotations

import os
import subprocess
import sys


def beep_ok() -> None:
    # macOS: built-in system sound
    if sys.platform == "darwin":
        # "Glass" is short and noticeable; fallback to default if missing
        sound = "/System/Library/Sounds/Glass.aiff"
        if os.path.exists(sound):
            subprocess.Popen(["afplay", sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    # Fallback: terminal bell
    print("\a", end="", flush=True)


def beep_error() -> None:
    if sys.platform == "darwin":
        sound = "/System/Library/Sounds/Basso.aiff"
        if os.path.exists(sound):
            subprocess.Popen(["afplay", sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    print("\a", end="", flush=True)

