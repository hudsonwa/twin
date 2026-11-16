"""twin#64: the origin note, a plugin-owned marked block in each twin's SOUL.md that says how the twin was made.

Fixed wording, filled only from this plugin's own constants (its version, the botport release it pins, the two
public repository addresses). No bot name, description, skill or routine text can reach it: build_body() takes no
argument. The block's first line is a version stamp, `<!-- grok-bot-twin:origin v=0.5.0 botport=0.3.3 -->`; a
refresh rewrites the block only when it differs, so after an update the first refresh writes it once and every later
one writes nothing. Text outside the markers is never touched (fleet_profiles.set_block). The owner turns the note
off with the `origin_note: off` setting: the next refresh takes the block out and none puts it back.

Refreshes run on the first hook of a process (register() itself stays free of file I/O), at the end of
`hermes twin setup --auto`, and after `from-hermes` / `from-grok`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from . import config
from . import osflags
from .model import PLUGIN_VERSION

log = logging.getLogger(__name__)

BEGIN = "<!-- grok-bot-twin:begin origin -->"
END = "<!-- grok-bot-twin:end origin -->"
TWIN_REPO = "github.com/hudsonwa/twin"
BOTPORT_REPO = "github.com/hudsonwa/botport"


def botport_version() -> str:
    from .engine import EXPECTED_BOTPORT_TAG
    return EXPECTED_BOTPORT_TAG.lstrip("v")


def stamp(plugin: str = PLUGIN_VERSION, botport: Optional[str] = None) -> str:
    return f"<!-- grok-bot-twin:origin v={plugin} botport={botport or botport_version()} -->"


def awareness_line() -> str:
    """The one line the per-turn awareness block carries (fixed wording, constants only)."""
    return f"Made by Grok Bot Twin {PLUGIN_VERSION} + botport {botport_version()} (open source); never guess a version."


def build_body() -> str:
    bp = botport_version()
    return "\n".join([
        stamp(PLUGIN_VERSION, bp),
        f"You are a Hermes twin of a Grok bot. You were made by Grok Bot Twin {PLUGIN_VERSION} (a Hermes plugin) using "
        f"botport {bp} (the engine that reads the Grok app). Both are open source: {TWIN_REPO} and {BOTPORT_REPO}.",
        "The copies on this computer are updated often, so the versions here may be newer. To check, run or suggest "
        "`hermes twin doctor`; never guess a version.",
        "Your instructions came from your Grok bot. This note is from the plugin, not from your owner.",
    ])


def enabled() -> bool:
    return bool(config.get("origin_note"))


CAP = 1024 * 1024


def _read_raw(path: Path) -> Optional[str]:
    """The file exactly as it is (byte-order mark and line endings kept): a regular file of this user, at most
    CAP bytes, UTF-8; None otherwise."""
    try:
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > CAP:
            return None
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return None
        with open(path, "rb") as fh:
            data = fh.read(CAP + 1)
        return None if len(data) > CAP else data.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _write_raw(path: Path, text: str) -> None:
    """Atomic replace that keeps the file's mode; the text is written as given, so every byte outside the block
    stays as the owner left it."""
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            os.chmod(tmp, mode)
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        osflags.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def refresh_home(home: Path) -> bool:
    """Bring one twin profile's origin block up to date (or take it out when the note is off). Only an existing
    SOUL.md is changed; nothing is written when nothing would change. Returns True when the file was written."""
    from .fleet_profiles import get_block, set_block
    path = Path(home) / "SOUL.md"
    current = _read_raw(path)
    if current is None:
        return False
    want = build_body() if enabled() else None
    have = get_block(current, BEGIN, END)
    if want is None and have is None:
        return False
    if want is not None and have == want and current.count(BEGIN) == 1:
        return False
    if have is None:  # a new block goes first: every byte of the owner's file then follows it unchanged
        text = f"{BEGIN}\n{want}\n{END}\n" + current
    else:
        text = set_block(current, BEGIN, END, want)
    if text == current:
        return False
    _write_raw(path, text)
    return True


def owned_profiles(svc: Any) -> tuple:
    """The Hermes profiles of this computer's real twins (the sample is never one)."""
    try:
        reg = svc._registry()
    except Exception:
        return ()
    out = []
    for e in (reg.values() if isinstance(reg, dict) else []):
        if not isinstance(e, dict) or e.get("sample") or e.get("demo"):
            continue
        prof = (e.get("hermes") or {}).get("profile")
        if isinstance(prof, str) and prof and prof != "default" and prof not in out:
            out.append(prof)
    return tuple(out)


def refresh(svc: Any = None, profiles: Optional[Iterable[str]] = None) -> int:
    """Refresh every owned twin profile; returns how many files were written. Never raises."""
    from . import store
    try:
        if profiles is None:
            if svc is None:
                from .service import get_service
                svc = get_service()
            profiles = owned_profiles(svc)
        n = 0
        for prof in profiles:
            try:
                n += refresh_home(store.profile_home(prof))
            except Exception:
                log.debug("grok-bot-twin: origin note not refreshed in one profile", exc_info=True)
        return n
    except Exception:
        log.debug("grok-bot-twin: origin note refresh skipped", exc_info=True)
        return 0


_once = threading.Event()


def refresh_once(svc: Any = None) -> None:
    """The plugin-load refresh: once per process, on the first hook."""
    if _once.is_set():
        return
    _once.set()
    refresh(svc)


def _reset_for_tests() -> None:
    _once.clear()
