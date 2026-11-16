"""Does this Hermes session have a screen? (twin#76 item 2)

Hermes was started over ssh on a Mac: the browser itself works, but a HEADED browser window there gets no window
session to draw in, so Chrome never paints a frame and Hermes' screenshot call waits until it times out. A
headless browser (Chrome's own `--headless=new`, which Hermes uses whenever `browser.headed` is off) draws off
screen and its screenshots work anywhere.

`has_gui(env, platform, probe)` answers from the environment the session was started with (all three injectable,
so tests never depend on the machine running them):

- Linux and the BSDs: a display is set (DISPLAY or WAYLAND_DISPLAY).
- macOS: not an ssh session (SSH_CONNECTION / SSH_CLIENT / SSH_TTY unset), or one that still reaches the logged-in
  window session (`launchctl managername` says "Aqua", as it does under Screen Sharing's own Terminal).
- Windows: not an ssh session (an ssh logon runs in Session 0, which has no desktop).

`fit_browser(config, ...)`: in a session with no screen a twin profile's `browser.headed: true` is turned off, so
the browser and its screenshots go the headless way; -> a note for the PASS line, or "" when nothing changed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Mapping, Optional

SSH_VARS = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
NOTE = ("browser headless (this session has no screen, so screenshots go the headless way; this stays in the twin's "
        "config: for a gateway run on a screen, set browser.headed: true there)")


def _launchctl_session() -> str:
    """macOS: the session type of this process ("Aqua" for the logged-in window session). "" when unknown."""
    try:
        out = subprocess.run(["/bin/launchctl", "managername"], capture_output=True, text=True, timeout=3,
                             check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (out.stdout or "").strip()


def has_gui(env: Optional[Mapping[str, str]] = None, platform: Optional[str] = None,
            probe: Optional[Callable[[], str]] = None) -> bool:
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    over_ssh = any(env.get(v) for v in SSH_VARS)
    if platform == "darwin":
        if not over_ssh:
            return True
        return (probe or _launchctl_session)() == "Aqua"
    if platform.startswith("win"):
        return not over_ssh
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def _truthy(v: object) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"))


def fit_browser(c: dict, env: Optional[Mapping[str, str]] = None, platform: Optional[str] = None,
                probe: Optional[Callable[[], str]] = None) -> str:
    """Turn `browser.headed` off in config `c` (in place) when this session has no screen. -> NOTE or ""."""
    b = c.get("browser")
    if not isinstance(b, dict) or not _truthy(b.get("headed")):
        return ""
    if has_gui(env, platform, probe):
        return ""
    b["headed"] = False
    return NOTE
